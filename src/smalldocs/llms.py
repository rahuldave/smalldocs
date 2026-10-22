"Write the Markdown copy of each page, `page.llms.md`, and the index `llms.txt`, for `website.llms-txt`."

import base64
import binascii
import html
import json
import re
from collections.abc import Callable

from .markdown import EXECUTABLE, is_fence_line, make_parser, parse_attrs, shown, split_front_matter
from .notebook import ANSI, DISPLAY_ORDER, IMAGES, cell_options, fence_for, source

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


DIV_END = re.compile(r"[ >]*:{3,}\s*")  # a line that only ends a div
PARSER = make_parser()  # the page's parser; only its block step is used, to find the page's divs, code and HTML


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
        "Turn some Markdown into the copy's; code blocks and HTML blocks stay as they are."
        out: list[str] = []
        lines, i = re.split(r"\r\n?|\n", body.rstrip()), 0  # the lines as markdown-it numbers them; trailing blank lines add none
        # the page's own blocks, from the block step of the parser that builds the page: where divs open, and where code and HTML are
        blocks: list = []
        PARSER.block.parse("\n".join(lines), PARSER, {}, blocks)
        opens = {t.map[0]: t for t in blocks if t.type == "div_open" and t.map}
        code = {t.map[0]: t for t in blocks if t.map and t.type in ("fence", "code_block", "html_block")}
        contained, depth = set(), 0  # the divs inside a list or a quote, which end with it
        for t in blocks:
            depth += t.nesting if t.type.startswith(("blockquote_", "list_item_")) else 0
            if t.type == "div_open" and depth:
                contained.add(t.map[0])
        ends: dict[int, list[str]] = {}  # the line where divs opened here end, and the quote marks before each
        base = len(self.stack)  # divs opened in an earlier call, as in an earlier cell of a notebook
        while i < len(lines):
            if i in ends:  # a div's end, where the page has it
                for quote in reversed(ends.pop(i)):  # the inner div first
                    self.close(out, quote)
                if DIV_END.fullmatch(lines[i]):
                    i += 1
                    continue
            if i in code:
                t, start, i = code[i], i, code[i].map[1]
                if not self.dropping and not (t.type == "fence" and hidden_cell(t.info, t.content, self.env)):
                    out += lines[start:i]
                continue
            line, i = lines[i], i + 1
            if i - 1 in opens:
                t = opens[i - 1]
                quote = re.match(r"[ >]*", line)[0]
                if t.map[1] < len(lines) or i - 1 in contained:  # a div left open outside a list or a quote goes on, into a notebook's next cell
                    ends.setdefault(t.map[1], []).append(quote)
                a = parse_attrs(t.info)
                keep = kept(a.classes, a.kv, self.env)
                self.stack.append("drop" if self.dropping or keep is False else "unwrap" if keep else "div")
                if self.stack[-1] == "div":
                    out += [quote + tag("div", t.info), quote.rstrip()]
            elif is_fence_line(line) == "" and base and not ends:  # the end of a div that an earlier call opened
                base -= 1
                self.close(out, "")
            elif not self.dropping:
                out.append(inline(line, self.link, self.env))
        for quote in reversed(ends.pop(len(lines), [])):  # a div left open in a quote or a list ends with it, as on the page
            self.close(out, quote)
        return "\n".join(out)

    def close(
        self,
        out: list[str],  # The copy's lines so far; this adds to it
        quote: str,  # The quote marks before the div's lines
    ) -> None:
        "End the innermost open div: write its closing tag, unless it was dropped or unwrapped."
        if self.stack.pop() == "div":
            blank = quote.rstrip()
            out += ([] if out and out[-1] == blank else [blank]) + [quote + "</div>", blank]  # blank lines, so Markdown is read on both sides

    def finish(self) -> str:  # The closing tags of the divs still open
        "Close the divs left open at the end of the page."
        shut = ["</div>" for k in self.stack if k == "div"]
        self.stack = []
        return "\n\n".join(shut)


def prose(
    body: str,  # Markdown, after includes and shortcodes
    p: Prose,  # The converter, with the page's links and environment
) -> str:  # The Markdown for the copy
    "Turn a page's Markdown into its copy's, with every div closed."
    return "\n\n".join(x for x in (p.feed(body).strip("\n"), p.finish()) if x)


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
    opts: dict,  # The cell's options, for `fig-cap` and `fig-alt`
    n: int,  # Which picture of the cell this is, from 0, for a list of captions
    caption: Callable[[str], str],  # Rewrites a caption's links
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
        try:
            files[file] = value.encode() if mime == "image/svg+xml" else base64.b64decode(value)
        except (binascii.Error, ValueError):
            return ""  # a picture whose data is broken
        caps, alt = opts.get("fig-cap"), opts.get("fig-alt")
        cap = caps[n] if isinstance(caps, list) and n < len(caps) else caps if isinstance(caps, str) else None
        alt = " ".join(str(alt).split()) if alt is not None else mime.split("/")[1].split("+")[0]
        alt = re.sub(r"([\\\[\]])", r"\\\1", alt)  # so a bracket in it does not end the alt text
        img = f"![{alt}]({folder}/{file})"
        return img if cap is None else f'{img}\n\n<div class="figure-caption">\n\n{caption(str(cap))}\n\n</div>'

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
                try:
                    files[file] = base64.b64decode(joined(data))
                except (binascii.Error, ValueError):
                    continue  # an attachment whose data is broken
                rest = rest.replace(f"attachment:{name}", f"{folder}/{file}")
            text = prose.feed(expand(rest)).strip("\n")
            for file in [f for f in files if f.startswith(f"{stem}_{n}_") and f"{folder}/{f}" not in text]:
                del files[file]  # an attachment of a cell the copy leaves out
            parts.append(text)
        elif kind == "code" and not prose.dropping:
            own, code = cell_options(src)
            opts = {**defaults, **own}
            if opts.get("include") is False:
                continue
            if opts.get("echo", True) is not False and code.strip() and "remove-input" not in tags:
                f = fence_for(code)
                parts.append(f"{f}{lang}\n{code.strip(chr(10))}\n{f}")
            if opts.get("output", True) is not False and "remove-output" not in tags:
                pics = 0
                for i, out in enumerate(cell.get("outputs", [])):
                    parts.append(output(out, f"{stem}_{n}_{i}", files, folder, opts, pics, lambda c: inline(c, prose.link, prose.env)))
                    data = out.get("data") or {}
                    pics += next((m for m in DISPLAY_ORDER if m in data), None) in IMAGES  # count pictures as the page does, for the captions
    parts.append(prose.finish())
    return "\n\n".join(p for p in parts if p.strip()), {f"{folder}/{k}": v for k, v in files.items()}


def page_markdown(
    title: str,  # The page's title, or empty when the body starts with it
    description: str,  # Its description, or empty
    body: str,  # The copy's body
) -> str:  # The Markdown copy
    "Put a page's title and description on top of its copy's body."
    head = ([f"# {title}"] if title else []) + ([description] if description else [])
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
