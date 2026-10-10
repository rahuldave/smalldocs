"Quarto's shortcodes that make sense without Pandoc: `include`, `meta`, `var`, `env` and `pagebreak`."

import os
import re
from pathlib import Path

from .config import read_yaml

SHORTCODE = re.compile(r"(\\?)\{\{<\s*(\w[\w-]*)\s*(.*?)\s*>\}\}")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def lookup(
    data: dict,  # Nested options
    key: str,  # A dotted key, such as `author.name`
) -> object:  # The value, or None
    "Find a dotted key in nested options."
    cur: object = data
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def expand(
    text: str,  # Markdown that may hold shortcodes
    here: Path,  # The file it comes from, for `include` paths
    root: Path,  # The project's root, for `_variables.yml` and paths from `/`
    meta: dict,  # The page's options, for `meta`
    warn: list[str],  # Where to note a shortcode that smalldocs does not know
    depth: int = 0,  # How deep in includes we are, to stop a loop
) -> str:  # The text with the shortcodes replaced; code blocks are left alone
    "Replace the shortcodes in a page, outside code blocks."
    if depth > 10:
        warn.append(f"{here}: includes nest more than 10 deep; stopped")
        return text
    variables = {}
    vf = root / "_variables.yml"
    if vf.exists():
        variables = read_yaml(vf) or {}
    out, fence = [], None
    for line in text.split("\n"):
        m = FENCE.match(line)
        if fence:
            out.append(line)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not line.strip()[len(m.group(1)) :].strip():
                fence = None
            continue
        if m:
            fence = m.group(1)
            out.append(line)
            continue

        def sub(mm: re.Match) -> str:
            if mm.group(1):
                return mm.group(0)[1:]
            name, arg = mm.group(2), mm.group(3).strip().strip("\"'")
            if name == "include":
                path = (root / arg.lstrip("/")) if arg.startswith("/") else (here.parent / arg)
                if not path.is_file():
                    warn.append(f"{here.name}: include {arg} not found")
                    return ""
                inc = path.read_text(encoding="utf-8-sig")
                inc = re.sub(r"\A---\r?\n.*?\r?\n---\r?\n", "", inc, flags=re.S)
                return expand(inc, path, root, meta, warn, depth + 1)
            if name == "meta":
                v = lookup(meta, arg)
                return "" if v is None else str(v)
            if name == "var":
                v = lookup(variables, arg)
                return "" if v is None else str(v)
            if name == "env":
                return os.environ.get(arg, "")
            if name == "pagebreak":
                return ""
            warn.append(f"{here.name}: shortcode {name} is not known to smalldocs; left as it is")
            return mm.group(0)

        out.append(SHORTCODE.sub(sub, line).replace("{{</*", "{{<").replace("*/>}}", ">}}"))
    return "\n".join(out)
