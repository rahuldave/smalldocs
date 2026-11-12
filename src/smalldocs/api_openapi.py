"""The reference of an HTTP API, from its OpenAPI document: a page for each tag, a page of schemas, and the names for links.

A section of `api` with `language: openapi` takes exactly one input:

    api:
      - language: openapi
        fastapi: api.app:app                  # a FastAPI app, as module:attribute, imported in the project's environment
        setup: api.routers:register_routers   # with fastapi: a function that adds the routes, for an app that adds them at startup
        out: reference
      - language: openapi
        command: cargo run --quiet --bin openapi   # a command that prints the document, run in root
        out: rust-http
      - language: openapi
        file: openapi.yaml                    # a JSON or YAML document, from the site's folder
        out: http

smalldocs reads OpenAPI 3.0 and 3.1. It parses the document with Python's json, or PyYAML for YAML. It never
imports FastAPI: a short program, `PROGRAM`, runs in the project's environment and prints the document.
"""

import contextlib
import json
import os
import re
import shlex
import signal
import subprocess
import tempfile
import threading
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

import yaml

from .api import (
    Settings,
    code_block,
    code_span,
    entry_ids,
    escape_angles,
    folder_indexes,
    front_matter,
    hand_written,
    heading_text,
    link_path,
    one_line,
    out_folder,
    page_key,
    source_line,
    table,
    type_cell,
    unique,
    write_reference,
)

METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")  # The keys of a path item that are operations
SCHEMA_REF = re.compile(r"#/components/schemas/([^/]+)")  # A `$ref` to a named schema, which is a link and is never inlined
FASTAPI_OWN = ("HTTPValidationError", "ValidationError")  # The schemas that FastAPI adds itself, which `check` does not hold
MARKER = "smalldocs-openapi-error: "  # The start of the line that the FastAPI program prints when a step fails
LIMIT = 2_000_000  # The most values a document may hold, its YAML aliases counted each time they are used
DEPTH = 40  # How deep a schema may nest, so that a YAML alias that loops stops the build and not Python
PROGRAM = r'''
import sys
while "" in sys.path:
    sys.path.remove("")  # the project's folder must not shadow the modules of this program, such as a `json.py`
import asyncio, importlib, inspect, json, os, traceback
sys.path.insert(0, "")  # and then the app imports from it
sys.stdout.flush()
out = os.fdopen(os.dup(1), "w", encoding="utf-8")  # the document alone goes to the first standard output
os.dup2(2, 1)  # anything else the app writes, even to file descriptor 1, goes to standard error
sys.stdout = sys.stderr


def flush():
    for f in (sys.__stdout__, sys.__stderr__, sys.stdout, sys.stderr):
        try:
            f.flush()  # what the app printed and did not flush
        except Exception:
            pass


def end(code):
    flush()
    os._exit(code)  # a thread or a worker that the app started must not hold the build


def fail(step, e):
    flush()  # the app's own output comes before the marker and the traceback, so the end of standard error shows them
    said = f"\nsmalldocs-openapi-error: {step}: {type(e).__name__}: {' '.join(str(e).split())}\n"  # on a line of its own, after a progress bar
    text = (said + "".join(traceback.format_exception(type(e), e, e.__traceback__))).encode("utf-8", "replace")
    try:
        os.write(2, text)  # to fd 2, though the app replaced sys.stderr
    except OSError:
        os.write(out.fileno(), text)  # the app closed fd 2
    end(1)


def find(spec):
    module, _, name = spec.partition(":")
    obj = importlib.import_module(module.strip())
    for part in name.strip().split("."):
        obj = getattr(obj, part)
    return obj


async def wait(value):
    return await value


try:
    app = find(os.environ["SMALLDOCS_FASTAPI_APP"])
except BaseException as e:
    fail("app-import", e)
setup = os.environ.get("SMALLDOCS_FASTAPI_SETUP", "")
if setup:
    try:
        func = find(setup)
        if not callable(func):
            raise TypeError(f"{setup} is not callable")
    except BaseException as e:
        fail("setup-import", e)
    try:
        value = func(app)
        if inspect.isawaitable(value):
            asyncio.run(wait(value))
    except BaseException as e:
        fail("setup-call", e)
try:
    doc = app.openapi()
except BaseException as e:
    fail("openapi", e)
for route in getattr(app, "routes", []):
    if not getattr(route, "include_in_schema", False) or not hasattr(route, "endpoint"):
        continue
    try:
        code = inspect.unwrap(route.endpoint)
        where = {"file": inspect.getsourcefile(code), "line": inspect.getsourcelines(code)[1]}
    except Exception:
        continue
    if not where["file"]:
        continue
    for method in getattr(route, "methods", None) or ():
        op = doc.get("paths", {}).get(getattr(route, "path_format", ""), {}).get(method.lower())
        if isinstance(op, dict):
            op["x-smalldocs-source"] = where
json.dump(doc, out)
out.flush()
end(0)
'''  # The program that prints a FastAPI app's document, with the file and line of each route; it runs with `-c`, in the project's folder


def section_name(
    s: Settings,  # The settings
) -> str:  # How messages name the section
    "Name a section in a message, by its `out`."
    return f"the api section with out {s.out!r}"


def kill_group(
    proc: subprocess.Popen,  # A process that leads its own session
) -> None:
    "Kill the process and every process it started in its session, such as the Python under `uv run` and the app's workers."
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:  # the group has ended
        with contextlib.suppress(OSError):
            proc.kill()


@contextlib.contextmanager
def killed_on_stop(
    proc: subprocess.Popen,  # A process that leads its own session, which a signal to the build does not reach
) -> Iterator[None]:  # The block in which a stop kills the process first
    "Kill the process's session when SIGTERM or SIGHUP would end the build, then end it as the signal asks."
    if threading.current_thread() is not threading.main_thread():  # only the main thread may set a handler
        yield
        return
    names = [getattr(signal, n) for n in ("SIGTERM", "SIGHUP") if hasattr(signal, n)]
    stops = [sig for sig in names if signal.getsignal(sig) == signal.SIG_DFL]  # an ignored or handled signal does not end the build, so it leaves the command

    def stop(sig: int, frame: object) -> None:
        "Kill the session, and end the build with the signal."
        kill_group(proc)
        signal.signal(sig, signal.SIG_DFL)
        signal.raise_signal(sig)

    for sig in stops:
        signal.signal(sig, stop)
    try:
        yield
    finally:
        for sig in stops:
            signal.signal(sig, signal.SIG_DFL)


def stderr_tail(
    text: str,  # What a command printed on its standard error
) -> str:  # Its last 12 lines, each cut to 500 characters
    "Give the end of standard error for a message, short enough to read."
    return "\n".join(ln if len(ln) <= 500 else ln[:500] + " ..." for ln in text.strip().splitlines()[-12:])


def run_tool(
    s: Settings,  # The settings
    words: list[str],  # The command and its arguments
    env: dict[str, str],  # More environment variables
    what: str,  # How the message names the command
) -> tuple[str, str]:  # What it printed on its standard output, and the end of its standard error
    "Run a command in the root, with no shell, and stop the build when it fails, with the end of its standard error."
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:  # files, not pipes: a worker that the command leaves may keep them open
        try:
            proc = subprocess.Popen(
                words, cwd=s.root, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **env}, stdout=output, stderr=errors, start_new_session=True
            )  # fmt: skip
        except OSError as e:
            raise ValueError(f"{section_name(s)}: {what} could not start: {e}") from e
        try:
            with killed_on_stop(proc):
                proc.wait(timeout=s.timeout)
        except subprocess.TimeoutExpired as e:
            raise ValueError(f"{section_name(s)}: {what} did not finish in {s.timeout:g} seconds; set timeout to wait longer") from e
        finally:  # a timeout, Ctrl-C, or the end: nothing that the command started outlives it
            kill_group(proc)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=5)
        output.seek(0)
        errors.seek(0)
        raw, stderr = output.read(), errors.read().decode("utf-8", "replace")
    if proc.returncode:
        lines = stderr.splitlines() + raw.decode("utf-8", "replace").splitlines()  # the marker is on standard output when the app closed fd 2
        at = next((i for i, ln in enumerate(lines) if MARKER in ln), None)
        if at is not None and s.fastapi:
            step = lines[at].split(MARKER, 1)[1]
            who = f"setup {s.setup}" if step.startswith("setup-") else f"fastapi {s.fastapi}"
            parts = [f"{section_name(s)}: {who}: {step}", stderr_tail("\n".join(lines[max(0, at - 6) : at])), stderr_tail("\n".join(lines[at + 1 :]))]
            raise ValueError("\n".join(p for p in parts if p))  # the step, what the app printed last, and the end of the traceback
        raise ValueError(f"{section_name(s)}: {what} failed with code {proc.returncode}:\n{stderr_tail(stderr)}")
    try:
        return raw.decode("utf-8"), stderr_tail(stderr)
    except UnicodeDecodeError as e:
        raise ValueError(f"{section_name(s)}: {what} printed text that is not UTF-8 ({e}); print the document in UTF-8") from e


def document_text(
    s: Settings,  # The settings
) -> tuple[str, str, str]:  # The document's text, how messages name where it came from, and the end of the command's standard error
    "Read the document from its input: the file, the output of the command, or the output of the FastAPI program."
    if s.file:
        f = s.site / s.file
        if not f.is_file():
            raise ValueError(f"{section_name(s)}: the file {s.file} is not found, from {s.site}")
        return f.read_text(encoding="utf-8"), f"the file {s.file}", ""
    if s.command:
        what = f"the command {shlex.join(s.command)}"
        text, said = run_tool(s, list(s.command), {}, what)
        return text, what, said
    runner = list(s.python) or ["uv", "run", "--frozen", "python"]
    what = f"the program for fastapi {s.fastapi}"
    text, said = run_tool(s, [*runner, "-c", PROGRAM], {"SMALLDOCS_FASTAPI_APP": s.fastapi, "SMALLDOCS_FASTAPI_SETUP": s.setup}, what)
    return text, what, said


def parse(
    s: Settings,  # The settings
    text: str,  # The document's text
    what: str,  # Where it came from, for messages
    said: str = "",  # The end of the command's standard error, which may say why it gave no document
) -> dict:  # The document
    "Parse the document as JSON, or else as YAML, and refuse what is not OpenAPI 3.0 or 3.1."
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        try:
            data = yaml.safe_load(text)
        except (yaml.YAMLError, RecursionError):
            data = None
    if not isinstance(data, dict):
        start = text.strip()[:60]
        why = f"\nIts standard error ends:\n{said}" if said else ""
        raise ValueError(f"{section_name(s)}: {what} gave no OpenAPI document in JSON or YAML; it starts {start!r}. Its standard output must hold only the document{why}")
    if "swagger" in data:
        raise ValueError(f"{section_name(s)}: {what} is Swagger {data['swagger']}; smalldocs reads OpenAPI 3.0 and 3.1")
    size(s, data)
    version = str(data.get("openapi", ""))
    if not re.match(r"3\.[0-2](\.|$)", version):
        raise ValueError(f"{section_name(s)}: {what} is not OpenAPI 3.0 or 3.1: its openapi is {version!r}")
    if version.startswith("3.2"):
        s.warnings.append(f"{section_name(s)}: OpenAPI {version} is read as 3.1, and its new fields are left out")
    return data


def size(
    s: Settings,  # The settings
    data: object,  # The document, as parsed
) -> int:  # How many values it holds, each alias of YAML counted as often as it is used
    "Refuse a document that holds itself, or that YAML's aliases make larger than `LIMIT` values, before a page repeats it."
    known: dict[int, int] = {}
    stack: set[int] = set()

    def count(
        node: object,  # A value
    ) -> int:  # The values it holds, with itself
        "Count once each object that YAML shares, and stop at a loop."
        if not isinstance(node, (dict, list)):
            return 1
        if id(node) in stack:
            raise ValueError(f"{section_name(s)}: the document holds itself, through a YAML alias")
        if id(node) not in known:
            stack.add(id(node))
            known[id(node)] = 1 + sum(count(v) for v in (node.values() if isinstance(node, dict) else node))
            stack.discard(id(node))
        return known[id(node)]

    try:
        n = count(data)
    except RecursionError as e:
        raise ValueError(f"{section_name(s)}: the document nests too deep") from e
    if n > LIMIT:
        raise ValueError(f"{section_name(s)}: the document holds more than {LIMIT:,} values, as its YAML aliases repeat them")
    return n


def json_text(
    value: object,  # A value from the document, such as a default
) -> str:  # It as JSON on one line
    "Write a value as JSON, as the document gives it."
    return json.dumps(value, ensure_ascii=False, default=str)


def natural_id(
    method: str,  # The method, such as `get`
    path: str,  # The path, such as `/api/players/{player_id}`
) -> str:  # The id, such as `get-api-players-player_id`
    "Make an operation's id from its method and its path: no braces, a `-` for each run of other signs, in lower case."
    return re.sub(r"[^A-Za-z0-9_.]+", "-", re.sub(r"[{}]", "", f"{method} {path}")).lower().strip("-")


def file_name(
    tag: str,  # A tag's name, such as `Head to Head`
) -> str:  # Its page's name, such as `head-to-head`, or `tag` when it has no letter or digit
    "Name a tag's page by the rule of operation ids."
    return re.sub(r"[^A-Za-z0-9_.]+", "-", tag).lower().strip("-.") or "tag"


@dataclass
class Operation:
    "One method on one path, and where its entry goes."

    method: str  # The method, in lower case, such as `get`
    path: str  # The path, such as `/api/players/{player_id}`
    node: dict  # The operation's object in the document
    item: dict  # The path item that holds it, for the parameters of the path
    id: str = ""  # Its id on the page, unique in the section
    page: str = ""  # Its page, such as `players.qmd`

    @property
    def name(self) -> str:  # The method and the path, such as `GET /api/players/{player_id}`
        "Name the operation as a reader calls it."
        return f"{self.method.upper()} {self.path}"


@dataclass
class Group:
    "The operations of one tag, which share one page."

    title: str  # The tag's name, or `default` for operations with no tag
    description: str  # The tag's description, from the document's `tags`
    ops: list[Operation]  # Its operations, in the document's order
    page: str = ""  # Its page, such as `players.qmd`


class Document:
    "An OpenAPI document, with its `$ref`s followed as they are read."

    def __init__(
        self,
        s: Settings,  # The settings
        data: dict,  # The document
    ) -> None:
        "Read the operations, the tags and the names of the schemas."
        self.s, self.data = s, data
        self.v30 = str(data.get("openapi", "")).startswith("3.0")
        components = data.get("components") or {}
        self.schemas = components.get("schemas") or {} if isinstance(components, dict) else None
        if not isinstance(self.schemas, dict):
            raise ValueError(f"{section_name(s)}: components and components.schemas must be mappings")
        folded = {one_line(str(k)): v for k, v in self.schemas.items()}  # a name such as `1:` in YAML is a number; a line break is a space
        if len(folded) < len(self.schemas):
            same = Counter(one_line(str(k)) for k in self.schemas)
            raise ValueError(f"{section_name(s)}: two schemas have the name {next(n for n, c in same.items() if c > 1)!r} on one line; give each a name of its own")
        self.schemas = folded
        names = list(self.schemas)
        ids = [re.sub(r"[^A-Za-z0-9_.-]", "-", str(n)) or "schema" for n in names]
        self.schema_ids = dict(zip(names, entry_ids(ids), strict=True))
        self.ops = self.operations()
        ids = [natural_id(op.method, op.path) for op in self.ops]
        for op, id_ in zip(self.ops, entry_ids(ids), strict=True):
            op.id = id_
        self.groups = self.grouped()

    def fail(
        self,
        message: str,  # What is wrong
    ) -> ValueError:  # The error, naming the section
        "Make the error that stops the build."
        return ValueError(f"{section_name(self.s)}: {message}")

    def pointer(
        self,
        ref: str,  # A `$ref`, such as `#/components/parameters/limit`
    ) -> object:  # What it points at
        "Follow a JSON pointer inside the document; a `$ref` to another file stops the build."
        if not ref.startswith("#"):
            raise self.fail(f"a $ref to another file, {ref}: smalldocs reads one document, so bundle it into one first")
        if ref != "#" and not ref.startswith("#/"):
            raise self.fail(f"the $ref {ref} points at nothing: smalldocs follows JSON pointers, such as #/components/schemas/Player")
        node: object = self.data
        for part in ref[1:].split("/")[1:]:
            key = unquote(part).replace("~1", "/").replace("~0", "~")
            found = ([key] if key in node else [k for k in node if str(k) == key]) if isinstance(node, dict) else []  # YAML reads `200:` as a number
            if isinstance(node, list) and key.isascii() and key.isdigit() and int(key) < len(node):
                node = node[int(key)]
            elif found:
                node = node[found[0]]
            else:
                raise self.fail(f"the $ref {ref} points at nothing")
        return node

    def named(
        self,
        node: object,  # Part of the document
    ) -> str | None:  # The name of the schema when it is a `$ref` to a named schema; `None` otherwise
        "Tell whether a node is a link to a named schema."
        ref = node.get("$ref") if isinstance(node, dict) else None
        m = SCHEMA_REF.fullmatch(ref) if isinstance(ref, str) else None
        if m is None:
            return None
        name = one_line(unquote(m.group(1)).replace("~1", "/").replace("~0", "~"))
        if name not in self.schemas:
            raise self.fail(f"the $ref {ref} points at nothing")
        return name

    def deref(
        self,
        node: object,  # Part of the document, which may be a `$ref`
        chain: tuple[str, ...] = (),  # The `$ref`s followed to reach it
    ) -> tuple[object, tuple[str, ...]]:  # What it stands for, and the chain with its own `$ref`s; a link to a named schema stays as it is
        "Follow each `$ref` that is not a named schema; one already on the chain is a loop, which stops the build."
        while isinstance(node, dict) and isinstance(node.get("$ref"), str) and self.named(node) is None:
            ref = node["$ref"]
            if ref in chain:
                raise self.fail(f"a loop of $ref: {' -> '.join([*chain, ref])}")
            chain = (*chain, ref)
            target = self.pointer(ref)
            beside = {k: v for k, v in node.items() if k in ("description", "summary") and not self.v30}  # 3.1 lets these sit beside a $ref
            node = {**target, **beside} if beside and isinstance(target, dict) else target
        return node, chain

    def link(
        self,
        name: str,  # A schema's name
    ) -> str:  # A Markdown link to its entry
        "Link a schema by its name."
        return f"[{type_cell(one_line(name))}](schemas.qmd#{self.schema_ids[name]})"

    def type_of(
        self,
        node: object,  # A schema
        chain: tuple[str, ...] = (),  # The `$ref`s followed to reach it
        depth: int = 0,  # How deep it is
    ) -> str:  # Its type in a short form, as Markdown: plain text, with a link for each named schema
        "Write a schema's type: `string (date-time)`, `array of Player`, `string or null`."
        if depth > DEPTH:
            raise self.fail(f"a schema nests deeper than {DEPTH} levels")
        if node is False:
            return "never"
        if not isinstance(node, dict) or not node:
            return "any"
        name = self.named(node)
        if name is None and "$ref" in node:
            target, chain = self.deref(node, chain)
            return self.type_of(target, chain, depth + 1)
        text = self.link(name) if name is not None else self.base_type(node, chain, depth)
        if node.get("nullable") is True and text != "null" and not text.endswith(" or null"):
            text += " or null"  # 3.0 writes a type that can be null so; last, after an `allOf` of a `$ref`
        return text

    def base_type(
        self,
        node: dict,  # A schema that is not a `$ref`
        chain: tuple[str, ...],  # The `$ref`s followed to reach it
        depth: int,  # How deep it is
    ) -> str:  # Its type, as Markdown
        "Write the type of a schema from its own keys: `const`, `enum`, `anyOf`, `oneOf`, `allOf` or `type`."
        if "const" in node:
            return code_span(json_text(node["const"]))
        if isinstance(node.get("enum"), list):
            return "one of " + ", ".join(code_span(json_text(v)) for v in node["enum"])
        for key, word in (("anyOf", " or "), ("oneOf", " or "), ("allOf", " and ")):
            if isinstance(node.get(key), list) and node[key]:
                return word.join(dict.fromkeys(self.type_of(n, chain, depth + 1) for n in node[key]))
        kind = node.get("type")
        kinds = kind if isinstance(kind, list) else [kind] if kind else []
        if not kinds:
            kinds = ["object"] if "properties" in node or "additionalProperties" in node else ["array"] if "items" in node else []
        return " or ".join(self.one_type(str(k), node, chain, depth) for k in kinds) or "any"

    def one_type(
        self,
        kind: str,  # One JSON type, such as `array`
        node: dict,  # The schema
        chain: tuple[str, ...],  # The `$ref`s followed to reach it
        depth: int,  # How deep it is
    ) -> str:  # The type, as Markdown
        "Write one JSON type of a schema: an array of its items, a map of its values, or a type with its format."
        if kind == "array" and "items" in node:
            return f"array of {wrap(self.type_of(node['items'], chain, depth + 1))}"
        values = node.get("additionalProperties")
        if kind == "object" and not node.get("properties") and isinstance(values, dict) and values:
            return f"map of {wrap(self.type_of(values, chain, depth + 1))}"
        fmt = node.get("format")
        return type_cell(one_line(f"{kind} ({fmt})") if isinstance(fmt, str) and fmt and kind not in ("array", "object", "null") else kind)

    def fields(
        self,
        node: object,  # An object schema
        chain: tuple[str, ...] = (),  # The `$ref`s followed to reach it
        prefix: str = "",  # The dotted name of the field that holds it, such as `stats.`
        depth: int = 1,  # How deep the fields are; three at most
    ) -> list[tuple[str, dict, bool, tuple[str, ...]]]:  # Each field: its dotted name, its schema, whether it is required, and its chain
        "List the fields of an object, and the fields of an inline object in a field, as `stats.runs`, to a depth of three."
        node, chain = self.deref(node, chain)
        if not isinstance(node, dict) or self.named(node) is not None:
            return []
        out = []
        parts = [node, *(p for p in node.get("allOf") or [] if isinstance(p, dict) and self.named(p) is None)]
        for part in parts:
            part, here = self.deref(part, chain)
            if not isinstance(part, dict):
                continue
            required = set(part.get("required") or [])
            for name, prop in (part.get("properties") or {}).items():
                prop = prop if isinstance(prop, dict) else {}
                out.append((f"{prefix}{name}", prop, name in required, here))
                inner, deeper = self.deref(prop, here)
                if depth < 3 and isinstance(inner, dict) and self.named(inner) is None and inner.get("properties"):
                    out += self.fields(inner, deeper, f"{prefix}{name}.", depth + 1)
        return out

    def description(
        self,
        node: object,  # A schema, a parameter or a response
        chain: tuple[str, ...] = (),  # The `$ref`s followed to reach it
    ) -> str:  # Its description, or that of what its `$ref` stands for; empty when there is none
        "Read a description."
        own = node.get("description") if isinstance(node, dict) else None
        if isinstance(own, str) and own.strip():
            return own
        target, _ = self.deref(node, chain)
        said = target.get("description") if isinstance(target, dict) and self.named(target) is None else None
        return said if isinstance(said, str) else ""

    def field_table(
        self,
        node: object,  # An object schema
        chain: tuple[str, ...] = (),  # The `$ref`s followed to reach it
    ) -> str:  # A Markdown table of its fields: type, default, whether it is required, and description
        "Describe an object by its fields."
        rows = []
        for name, prop, required, here in self.fields(node, chain):
            default = code_span(json_text(prop["default"])) if "default" in prop else ""
            said = one_line(escape_angles(self.description(prop, here)))
            rows.append([code_span(one_line(name)), self.type_of(prop, here), default, "yes" if required else "", ("Deprecated. " if prop.get("deprecated") is True else "") + said])
        return table(rows, ["Field", "Type", "Default", "Required", "Description"])

    def operations(self) -> list[Operation]:  # Each operation, in the document's order
        "List the operations of the document's paths."
        paths = self.data.get("paths") or {}
        if not isinstance(paths, dict):
            raise self.fail("paths must be a mapping")
        out = []
        for path, item in paths.items():
            item, _ = self.deref(item)
            if not isinstance(item, dict):
                continue
            out += [Operation(m, one_line(str(path)), op, item) for m, op in item.items() if m in METHODS and isinstance(op, dict)]
        return out

    def grouped(self) -> list[Group]:  # One group for each tag that an operation has first, in the order of `tags`, then of first use
        "Put each operation in the group of its first tag, or in `default` when it has none, and name each group's page."
        said = {one_line(str(t.get("name"))): t for t in self.data.get("tags") or [] if isinstance(t, dict)}
        groups: dict[str, Group] = {}
        for op in self.ops:
            tags = op.node.get("tags") or []
            tag = one_line(str(tags[0])) if isinstance(tags, list) and tags else "default"
            key = "default" if tag.casefold() == "default" else tag  # Swagger UI puts a tag `Default` with the operations that have none
            if key not in groups:
                desc = (said.get(tag) or said.get(key) or {}).get("description")
                groups[key] = Group(key, desc if isinstance(desc, str) else "", [])
            groups[key].ops.append(op)
        declared = [("default" if n.casefold() == "default" else n) for n in said]
        order = [k for k in dict.fromkeys(declared) if k in groups] + [k for k in groups if k not in declared]
        found = [groups[k] for k in order]
        taken = {page_key(t) for t in hand_written(out_folder(self.s)) if "/" not in t}
        reserved = re.compile("|".join(re.escape(n) for n in sorted({"schemas", "index", *taken})), re.IGNORECASE)
        for g, name in zip(found, unique([file_name(g.title) for g in found], reserved), strict=True):
            g.page = f"{name}.qmd"
            for op in g.ops:
                op.page = g.page
        return found

    def source(
        self,
        node: dict,  # An operation or a schema
    ) -> str:  # Its source link, from `x-smalldocs-source`; empty when it has none, or its file is outside the root
        "Link an entry to the file and line that `x-smalldocs-source` gives."
        where = node.get("x-smalldocs-source")
        if not isinstance(where, dict) or not isinstance(where.get("file"), str) or type(where.get("line")) is not int or not self.s.root:
            return ""
        f = Path(where["file"])
        try:
            rel = (f if f.is_absolute() else self.s.root / f).resolve().relative_to(self.s.root)
        except ValueError:
            return ""
        return source_line(self.s, rel.as_posix(), where["line"])

    def parameters(
        self,
        op: Operation,  # An operation
    ) -> list[tuple[dict, tuple[str, ...]]]:  # Each parameter, with the chain of `$ref`s to it: the path's, then the operation's own
        "List an operation's parameters; one of the operation replaces the path's with the same name and place."
        found: dict[tuple[str, str], tuple[dict, tuple[str, ...]]] = {}
        for p in [*(op.item.get("parameters") or []), *(op.node.get("parameters") or [])]:
            p, chain = self.deref(p)
            if isinstance(p, dict) and "name" in p:
                p = {**p, "name": one_line(str(p["name"])), "in": one_line(str(p.get("in", "")))}  # a line break in a name would split a row or a line
                key = (p["name"], p["in"])
                found.pop(key, None)
                found[key] = (p, chain)
        return list(found.values())

    def param_schema(
        self,
        p: dict,  # A parameter
    ) -> object:  # Its schema, or that of its first media type
        "Find a parameter's schema."
        if "schema" in p:
            return p["schema"]
        content = p.get("content")
        return next((m.get("schema") for m in content.values() if isinstance(m, dict)), None) if isinstance(content, dict) else None

    def request(
        self,
        op: Operation,  # An operation
    ) -> str:  # The HTTP request in a code block: the path, the query with its defaults, the headers and the cookies
        "Write the request as the signature of the operation."
        params = [p for p, _ in self.parameters(op)]
        query = []
        for p in (p for p in params if p.get("in") == "query"):
            schema, _ = self.deref(self.param_schema(p))
            default = schema.get("default") if isinstance(schema, dict) and "default" in schema else None
            value = "{" + str(p["name"]) + "}" if default is None else one_line(default) if isinstance(default, str) else json_text(default)
            query.append(f"{p['name']}={value}")
        lines = [f"{op.method.upper()} {op.path}" + ("?" + "&".join(query) if query else "")]
        lines += [f"{p['name']}: {{{p['name']}}}" for p in params if p.get("in") == "header"]
        cookies = [f"{p['name']}={{{p['name']}}}" for p in params if p.get("in") == "cookie"]
        lines += [f"Cookie: {'; '.join(cookies)}"] if cookies else []
        return code_block("\n".join(lines), "http")

    def params_table(
        self,
        op: Operation,  # An operation
    ) -> str:  # A Markdown table of its parameters: place, type, default, whether it is required, and description
        "Describe an operation's parameters."
        rows = []
        for p, chain in self.parameters(op):
            schema = self.param_schema(p)
            target, _ = self.deref(schema, chain)
            default = code_span(json_text(target["default"])) if isinstance(target, dict) and "default" in target else ""
            said = ("Deprecated. " if p.get("deprecated") is True else "") + one_line(escape_angles(self.description(p, chain)))
            rows.append([code_span(str(p["name"])), type_cell(str(p.get("in", ""))), self.type_of(schema, chain), default, "yes" if p.get("required") is True else "", said.strip()])
        return table(rows, ["Parameter", "In", "Type", "Default", "Required", "Description"])

    def body(
        self,
        op: Operation,  # An operation
    ) -> list[str]:  # The paragraphs of its request body: a line of its media types and types, its description, and the table of an inline object's fields
        "Describe an operation's request body."
        node, chain = self.deref(op.node.get("requestBody"))
        if not isinstance(node, dict):
            return []
        content = node.get("content") if isinstance(node.get("content"), dict) else {}
        kinds = "; ".join(f"{code_span(one_line(str(mt)))}, {self.type_of(m.get('schema'), chain)}" for mt, m in content.items() if isinstance(m, dict))
        out = [f"Request body{', required' if node.get('required') is True else ''}: {kinds or 'any'}."]
        said = node.get("description")
        out += [escape_angles(said.strip())] if isinstance(said, str) and said.strip() else []
        inline = next((m.get("schema") for m in content.values() if isinstance(m, dict) and self.named(m.get("schema")) is None), None)
        out += [self.field_table(inline, chain)] if inline is not None else []
        return out

    def responses(
        self,
        op: Operation,  # An operation
    ) -> str:  # A Markdown table of its responses: one row for each status and media type
        "Describe an operation's responses."
        rows = []
        for status, r in (op.node.get("responses") or {}).items():
            r, chain = self.deref(r)
            if not isinstance(r, dict):
                continue
            said = one_line(escape_angles(r.get("description") or "")) if isinstance(r.get("description") or "", str) else ""
            content = r.get("content") if isinstance(r.get("content"), dict) else {}
            media = [(mt, m) for mt, m in content.items() if isinstance(m, dict)]
            rows += [[type_cell(one_line(str(status))), code_span(one_line(str(mt))), self.type_of(m["schema"], chain) if "schema" in m else "", said] for mt, m in media]
            rows += [] if media else [[type_cell(one_line(str(status))), "", "", said]]
        return table(rows, ["Status", "Media type", "Type", "Description"])

    def operation_entry(
        self,
        op: Operation,  # An operation
    ) -> str:  # Its entry: a heading with an id, a source link, the request, the summary and description, and the tables
        "Write one operation's entry."
        summary, said = (op.node.get(k) if isinstance(op.node.get(k), str) else "" for k in ("summary", "description"))
        summary, said = summary.strip(), said.strip()
        parts = [
            f"## {heading_text(op.name)} {{#{op.id}}}",
            self.source(op.node),
            "Deprecated." if op.node.get("deprecated") is True else "",
            self.request(op),
            "" if said.startswith(summary) else escape_angles(summary),
            escape_angles(said),
            self.params_table(op),
            *self.body(op),
            self.responses(op),
        ]
        return "\n\n".join(p for p in parts if p)

    def schema_entry(
        self,
        name: str,  # A schema's name
    ) -> str:  # Its entry: a heading with an id, a source link, its description, and its type or the table of its fields
        "Write one schema's entry."
        node = self.schemas[name]
        node = node if isinstance(node, dict) else {}
        target, chain = self.deref(node)
        target = target if isinstance(target, dict) else {}
        parts = [f"## {heading_text(one_line(name))} {{#{self.schema_ids[name]}}}", self.source(node), escape_angles(self.description(node).strip())]
        fields = self.fields(target, chain)
        bases = [self.link(n) for n in (self.named(p) for p in target.get("allOf") or [] if isinstance(target.get("allOf"), list)) if n]
        if isinstance(target.get("enum"), list):
            parts.append("One of " + ", ".join(code_span(json_text(v)) for v in target["enum"]) + ".")
        elif bases:
            parts.append(f"It has the fields of {', '.join(bases)}" + (", and these." if fields else "."))
        elif not fields:
            parts.append(f"Type: {self.type_of(node)}.")
        parts.append(self.field_table(target, chain))
        return "\n\n".join(p for p in parts if p)


def wrap(
    text: str,  # A type
) -> str:  # It in parentheses when it joins types with "or" or "and"
    "Keep `array of (string or null)` apart from `array of string, or null`."
    return f"({text})" if " or " in text or " and " in text else text


def load(
    s: Settings,  # The settings
) -> Document:  # The document, read
    "Read the document from its input, and refuse one with no operations."
    out_folder(s)  # before any tool runs, refuse an `out` that is the site or outside it
    text, what, said = document_text(s)
    doc = Document(s, parse(s, text, what, said))
    if not doc.ops:
        why = f"; the setup {s.setup} ran, and added none" if s.setup else "; an app that adds its routers only at startup can name the function that adds them in setup" if s.fastapi else ""
        raise ValueError(f"{section_name(s)}: {what} gave a document with no operations{why}")
    return doc


def paragraphs(
    text: str,  # A description, in Markdown
) -> tuple[str, str]:  # Its first paragraph on one line, for the front matter, and the rest
    "Split a description into its summary and the rest."
    head, _, rest = text.strip().partition("\n\n")
    return one_line(escape_angles(head)), escape_angles(rest.strip())


def readable(
    s: Settings,  # The settings
    work: "object",  # A function of the settings that reads the document, `write_pages` or `gaps`
) -> object:  # What it gives
    "Run a step that reads the document, and turn a value of the wrong kind, such as a list where OpenAPI has a mapping, into an error that names the section."
    try:
        return work(s)
    except (AttributeError, TypeError, KeyError, IndexError, RecursionError, UnicodeError) as e:
        raise ValueError(f"{section_name(s)}: the document has a value of the wrong kind ({type(e).__name__}: {e}); check it with an OpenAPI validator") from e


def build(
    s: Settings,  # The settings
) -> list[Path]:  # The pages written
    "Write a page for each tag, a page of schemas, the folder's index, and the names for links."
    return readable(s, write_pages)


def write_pages(
    s: Settings,  # The settings
) -> list[Path]:  # The pages written
    "Write the pages of the document."
    taken = hand_written(out_folder(s))  # before the program or the command runs
    doc = load(s)
    pages: dict[str, str] = {}
    summaries: dict[str, str] = {}
    for n, g in enumerate(doc.groups, 1):
        head, rest = paragraphs(g.description)
        summaries[g.page] = head
        body = [rest, *(doc.operation_entry(op) for op in g.ops)]
        pages[g.page] = front_matter(g.title, head or None, n) + "\n\n".join(p for p in body if p) + "\n"
    if doc.schemas:
        summaries["schemas.qmd"] = "The shape of each kind of data that the API takes or gives."
        body = [doc.schema_entry(name) for name in doc.schemas]
        pages["schemas.qmd"] = front_matter("Schemas", summaries["schemas.qmd"], len(doc.groups) + 1) + "\n\n".join(body) + "\n"
    info = doc.data.get("info") if isinstance(doc.data.get("info"), dict) else {}
    pages |= folder_indexes(s.out, summaries, taken, paragraphs(info.get("description") or "")[0] if isinstance(info.get("description"), str) else "")
    index: dict[str, str] = {}
    full: set[str] = set()
    for op in doc.ops:
        target = f"{link_path(f'/{s.out}/{op.page}')}#{op.id}"
        index.setdefault(op.name, target)
        if isinstance(op.node.get("operationId"), str):
            index.setdefault(one_line(op.node["operationId"]), target)
    for name, id_ in doc.schema_ids.items():
        target = f"{link_path(f'/{s.out}/schemas.qmd')}#{id_}"
        index.setdefault(str(name), target)
        dotted = f"{s.out.replace('/', '.')}.{name}"
        index.setdefault(dotted, target)
        full.add(dotted)
    return write_reference(s, pages, index, taken, full)


def response_has_schema(
    doc: Document,  # The document
    r: object,  # A response
) -> bool:  # Whether some media type of it has a schema that says something: not `{}`, nor an object with no fields
    "Tell whether a response gives the shape of its body."
    r, _ = doc.deref(r)
    content = r.get("content") if isinstance(r, dict) and isinstance(r.get("content"), dict) else {}
    for m in content.values():
        schema, _ = doc.deref(m.get("schema") if isinstance(m, dict) else None)
        if not isinstance(schema, dict) or not schema:
            continue
        values = schema.get("additionalProperties")
        bare = schema.get("type") == "object" and not schema.get("properties") and not (isinstance(values, dict) and values) and not schema.get("allOf")
        if not bare:
            return True
    return False


def check(
    s: Settings,  # The settings
    shown: bool = False,  # Hold only what the pages show; the pages show every operation and schema, so this changes nothing
) -> int:  # The exit code: 0 when nothing is missing, 1 otherwise
    "Print how much of each tag and of the schemas is documented, then every gap, the parameters with no description by name, and the total."
    return readable(s, gaps)


def gaps(
    s: Settings,  # The settings
) -> int:  # The exit code: 0 when nothing is missing, 1 otherwise
    "Hold the document to the convention, and print what it finds."
    doc = load(s)
    found: list[str] = []
    unsaid: Counter = Counter()
    rows: list[tuple[str, int, int]] = []
    for g in doc.groups:
        complete = 0
        for op in g.ops:
            gaps = []
            summary, said = (op.node.get(k) if isinstance(op.node.get(k), str) else "" for k in ("summary", "description"))
            if not said.strip() and (s.fastapi or not summary.strip()):
                gaps.append(f"{op.name}: no description" if s.fastapi else f"{op.name}: no summary or description")
            for p, chain in doc.parameters(op):
                if not doc.description(p, chain).strip():
                    gaps.append(f"{op.name} ({p.get('in', '')} {p['name']}): no description")
                    unsaid[str(p["name"])] += 1
            if s.check_responses:
                for status, r in (op.node.get("responses") or {}).items():
                    code = str(status)
                    if re.fullmatch(r"2(\d\d|XX)", code, re.IGNORECASE) and code != "204" and not response_has_schema(doc, r):
                        gaps.append(f"{op.name} {code}: no response schema")
            complete += not gaps
            found += gaps
        rows.append((g.title, complete, len(g.ops)))
    held = [n for n in doc.schemas if n not in FASTAPI_OWN]
    complete = 0
    for name in held:
        gaps = [] if doc.description(doc.schemas[name]).strip() else [f"schemas:{name}: no description"]
        gaps += [f"schemas:{name}.{f}: no description" for f, prop, _, here in doc.fields(doc.schemas[name]) if not doc.description(prop, here).strip()]
        complete += not gaps
        found += gaps
    if held:
        rows.append(("schemas", complete, len(held)))
    width = max((len(t) for t, _, _ in rows), default=10)
    for title, done, total in rows:
        print(f"{title:{width}s} {done:3d} of {total:3d}")
    print("\n".join(["", *found]) if found else "")
    if unsaid:
        print("Parameters with no description, by name:")
        name_width = max(len(n) for n in unsaid)
        for n, k in sorted(unsaid.items(), key=lambda x: (-x[1], x[0])):
            print(f"  {n:{name_width}s} {k:5d}")
        print()
    done, total = sum(r[1] for r in rows), sum(r[2] for r in rows)
    print(f"{done} of {total} operations and schemas are documented")
    return 1 if found else 0
