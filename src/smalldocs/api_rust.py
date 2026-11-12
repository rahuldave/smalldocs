"""The API reference of a Rust crate, made from rustdoc's JSON: one page per module, as the Python pages are.

    api:
      language: rust
      manifest: ../Cargo.toml     # the crate, from the site's folder; the root's Cargo.toml by default
      toolchain: nightly          # the toolchain that runs rustdoc, which needs `-Z unstable-options`
      private: false              # document private items too; a crate with only a binary always does
      out: api
      source: https://github.com/me/mycrate/blob/main

rustdoc writes what it knows of the crate as JSON. It does not keep the comment after a parameter, so
that comment is read from the source, by the lines that the JSON gives. Only the standard library is used.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .api import Settings, table

FORMATS = (57, 61)  # The versions of rustdoc's JSON that smalldocs reads
COMPILER_TRAITS = {"StructuralPartialEq", "StructuralEq"}  # Markers that `#[derive(PartialEq)]` adds, which say nothing to a reader
LIB_KINDS ={"lib", "rlib", "dylib", "cdylib", "staticlib", "proc-macro"}
HIDDEN_KINDS = {"impl", "use", "module", "extern_crate", "primitive", "struct_field", "variant", "assoc_type", "assoc_const"}
RUST_FENCE = {"", "rust", "ignore", "no_run", "should_panic", "compile_fail", "test_harness", "edition2015", "edition2018", "edition2021", "edition2024"}
EXTERNAL_PAGE = {
    "struct": "struct",
    "enum": "enum",
    "trait": "trait",
    "union": "union",
    "macro": "macro",
    "constant": "constant",
    "static": "static",
    "type_alias": "type",
    "function": "fn",
    "trait_alias": "traitalias",
    "primitive": "primitive",
    "proc_attribute": "attr",
    "proc_derive": "derive",
}
MEMBER_ANCHOR = {"function": "method", "variant": "variant", "struct_field": "structfield", "assoc_const": "associatedconstant", "assoc_type": "associatedtype"}
LINK = re.compile(r"(`+[^`]*`+)|\[((?:[^\[\]]|\[[^\[\]]*\])+)\](\([^)\s]*\)|\[[^\]]*\])?")  # a code span, which is left alone, or a link
KEYWORDS = set(  # A name that is one of these is written `r#name` in the source
    re.findall(
        r"\w+",
        "as async await break const continue crate dyn else enum extern false fn for gen if impl in let loop match mod move mut pub ref return "
        "static struct super trait true try type unsafe use where while abstract become box do final macro override priv typeof unsized virtual yield",
    )
)
HTML_START = re.compile(  # what may follow a `<` that starts HTML on purpose: a common tag in lower case, an autolink or a comment
    r"(?:/?(?:a|b|i|p|s|u|br|hr|h[1-6]|em|strong|del|ins|abbr|code|pre|kbd|sub|sup|span|div|img|details|summary|table|thead|tbody|tr|td|th|ul|ol|li|dl|dt|dd"
    r"|blockquote)(?=[\s>/])|https?://|mailto:|[^\s<>@`]+@[^\s<>@`]+>|!--)"
)  # in lower case only, so that a generic such as `Wrapper<B>` is text
LIST_ITEM = re.compile(r"^(?:[*+-]|\d{1,9}[.)])(?:\s|$)")  # A line that starts a list item, at the left edge
MARK = "# written by smalldocs api build; a build writes over it"  # The first line of the front matter of each page a build writes
DISAMBIGUATOR =re.compile(r"^(`?)(?:struct|enum|trait|union|mod|module|const|constant|fn|function|method|derive|type|value|macro|prim|primitive|static|field|variant|tymethod|attr)@")
REF_DEF = re.compile(r"^( {0,3}\[[^\]]+\]:\s*)(\S+)(.*)$")
ARG_LINE = re.compile(r"^\s*[*-]\s+`?([A-Za-z_][A-Za-z0-9_]*)`?\s*(?:-|:|–|—)\s*(.*)$")


# ---------------------------------------------------------------- running rustdoc


def cargo(
    args: list[str],  # The arguments after `cargo +TOOLCHAIN`
    s: Settings,  # The settings, for the toolchain
    env: dict | None = None,  # More environment variables
    cwd: Path | None = None,  # The folder cargo runs in
) -> str:  # What cargo wrote to its standard output
    "Run cargo with the toolchain of the settings; stop with a clear message when cargo or the toolchain is missing, or cargo fails."
    exe = shutil.which("cargo")
    if exe is None:
        raise ValueError("the api settings say language: rust, but cargo is not installed. Install Rust with rustup: https://rustup.rs")
    run_env = {**os.environ, "RUSTUP_AUTO_INSTALL": "0", **(env or {})}
    done = subprocess.run([exe, f"+{s.toolchain}", *args], capture_output=True, text=True, env=run_env, cwd=cwd)
    if done.returncode == 0:
        return done.stdout
    err = done.stderr.strip()
    if "toolchain" in err and "is not installed" in err:
        raise ValueError(f"the Rust toolchain {s.toolchain} is not installed. Install it with `rustup toolchain install {s.toolchain}`; it does not replace your default toolchain")
    if "no such command" in err and f"+{s.toolchain}" in err:
        raise ValueError(f"cargo +{s.toolchain} needs rustup, and this cargo is not rustup's. Install Rust with rustup: https://rustup.rs")
    tail = "\n".join(err.splitlines()[-20:])
    raise ValueError(f"cargo {args[0]} failed:\n{tail}")


def cache_folder() -> Path:  # The user's own folder for rustdoc's output, in the temporary folder
    "Make the folder that holds rustdoc's output and lock files: one per user, that only the user can write, so that no one else can plant files in it."
    user = getattr(os, "getuid", lambda: None)()
    folder = Path(tempfile.gettempdir()) / f"smalldocs-rustdoc-{user if user is not None else os.environ.get('USERNAME', 'user')}"
    folder.mkdir(mode=0o700, exist_ok=True)
    if user is not None and (folder.stat().st_uid != user or folder.stat().st_mode & 0o022):
        raise ValueError(f"{folder} belongs to another user, or others can write to it; remove it, and smalldocs makes it again")
    return folder


def rustdoc(
    s: Settings,  # The settings
    private: bool = False,  # Document private items too
) -> tuple[dict, Path]:  # rustdoc's JSON of the crate, and the folder its file names start from (the workspace's root)
    "Run rustdoc on the crate, with its output and its lock file in a temporary folder, so that nothing is written into the project."
    manifest = (s.manifest or (s.root or s.site) / "Cargo.toml").resolve()
    if not manifest.is_file():
        raise ValueError(f"the api settings: there is no Cargo.toml at {manifest}; set manifest to the crate's Cargo.toml, from the site's folder")
    work = cache_folder() / hashlib.sha256(str(manifest).encode()).hexdigest()[:16]
    work.mkdir(exist_ok=True)
    lock = work / "Cargo.lock"
    here = manifest.parent  # cargo reads `.cargo/config.toml` from the folder it runs in, so it runs in the crate's
    meta = json.loads(cargo(["metadata", "--no-deps", "--format-version", "1", "--manifest-path", str(manifest)], s, cwd=here))
    workspace = Path(meta["workspace_root"])
    project_lock = workspace / "Cargo.lock"
    before = project_lock.read_bytes() if project_lock.is_file() else None
    if before is not None:
        lock.write_bytes(before)  # cargo may update the lock file; it updates this copy
    package = next((p for p in meta["packages"] if Path(p["manifest_path"]).resolve() == manifest), None)
    if package is None:
        raise ValueError(f"{manifest} is a workspace with no package of its own; set manifest to the Cargo.toml of one of its packages")
    libs = [t for t in package["targets"] if LIB_KINDS & set(t["kind"])]
    bins = [t for t in package["targets"] if "bin" in t["kind"]]
    if libs:
        target, pick = libs[0], ["--lib"]
    elif bins:
        target = next((t for t in bins if t["name"] == package["name"]), bins[0])
        pick, private = ["--bin", target["name"]], True  # a binary has no public API, so its private items are documented
    else:
        raise ValueError(f"{manifest} has no library and no binary to document")
    flags = ["-Z", "unstable-options", "--output-format", "json", *(["--document-private-items"] if private else [])]
    lockfile = "resolver.lockfile-path=" + json.dumps(str(lock))
    name = f"{target['name'].replace('-', '_')}.json"
    for old in (work / "target").glob(f"**/doc/{name}"):
        old.unlink()  # so that a JSON from an earlier run is never read
    try:
        cargo(["rustdoc", "--manifest-path", str(manifest), "--config", lockfile, *pick, "--", *flags], s, {"CARGO_TARGET_DIR": str(work / "target")}, cwd=here)
    finally:
        after = project_lock.read_bytes() if project_lock.is_file() else None
        if after != before and before is None:  # a cargo that ignores `resolver.lockfile-path` wrote the project's lock file
            project_lock.unlink()
        elif after != before:
            project_lock.write_bytes(before)  # put it back as it was
    found = sorted((work / "target").glob(f"**/doc/{name}"))
    if not found:
        raise ValueError(f"cargo rustdoc ran, but wrote no {name} under {work / 'target'}")
    data = json.loads(found[0].read_text(encoding="utf-8"))
    version = data.get("format_version")
    if version not in FORMATS:
        known = " and ".join(str(v) for v in FORMATS)
        raise ValueError(
            f"rustdoc of the toolchain {s.toolchain} wrote JSON format {version}, and smalldocs reads formats {known}. "
            "Set toolchain to a nightly that writes one of them, such as nightly-2026-11-11"
        )
    return data, workspace


# ---------------------------------------------------------------- writing types and signatures


def path_text(
    p: dict,  # A path of rustdoc's JSON: `path`, `id` and `args`
) -> str:  # Its last name with its generic arguments, as rustdoc's pages show it
    "Write a path as its last name and its arguments, such as `Option<T>`."
    return p["path"].rpartition("::")[2] + args_text(p.get("args"))


def args_text(
    args: dict | str | None,  # The generic arguments of a path
) -> str:  # They as Rust writes them, such as `<T, Item = u8>` or `(u8) -> bool`
    "Write the generic arguments of a path."
    if not args:
        return ""
    if args == "return_type_notation":
        return "(..)"
    if "parenthesized" in args:
        p = args["parenthesized"]
        out = p.get("output")
        return "(" + ", ".join(type_text(t) for t in p["inputs"]) + ")" + (f" -> {type_text(out)}" if out else "")
    a = args.get("angle_bracketed") or {}
    parts = []
    for arg in a.get("args", []):
        if arg == "infer":
            parts.append("_")
        elif "lifetime" in arg:
            parts.append(arg["lifetime"])
        elif "type" in arg:
            parts.append(type_text(arg["type"]))
        elif "const" in arg:
            parts.append(arg["const"].get("expr") or arg["const"].get("value") or "_")
    for c in a.get("constraints", []):
        binding = c.get("binding") or {}
        name = c["name"] + args_text(c.get("args"))
        if "equality" in binding:
            term = binding["equality"]
            parts.append(f"{name} = {type_text(term['type']) if 'type' in term else term.get('constant', {}).get('expr', '_')}")
        elif "constraint" in binding:
            parts.append(f"{name}: {bounds_text(binding['constraint'])}")
    return f"<{', '.join(parts)}>" if parts else ""


def bounds_text(
    bounds: list[dict],  # The bounds of a generic, a trait or an `impl Trait`
) -> str:  # They joined by ` + `
    "Write a list of bounds, such as `Clone + 'a`."
    out = []
    for b in bounds:
        if "trait_bound" in b:
            t = b["trait_bound"]
            pre = "?" if t.get("modifier") == "maybe" else "~const " if t.get("modifier") == "maybe_const" else ""
            hrtb = generic_params_text(t.get("generic_params") or [])
            out.append(f"{'for' + hrtb + ' ' if hrtb else ''}{pre}{path_text(t['trait'])}")
        elif "outlives" in b:
            out.append(b["outlives"])
        elif "use" in b:
            out.append("use<" + ", ".join(u if isinstance(u, str) else next(iter(u.values())) for u in b["use"]) + ">")
    return " + ".join(out)


def type_text(
    t: dict | None,  # A type of rustdoc's JSON
) -> str:  # The type as Rust writes it, each path by its last name
    "Write a type as Rust does: `&mut [u8]`, `Option<T>`, `impl Fn(u8) -> bool`."
    if t is None:
        return "()"
    kind, v = next(iter(t.items()))
    if kind in ("primitive", "generic"):
        return v
    if kind == "resolved_path":
        return path_text(v)
    if kind == "borrowed_ref":
        return "&" + (f"{v['lifetime']} " if v.get("lifetime") else "") + ("mut " if v.get("is_mutable") else "") + type_text(v["type"])
    if kind == "raw_pointer":
        return ("*mut " if v.get("is_mutable") else "*const ") + type_text(v["type"])
    if kind == "slice":
        return f"[{type_text(v)}]"
    if kind == "array":
        return f"[{type_text(v['type'])}; {v['len']}]"
    if kind == "tuple":
        return "(" + ", ".join(type_text(x) for x in v) + ("," if len(v) == 1 else "") + ")"
    if kind == "impl_trait":
        return "impl " + bounds_text(v)
    if kind == "dyn_trait":
        traits = [("for" + generic_params_text(p["generic_params"]) + " " if p.get("generic_params") else "") + path_text(p["trait"]) for p in v["traits"]]
        return "dyn " + " + ".join(traits + ([v["lifetime"]] if v.get("lifetime") else []))
    if kind == "qualified_path":
        own = v["name"] + args_text(v.get("args"))
        self_type = type_text(v["self_type"])
        if not v.get("trait") or self_type == "Self":
            return f"{self_type}::{own}"
        return f"<{self_type} as {path_text(v['trait'])}>::{own}"
    if kind == "function_pointer":
        sig = v["sig"]
        out = f" -> {type_text(sig['output'])}" if sig.get("output") else ""
        return "fn(" + ", ".join(type_text(x[1]) for x in sig["inputs"]) + ")" + out
    if kind == "pat":
        return type_text(v["type"])
    return "_"


def generic_params_text(
    params: list[dict],  # The generic parameters of an item
) -> str:  # They in angle brackets, such as `<'a, T: Clone>`; empty when there are none
    "Write the generic parameters of an item, without the ones that an `impl Trait` argument makes."
    parts = []
    for p in params:
        kind, v = next(iter(p["kind"].items()))
        if kind == "lifetime":
            parts.append(p["name"] + (": " + " + ".join(v["outlives"]) if v.get("outlives") else ""))
        elif kind == "type":
            if v.get("is_synthetic"):
                continue
            text = p["name"] + (f": {bounds_text(v['bounds'])}" if v.get("bounds") else "")
            parts.append(text + (f" = {type_text(v['default'])}" if v.get("default") else ""))
        elif kind == "const":
            parts.append(f"const {p['name']}: {type_text(v['type'])}" + (f" = {v['default']}" if v.get("default") else ""))
    return f"<{', '.join(parts)}>" if parts else ""


def where_text(
    generics: dict,  # The generics of an item
) -> str:  # Its `where` clause, such as ` where T: Debug`; empty when it has none
    "Write the `where` clause of an item."
    parts = []
    for w in generics.get("where_predicates", []):
        kind, v = next(iter(w.items()))
        if kind == "bound_predicate":
            hrtb = generic_params_text(v.get("generic_params") or [])
            parts.append(f"{'for' + hrtb + ' ' if hrtb else ''}{type_text(v['type'])}: {bounds_text(v['bounds'])}")
        elif kind == "lifetime_predicate":
            parts.append(f"{v['lifetime']}: {' + '.join(v['outlives'])}")
        elif kind == "eq_predicate":
            rhs = v["rhs"]
            parts.append(f"{type_text(v['lhs'])} = {type_text(rhs['type']) if 'type' in rhs else rhs.get('constant', {}).get('expr', '_')}")
    return " where " + ", ".join(parts) if parts else ""


def visibility(
    item: dict,  # An item of rustdoc's JSON
    here: str = "",  # The id of the module the item is in
    at_root: bool = False,  # Whether that module is the crate's root
) -> str:  # `pub `, `pub(crate) ` and so on; empty for a private item, or one in a trait
    "Write an item's visibility, as its source does; rustdoc writes a private item as one restricted to its own module, which at the root is `crate`."
    v = item.get("visibility")
    if v == "public":
        return "pub "
    if v == "crate":
        return "" if at_root else "pub(crate) "
    if isinstance(v, dict) and "restricted" in v:
        if str(v["restricted"].get("parent")) == here:
            return ""
        path = v["restricted"]["path"]
        path = "crate" + path if path.startswith("::") else path
        return f"pub({path}) " if path in ("super", "self", "crate") else f"pub(in {path}) "
    return ""


def self_text(
    t: dict,  # The type of a `self` parameter
) -> str:  # `self`, `&self`, `&mut self` or `self: Box<Self>`
    "Write a method's `self` parameter as its source does."
    if t == {"generic": "Self"}:
        return "self"
    ref = t.get("borrowed_ref")
    if ref and ref["type"] == {"generic": "Self"}:
        return "&" + (f"{ref['lifetime']} " if ref.get("lifetime") else "") + ("mut " if ref.get("is_mutable") else "") + "self"
    return f"self: {type_text(t)}"


def fn_signature(
    item: dict,  # A function or method of rustdoc's JSON
    name: str,  # Its name
    here: str = "",  # The id of the module it is in
    at_root: bool = False,  # Whether that module is the crate's root
) -> str:  # Its signature as Rust, on one line, or with a parameter per line when that is long
    "Write a function's signature: its visibility, its qualifiers, its generics, its parameters, its return and its `where` clause."
    f = item["inner"]["function"]
    h = f["header"]
    abi = h.get("abi", "Rust")
    quals = "".join(q for q, on in (("const ", h.get("is_const")), ("async ", h.get("is_async")), ("unsafe ", h.get("is_unsafe"))) if on)
    if abi != "Rust":
        quals += f'extern "{abi if isinstance(abi, str) else next(iter(abi))}" '
    params = [self_text(t) if n == "self" else f"{n}: {type_text(t)}" for n, t in f["sig"]["inputs"]]
    if f["sig"].get("is_c_variadic"):
        params.append("...")
    out = f" -> {type_text(f['sig']['output'])}" if f["sig"].get("output") else ""
    head = f"{visibility(item, here, at_root)}{quals}fn {'r#' if name in KEYWORDS else ''}{name}{generic_params_text(f['generics']['params'])}"
    where = where_text(f["generics"])
    line = f"{head}({', '.join(params)}){out}{where}"
    if len(line) <= 100:
        return line
    body = "".join(f"\n    {p}," for p in params)
    return f"{head}({body}\n){out}" + (where.replace(" where ", "\nwhere\n    ", 1).replace(", ", ",\n    ") if where else "")


# ---------------------------------------------------------------- reading comments from the source


def split_comment(
    line: str,  # One line of Rust
) -> tuple[str, str]:  # The code before a `//` comment, and the comment; a doc comment, `///` or `//!`, is no comment here
    "Split a line of Rust into its code and its `//` comment, outside strings, character literals and `/* */` comments."
    quoted = False
    code, i = [], 0
    while i < len(line):
        c = line[i]
        if quoted:
            step = 2 if c == "\\" else 1
            quoted = c != '"'
            code.append(line[i : i + step])
            i += step
            continue
        char = re.match(r"'(?:\\.[^']*|[^'\\])'", line[i:])
        if char:  # a character literal, such as '"'; a lifetime, such as 'a, has no closing quote
            code.append(char.group(0))
            i += len(char.group(0))
            continue
        if line.startswith("/*", i):
            close = line.find("*/", i + 2)
            i = len(line) if close < 0 else close + 2
            continue
        if line.startswith("//", i):
            said = line[i + 2 :]
            return "".join(code), "" if said.startswith(("/", "!")) else said.strip()
        quoted = c == '"'
        code.append(c)
        i += 1
    return "".join(code), ""


def signature_lines(
    lines: list[str],  # The lines of the source file
    item: dict,  # A function or method of rustdoc's JSON, with its span
    name: str,  # Its name
) -> list[tuple[str, str, bool, bool]]:  # For each line of the signature: its code, its comment, whether it has the `->`, and whether it opens the body
    "Find the lines of a function's signature, from `fn NAME` to the `{` that opens its body, or the `;` that ends it; the `->` of the return is the one outside brackets, generics and the `where` clause."
    span = item["span"]
    begin, end = span["begin"][0] - 1, span["end"][0]
    pattern = rf"\bfn\s+(?:r#)?{re.escape(name)}\b"
    start = next((i for i in range(begin, min(end, len(lines))) if re.search(pattern, split_comment(lines[i])[0])), None)
    if start is None:
        return []
    out, depth, angle, opened, where = [], 0, 0, False, False
    for i in range(start, min(end, len(lines))):
        code, said = split_comment(lines[i])
        arrow = body = False
        j = re.search(pattern, code).end() if i == start else 0
        while j < len(code):
            c = code[j]
            outside = depth == 0 and angle == 0
            if code.startswith("->", j):
                arrow = arrow or (outside and opened and not where)
                j += 2
                continue
            if c in "([":
                opened = opened or (c == "(" and outside)
                depth += 1
            elif c in ")]":
                depth -= 1
            elif c == "<" and depth == 0:
                angle += 1
            elif c == ">" and depth == 0:
                angle -= 1
            elif outside and opened and re.match(r"where\b", code[j:]) and (j == 0 or not (code[j - 1].isalnum() or code[j - 1] == "_")):
                where = True
            elif outside and opened and c in "{;":
                body = True
                break
            j += 1
        out.append((code, said, arrow, body))
        if body:
            break
    return out


def param_pattern(
    name: str,  # A parameter as rustdoc names it: `a`, or a pattern such as `(b, c)`
) -> str:  # A regular expression that finds it before its `:` in the source
    "Make the regular expression that finds a parameter in a signature: `name:`, `mut name:`, `r#name:`, or a pattern with any spacing."
    spaced = r"\s*".join(re.escape(p) for p in re.findall(r"\w+|[^\w\s]", name))
    return r"(?<![\w.])(?:r#)?" + spaced + r"\s*:(?!:)"


def param_comments(
    lines: list[str],  # The lines of the source file
    item: dict,  # A function or method of rustdoc's JSON
    name: str,  # Its name
) -> tuple[dict[str, str], str]:  # The comment after each parameter, under its name, and the comment on the return
    "Read the docments of a function: the `//` comment on a parameter's line, and the one on the line of `->` or of the `{`."
    sig = signature_lines(lines, item, name)
    names = [n for n, _ in item["inner"]["function"]["sig"]["inputs"] if n != "self"]
    found = {n: next((i for i, (code, *_) in enumerate(sig) if re.search(param_pattern(n), code)), None) for n in names}
    out, returns = {}, ""
    for i, (_, said, arrow, body) in enumerate(sig):
        if not said:
            continue
        here = [n for n, at in found.items() if at == i]
        if arrow:
            returns = returns or said
        elif len(here) == 1:
            out[here[0]] = said
        elif body and not here:
            returns = returns or said
    return out, returns


def line_comment(
    lines: list[str],  # The lines of the source file
    item: dict,  # A field or a variant of rustdoc's JSON, with its span
    shared: set[int] = frozenset(),  # Lines that hold more than this field, such as `pub struct P { pub x: u8, pub y: u8 } // a point`
) -> str:  # The `//` comment on its first line or its last; empty when there is none
    "Read the comment after a field or a variant, such as `pub y: f64,  // Up`, on a line that is its own."
    span = item.get("span")
    if not span:
        return ""
    for n in (span["begin"][0], span["end"][0]):
        if 0 < n <= len(lines) and n not in shared and (said := split_comment(lines[n - 1])[1]):
            return said
    return ""


def arguments_section(
    text: str,  # A doc comment
) -> tuple[dict[str, str], str]:  # The description of each parameter in its `# Arguments` list, and the doc comment without that section
    "Read a `# Arguments` list, with lines such as ``* `a` - the first number``, and take it out of the doc comment."
    lines = text.split("\n")
    start = next((i for i, line in enumerate(lines) if re.fullmatch(r"#+\s*Arguments\s*", line.strip())), None)
    if start is None:
        return {}, text
    stop = next((i for i in range(start + 1, len(lines)) if re.match(r"#+\s", lines[i])), len(lines))
    said, last = {}, None
    for line in lines[start + 1 : stop]:
        m = ARG_LINE.match(line)
        if m:
            last = m.group(1)
            said[last] = m.group(2).strip()
        elif last and line.strip() and line.startswith((" ", "\t")):
            said[last] += " " + line.strip()
    if not said:
        return {}, text
    rest = "\n".join(lines[:start] + lines[stop:]).strip()
    return said, re.sub(r"\n{3,}", "\n\n", rest)


# ---------------------------------------------------------------- the crate


@dataclass
class Entry:
    "One entry on a page: an item, its heading, its anchor and its level."

    id: str  # The item's id in rustdoc's JSON
    name: str  # The name in its heading, such as `Point` or `Point::distance`
    anchor: str  # The id of its heading, such as `Point.distance`
    level: int  # The heading level: 2 for an item of the module, 3 for a method
    module: str  # The full name of its module, such as `mycrate::parse`


@dataclass
class Page:
    "One module's page: the module, its file name and its entries."

    id: str  # The module's id in rustdoc's JSON
    path: str  # Its full name, such as `mycrate::parse`
    file: str = ""  # The page's file, from the folder of pages, such as `cli/commands/index.qmd`
    entries: list[Entry] = field(default_factory=list)  # Its entries, in the order of the page
    reexports: list[tuple[str, str]] = field(default_factory=list)  # The names it re-exports from elsewhere, with the id of each
    modules: list[str] = field(default_factory=list)  # The ids of its own modules


def page_file(
    page: Page,  # A module's page, with its modules found
    taken: set[str] = frozenset(),  # Pages that someone wrote, which a build never writes over
) -> str:  # Its file, from the folder of pages: the folders follow the modules
    "Place a module's page: the crate's root at `mycrate.qmd`, a module with modules in `a/b/index.qmd`, and one without at `a/b.qmd`."
    names = page.path.split("::")
    if len(names) == 1:
        return f"{names[0]}.qmd"  # never `index.qmd`, which is the folder's
    folder, name = "/".join(names[1:-1]), names[-1]
    at = f"{folder}/" if folder else ""
    if page.modules:
        index = f"{at}{name}/index.qmd"
        return index if index not in taken else f"{at}{name}/{name}.qmd"  # a hand-written index keeps its place
    return f"{at}{name if name != 'index' else 'index-module'}.qmd"


def unique(
    file: str,  # A page's file, from the folder of pages
    used: set[str],  # The files that other pages have, in lower case, as a disk may not tell `A.qmd` from `a.qmd`; the new file joins it
) -> str:  # The file, or `name-module.qmd`, `name-module-2.qmd` and so on when another page has it
    "Give a page a file that no other page has, such as a module `mycrate::mycrate` beside the root `mycrate.qmd`."
    stem, n, out = file.removesuffix(".qmd"), 1, file
    while out.casefold() in used:
        out = f"{stem}-module{'' if n == 1 else f'-{n}'}.qmd"
        n += 1
    used.add(out.casefold())
    return out


class Crate:
    "A crate as rustdoc's JSON describes it, with a page for each module and an entry for each item."

    def __init__(
        self,
        data: dict,  # rustdoc's JSON
        root: Path,  # The folder that the file names of the spans start from
        out: str = "api",  # The folder of the pages, inside the site
        taken: set[str] = frozenset(),  # Pages in that folder that someone wrote, from the folder, such as `cli/index.qmd`
    ) -> None:
        "Read the JSON: find each module's page, and the page and the anchor of each item."
        self.data, self.root, self.out = data, root, out
        self.index: dict[str, dict] = data["index"]
        self.paths: dict[str, dict] = data["paths"]
        self.files: dict[str, list[str]] = {}
        self.pages: list[Page] = []
        self.where: dict[str, tuple[Page, str]] = {}  # The page and the anchor of each item that has an entry
        self.home: dict[str, Page] = {}
        self.name_of: dict[str, str] = {}  # The name an item has where it is documented, which a `pub use ... as` may change
        self.modules = {tuple(v["path"]): k for k, v in self.paths.items() if v.get("crate_id") == 0 and v.get("kind") == "module"}
        self.kinds = {(v.get("crate_id"), tuple(v["path"])): v["kind"] for v in self.paths.values()}
        self.claimed: set[str] = set()  # The modules that have, or will have, a page
        self.owners: dict[str, str] = {}  # The struct, union or enum that each field and variant is part of
        for k, v in self.index.items():
            inner = v["inner"] if isinstance(v["inner"], dict) else {}
            if "enum" in inner:
                self.owners.update({str(i): k for i in inner["enum"]["variants"]})
            elif "struct" in inner or "union" in inner:
                self.owners.update({str(i): k for i in self.field_ids(v)})
        self.walk(str(data["root"]), [])
        used = {f.casefold() for f in taken} | {"index.qmd"}  # the folder's index is written last
        for p in self.pages:
            p.file = unique(page_file(p, taken), used)
        for p in self.pages:
            for e in p.entries:
                self.where[e.id] = (p, e.anchor)

    def field_ids(
        self,
        item: dict,  # A struct or a union
    ) -> list[int]:  # The ids of the fields that the JSON keeps, in order
        "List the ids of the fields of a struct or a union: named, in a tuple, or none."
        inner = item["inner"].get("struct") or item["inner"].get("union")
        kind = inner.get("kind") if "struct" in item["inner"] else {"plain": {"fields": inner.get("fields", [])}}
        if isinstance(kind, dict) and "plain" in kind:
            return kind["plain"]["fields"]
        if isinstance(kind, dict) and "tuple" in kind:
            return [i for i in kind["tuple"] if i is not None]
        return []

    def shared_lines(
        self,
        id: str | int,  # The id of a field or a variant
    ) -> set[int]:  # The lines that hold more than one field or variant of its owner, or the owner's own first line
        "Find the lines whose comment belongs to no single field, such as `pub struct P { pub x: u8, pub y: u8 } // a point`."
        owner = self.item(self.owners.get(str(id), ""))
        if owner is None or not owner.get("span"):
            return set()
        inner = owner["inner"]
        ids = inner["enum"]["variants"] if "enum" in inner else self.field_ids(owner)
        starts = [s["span"]["begin"][0] for s in (self.item(i) for i in ids) if s and s.get("span")]
        return {owner["span"]["begin"][0]} | {n for n in starts if starts.count(n) > 1}

    def item(
        self,
        id: str | int,  # An item's id
    ) -> dict | None:  # The item, or `None` when the JSON leaves it out
        "Find an item by its id."
        return self.index.get(str(id))

    def kind(
        self,
        id: str | int,  # An item's id
    ) -> str:  # Its kind, such as `function` or `struct`; empty when it is not in the JSON
        "Say what kind of item an id is."
        it = self.item(id)
        if it is None:
            return ""
        inner = it["inner"]
        return inner if isinstance(inner, str) else next(iter(inner))

    def walk(
        self,
        id: str,  # A module's id
        parents: list[str],  # The names of the modules it is in
    ) -> None:
        "Make the page of a module and of each module in it, and give each item its page; a re-exported item from a hidden module joins the page that re-exports it."
        mod = self.item(id)
        if mod is None or mod["inner"]["module"].get("is_stripped"):
            return
        self.claimed.add(id)
        page = Page(id, "::".join([*parents, mod["name"]]))
        self.pages.append(page)
        for child in mod["inner"]["module"]["items"]:
            child = str(child)
            kind = self.kind(child)
            if kind == "module":
                self.claim(page, child)
            elif kind == "use":
                self.adopt(page, child, set())
            elif kind and kind not in HIDDEN_KINDS:
                self.place(page, child)
        for child in page.modules:
            self.walk(child, [*parents, mod["name"]])

    def claim(
        self,
        page: Page,  # A module's page
        id: str,  # The id of a module in it, or that it re-exports
    ) -> bool:  # Whether the module is now one of the page's modules
        "Make a module, that has no page yet, a module of this page, to be walked after the page's items."
        mod = self.item(id)
        if mod is None or mod["inner"]["module"].get("is_stripped") or id in self.claimed:
            return False
        self.claimed.add(id)
        page.modules.append(id)
        return True

    def adopt(
        self,
        page: Page,  # The page of the module that has the `pub use`
        id: str,  # The id of the `use` item
        seen: set[str],  # The hidden modules whose items a glob has already brought here, so that a cycle of globs ends
    ) -> None:
        "Give a re-exported item an entry on this page when it has no page of its own yet; otherwise list it as a re-export."
        use = self.item(id)
        if use.get("visibility") != "public":
            return  # a private `use`, in a crate documented with its private items, is an import
        u = use["inner"]["use"]
        target = str(u["id"]) if u.get("id") is not None else None
        kind = self.kind(target) if target else ""
        if u.get("is_glob"):
            if kind == "module" and self.item(target)["inner"]["module"].get("is_stripped"):
                if target in seen:
                    return
                seen.add(target)
                for child in self.item(target)["inner"]["module"]["items"]:
                    child = str(child)
                    if self.kind(child) == "use":
                        self.adopt(page, child, seen)
                    elif self.kind(child) == "module":
                        self.claim(page, child)
                    elif self.kind(child) not in HIDDEN_KINDS:
                        self.place(page, child)
            elif target:
                page.reexports.append((u["source"] + "::*", target))
            return
        if kind == "module" and self.public_home(target) is None and self.claim(page, target):
            return  # a public module inside a hidden one has its own page
        if kind and kind not in HIDDEN_KINDS and target not in self.home and self.public_home(target) is None:
            self.place(page, target, u["name"])
        elif target:
            page.reexports.append((u["name"], target))

    def public_home(
        self,
        id: str,  # An item's id
    ) -> str | None:  # The module it is defined in, when that module has a page of its own; otherwise `None`
        "Say whether an item will have an entry where it is defined, so that a re-export of it is only a link."
        path = (self.paths.get(id) or {}).get("path") or []
        mod_id = self.modules.get(tuple(path[:-1]))
        mod = self.item(mod_id) if mod_id else None
        if mod is None or mod["inner"]["module"].get("is_stripped"):
            return None
        return mod_id if int(id) in mod["inner"]["module"]["items"] else None

    def place(
        self,
        page: Page,  # The page the item goes on
        id: str,  # The item's id
        name: str | None = None,  # The name it has there, when a `pub use ... as` renames it
    ) -> None:
        "Give an item its entry on a page, with the entries of its methods under it."
        if id in self.home:
            return
        item = self.item(id)
        name = name or item["name"]
        self.home[id], self.name_of[id] = page, name
        used = {e.anchor for e in page.entries}
        anchor = name if name not in used else f"{self.kind(id)}.{name}"
        page.entries.append(Entry(id, name, anchor, 2, page.path))
        used.add(anchor)
        for sub, sub_name in self.members(id):
            self.home[sub], self.name_of[sub] = page, sub_name
            sub_anchor, n = f"{anchor}.{sub_name}", 1
            while sub_anchor in used:  # two `impl` blocks, such as `impl G<u8>` and `impl G<u16>`, may each have a `new`
                n += 1
                sub_anchor = f"{anchor}.{sub_name}-{n}"
            used.add(sub_anchor)
            page.entries.append(Entry(sub, f"{name}::{sub_name}", sub_anchor, 3, page.path))

    def members(
        self,
        id: str,  # The id of a struct, an enum, a union or a trait
    ) -> list[tuple[str, str]]:  # The id and the name of each method and associated item that gets an entry under it
        "List the methods of a type's own `impl` blocks, or the items of a trait."
        kind = self.kind(id)
        inner = self.item(id)["inner"].get(kind) if kind else None
        if kind == "trait":
            return [(str(i), self.item(i)["name"]) for i in inner["items"] if self.item(i)]
        if kind not in ("struct", "enum", "union"):
            return []
        out = []
        for impl_id in inner.get("impls", []):
            impl = self.item(impl_id)
            if impl and impl["inner"]["impl"]["trait"] is None:
                out += [(str(i), self.item(i)["name"]) for i in impl["inner"]["impl"]["items"] if self.item(i)]
        return out

    def trait_impls(
        self,
        id: str,  # The id of a struct, an enum or a union
    ) -> list[dict]:  # The paths of the traits it implements; not the auto traits, such as `Send`, nor the blanket impls, such as `From<T>`
        "List the traits a type implements in its own code, or derives."
        kind = self.kind(id)
        out = []
        for impl_id in self.item(id)["inner"][kind].get("impls", []):
            impl = (self.item(impl_id) or {}).get("inner", {}).get("impl")
            if not impl or not impl["trait"] or impl["trait"]["path"].rpartition("::")[2] in COMPILER_TRAITS:
                continue
            if not impl["is_synthetic"] and not impl.get("blanket_impl") and not impl.get("is_negative"):
                out.append(impl["trait"])
        return out

    def source(
        self,
        item: dict,  # An item with a span
    ) -> list[str]:  # The lines of its source file; empty when the file cannot be read
        "Read the lines of an item's source file, once per file."
        span = item.get("span")
        if not span:
            return []
        name = span["filename"]
        if name not in self.files:
            path = self.root / name
            try:
                self.files[name] = path.read_text(encoding="utf-8").split("\n")
            except (OSError, UnicodeDecodeError):
                self.files[name] = []
        return self.files[name]

    def url(
        self,
        id: str | int | None,  # An item's id, from a link or a path
    ) -> str | None:  # A link to its entry, to its page, or to the docs of the crate it is from; `None` when it has none
        "Find where an item is documented: on a page of this site, or in the docs of another crate."
        if id is None:
            return None
        id = str(id)
        if id in self.where:
            page, anchor = self.where[id]
            return f"/{self.out}/{page.file}#{anchor}"
        page = next((p for p in self.pages if p.id == id), None)
        if page is not None:
            return f"/{self.out}/{page.file}"
        owner = self.owners.get(id)
        if owner and owner in self.where:
            page, anchor = self.where[owner]
            return f"/{self.out}/{page.file}#{anchor}"
        return self.external_url(id)

    def external_url(
        self,
        id: str,  # The id of an item of another crate
    ) -> str | None:  # A link to its page in that crate's docs: its `html_root_url`, or docs.rs
        "Link an item of another crate to its docs, as rustdoc's pages do."
        p = self.paths.get(id)
        if not p or p.get("crate_id", 0) == 0:
            return None
        crate = self.data["external_crates"].get(str(p["crate_id"])) or {}
        root = (crate.get("html_root_url") or f"https://docs.rs/{crate.get('name', p['path'][0])}/latest/").rstrip("/") + "/"
        path, kind = p["path"], p["kind"]
        if kind == "module":
            return root + "/".join(path) + "/index.html"
        if kind in MEMBER_ANCHOR and len(path) > 2:
            parent = self.external_kind(path[:-1], p["crate_id"])
            if parent in EXTERNAL_PAGE:
                return root + "/".join(path[:-2]) + f"/{EXTERNAL_PAGE[parent]}.{path[-2]}.html#{MEMBER_ANCHOR[kind]}.{path[-1]}"
        if kind in EXTERNAL_PAGE:
            return root + "/".join(path[:-1]) + f"/{EXTERNAL_PAGE[kind]}.{path[-1]}.html"
        return None

    def external_kind(
        self,
        path: list[str],  # The full path of an item of another crate
        crate_id: int,  # The crate's id
    ) -> str:  # The item's kind; empty when the JSON does not list it
        "Find the kind of another crate's item by its path, to link a method on its type's page."
        return self.kinds.get((crate_id, tuple(path)), "")


# ---------------------------------------------------------------- writing the pages


def fence_run(
    stripped: str,  # A line of Markdown, without its indent
) -> str:  # The run of three or more backticks or tildes it starts with, such as "````"; empty when it starts no fence
    "Find the fence mark a line starts with."
    m = re.match(r"`{3,}|~{3,}", stripped)
    return m.group(0) if m else ""


def closes(
    stripped: str,  # A line of Markdown, without its indent, inside a fence
    fence: str,  # The mark that opened the fence
) -> bool:  # Whether the line closes it: as many marks of the same kind or more, and nothing after
    "Tell whether a line closes a fenced code block, as CommonMark says."
    run = fence_run(stripped)
    return bool(run) and run[0] == fence[0] and len(run) >= len(fence) and not stripped[len(run) :].strip()


def link_docs(
    text: str,  # A doc comment, as Markdown
    links: dict[str, int],  # rustdoc's links of the item: the target as written, and the id it resolves to
    crate: Crate,  # The crate
) -> str:  # The same Markdown with each intra-doc link made a link to its entry
    "Turn the intra-doc links of a doc comment, such as ``[`Parser`]``, into links to their entries."
    if not links:
        return text

    def target(
        key: str,  # The link's target as the doc comment writes it
    ) -> str | None:  # Its URL, or `None` when it is not an intra-doc link with a page
        "Find the URL of one intra-doc link."
        return crate.url(links[key]) if key in links else None

    def swap(
        m: re.Match,  # A code span, or a link with its target
    ) -> str:  # The text, with the link's target made a URL
        "Replace one link."
        if m.group(1):
            return m.group(0)
        label, rest = m.group(2), m.group(3)
        if rest and rest.startswith("("):
            url = target(rest[1:-1])
            return f"[{label}]({url})" if url else (label if rest[1:-1] in links else m.group(0))
        key = rest[1:-1] if rest and rest[1:-1] else label
        shown = DISAMBIGUATOR.sub(r"\1", label) if key == label else label  # rustdoc shows `[fn@add]` as `add`
        url = target(key)
        if url:
            return f"[{shown}]({url})"
        return shown if key in links else m.group(0)

    out, fence = [], ""
    for line in text.split("\n"):
        stripped = line.lstrip()
        run = fence_run(stripped)
        if run:
            fence = run if not fence else "" if closes(stripped, fence) else fence
            out.append(line)
            continue
        if fence:
            out.append(line)
            continue
        ref = REF_DEF.match(line)
        if ref and ref.group(2) in links:
            url = target(ref.group(2))
            out.append(f"{ref.group(1)}{url}{ref.group(3)}" if url else "")
            continue
        out.append(LINK.sub(swap, line))
    return "\n".join(out)


def escape_angles(
    line: str,  # Some lines of Markdown prose, outside a code block
) -> str:  # The same line with each `<` that starts no HTML tag, autolink or comment written `&lt;`; code spans stay as they are
    "Escape a stray `<`, such as in `Vec<u8>` written outside backticks, so that it shows as text and does not start HTML."

    def one(
        m: re.Match,  # A code span, or a `<`
    ) -> str:  # The code span as it is, or the `<`, escaped unless it starts a tag
        "Escape one `<`."
        if m.group(1):
            return m.group(1)
        return "<" if HTML_START.match(line, m.end()) else "&lt;"

    return re.sub(r"((`+)(?:(?!\n[ \t]*\n)[\s\S])*?(?<!`)\2(?!`))|<", one, line)


def tidy_docs(
    text: str,  # A doc comment, as Markdown
    shift: int,  # How many levels to move its headings down, so that they sit under the entry's heading
) -> str:  # The same Markdown, with its headings moved down and its Rust examples as rustdoc shows them
    "Make a doc comment fit a page: its headings under the entry's, a code block with no language as Rust, and no lines hidden with `# `."
    out, prose, fence, rust, listed = [], [], "", False, False

    def flush() -> None:
        "Escape the stray `<` of the prose so far, as a whole, so that a code span may run over lines."
        if prose:
            out.extend(escape_angles("\n".join(prose)).split("\n"))
            prose.clear()

    for line in text.split("\n"):
        stripped = line.lstrip()
        run = fence_run(stripped)
        last = (prose or out or [""])[-1]
        if not fence and stripped and not line.startswith((" ", "\t")):
            listed = bool(LIST_ITEM.match(line))  # an indented line after a list item continues the item, and is no code
        indented = line.startswith(("    ", "\t")) and not listed
        if not fence and indented and (not last.strip() or (not prose and out and out[-1].startswith(("    ", "\t")))):
            flush()
            out.append(line)  # an indented code block, as it is
            continue
        if run or fence:
            flush()
        if run:
            if not fence:
                fence = run
                langs = {x.strip() for x in stripped[len(run) :].split(",")}
                rust = langs <= RUST_FENCE or "rust" in langs
                out.append(line[: len(line) - len(stripped)] + run + ("rust" if rust else stripped[len(run) :]))
                continue
            if closes(stripped, fence):
                fence, rust = "", False
            out.append(line)
            continue
        if fence:
            if rust and (stripped == "#" or stripped.startswith("# ")):
                continue  # rustdoc hides these lines of an example
            out.append(line.replace("##", "#", 1) if rust and stripped.startswith("##") else line)
            continue
        m = re.match(r"^(#{1,6})(\s.*)$", line)
        prose.append("#" * min(6, len(m.group(1)) + shift) + m.group(2) if m else line)
    flush()
    return "\n".join(out)


def summary(
    text: str,  # A doc comment
) -> str:  # Its first paragraph on one line, with links as their text; empty when it starts with a heading or code
    "Read the summary of a doc comment: its first paragraph."
    first = text.strip().split("\n\n", 1)[0]
    if not first or first.startswith(("#", "```", "~~~", "|")):
        return ""
    plain = LINK.sub(lambda m: m.group(1) or DISAMBIGUATOR.sub(r"\1", m.group(2)), first)  # a code span, such as `&[u8]`, stays as it is
    return escape_angles(" ".join(plain.split()))


def source_link(
    s: Settings,  # The settings
    crate: Crate,  # The crate
    item: dict,  # An item with a span
) -> str:  # A Markdown link to its first line, or empty when there is no `source` or the file is not in the repository
    "Link an item to the line that defines it."
    span = item.get("span")
    if not s.source or not span:
        return ""
    path = (crate.root / span["filename"]).resolve()
    try:
        file = path.relative_to(s.root) if s.root else path
    except ValueError:
        return ""
    return f"[source]({s.source}/{file.as_posix()}#L{span['begin'][0]}){{.source-link}}"


def code(
    text: str,  # Rust code
) -> str:  # It in a `rust` code block
    "Put Rust code in a code block."
    return f"```rust\n{text}\n```"


def type_cell(
    text: str,  # A type as Rust writes it
) -> str:  # It as plain text, as the Python pages write types, with Markdown's and HTML's signs escaped; `table` escapes `|`
    "Write a type in a table cell as plain text, so that `&`, `<`, `>`, `*`, `_`, `[` and `]` show as they are."
    text = re.sub(r"([\\`*_\[\]])", r"\\\1", text)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fn_table(
    crate: Crate,  # The crate
    item: dict,  # A function or method
    args: dict[str, str],  # The descriptions of its `# Arguments` list
) -> str:  # A Markdown table of its parameters and its return: type, description
    "Describe a function by its parameters and its return: the type and the comment of each."
    said, returns = param_comments(crate.source(item), item, item["name"])  # the name in the source, not one that a `pub use ... as` gives
    sig = item["inner"]["function"]["sig"]
    rows = [[f"`{n}`", type_cell(type_text(t)), said.get(n) or args.get(n, "")] for n, t in sig["inputs"] if n != "self"]
    if sig.get("output"):
        rows.append(["returns", type_cell(type_text(sig["output"])), returns])
    return table(rows, ["Parameter", "Type", "Description"])


def fields_of(
    crate: Crate,  # The crate
    item: dict,  # A struct or a union
) -> list[tuple[str, dict]]:  # The name and the item of each field that the JSON keeps, in order
    "List the fields of a struct or a union."
    return [(crate.item(i)["name"], crate.item(i)) for i in crate.field_ids(item) if crate.item(i)]


def describe(
    crate: Crate,  # The crate
    item: dict,  # A field or a variant
) -> str:  # Its doc comment on one line, or else the comment after it
    "Describe a field or a variant: its doc comment, with its links, or the comment after it, on a line that holds only it."
    docs = " ".join((item.get("docs") or "").split())
    if docs:
        return escape_angles(link_docs(docs, item.get("links") or {}, crate))
    return line_comment(crate.source(item), item, crate.shared_lines(item["id"]))


def variant_text(
    crate: Crate,  # The crate
    item: dict,  # A variant
) -> str:  # It as Rust writes it, such as `Rgb(u8, u8, u8)` or `Named { name: String }`
    "Write a variant of an enum."
    v = item["inner"]["variant"]
    kind = v["kind"]
    text = item["name"]
    if isinstance(kind, dict) and "tuple" in kind:
        text += "(" + ", ".join(type_text(crate.item(i)["inner"]["struct_field"]) if i is not None and crate.item(i) else "_" for i in kind["tuple"]) + ")"
    elif isinstance(kind, dict) and "struct" in kind:
        fs = [crate.item(i) for i in kind["struct"]["fields"] if crate.item(i)]
        named = " { " + ", ".join(f"{f['name']}: {type_text(f['inner']['struct_field'])}" for f in fs) + " }"
        text += named if len(named) <= 60 else " { .. }"
    if v.get("discriminant"):
        text += f" = {v['discriminant'].get('expr') or v['discriminant'].get('value')}"
    return text


def item_signature(
    crate: Crate,  # The crate
    item: dict,  # An item that is not a function
    name: str,  # The name it has on the page
    here: str = "",  # The id of the module it is in
) -> str:  # Its declaration as Rust, without its body
    "Write the declaration of a struct, an enum, a trait, a type, a constant, a static or a macro."
    kind = crate.kind(item["id"])
    v = item["inner"][kind]
    at_root = here == str(crate.data["root"])
    vis = visibility(item, here, at_root)
    gen = v.get("generics") or {"params": [], "where_predicates": []} if isinstance(v, dict) else {}
    params = generic_params_text(gen.get("params", [])) if gen else ""
    where = where_text(gen) if gen else ""
    if kind in ("struct", "union"):
        k = v.get("kind")
        if k == "unit":
            return f"{vis}struct {name}{params}{where};"
        if isinstance(k, dict) and "tuple" in k:
            parts = [visibility(crate.item(i), here, at_root) + type_text(crate.item(i)["inner"]["struct_field"]) if i is not None and crate.item(i) else "/* private field */" for i in k["tuple"]]
            return f"{vis}struct {name}{params}({', '.join(parts)}){where};"
        return f"{vis}{kind} {name}{params}{where}"
    if kind == "enum":
        return f"{vis}enum {name}{params}{where}"
    if kind == "trait":
        quals = ("unsafe " if v.get("is_unsafe") else "") + ("auto " if v.get("is_auto") else "")
        bounds = f": {bounds_text(v['bounds'])}" if v.get("bounds") else ""
        return f"{vis}{quals}trait {name}{params}{bounds}{where}"
    if kind == "type_alias":
        return f"{vis}type {name}{params}{where} = {type_text(v['type'])};"
    if kind == "constant":
        expr = v["const"].get("expr")
        return f"{vis}const {name}: {type_text(v['type'])}" + (f" = {expr};" if expr and expr != "_" else ";")
    if kind == "static":
        expr = v.get("expr")
        return f"{vis}static {'mut ' if v.get('is_mutable') else ''}{name}: {type_text(v['type'])}" + (f" = {expr};" if expr and expr != "_" else ";")
    if kind == "macro":
        return v
    if kind == "proc_macro":
        return {"derive": f"#[derive({name})]", "attr": f"#[{name}]"}.get(v.get("kind"), f"{name}!()")
    if kind == "assoc_type":
        bounds = f": {bounds_text(v['bounds'])}" if v.get("bounds") else ""
        return f"type {name}{params}{bounds}" + (f" = {type_text(v['type'])}" if v.get("type") else "") + ";"
    if kind == "assoc_const":
        return f"const {name}: {type_text(v['type'])}" + (f" = {v['value']}" if v.get("value") else "") + ";"
    return f"{vis}{kind} {name}"


def impl_line(
    crate: Crate,  # The crate
    id: str,  # The id of a struct, an enum or a union
) -> str:  # A line such as "Implements `Display`, `Clone`.", with links; empty when it implements no trait itself
    "List the traits a type implements, each by its name, linked to its docs."
    names = []
    for t in crate.trait_impls(id):
        text = f"`{path_text(t)}`"
        url = crate.url(t.get("id"))
        names.append(f"[{text}]({url})" if url else text)
    return f"Implements {', '.join(dict.fromkeys(names))}." if names else ""


def implementors_line(
    crate: Crate,  # The crate
    item: dict,  # A trait
) -> str:  # A line such as "Implemented for `Circle`.", with links; empty when nothing in the crate implements it
    "List the types of the crate that implement a trait."
    names = []
    for impl_id in item["inner"]["trait"].get("implementations", []):
        impl = (crate.item(impl_id) or {}).get("inner", {}).get("impl")
        if not impl or impl.get("blanket_impl"):
            continue
        for_ = impl["for"]
        text = f"`{type_text(for_)}`"
        url = crate.url(for_["resolved_path"]["id"]) if "resolved_path" in for_ else None
        names.append(f"[{text}]({url})" if url else text)
    return f"Implemented for {', '.join(dict.fromkeys(names))}." if names else ""


def entry_markdown(
    s: Settings,  # The settings
    crate: Crate,  # The crate
    e: Entry,  # One entry
) -> str:  # Its Markdown: heading, source link, signature, doc comment and tables
    "Write one entry: a heading with its id, a source link, the signature, the doc comment and the table of its parameters, fields or variants."
    item = crate.item(e.id)
    kind = crate.kind(e.id)
    label = {"function": "fn " if e.level == 2 else "", "macro": "macro ","type_alias": "type ", "constant": "const ", "assoc_type": "type ", "assoc_const": "const "}.get(kind, f"{kind} ")
    parts = [f"{'#' * e.level} {label}{e.name} {{#{e.anchor}}}", source_link(s, crate, item)]
    docs = item.get("docs") or ""
    args: dict[str, str] = {}
    name, here = crate.name_of.get(e.id, item["name"]), crate.home[e.id].id
    if kind == "function":
        args, docs = arguments_section(docs)
        parts.append(code(fn_signature(item, name, here, here == str(crate.data["root"])) + (";" if e.level == 3 and not item["inner"]["function"]["has_body"] else "")))
    else:
        parts.append(code(item_signature(crate, item, name, here)))
    parts.append(tidy_docs(link_docs(docs.strip(), item.get("links") or {}, crate), e.level + 1))
    if kind == "function":
        parts.append(fn_table(crate, item, args))
    elif kind in ("struct", "union"):
        fs = fields_of(crate, item)
        rows = [[f"`{n}`", type_cell(type_text(f["inner"]["struct_field"])), describe(crate, f)] for n, f in fs]
        if any(r[2] for r in rows) or "plain" in (item["inner"][kind].get("kind") or {}):
            parts.append(table(rows, ["Field", "Type", "Description"]))
        parts.append(impl_line(crate, e.id))
    elif kind == "enum":
        rows = [[f"`{variant_text(crate, crate.item(i))}`", describe(crate, crate.item(i))] for i in item["inner"]["enum"]["variants"] if crate.item(i)]
        parts.append(table(rows, ["Variant", "Description"]))
        parts.append(impl_line(crate, e.id))
    elif kind == "trait":
        parts.append(implementors_line(crate, item))
    return "\n\n".join(p for p in parts if p)


def page_markdown(
    s: Settings,  # The settings
    crate: Crate,  # The crate
    page: Page,  # One module's page
) -> str:  # The text of its `.qmd` page
    "Write one module's page: front matter, the module's doc comment, its modules and re-exports, then an entry for each item."
    mod = crate.item(page.id)
    docs = tidy_docs(link_docs((mod.get("docs") or "").strip(), mod.get("links") or {}, crate), 1)
    said = summary(mod.get("docs") or "")
    first = docs.split("\n\n", 1)
    if said and len(first) and " ".join(re.sub(r"\[([^\]]+)\](\([^)]*\))?", r"\1", first[0]).split()) == said:
        docs = first[1] if len(first) > 1 else ""
    parts = [docs.strip(), modules_table(crate, [next(p for p in crate.pages if p.id == m) for m in page.modules])]
    names = []
    for name, target in page.reexports:
        url = crate.url(target)
        names.append(f"[`{name}`]({url})" if url else f"`{name}`")
    parts.append(f"Re-exports {', '.join(names)}." if names else "")
    parts += [entry_markdown(s, crate, e) for e in page.entries]
    front = f"---\n{MARK}\ntitle: {json.dumps(page.path.rpartition('::')[2])}\ndescription: {json.dumps(said)}\n---\n\n"
    return front + "\n\n".join(p for p in parts if p) + "\n"


def modules_table(
    crate: Crate,  # The crate
    pages: list[Page],  # The pages of some modules
) -> str:  # A Markdown table with a link to each, by its name, and its summary
    "List some modules, each by its own name, linked to its page, with its summary."
    rows = [[f"[`{p.path.rpartition('::')[2]}`](/{crate.out}/{p.file})", summary(crate.item(p.id).get("docs") or "")] for p in pages]
    return table(rows, ["Module", "Summary"])


def index_markdown(
    crate: Crate,  # The crate
) -> str:  # The text of the folder's `index.qmd`: the crate's summary and links to the pages at the top
    "Write the index of the folder of pages, which heads its section of the sidebar: the crate's summary, and a link to its root page and to each of its modules."
    root = crate.pages[0]
    said = summary(crate.item(root.id).get("docs") or "")
    tops = [root, *(next(p for p in crate.pages if p.id == m) for m in root.modules)]
    return f"---\n{MARK}\ntitle: \"API\"\ndescription: {json.dumps(said)}\n---\n\n" + modules_table(crate, tops) + "\n"


def write_pages(
    s: Settings,  # The settings
    pages: dict[str, str],  # The text of each page, under its file name
    index: dict[str, str],  # The index of names for links
) -> list[Path]:  # The pages written
    "Write the pages and `_symbols.json`, and delete the pages that an earlier build wrote and this one did not, as the Python build does."
    out_dir = (s.site / s.out).resolve()
    if s.site.resolve() not in out_dir.parents:
        raise ValueError(f"api.out {s.out!r} must be a folder inside the site, such as api")
    out_dir.mkdir(parents=True, exist_ok=True)
    before = written_before(out_dir)
    written = []
    for name, text in pages.items():
        f = out_dir / name
        f.parent.mkdir(parents=True, exist_ok=True)
        if not f.exists() or f.read_text(encoding="utf-8") != text:
            f.write_text(text, encoding="utf-8")
        written.append(f)
    names = set(pages)
    for stale in sorted(before - names):
        f = (out_dir / stale).resolve()
        if stale.endswith(".qmd") and not Path(stale).is_absolute() and ".." not in Path(stale).parts and out_dir in f.parents and f.is_file():
            f.unlink()  # only a page that an earlier build wrote, inside the folder of pages, and this one did not
            for folder in f.parents:
                if folder == out_dir or any(folder.iterdir()):
                    break
                folder.rmdir()  # a folder that the stale page leaves empty
    manifest = out_dir / ".smalldocs-api"
    manifest.write_text("\n".join(sorted(names)), encoding="utf-8")
    sym = s.site / "_symbols.json"
    text = json.dumps(index, indent=1)
    if not sym.exists() or sym.read_text(encoding="utf-8") != text:
        sym.write_text(text, encoding="utf-8")
    return written


def symbols(
    crate: Crate,  # The crate
) -> dict[str, str]:  # Each name, under its short form and its full path, with the link to its entry
    "Make the index of names that links use: `Point`, `Point::distance`, `Point.distance` and `mycrate::Point::distance`."
    index: dict[str, str] = {}
    for page in crate.pages:
        for e in page.entries:
            target = f"/{crate.out}/{page.file}#{e.anchor}"
            index.setdefault(e.name.rpartition("::")[2] if e.level == 2 else e.name, target)
            index.setdefault(e.name.replace("::", "."), target)
            index.setdefault(f"{page.path}::{e.name}", target)
    return index


def written_before(
    out_dir: Path,  # The folder of pages
) -> set[str]:  # The pages that the last build wrote, from its manifest, as paths from the folder
    "Read the manifest of the last build."
    manifest = out_dir / ".smalldocs-api"
    return set(manifest.read_text(encoding="utf-8").split("\n")) - {""} if manifest.exists() else set()


def hand_written(
    out_dir: Path,  # The folder of pages
) -> set[str]:  # The pages in it that no build wrote, as paths from the folder
    "Find the pages that someone wrote in the folder of pages, which a build never writes over: not in the manifest, and without the mark of a build."
    if not out_dir.is_dir():
        return set()
    before = written_before(out_dir)

    def ours(
        f: Path,  # A page
    ) -> bool:  # Whether a build wrote it, by its mark, so that a lost manifest leaves no page frozen
        "Read a page's mark."
        with f.open(encoding="utf-8", errors="replace") as h:
            return h.read(len(MARK) + 5) == f"---\n{MARK}\n"

    return {n for f in out_dir.rglob("*.qmd") if (n := f.relative_to(out_dir).as_posix()) not in before and f.is_file() and not ours(f)}


def load(
    s: Settings,  # The settings
    private: bool = False,  # Document private items too
    taken: set[str] = frozenset(),  # Pages that someone wrote in the folder of pages
) -> Crate:  # The crate, read from rustdoc's JSON
    "Run rustdoc and read its JSON."
    data, root = rustdoc(s, private or s.private)
    return Crate(data, root, s.out, taken)


def build(
    s: Settings,  # The settings
) -> list[Path]:  # The pages written
    "Write a reference page per module of the crate, in folders that follow the modules, an `index.qmd` for the folder of pages, and `_symbols.json`."
    out_dir = (s.site / s.out).resolve()
    if s.site.resolve() not in out_dir.parents:
        raise ValueError(f"api.out {s.out!r} must be a folder inside the site, such as api")  # before rustdoc runs
    taken = hand_written(out_dir)
    crate = load(s, taken=taken)
    pages = {p.file: page_markdown(s, crate, p) for p in crate.pages if p.file not in taken}
    if "index.qmd" not in taken:
        pages["index.qmd"] = index_markdown(crate)
    return write_pages(s, pages, symbols(crate))


# ---------------------------------------------------------------- checking the convention


def entry_gaps(
    crate: Crate,  # The crate
    e: Entry,  # One entry
) -> list[str]:  # One message per gap; empty when the entry is documented
    "Find what one entry is missing: a doc comment, a docment for a parameter or the return, or a comment for a field or a variant."
    item = crate.item(e.id)
    kind = crate.kind(e.id)
    name = f"{e.module}:{e.name}"
    docs = item.get("docs") or ""
    out = [] if docs.strip() else [f"{name}: no doc comment"]
    if kind == "function":
        args, _ = arguments_section(docs)
        said, returns = param_comments(crate.source(item), item, item["name"])
        sig = item["inner"]["function"]["sig"]
        out += [f"{name}({n}): no docment" for n, _ in sig["inputs"] if n != "self" and not (said.get(n) or args.get(n))]
        if sig.get("output") and not returns:
            out.append(f"{name}: no return docment")
    elif kind in ("struct", "union") and "plain" in (item["inner"][kind].get("kind") or {"plain": 1}):
        out += [f"{name}.{n}: no docment" for n, f in fields_of(crate, item) if not describe(crate, f)]
    elif kind == "enum":
        out += [f"{name}.{v['name']}: no docment" for v in (crate.item(i) for i in item["inner"]["enum"]["variants"]) if v and not describe(crate, v)]
    return out


def check(
    s: Settings,  # The settings
    shown: bool = False,  # Hold the crate only to what its pages show; otherwise its private items too
) -> int:  # The exit code: 0 when nothing is missing, 1 otherwise
    "Print how much of each module is documented, then every gap, then the total."
    crate = load(s, private=not shown)
    found, done, total = [], 0, 0
    width = max((len(p.path) for p in crate.pages), default=10)
    for page in crate.pages:
        if not (crate.item(page.id).get("docs") or "").strip():
            found.append(f"{page.path}: no module doc comment")
        missing = [entry_gaps(crate, e) for e in page.entries]
        complete = sum(not g for g in missing)
        print(f"{page.path:{width}s} {complete:3d} of {len(missing):3d}")
        found += [m for g in missing for m in g]
        done, total = done + complete, total + len(missing)
    print("\n".join(["", *found]) if found else "")
    print(f"{done} of {total} items are documented")
    sys.stdout.flush()
    return 1 if found else 0
