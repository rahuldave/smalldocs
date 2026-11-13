"""The API reference of a TypeScript package, from the JSON that TypeDoc writes: one page per entry point.

TypeDoc gives each exported item with its JSDoc comment, its types and its defaults. It does not keep the
comment after a parameter, so smalldocs reads that from the source file, at the line TypeDoc gives:

    export function add(a: number,      // the first number
                        b: number = 1,  // the second number
    ): number {                         // the sum

The settings are `api` in `_smalldocs.yml`, or `smalldocs.api` in `_quarto.yml`:

    api:
      language: typescript
      entry: ../src/index.ts     # the entry points, one path or a list, or a folder; from the site's folder
      tsconfig: ../tsconfig.json # optional
      out: api
      source: https://github.com/me/mypkg/blob/main
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path

from .api import (
    Settings,
    escape_angles,
    folder_indexes,
    folder_listing,
    front_matter,
    hand_written,
    heading_text,
    link_path,
    one_line,
    out_folder,
    page_key,
    table,
    type_cell,
    unique,
    warn_unlinked,
    write_reference,
)

TYPEDOC = ["npx", "--yes", "--package", "typedoc@0.28", "typedoc"]  # TypeDoc from npm's cache, when the project has none
MODULE, NAMESPACE, ENUM, MEMBER, VARIABLE, FUNCTION, CLASS, INTERFACE = 2, 4, 8, 16, 32, 64, 128, 256
CONSTRUCTOR, PROPERTY, METHOD, ACCESSOR, ALIAS, REFERENCE = 512, 1024, 2048, 262144, 2097152, 4194304
KEYWORD = {CLASS: "class ", INTERFACE: "interface ", ALIAS: "type ", ENUM: "enum ", NAMESPACE: "namespace "}
NAME = r"[A-Za-z_$][\w$]*"
ANSI = re.compile(r"\x1b\[[0-9;]*m")


@dataclass
class Field:
    "One field of an interface, a type, a class or a component's props."

    name: str  # The field's name
    type: str  # Its type, as TypeScript writes it
    optional: bool  # Whether it is written `name?`
    doc: str  # The comment after it, or its JSDoc comment; empty when there is none
    default: str = ""  # Its default, from a component's destructured props; empty when there is none
    shared: bool = False  # Whether its line has a comment that it shares with other fields, so that the comment is no one's
    listed: bool = False  # Whether its type has an entry of its own, where `check` reports the field


# ---------------------------------------------------------------- running TypeDoc


def entries_of(
    s: Settings,  # The settings
) -> list[Path]:  # The entry points, from the site's folder
    "Find the entry points that `entry` names."
    if not s.entry:
        raise ValueError("the api settings need entry: the TypeScript entry points, or a folder, from the site's folder")
    out = [(s.site / e).resolve() for e in s.entry]
    for p in out:
        if not p.exists():
            raise ValueError(f"api.entry: {p} does not exist")
    return out


def project_of(
    s: Settings,  # The settings
    entries: list[Path],  # The entry points
) -> Path:  # The folder TypeDoc runs in: the tsconfig's, or the nearest with a package.json or a tsconfig.json
    "Find the TypeScript project's folder, where TypeDoc runs and where the paths in its JSON start."
    if s.tsconfig:
        return (s.site / s.tsconfig).resolve().parent
    start = entries[0] if entries[0].is_dir() else entries[0].parent
    for d in [start, *start.parents]:
        if (d / "package.json").exists() or (d / "tsconfig.json").exists():
            return d
    return start


def command(
    project: Path,  # The TypeScript project's folder
) -> list[str]:  # The command that runs TypeDoc: the project's own, or npx's
    "Choose the project's TypeDoc when `node_modules/.bin/typedoc` exists, else TypeDoc 0.28 through npx."
    own = project / "node_modules" / ".bin" / "typedoc"
    if own.exists() and shutil.which("node"):
        return [str(own)]
    if not shutil.which("npx"):
        raise ValueError("TypeScript API pages need Node and npx, to run TypeDoc. Install Node, then run npm install in the project")
    return list(TYPEDOC)


def run_typedoc(
    project: Path,  # The TypeScript project's folder
    entries: list[Path],  # The entry points: files, or folders
    tsconfig: Path | None = None,  # The tsconfig to use; `None` lets TypeDoc find the project's
) -> dict:  # TypeDoc's JSON, with each file named from the project's folder
    "Run TypeDoc on the entry points, into a temporary file outside the project, and read its JSON."
    with tempfile.TemporaryDirectory(prefix="smalldocs-typedoc-") as tmp:
        out = Path(tmp) / "api.json"
        args = [*command(project), "--json", str(out), "--displayBasePath", str(project), "--sort", "source-order", "--logLevel", "Error"]
        if tsconfig:
            args += ["--tsconfig", str(tsconfig)]
        if any(e.is_dir() for e in entries):
            args += ["--entryPointStrategy", "expand"]
        args += [str(e) for e in entries]
        try:
            done = subprocess.run(args, cwd=project, capture_output=True, text=True, env={**os.environ, "NO_COLOR": "1"})
        except OSError as e:
            raise ValueError(f"cannot run TypeDoc: {e}") from e
        if done.returncode != 0 or not out.exists():
            said = ANSI.sub("", (done.stdout + done.stderr).strip())
            tail = "\n".join(said.splitlines()[-20:])
            raise ValueError(f"TypeDoc failed in {project}:\n{tail}")
        return json.loads(out.read_text(encoding="utf-8"))


def typedoc_json(
    s: Settings,  # The settings
) -> tuple[dict, Path]:  # TypeDoc's JSON, and the project's folder that its file names start from
    "Run TypeDoc as the settings say."
    entries = entries_of(s)
    project = project_of(s, entries)
    return run_typedoc(project, entries, (s.site / s.tsconfig).resolve() if s.tsconfig else None), project


# ---------------------------------------------------------------- reading the source


class Sources:
    "The project's source files, read once, and the comments on their lines."

    def __init__(
        self,
        project: Path,  # The folder that TypeDoc's file names start from
    ) -> None:
        "Keep the project's folder; read files when they are asked for."
        self.project = project
        self.files: dict[str, list[Line]] = {}
        self.unlinked: set[str] = set()  # The files outside the root, whose items get no source link

    def lines(
        self,
        name: str,  # A file name from TypeDoc's JSON
    ) -> list["Line"]:  # Each line as its code and its `//` comment
        "Read one file as lines of code and comments; no lines when it cannot be read."
        if name not in self.files:
            try:
                text = (self.project / name).read_text(encoding="utf-8")
            except OSError:
                text = ""
            self.files[name] = split_comments(text)
        return self.files[name]

    def comment(
        self,
        node: dict,  # An item of TypeDoc's JSON that has `sources`
    ) -> str:  # The `//` comment on its line, when it is the last item there; empty otherwise
        "Read the comment after a field or a member, on the line where it starts, when nothing else follows it on that line."
        src = (node.get("sources") or [{}])[0]
        lines = self.lines(src.get("fileName", ""))
        line = src.get("line", 0)
        if not 0 < line <= len(lines):
            return ""
        return escape_angles(lines[line - 1].comment) if alone(lines[line - 1].code, src.get("character", 0)) else ""

    def shared(
        self,
        node: dict,  # An item of TypeDoc's JSON that has `sources`
    ) -> bool:  # Whether its line has a `//` comment that is not its alone, because more follows it on the line
        "Tell whether the comment on an item's line belongs to no one item, as in `{ a: number; b: number }  // the size`."
        src = (node.get("sources") or [{}])[0]
        lines = self.lines(src.get("fileName", ""))
        line = src.get("line", 0)
        return 0 < line <= len(lines) and bool(lines[line - 1].comment) and not alone(lines[line - 1].code, src.get("character", 0))


@dataclass
class Line:
    "One line of a source file, split into its code and its comment."

    code: str  # The code, with comments and the insides of strings blanked, so that brackets in them do not count
    text: str  # The same code with its strings, at the same columns, to copy a type or a default from
    comment: str  # The text of its `//` comment; empty when there is none
    raw: str  # The line as it is


def regex_end(
    raw: str,  # A line
    start: int,  # The column of a `/` that may open a regular expression
) -> int:  # The column after the expression and its flags; -1 when the line has no closing `/`
    "Find where a regular expression literal ends, past its escapes and its `[...]` classes."
    k, cls = start + 1, False
    while k < len(raw):
        ch = raw[k]
        if ch == "\\":
            k += 2
            continue
        if cls:
            cls = ch != "]"
        elif ch == "[":
            cls = True
        elif ch == "/":
            k += 1
            while k < len(raw) and raw[k].isalpha():
                k += 1
            return k
        k += 1
    return -1


REGEX_AFTER = re.compile(r"(^|[(,=:\[!&|?{};]|\b(?:return|typeof|case|of|in))\s*$")  # code that a regular expression can follow


def split_comments(
    source: str,  # A TypeScript file
) -> list[Line]:  # Its lines, each split into code and its `//` comment
    "Split each line of a file into code and its `//` comment, past strings, regular expressions and `/* */` comments."
    out, quote, block = [], "", False
    for raw in source.split("\n"):
        code, text, said, i = [], [], "", 0

        def put(
            blanked: str,  # What goes into the code
            kept: str,  # What goes into the text, as long
            code: list[str] = code,  # This line's code
            text: list[str] = text,  # This line's text
        ) -> None:
            "Add the same columns to the code and to the text."
            code.append(blanked)
            text.append(kept)

        while i < len(raw):
            c, two = raw[i], raw[i : i + 2]
            if block:
                if two == "*/":
                    block = False
                    put("  ", "  ")
                    i += 2
                    continue
                put(" ", " ")
            elif quote:
                if c == "\\":
                    put(" " * len(two), two)
                    i += 2
                    continue
                if c == quote:
                    quote = ""
                put(c if not quote else " ", c)
            elif two == "//":
                said = raw[i + 2 :].strip()
                break
            elif two == "/*":
                block = True
                put("  ", "  ")
                i += 2
                continue
            elif c == "/" and (end := regex_end(raw, i)) > 0 and REGEX_AFTER.search("".join(code)):
                put("/" + " " * (end - i - 1), raw[i:end])
                i = end
                continue
            else:
                if c in "'\"`":
                    quote = c
                put(c, c)
            i += 1
        if quote in "'\"":
            quote = ""  # a quote does not run past its line; only a template string does
        out.append(Line("".join(code), "".join(text), said, raw))
    return out


def alone(
    code: str,  # A line's code, as `split_comments` gives it
    column: int,  # The column where an item starts
) -> bool:  # Whether the item is the last thing on the line, so that the comment after it is its own
    "Tell whether nothing follows an item on its line but its `;` or `,`: not another field, and not the end of what holds it."
    depth = angle = 0
    for k in range(column, len(code)):
        c = code[k]
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth < 0:
                return False  # what holds it ends on this line, so the comment is not the item's alone
        elif c == "<":
            angle += 1
        elif c == ">" and code[k - 1] != "=" and angle:
            angle -= 1
        elif c in ";," and depth == 0 and angle == 0:
            return not code[k + 1 :].strip()
    return True


@dataclass
class Signature:
    "What the source of one signature says: the comments after its parameters and its return, and its destructured defaults."

    params: list[str]  # The comment after each parameter, in order; empty for one without
    returns: str  # The comment on the line of the return type or of the `{`; empty when there is none
    defaults: dict[str, str]  # The defaults of a destructured first parameter, `{ a, b = 1 }`, by name
    destructured: bool = False  # Whether the first parameter is destructured, as `{ a, b }`


def read_signature(
    lines: list[Line],  # The file, as `split_comments` gives it
    line: int,  # The line the signature starts on, from 1
    column: int = 0,  # The column its name starts at
) -> Signature:  # The comments, by parameter, and the return's
    "Read a signature from its source: a comment on a parameter's line is that parameter's, one on the line of the return or the `{` is the return's."
    starts: list[int] = []  # the line each parameter starts on
    defaults: dict[str, str] = {}
    depth, angle, open_line, close_line, end_line = 0, 0, -1, -1, -1
    pattern, kept, in_pattern, destructuring = "", "", False, False  # a destructured first parameter: its code, and its text with strings
    first = True
    typed, expect, last = False, False, ""  # after the `)`: whether a `:` began a return type, whether a type comes next, the last sign
    for n in range(line - 1, min(len(lines), line + 400)):
        start = column if n == line - 1 else 0
        code, text = lines[n].code[start:], lines[n].text[start:]
        i = 0
        while i < len(code):
            c = code[i]
            arrow = code[i - 1 : i + 1] == "=>"
            if open_line < 0:
                if c == "<":
                    angle += 1
                elif c == ">" and not arrow:
                    angle -= 1
                elif c == "(" and angle <= 0:
                    open_line, depth, first, angle = n, 1, True, 0
                elif c in "{;" and angle <= 0:
                    return Signature([], "", {})  # no parameter list: not a function
                i += 1
                continue
            if close_line < 0:
                if depth == 1 and first and not c.isspace() and c != ")":  # `)` after a trailing comma starts no parameter
                    starts.append(n)
                    first = False
                    in_pattern = c == "{" and len(starts) == 1
                    destructuring = destructuring or in_pattern
                if c in "([{":
                    depth += 1
                elif c in ")]}":
                    depth -= 1
                    if depth == 1 and in_pattern and c == "}":
                        in_pattern = False
                        defaults = destructured(pattern, kept)
                elif c == "<":
                    angle += 1
                elif c == ">" and not arrow and angle:
                    angle -= 1
                elif c == "," and depth == 1 and angle == 0:
                    first = True
                if in_pattern and depth >= 2 and not (depth == 2 and c == "{" and not pattern):
                    pattern, kept = pattern + c, kept + text[i]
                if depth == 0:
                    close_line = n
            elif depth > 0:  # inside the brackets of the return type
                if c in "([{<":
                    depth += 1
                elif c in ")]}" or (c == ">" and not arrow):
                    depth -= 1
                    last = c
            elif code[i : i + 2] == "=>":
                if not (typed and last == ")"):
                    end_line = n  # an arrow function's body
                    break
                expect, last = True, ">"  # a function type, `(v: string) => void`
                i += 1
            elif c == ";" or (c == "{" and not expect):
                end_line = n  # the body, or the end of an overload
                break
            elif c in "([{<":
                depth, expect = depth + 1, False
            elif c == ":":
                typed, expect = True, True
            elif c in "|&?":
                expect = True
            elif not c.isspace():
                expect, last = False, c
            i += 1
        if pattern and in_pattern:
            pattern, kept = pattern + "\n", kept + "\n"
        if end_line >= 0:
            break
    if close_line < 0:
        return Signature([], "", {})
    end_line = end_line if end_line >= 0 else close_line
    returns = lines[close_line].comment or lines[end_line].comment  # the lines between hold the return type's own parts
    params = [lines[n].comment if n < close_line and starts.count(n) == 1 else "" for n in starts]
    return Signature(params, returns, defaults, destructuring)


def destructured(
    pattern: str,  # The inside of `{ a, b = 1, c: d = 2 }`, without the braces, with its strings blanked
    kept: str,  # The same, with its strings, at the same columns
) -> dict[str, str]:  # The default of each name that has one
    "Read the defaults of a destructured parameter, splitting at the commas outside brackets and strings."
    out, depth, begin = {}, 0, 0
    for k, c in enumerate(pattern + ","):
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            m = re.match(rf"\s*({NAME})\s*(?::\s*{NAME}\s*)?=\s*", pattern[begin:k])
            if m:
                out[m.group(1)] = " ".join(kept[begin + m.end() : k].split())
            begin = k + 1
    return out


FIELD = re.compile(rf"\s*(?:readonly\s+)?['\"]?({NAME}|[\w$-]+)['\"]?(\?)?\s*:\s*")  # a field's name, in the text with its strings


def body_start(
    code: str,  # A line's code
    name: str,  # The name of an interface or a type
) -> int | None:  # The column after the `{` that opens its body; `None` when the line declares no such object type
    "Find the body of `interface Name ... {` or `type Name = {`, past the braces inside type parameters."
    m = re.search(rf"\b(interface|type)\s+{re.escape(name)}\b", code)
    if not m:
        return None
    angle = 0
    for k in range(m.end(), len(code)):
        c = code[k]
        if c == "<":
            angle += 1
        elif c == ">" and code[k - 1] != "=":
            angle -= 1
        elif c == "{" and angle == 0:
            ok = m.group(1) == "interface" or re.fullmatch(r"\s*(<.*>)?\s*=\s*", code[m.end() : k], re.S)
            return k + 1 if ok else None
        elif c == ";" and angle == 0:
            return None
    return None


def end_field(
    f: Field | None,  # A field whose type has ended, or `None`
) -> None:
    "Tidy a field's type once it ends."
    if f is not None:
        f.type = " ".join(f.type.split()).rstrip(";,").strip()


def declared_fields(
    lines: list[Line],  # The file, as `split_comments` gives it
    name: str,  # The name of an interface or a type that is not exported
) -> list[Field] | None:  # Its fields, or `None` when the file declares no such object type
    "Read the fields of an interface or an object type that TypeDoc leaves out, because the file does not export it."
    raws = [ln.raw for ln in lines]
    for n, line in enumerate(lines):
        at = body_start(line.code, name)
        if at is None:
            continue
        out, depth, angle, cur, doc = [], 1, 0, None, ""
        for k in range(n, len(lines)):
            code, text, i = lines[k].code, lines[k].text, at if k == n else 0
            if depth == 1 and cur is None and "/**" in raws[k]:
                doc = jsdoc_at(raws, k)
            while i < len(code):
                if depth == 1 and cur is None and (f := FIELD.match(text, i)):
                    mine = alone(code, i)
                    said = escape_angles((lines[k].comment if mine else "") or doc)
                    cur = Field(f.group(1), "", bool(f.group(2)), said, shared=bool(lines[k].comment) and not mine)
                    out.append(cur)
                    doc, i = "", f.end()
                    continue
                c = code[i]
                if c in "([{":
                    depth += 1
                elif c in ")]}":
                    depth -= 1
                elif c == "<":
                    angle += 1
                elif c == ">" and code[i - 1] != "=" and angle:
                    angle -= 1
                if depth == 0:
                    end_field(cur)
                    return out
                if depth == 1 and angle == 0 and cur is not None and c in ";,":
                    end_field(cur)
                    cur = None
                elif cur is not None:
                    cur.type += text[i]
                i += 1
            if cur is not None and depth == 1 and angle == 0:
                end_field(cur)  # the end of a line ends a field
                cur = None
            elif cur is not None:
                cur.type += " "
        return out
    return None


def jsdoc_at(
    raws: list[str],  # The lines of a file
    start: int,  # The line, from 0, where a `/**` comment opens
) -> str:  # The comment's text, its lines joined
    "Read the text of a `/** */` comment that opens at a line."
    text = []
    for k in range(start, len(raws)):
        text.append(raws[k])
        if "*/" in raws[k][raws[k].find("/**") + 3 if k == start else 0 :]:
            break
    body = "\n".join(text)
    body = body[body.find("/**") + 3 : body.rfind("*/")]
    return " ".join(re.sub(r"^\s*\* ?", "", ln).strip() for ln in body.split("\n")).strip()


def header_comment(
    text: str,  # A TypeScript file
) -> str:  # The `/** */` comment at its top, when no declaration takes it; empty otherwise
    "Read a file's opening comment as the module's, when TypeDoc drops it: no `@module` marks it, and no declaration follows it at once."
    other = r"(?>//[^\n]*|/\*(?!\*[^/])(?:(?!\*/).)*\*/)\s*"  # a comment that is no doc comment, such as a licence or `/**/`; atomic, so it never backtracks
    before = rf"\ufeff?(?:#![^\n]*\n)?\s*(?:{other})*+"  # a byte-order mark, a `#!` line, and such comments
    after = r"import\b|export\s+(?:type\s+)?(?:\*|\{[^}]*\}\s*from)|[\"']use \w+[\"']|/\*\*|$"  # an import, a re-export, a directive, a doc comment, the end
    m = re.match(rf"{before}/\*\*(?!/)((?:(?!\*/).)*)\*/\s*(?:{other})*+(?={after})", text, re.S)
    if not m:
        return ""
    lines = [re.sub(r"^\s*\* ?", "", ln) for ln in m.group(1).split("\n")]
    return escape_angles("\n".join(lines).strip("\n").rstrip())


PARAM_TAG = re.compile(r"@param\s+(?:\{(?:[^{}]|\{[^{}]*\})*\}\s*)?(?:\[\s*([\w$.]+)\s*(?:=[^\]]*)?\]|([\w$.]+))\s*(?:-\s+)?(.*)")


def param_tags(
    lines: list[Line],  # The file, as `split_comments` gives it
    line: int,  # The line of a declaration, from 1
) -> dict[str, str]:  # The text of each `@param` of the doc comment just above it, by name; `props.a` also as `.a`
    "Read the `@param` tags of a declaration's doc comment from its source, as JSDoc writes them for a destructured parameter: `@param a` or `@param props.a`."
    raws = [ln.raw for ln in lines]
    end = line - 2
    start = None
    while 0 <= end < len(raws) and start is None:
        if not raws[end].strip() or raws[end].strip().startswith("//"):
            end -= 1  # TypeDoc reads the doc comment past blank lines and comments
            continue
        if not raws[end].rstrip().endswith("*/"):
            return {}
        opens = next((k for k in range(end, -1, -1) if "/*" in raws[k][: len(raws[k]) - 2 if k == end else None]), None)
        if opens is None:
            return {}
        if re.search(r"/\*\*(?!/)", raws[opens]):
            start = opens
        else:
            end = opens - 1  # a comment that is no doc comment, such as `/* eslint-disable */`
    if start is None:
        return {}
    out: dict[str, str] = {}
    name = ""
    body = "\n".join(raws[start : end + 1])
    for text in body[body.find("/**") + 3 : body.rfind("*/")].split("\n"):
        text = re.sub(r"^\s*\* ?", "", text).strip()
        m = PARAM_TAG.match(text)
        if m:
            name = m.group(1) or m.group(2)
            out[name] = m.group(3).strip()
        elif text.startswith("@"):
            name = ""
        elif name and text:
            out[name] = (out[name] + " " + text).strip()
    for key, said in list(out.items()):
        head, dot, field = key.partition(".")
        if dot and head and "." not in field:
            out.setdefault("." + field, said)
    return out


PRIMITIVES = {"string", "number", "boolean", "bigint", "symbol"}  # Types that no props object has
JSX_TYPES = {"JSX.Element", "ReactElement", "ReactNode", "ReactPortal"}  # What a React component returns, without `React.`


def is_jsx(
    t: dict | None,  # A return type
) -> bool:  # Whether it is what a React component returns: `JSX.Element`, `ReactNode` and the like, alone or with `null`
    "Tell whether a function returns what React draws."
    if not t:
        return False
    if t.get("type") == "union":
        nothing = [x for x in t["types"] if (x.get("type") == "literal" and (x.get("value") is None or x.get("value") is False)) or (x.get("type") == "intrinsic" and x.get("name") in ("null", "undefined"))]
        rest = [x for x in t["types"] if x not in nothing]
        return bool(rest) and all(is_jsx(x) for x in rest)
    name = (t.get("qualifiedName") or t.get("name") or "").removeprefix("React.")
    return t.get("type") == "reference" and name in JSX_TYPES


# ---------------------------------------------------------------- writing it as Markdown


def wrap(
    t: dict,  # A type
) -> str:  # It as text, in parentheses when it is a union, an intersection or a function
    "Write a type that goes before `[]`, or inside a union, in parentheses when it needs them."
    text = type_text(t)
    needs = t.get("type") in ("union", "intersection", "conditional") or (t.get("type") == "reflection" and t["declaration"].get("signatures"))
    return f"({text})" if needs else text


def type_text(
    t: dict | None,  # A type from TypeDoc's JSON
) -> str:  # It as TypeScript writes it
    "Write a type the way TypeScript does."
    if not t:
        return ""
    k = t.get("type")
    if k in ("intrinsic", "unknown"):
        return t.get("name", "")
    if k == "inferred":
        return f"infer {t['name']}"
    if k == "literal":
        v = t.get("value")
        if isinstance(v, dict):  # a bigint
            return f"{'-' if v.get('negative') else ''}{v.get('value')}n"
        return json.dumps(v)
    if k == "reference":
        name = t.get("name", "")
        q = t.get("qualifiedName", "")
        if q.endswith("." + name) and isinstance(t.get("target"), dict) and not t.get("refersToTypeParameter"):
            name = q  # `JSX.Element`, not `Element`
        args = t.get("typeArguments")
        return f"{name}<{', '.join(type_text(a) for a in args)}>" if args else name
    if k == "array":
        return wrap(t["elementType"]) + "[]"
    if k in ("union", "intersection"):
        return (" | " if k == "union" else " & ").join(wrap(x) if x.get("type") in ("union", "intersection") else type_text(x) for x in t["types"])
    if k == "tuple":
        return "[" + ", ".join(type_text(x) for x in t.get("elements", [])) + "]"
    if k == "namedTupleMember":
        return f"{t['name']}{'?' if t.get('isOptional') else ''}: {type_text(t['element'])}"
    if k == "optional":
        return type_text(t["elementType"]) + "?"
    if k == "rest":
        return "..." + type_text(t["elementType"])
    if k == "typeOperator":
        return f"{t['operator']} {type_text(t['target'])}"
    if k == "query":
        return f"typeof {type_text(t['queryType'])}"
    if k == "indexedAccess":
        return f"{type_text(t['objectType'])}[{type_text(t['indexType'])}]"
    if k == "conditional":
        return f"{type_text(t['checkType'])} extends {type_text(t['extendsType'])} ? {type_text(t['trueType'])} : {type_text(t['falseType'])}"
    if k == "mapped":
        return f"{{ [{t['parameter']} in {type_text(t['parameterType'])}]: {type_text(t['templateType'])} }}"
    if k == "predicate":
        return f"{'asserts ' if t.get('asserts') else ''}{t['name']}{' is ' + type_text(t['targetType']) if t.get('targetType') else ''}"
    if k == "templateLiteral":
        return "`" + t.get("head", "") + "".join(f"${{{type_text(a)}}}{b}" for a, b in t.get("tail", [])) + "`"
    if k == "reflection":
        d = t["declaration"]
        if d.get("signatures"):
            sig = d["signatures"][0]
            return f"({params_text(sig)}) => {type_text(sig.get('type'))}"
        parts = [f"{c['name']}{'?' if c.get('flags', {}).get('isOptional') else ''}: {type_text(member_type(c))}" for c in d.get("children", [])]
        parts += [f"[{p['name']}: {type_text(p.get('type'))}]: {type_text(x.get('type'))}" for x in d.get("indexSignatures", []) for p in x.get("parameters", [])]
        return "{ " + "; ".join(parts) + " }" if parts else "{}"
    return k or ""


def member_type(
    c: dict,  # A property, an accessor or a method of TypeDoc's JSON
) -> dict | None:  # Its type: a property's own, an accessor's getter's, or a method's as a function
    "Find the type of a member, whatever its kind."
    if c.get("type"):
        return c["type"]
    if c.get("getSignature"):
        return c["getSignature"].get("type")
    if c.get("signatures"):
        return {"type": "reflection", "declaration": {"signatures": c["signatures"]}}
    return None


def param_name(
    p: dict,  # A parameter of TypeDoc's JSON
) -> str:  # Its name; `props` for a destructured one, which TypeDoc calls `__namedParameters`
    "Name a parameter as a reader would."
    return "props" if p["name"] == "__namedParameters" else p["name"]


def params_text(
    sig: dict,  # A signature of TypeDoc's JSON
) -> str:  # Its parameters as TypeScript writes them, without the parentheses
    "Write the parameters of a signature: each with its type and default."
    parts = []
    for p in sig.get("parameters", []):
        flags = p.get("flags", {})
        text = ("..." if flags.get("isRest") else "") + param_name(p) + ("?" if flags.get("isOptional") else "")
        text += f": {type_text(p.get('type'))}" if p.get("type") else ""
        text += f" = {p['defaultValue']}" if p.get("defaultValue") not in (None, "...") else ""
        parts.append(text)
    return ", ".join(parts)


def type_params(
    node: dict,  # A signature, a class, an interface or a type of TypeDoc's JSON
) -> str:  # Its type parameters, `<T extends X = Y>`; empty when it has none
    "Write the type parameters of an item."
    out = []
    for p in node.get("typeParameters") or []:
        text = p["name"] + (f" extends {type_text(p['type'])}" if p.get("type") else "")
        out.append(text + (f" = {type_text(p['default'])}" if p.get("default") else ""))
    return f"<{', '.join(out)}>" if out else ""


LIST_ITEM = re.compile(r"\s*(?:[-*+]|\d+[.)])\s")


def structure(
    text: str,  # A comment, whose lines a `*` or the code's indentation may have pushed right
) -> str:  # The same Markdown: prose at the left, lists as lists with their nesting, fenced code as it is
    "Keep a comment's paragraphs and lists: an indented `- item` stays a list item, and indented prose is no code block."
    out: list[str] = []
    fence, shift, base = "", 0, None  # the open fence and its indent; the indent of the list we are in, or `None`
    for line in text.split("\n"):
        indent = len(line) - len(line.lstrip())
        if fence:
            if line.strip().startswith(fence):
                fence = ""
            out.append(line[min(shift, indent) :])
            continue
        if line.lstrip().startswith(("```", "~~~")):
            fence, shift = line.lstrip()[:3], indent
            out.append(line.lstrip())
            continue
        if not line.strip():
            base = None if out and not out[-1].strip() else base  # two blank lines, or prose after one, end a list
            out.append("")
            continue
        m = LIST_ITEM.match(line)
        if m and base is None and out and out[-1].strip():
            if re.match(r"\s*\d+[.)]", line) and not re.match(r"\s*1[.)]", line):
                out.append(line.lstrip())  # `2024. was` in prose: only a list from 1 breaks a paragraph
                continue
            out.append("")  # a list after a line of prose starts its own block
        if m and base is None:
            base = indent
        if base is not None and (m or indent > base):
            out.append(line[min(base, indent) :])  # inside a list: keep the nesting
        else:
            base = None
            out.append(line.lstrip())
    return "\n".join(out)


def comment_text(
    parts: list[dict] | None,  # The parts of a comment: text, code and inline tags
) -> str:  # The comment as Markdown; a `{@link Name}` becomes `` `Name` ``, which links when linkify is on
    "Write the parts of a TypeDoc comment as Markdown."
    out = []
    for p in parts or []:
        if p.get("kind") == "inline-tag":
            out.append(f"`{p.get('text', '').strip()}`")
        elif p.get("kind") == "code":
            out.append(p.get("text", ""))
        else:
            out.append(escape_angles(p.get("text", "")))
    return "".join(out).strip()


def doc(
    node: dict | None,  # An item or a signature of TypeDoc's JSON
) -> str:  # Its JSDoc comment as Markdown: the summary, then `@remarks`, `@example` and `@deprecated`
    "Write the doc comment of an item."
    c = (node or {}).get("comment") or {}
    parts = [comment_text(c.get("summary"))]
    for tag in c.get("blockTags", []):
        said = comment_text(tag.get("content"))
        if tag["tag"] == "@deprecated":
            parts.append(f"Deprecated. {said}".strip())
        elif tag["tag"] in ("@remarks", "@example"):
            parts.append(said)
    return structure("\n\n".join(p for p in parts if p))


def returns_doc(
    sig: dict,  # A signature of TypeDoc's JSON
) -> str:  # The text of its `@returns` tag; empty when there is none
    "Read a signature's `@returns`."
    for tag in (sig.get("comment") or {}).get("blockTags", []):
        if tag["tag"] in ("@returns", "@return"):
            return comment_text(tag.get("content"))
    return ""


def is_void(
    t: dict | None,  # A return type
) -> bool:  # Whether it is `void`, which needs no row and no comment
    "Tell whether a return type says nothing comes back."
    return not t or (t.get("type") == "intrinsic" and t.get("name") == "void")


class Module:
    "One page of the reference: an entry point or a file, and what it exports."

    def __init__(
        self,
        name: str,  # The module's name, such as `components/Button`
        node: dict,  # Its part of TypeDoc's JSON
        ids: dict[int, dict],  # Every item of the JSON by its id, to follow a type to its fields
        src: Sources,  # The project's source files
    ) -> None:
        "Keep what a page needs."
        self.name, self.node, self.ids, self.src = name, node, ids, src

    def summary(self) -> str:  # The module's comment; its opening comment when TypeDoc has none
        "Read the module's comment."
        said = doc(self.node)
        if said or not self.node.get("sources"):
            return said
        name = self.node["sources"][0]["fileName"]
        try:
            return header_comment((self.src.project / name).read_text(encoding="utf-8"))
        except OSError:
            return ""

    def items(self) -> list[tuple[dict, str, int]]:  # Each item, its name on the page, and its heading level
        "List what the module exports, in source order: each item, then its methods and its namespace's items."
        return list(self.walk(self.node.get("children", []), "", 2))

    def walk(
        self,
        children: list[dict],  # Items of TypeDoc's JSON
        prefix: str,  # The name of the class or namespace they are in, with a dot; empty at the top
        level: int,  # Their heading level
    ) -> list[tuple[dict, str, int]]:  # Each item, its name on the page, and its heading level
        "List items and what they hold, as `items` does."
        out = []
        for c in children:
            if c["kind"] in (REFERENCE, MODULE) or c.get("inheritedFrom") or c.get("flags", {}).get("isPrivate") or c["name"].startswith("#"):
                continue  # a re-export has its entry where it is declared
            name = prefix + (self.default_name(c) if c["name"] == "default" else c["name"])
            out.append((c, name, level))
            if c["kind"] in (CLASS, INTERFACE):
                out += self.walk([m for m in c.get("children", []) if m["kind"] == METHOD], name + ".", level + 1)
            elif c["kind"] == NAMESPACE:
                out += self.walk(c.get("children", []), name + ".", level + 1)
        return out

    def default_name(
        self,
        c: dict,  # An item that the file exports as `default`
    ) -> str:  # The name the source gives it, as in `export default function Button`; `default` when it has none
        "Name a default export by the name in its source."
        src = (c.get("sources") or [{}])[0]
        lines = self.src.lines(src.get("fileName", ""))
        line = src.get("line", 0)
        code = lines[line - 1].code if 0 < line <= len(lines) else ""
        m = re.search(rf"export\s+default\s+(?:abstract\s+)?(?:async\s+)?(?:function\s*\*?|class)\s*({NAME})", code)
        m = m or re.search(rf"export\s+default\s+({NAME})\s*;?\s*$", code)
        return m.group(1) if m else "default"

    def fields(
        self,
        t: dict | None,  # A type: an object type, or a reference to an interface or a type
    ) -> list[Field] | None:  # Its fields, or `None` when it is no object type
        "Find the fields of a type, following a reference; a type that is not exported is read from its file."
        if not t:
            return None
        if t.get("type") == "reflection" and "children" in t["declaration"]:
            return self.own_fields(t["declaration"])
        if t.get("type") == "intersection":  # `Props & { more?: string }`: the fields of each part
            parts = [self.fields(x) for x in t["types"]]
            return None if any(x is None for x in parts) else [f for x in parts for f in x]
        if t.get("type") != "reference":
            return None
        target = t.get("target")
        if isinstance(target, int) and target in self.ids:
            node = self.ids[target]
            if node["kind"] == INTERFACE or (node["kind"] == ALIAS and "children" in node):
                return self.own_fields(node, listed=True)
            if node["kind"] == ALIAS:
                return self.fields(node.get("type"))
            return None
        if isinstance(target, dict) and target.get("packagePath") and "node_modules" not in target["packagePath"]:
            name = target["packagePath"]
            path = self.src.project / name
            if path.suffix in (".ts", ".tsx", ".mts", ".cts") and path.exists():
                return declared_fields(self.src.lines(name), target.get("qualifiedName", t.get("name", "")))
        return None

    def own_fields(
        self,
        node: dict,  # An interface, a type or a class of TypeDoc's JSON, with `children`
        listed: bool = False,  # Whether the node has an entry of its own, where `check` reports its fields
    ) -> list[Field]:  # Its properties and accessors, each with the comment after it or its JSDoc
        "List the fields of an interface, a type or a class."
        out = []
        for c in node.get("children", []):
            if c["kind"] not in (PROPERTY, ACCESSOR) or c.get("inheritedFrom") or c.get("flags", {}).get("isPrivate"):
                continue
            said = self.src.comment(c) or doc(c) or doc(c.get("getSignature"))
            optional = bool(c.get("flags", {}).get("isOptional"))
            out.append(Field(c["name"], type_text(member_type(c)), optional, said, shared=self.src.shared(c), listed=listed))
        return out

    def props(
        self,
        name: str,  # The item's name on the page
        sig: dict,  # Its first signature
    ) -> list[Field] | None:  # The fields of its props, when it is a React component; otherwise `None`
        "List a React component's props: a component is a function with a capital name that returns JSX and takes no parameter or one props object."
        params = sig.get("parameters", [])
        if not component(name, sig):
            return None
        return self.fields(params[0].get("type")) if params else []

    def named(
        self,
        sig: dict,  # A signature of TypeDoc's JSON
    ) -> dict:  # The same, its destructured parameter named `props` again when TypeDoc named it after the `@param` of one of its fields
        "Undo TypeDoc's naming of a destructured parameter after a `@param` that is JSDoc's for one of its fields, as `@param a` for `{ a }`."
        params = sig.get("parameters") or []
        if not params or params[0]["name"] == "__namedParameters" or not self.read(sig).destructured:
            return sig
        if params[0]["name"] not in {f.name for f in self.fields(params[0].get("type")) or []}:
            return sig
        first = {k: v for k, v in params[0].items() if k != "comment"} | {"name": "__namedParameters"}
        return sig | {"parameters": [first, *params[1:]]}

    def read(
        self,
        sig: dict,  # A signature of TypeDoc's JSON
    ) -> Signature:  # What its source says
        "Read a signature's comments from its source."
        src = (sig.get("sources") or [{}])[0]
        return read_signature(self.src.lines(src.get("fileName", "")), src.get("line", 0), src.get("character", 0))

    def param_rows(
        self,
        name: str,  # The item's name on the page
        sig: dict,  # A signature of TypeDoc's JSON
        constructor: bool = False,  # Whether it is a class's constructor, which has no return row
    ) -> tuple[list[list[str]], list[str]]:  # The rows of its parameters table, and its gaps for `check`
        "Describe a signature by its parameters and its return; a component by its props."
        said, rows, gaps = self.read(sig), [], []
        props = self.props(name, sig)
        if props is not None:
            src = (sig.get("sources") or [{}])[0]
            tags = param_tags(self.src.lines(src.get("fileName", "")), src.get("line", 0)) if props else {}
            for f in props:
                default = f"`{said.defaults[f.name]}`" if f.name in said.defaults else "optional" if f.optional else "required"
                text = f.doc or escape_angles(tags.get(f.name) or tags.get("." + f.name, ""))
                rows.append([f"`{f.name}`", type_cell(f.type), default, one_line(text)])
                gaps += [] if text or f.listed else [f"({f.name}): {gap(f)}"]  # a field of a type with its own entry is reported there
        else:
            for i, p in enumerate(sig.get("parameters", [])):
                flags = p.get("flags", {})
                text = (said.params[i] if i < len(said.params) else "") or doc(p)
                default = "" if flags.get("isRest") else f"`{p['defaultValue']}`" if p.get("defaultValue") else "optional" if flags.get("isOptional") else "required"
                rows.append([f"`{param_name(p)}`", type_cell(type_text(p.get("type"))), default, one_line(text)])
                gaps += [] if text else [f"({param_name(p)}): no comment"]
        if not constructor and not is_void(sig.get("type")):
            text = said.returns or returns_doc(sig)
            rows.append(["returns", type_cell(type_text(sig.get("type"))), "", one_line(text)])
            gaps += [] if text or component(name, sig) else [": no return comment"]  # a component returns what it draws
        return rows, gaps

    def entry(
        self,
        c: dict,  # One item of TypeDoc's JSON
        name: str,  # Its name on the page, such as `Rect.area`
        level: int,  # Its heading level
    ) -> tuple[str, list[str]]:  # The Markdown of its entry, without the heading, and its gaps for `check`
        "Write one item: its signature, its doc comment and its table."
        kind, short = c["kind"], name.rpartition(".")[2]
        gaps = [] if doc(c) or doc((c.get("signatures") or [None])[0]) else [": no doc comment"]
        if kind in (FUNCTION, METHOD):
            sigs = [self.named(x) if self.props(name, x) is not None else x for x in c.get("signatures", [])]
            word = "function " if kind == FUNCTION else "static " if c.get("flags", {}).get("isStatic") else ""
            code = "\n".join(f"{word}{short}{type_params(x)}({params_text(x)}): {type_text(x.get('type'))}" for x in sigs)
            rows, more = self.param_rows(name, sigs[0]) if sigs else ([], [])
            return self.parts(code, doc(c) or doc(sigs[0] if sigs else None), table(rows, ["Parameter", "Type", "Default", "Description"])), gaps + more
        if kind == CLASS:
            heads = [f"class {short}{type_params(c)}"]
            heads += [f"extends {', '.join(type_text(x) for x in c['extendedTypes'])}"] if c.get("extendedTypes") else []
            heads += [f"implements {', '.join(type_text(x) for x in c['implementedTypes'])}"] if c.get("implementedTypes") else []
            ctor = next((m for m in c.get("children", []) if m["kind"] == CONSTRUCTOR), None)
            code, rows, more = " ".join(heads), [], []
            if ctor and ctor.get("signatures"):
                code += "\n" + "\n".join(f"new {short}({params_text(x)})" for x in ctor["signatures"])
                rows, more = self.param_rows(name, ctor["signatures"][0], constructor=True)
            fields = self.own_fields(c)
            gaps += more + [f".{f.name}: {gap(f)}" for f in fields if not f.doc]
            return self.parts(code, doc(c), table(rows, ["Parameter", "Type", "Default", "Description"]), fields_table(fields)), gaps
        if kind == INTERFACE or (kind == ALIAS and "children" in c):
            word = "interface" if kind == INTERFACE else "type"
            heads = [f"{word} {short}{type_params(c)}"]
            heads += [f"extends {', '.join(type_text(x) for x in c['extendedTypes'])}"] if c.get("extendedTypes") else []
            fields = self.own_fields(c)
            gaps += [f".{f.name}: {gap(f)}" for f in fields if not f.doc]
            return self.parts(" ".join(heads), doc(c), fields_table(fields)), gaps
        if kind == ALIAS:
            return self.parts(f"type {short}{type_params(c)} = {type_text(c.get('type'))}", doc(c)), gaps
        if kind == ENUM:
            rows = [[f"`{m['name']}`", type_cell(type_text(m.get("type"))), one_line(self.src.comment(m) or doc(m))] for m in c.get("children", []) if m["kind"] == MEMBER]
            return self.parts(f"enum {short}", doc(c), table(rows, ["Member", "Value", "Description"])), gaps
        if kind == VARIABLE:
            word = "const" if c.get("flags", {}).get("isConst") else "let"
            return self.parts(f"{word} {short}: {type_text(c.get('type'))}", doc(c)), gaps
        if kind == NAMESPACE:
            return self.parts("", doc(c)), gaps
        return self.parts("", doc(c)), gaps

    def parts(
        self,
        code: str,  # The signature, or empty for none
        *rest: str,  # The doc comment and the tables, each empty when there is none
    ) -> str:  # The parts as Markdown, the signature in a `ts` block
        "Join the parts of an entry."
        return "\n\n".join(p for p in [f"```ts\n{code}\n```" if code else "", *rest] if p)


def gap(
    f: Field,  # A field with no comment
) -> str:  # What `check` says of it
    "Say why a field has no comment: it has none, or the comment on its line follows more than the field, so it belongs to no field."
    said = "no comment: the comment on its line follows more than this field, so it is no field's; put each field on its own line, or give each a JSDoc"
    return said if f.shared else "no comment"


def component(
    name: str,  # A function's name on the page
    sig: dict,  # Its signature
) -> bool:  # Whether it is a React component: a capital name, JSX back, and no parameter or one
    "Tell a React component by React's rules: its props may be of any object type, even one that smalldocs cannot read, but not a string or a number."
    params = sig.get("parameters", [])
    if len(params) > 1 or not name.rpartition(".")[2][:1].isupper() or not is_jsx(sig.get("type")):
        return False
    return not params or not primitive(params[0].get("type") or {})


def primitive(
    t: dict,  # A type
) -> bool:  # Whether it is a string, a number, a boolean, a bigint, a symbol, a literal, or a union of them, which no props object is
    "Tell a type that no props object can have."
    if t.get("type") == "union":
        return all(primitive(x) for x in t["types"])
    return t.get("type") == "literal" or (t.get("type") == "intrinsic" and t.get("name") in PRIMITIVES)


def fields_table(
    fields: list[Field],  # The fields of an interface, a type or a class
) -> str:  # A Markdown table of them: type and description; empty when there are none
    "Describe an object type by its fields."
    return table([[f"`{f.name}`" + ("?" if f.optional else ""), type_cell(f.type), one_line(f.doc)] for f in fields], ["Field", "Type", "Description"])


def source_link(
    s: Settings,  # The settings
    src: Sources,  # The project's source files
    c: dict,  # An item of TypeDoc's JSON
) -> str:  # A Markdown link to the line that defines it, or empty when there is no `source`
    "Link an item to the line that defines it."
    where = (c.get("sources") or [{}])[0]
    if not s.source or not where.get("fileName"):
        return ""
    path = (src.project / where["fileName"]).resolve()
    try:
        file = path.relative_to(s.root) if s.root else path
    except ValueError:
        if path.is_relative_to(src.project.resolve()) and "node_modules" not in path.parts:
            src.unlinked.add(where["fileName"])  # the project's own file; a package's can have no link
        return ""
    return f"[source]({s.source}/{link_path(file.as_posix())}#L{where.get('line', 1)}){{.source-link}}"


def modules(
    data: dict,  # TypeDoc's JSON
    src: Sources,  # The project's source files
) -> list[Module]:  # One module per entry point, named from the folder they share
    "List the modules of TypeDoc's JSON: the project itself for one entry point, its modules for several."
    ids: dict[int, dict] = {}

    def index(o: object) -> None:
        "Note every item of the JSON under its id."
        if isinstance(o, dict):
            if isinstance(o.get("id"), int) and "kind" in o:
                ids[o["id"]] = o
            for v in o.values():
                index(v)
        elif isinstance(o, list):
            for v in o:
                index(v)

    index(data)
    mods = [c for c in data.get("children", []) if c["kind"] == MODULE]
    if not mods:
        entry = next(iter((data.get("files") or {}).get("entries", {}).values()), "index")
        name = str(data.get("name")).rpartition("/")[2] if data.get("name") not in (None, "", "Documentation") else src.project.name
        stem = re.sub(r"\.[cm]?tsx?$", "", Path(entry).name)
        return [Module(name if stem == "index" else stem, data, ids, src)]
    names = [m["name"] for m in mods]
    top = names[0].split("/")[0] + "/"
    if len(names) > 1 and all(n.startswith(top) for n in names):
        names = [n[len(top) :] for n in names]  # `src/` is in every name, so it says nothing
    names = [n[: -len("/index")] if n.endswith("/index") else n for n in names]
    return [Module(n, m, ids, src) for n, m in zip(names, mods, strict=True)]


def page_paths(
    mods: list[Module],  # The modules
    taken: set[str] = frozenset(),  # Pages that someone wrote, which a build never writes over, such as `components/index.qmd`
) -> list[str]:  # The path of each one's page in `out`, without `.qmd`, as its folders: `components/Badge`
    "Place each module's page as its file is placed; a module named as a folder, from its `index.ts`, is that folder's `index`, or sits beside a hand-written one."
    names, spelt = [m.name for m in mods], {}
    out = []
    for n in names:
        parts = n.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise ValueError(f"a TypeScript module has a name that is no path inside api.out: {n!r}")
        for k in range(1, len(parts)):  # a folder keeps the spelling it first had: `A/x` and `a/y` share one folder, as on macOS
            parts[k - 1] = spelt.setdefault("/".join(parts[:k]).casefold(), parts[k - 1])
        if any(o.casefold().startswith(n.casefold() + "/") for o in names):
            held = page_key("/".join([*parts, "index.qmd"])) in {page_key(x) for x in taken}
            parts.append(parts[-1] if held else "index")  # a hand-written index keeps its place
        elif parts[-1].casefold() == "index":
            parts[-1] += "-module"  # `index.qmd` is the page of its folder
        out.append("/".join(parts))
    return unique(out)


def written_pages(
    s: Settings,  # The settings
    mods: list[Module],  # The modules
    taken: set[str] = frozenset(),  # Pages that someone wrote, from `hand_written`
) -> tuple[dict[str, str], dict[str, str], set[str]]:  # Each page's text by its path in `out`; the index of names; the full names in it
    "Write every page in memory: one per module, in its folder, and an `index.qmd` for each folder with none, that lists its pages."
    rels = page_paths(mods, taken)
    summaries = {f"{rel}.qmd": one_line(m.summary().partition("\n\n")[0]) for m, rel in zip(mods, rels, strict=True)}
    out: dict[str, str] = {}
    names: dict[str, str] = {}
    full: set[str] = set()
    for mod, rel in zip(mods, rels, strict=True):
        folder = rel.rpartition("/")[0] if rel.endswith("/index") or rel == "index" else None
        out[f"{rel}.qmd"] = page(s, mod, folder_listing(s.out, folder, summaries) if folder is not None else "")
        for id_ in unique([n for _, n, _ in mod.items()]):
            target = f"{link_path(f'/{s.out}/{rel}.qmd')}#{id_}"
            names.setdefault(id_, target)
            names[f"{mod.name}.{id_}"] = target
            full.add(f"{mod.name}.{id_}")
    return out | folder_indexes(s.out, summaries, taken), names, full


def page(
    s: Settings,  # The settings
    mod: Module,  # One module
    pages: str = "",  # The table of its folder's pages, when it is the folder's index
) -> str:  # The text of its `.qmd` page
    "Write one module's page: front matter, the module's comment, its folder's pages, then an entry for each item, with an id and a source link."
    said = mod.summary()
    head, _, rest = said.partition("\n\n")
    rest = structure(textwrap.dedent(rest.strip("\n"))).rstrip()  # prose indented under a `*` is no code block
    out = [x for x in (rest, pages) if x]
    again = [f"`{c['name']}`" for c in mod.node.get("children", []) if c["kind"] == REFERENCE]
    if again:
        out.append(f"It exports again {', '.join(again)}, from the modules that declare them.")
    items = mod.items()
    for (c, name, level), id_ in zip(items, unique([n for _, n, _ in items]), strict=True):
        word = "static " if c.get("flags", {}).get("isStatic") else KEYWORD.get(c["kind"], "")
        link = source_link(s, mod.src, c)
        body, _ = mod.entry(c, name, level)
        out.append("\n\n".join(p for p in [f"{'#' * level} {heading_text(word + name)} {{#{id_}}}", link, body] if p))
    return front_matter(mod.name.rpartition("/")[2], one_line(head)) + "\n\n".join(out) + "\n"


def load(
    s: Settings,  # The settings
) -> list[Module]:  # The modules that TypeDoc finds
    "Run TypeDoc and read its modules."
    data, project = typedoc_json(s)
    return modules(data, Sources(project))


def build(
    s: Settings,  # The settings
) -> list[Path]:  # The pages written
    "Write one reference page per entry point or file, and `_symbols.json`, the index of names that links use."
    taken = hand_written(out_folder(s))  # before TypeDoc runs, which refuses an `out` outside the site
    mods = load(s)
    texts, index, full = written_pages(s, mods, taken)
    warn_unlinked(s, mods[0].src.unlinked if mods else set())
    return write_reference(s, texts, index, taken, full)


def check(
    s: Settings,  # The settings
    shown: bool = False,  # Hold only what the pages show; TypeDoc gives only what is exported, so this is always so
) -> int:  # The exit code: 0 when nothing is missing, 1 otherwise
    "Print how much of each module is documented, then every gap, then the total."
    mods = load(s)
    found, done, total = [], 0, 0
    width = max((len(m.name) for m in mods), default=10)
    for mod in mods:
        found += [] if mod.summary() else [f"{mod.name}: no module comment"]
        items = mod.items()
        complete = 0
        for c, name, level in items:
            gaps = mod.entry(c, name, level)[1]
            complete += not gaps
            found += [f"{mod.name}:{name}{g}" for g in gaps]
        print(f"{mod.name:{width}s} {complete:3d} of {len(items):3d}")
        done, total = done + complete, total + len(items)
    print("\n".join(["", *found]) if found else "")
    print(f"{done} of {total} functions, classes, interfaces, types and constants are documented")
    return 1 if found else 0

