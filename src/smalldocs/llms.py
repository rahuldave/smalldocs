"Write the Markdown copy of each page, `page.llms.md`, and the index `llms.txt`, for `website.llms-txt`."

import base64
import html
import json
import re
from collections.abc import Callable

from .markdown import EXECUTABLE, is_fence_line, parse_attrs, shown, split_front_matter
from .notebook import ANSI, cell_options, fence_for, source

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
CODE_SPAN = re.compile(r"(`+)(?:.+?)\1", re.S)
INLINE_LINK = re.compile(r"(\]\(\s*<?)([^)\s>]+)")  # `[text](href` and `![alt](href`
REF_DEF = re.compile(r"^( {0,3}\[(?!\^)[^\]]+\]:\s*<?)(\S+?)(>?(?:\s|$))")  # `[label]: href`, not a footnote
# `[text]{.class}`, Pandoc's span: its braces start with `.` or `#`, or hold `k=v`, so LaTeX's `\sqrt[3]{x}` is not one
SPAN = re.compile(r"(?<![!\]\\])\[([^\[\]\n]*)\]\{(\s*[.#][^{}\n]*|[^{}\n]*=[^{}\n]*)\}")
CELL = re.compile(r"\{(\w+)[\s,}]")  # an executable cell's fence, such as ```` ```{python} ````
# As nbconvert's Markdown exporter: the first of these that an output has is the one shown
NB_ORDER = ["text/html", "text/markdown", "image/svg+xml", "text/latex", "image/png", "image/jpeg", "text/plain"]
NB_FILES = {"image/svg+xml": ".svg", "image/png": ".png", "image/jpeg": ".jpg"}  # the outputs nbconvert saves as files


def kept(
    classes: list[str],  # The classes of a div or a span
    kv: dict[str, str],  # Its other attributes
    env: dict,  # The page's render environment
) -> bool | None:  # Whether the copy keeps its content; None when it is not conditional
    "Decide conditional content for the copy: a condition on `llms-txt` decides alone, as in Quarto; any other, as on the HTML page."
    visible = "content-visible" in classes
    if not visible and "content-hidden" not in classes:
        return None
    when, unless = (kv.get(f"{k}-format", "").strip() == "llms-txt" for k in ("when", "unless"))
    if when or unless:
        return when if visible else unless
    return shown(classes, kv, env)


def tag(
    name: str,  # `div` or `span`
    params: str,  # Pandoc attributes, such as `.callout-note title="A"`
) -> str:  # The HTML opening tag
    "Write Pandoc attributes as an HTML opening tag."
    a = parse_attrs(params)
    attrs = ([f'id="{html.escape(a.id)}"'] if a.id else []) + ([f'class="{html.escape(" ".join(a.classes))}"'] if a.classes else [])
    attrs += [f'{k}="{html.escape(v)}"' for k, v in a.kv.items()]
    return f"<{name}{''.join(' ' + x for x in attrs)}>"


def inline(
    text: str,  # A line of Markdown, outside code blocks
    link: Callable[[str], str],  # Rewrites one link
    env: dict,  # The page's render environment
) -> str:  # The line with its links rewritten and its spans as HTML, and its code spans as they were
    "Rewrite the links and spans of a line, but not those inside code spans."

    def span(m: re.Match) -> str:
        a = parse_attrs(m[2])
        keep = kept(a.classes, a.kv, env)
        if keep is not None:
            return m[1] if keep else ""
        return f"{tag('span', m[2])}{m[1]}</span>"

    def part(s: str) -> str:
        return SPAN.sub(span, INLINE_LINK.sub(lambda x: x[1] + link(x[2]), s))

    out, last = [], 0
    for m in CODE_SPAN.finditer(text):
        out += [part(text[last : m.start()]), m[0]]
        last = m.end()
    out.append(part(text[last:]))
    return REF_DEF.sub(lambda x: x[1] + link(x[2]) + x[3], "".join(out))


def hidden_cell(
    info: str,  # The text after a code fence's backticks
    code: str,  # The code in the fence
    env: dict,  # The page's render environment, with its `cell_defaults`
) -> bool:  # Whether the page hides the cell
    "Say whether an executable cell is hidden on the page by `echo: false` or `include: false`, as `markdown.fence` decides."
    m = CELL.match(info.strip() + " ")
    if not m or m[1].lower() not in EXECUTABLE:
        return False
    opts = {k: str(v).lower() for k, v in (env.get("cell_defaults") or {}).items()}
    for line in code.split("\n"):
        if not line.startswith("#|"):
            break
        k, _, v = line[2:].partition(":")
        opts[k.strip()] = v.strip()
    return opts.get("echo") == "false" or opts.get("include") == "false"


class Prose:
    "Turn a page's Markdown into the copy's: Pandoc's divs become HTML divs, conditional content is kept or dropped, and links are rewritten."

    def __init__(
        self,
        link: Callable[[str], str],  # Rewrites one link, to another page's copy
        env: dict,  # The page's render environment
    ):
        self.link, self.env = link, env
        self.stack: list[str] = []  # for each open div: `div`, `unwrap` (conditional and kept) or `drop`

    @property
    def dropping(self) -> bool:  # Whether the text here is left out
        "Say whether an open div is dropped, so the text here is left out of the copy."
        return "drop" in self.stack

    def feed(
        self,
        body: str,  # Markdown; a div may open in one call and close in a later one, as across a notebook's cells
    ) -> str:  # The Markdown for the copy
        "Turn some Markdown into the copy's; code blocks, maths and comments stay as they are."
        out: list[str] = []
        lines, i = body.splitlines(), 0
        comment = False
        while i < len(lines):
            line, i = lines[i], i + 1
            m = FENCE.match(line)
            if comment or (m is None and "<!--" in line):
                comment = "-->" not in line.split("<!--")[-1] if "<!--" in line else "-->" not in line
                if not self.dropping:
                    out.append(line)
                continue
            if m:
                block = [line]
                while i < len(lines):
                    block.append(lines[i])
                    i += 1
                    c = FENCE.match(block[-1])
                    if c and c[1][0] == m[1][0] and len(c[1]) >= len(m[1]) and not block[-1].strip(" `~"):
                        break
                code = "\n".join(block[1:-1])
                if not self.dropping and not hidden_cell(line.strip()[len(m[1]) :], code, self.env):
                    out += block
                continue
            params = is_fence_line(line)
            if params:
                a = parse_attrs(params)
                keep = kept(a.classes, a.kv, self.env)
                self.stack.append("drop" if self.dropping or keep is False else "unwrap" if keep else "div")
                if self.stack[-1] == "div":
                    out += [tag("div", params), ""]
            elif params is not None:
                if self.stack and self.stack.pop() == "div":
                    out += ([] if out and out[-1] == "" else [""]) + ["</div>", ""]  # blank lines, so Markdown is read on both sides
            elif not self.dropping:
                out.append(inline(line, self.link, self.env))
        return "\n".join(out)

    def close(self) -> str:  # The closing tags of the divs still open
        "Close the divs left open at the end of the page."
        shut = ["</div>" for k in self.stack if k == "div"]
        self.stack = []
        return "\n\n".join(shut)


def prose(
    body: str,  # Markdown, after includes and shortcodes
    p: Prose,  # The converter, with the page's links and environment
) -> str:  # The Markdown for the copy
    "Turn a page's Markdown into its copy's, with every div closed."
    return "\n\n".join(x for x in (p.feed(body).strip("\n"), p.close()) if x)


def indent(
    text: str,  # Text to show as code
) -> str:  # The text indented by four spaces, Markdown's indented code block
    "Indent text by four spaces, as nbconvert's `indent` filter does."
    return "\n".join("    " + x if x.strip() else "" for x in text.rstrip("\n").split("\n"))


def joined(
    value: str | list,  # A notebook string, which may be stored as a list of lines
) -> str:  # It as one string
    "Join a notebook string that is stored as a list of lines."
    return "".join(value) if isinstance(value, list) else value


def output(
    out: dict,  # One stored output of a code cell
    name: str,  # The file name for a picture, without its extension
    files: dict[str, bytes],  # The pictures to save beside the copy; this adds to it
    folder: str,  # The folder of the pictures, relative to the copy
) -> str:  # The output as Markdown
    "Write one stored output as nbconvert's Markdown exporter does."
    kind = out.get("output_type")
    if kind == "stream":
        return indent(ANSI.sub("", joined(out.get("text", ""))))
    if kind == "error":
        return indent(ANSI.sub("", "\n".join(out.get("traceback") or [f"{out.get('ename')}: {out.get('evalue')}"])))
    data = out.get("data") or {}
    mime = next((m for m in NB_ORDER if m in data), None)
    if mime is None:
        return ""
    value = joined(data[mime])
    if mime in NB_FILES:
        file = name + NB_FILES[mime]
        files[file] = value.encode() if mime == "image/svg+xml" else base64.b64decode(value)
        return f"![{mime.split('/')[1].split('+')[0]}]({folder}/{file})"
    return indent(value) if mime == "text/plain" else value.strip("\n")


def notebook(
    text: str,  # The notebook's JSON
    defaults: dict,  # The page's `echo`, `output` and `include`, which a cell's `#|` options override
    stem: str,  # The notebook's name without `.ipynb`, which names its pictures
    prose: Prose,  # Turns the Markdown cells into the copy's; a div may span cells
    expand: Callable[[str], str],  # Expands the shortcodes of a Markdown cell
) -> tuple[str, dict[str, bytes]]:  # The copy's body, and the pictures to save beside it, by path
    "Write a notebook as nbconvert's Markdown exporter does, showing the cells and outputs that the page shows."
    nb = json.loads(text)
    meta = nb.get("metadata") or {}
    lang = (meta.get("kernelspec") or {}).get("language") or (meta.get("language_info") or {}).get("name") or "python"
    folder = f"{stem}_files"
    parts: list[str] = []
    files: dict[str, bytes] = {}
    for n, cell in enumerate(nb.get("cells", [])):
        src, kind = source(cell), cell.get("cell_type")
        tags = set((cell.get("metadata") or {}).get("tags") or [])
        if "remove-cell" in tags:
            continue
        if kind in ("markdown", "raw"):
            rest = split_front_matter(src)[1] if n == 0 else src
            for name, bundle in (cell.get("attachments") or {}).items() if kind == "markdown" else ():
                data = next(iter(bundle.values()), "")
                file = f"{stem}_{n}_" + re.sub(r"[^\w.-]", "_", name)  # never a path out of the folder
                files[file] = base64.b64decode(joined(data))
                rest = rest.replace(f"attachment:{name}", f"{folder}/{file}")
            parts.append(prose.feed(expand(rest)).strip("\n"))
        elif kind == "code" and not prose.dropping:
            own, code = cell_options(src)
            opts = {**defaults, **own}
            if opts.get("include") is False:
                continue
            if opts.get("echo", True) is not False and code.strip() and "remove-input" not in tags:
                f = fence_for(code)
                parts.append(f"{f}{lang}\n{code.strip(chr(10))}\n{f}")
            if opts.get("output", True) is not False and "remove-output" not in tags:
                for i, out in enumerate(cell.get("outputs", [])):
                    parts.append(output(out, f"{stem}_{n}_{i}", files, folder))
    parts.append(prose.close())
    return "\n\n".join(p for p in parts if p.strip()), {f"{folder}/{k}": v for k, v in files.items()}


def page_markdown(
    title: str,  # The page's title
    description: str,  # Its description, or empty
    body: str,  # The copy's body
) -> str:  # The Markdown copy
    "Put a page's title and description on top of its copy's body."
    head = [f"# {title}"] + ([description] if description else [])
    return "\n\n".join([*head, body.strip()]) + "\n"


def index(
    title: str,  # The site's title
    description: str,  # The site's description, or empty
    pages: list[tuple[str, str]],  # Each page's title and the address of its Markdown copy
) -> str:  # The text of `llms.txt`
    "Write `llms.txt`, as Quarto does: the site's title, its description, and a list of the pages."
    lines = [f"# {title or 'Untitled'}", ""]
    if description:
        lines += [f"> {description}", ""]
    lines += ["## Pages", ""]
    lines += [f"- [{t}]({p})" for t, p in pages]
    return "\n".join(lines) + "\n"
