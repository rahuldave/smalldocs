"Turn a Jupyter notebook into Markdown that the page pipeline renders: its cells and their stored outputs, never run."

import base64
import html
import json
import re

import yaml

from .markdown import split_front_matter

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
DISPLAY_ORDER = ["text/html", "image/svg+xml", "image/png", "image/jpeg", "image/gif", "text/markdown", "text/latex", "text/plain"]


def source(
    cell: dict,  # A notebook cell
) -> str:  # Its source as one string
    "Join a cell's source, which a notebook may store as a list of lines."
    s = cell.get("source", "")
    return "".join(s) if isinstance(s, list) else s


def fence_for(
    text: str,  # What goes inside the fence
) -> str:  # A run of backticks longer than any in the text
    "Choose a code fence that the text cannot close."
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def raw_html(
    content: str,  # HTML
) -> str:  # A Markdown raw block that passes the HTML through untouched
    "Wrap HTML in a raw `{=html}` block."
    f = fence_for(content)
    return f"{f}{{=html}}\n{content}\n{f}\n"


def cell_options(
    code: str,  # The source of a code cell
) -> tuple[dict, str]:  # The `#|` options, and the code without them
    "Read Quarto's `#| key: value` options from the top of a code cell."
    lines = code.split("\n")
    opts = []
    while lines and lines[0].startswith("#|"):
        opts.append(lines.pop(0)[2:].strip())
    try:
        parsed = yaml.safe_load("\n".join(opts)) if opts else {}
    except yaml.YAMLError:
        parsed = {}
    return (parsed if isinstance(parsed, dict) else {}), "\n".join(lines)


IMAGES = ("image/svg+xml", "image/png", "image/jpeg", "image/gif")


def figure(
    img: str,  # The HTML of the picture
    opts: dict,  # The cell's `#|` options
    n: int,  # Which figure of the cell this is, from 0, for a list of captions
) -> str:  # The picture, in a figure with its caption, when the cell asks for one
    "Put a picture in Quarto's figure markup when the cell has `fig-cap`, `fig-alt` or `fig-align`."
    caps = opts.get("fig-cap")
    cap = caps[n] if isinstance(caps, list) and n < len(caps) else (caps if isinstance(caps, str) else None)
    alt, align = opts.get("fig-alt"), opts.get("fig-align")
    if cap is None and alt is None and align is None:
        return img
    if alt is not None:
        img = re.sub(r"^<(img|svg)\b", lambda m: f'<{m.group(1)} alt="{html.escape(str(alt))}"', img, count=1)
    side = align if align in ("left", "right", "center") else "center"
    caption = f'\n<figcaption>{html.escape(str(cap))}</figcaption>' if cap is not None else ""
    return f'<div class="quarto-figure quarto-figure-{side}">\n<figure class="figure">\n<p>{img}</p>{caption}\n</figure>\n</div>'


def output_html(
    out: dict,  # One output of a code cell
    opts: dict | None = None,  # The cell's `#|` options: `fig-cap`, `fig-alt`, `fig-align`, `tbl-cap`
    n: int = 0,  # Which picture of the cell this is, from 0
) -> str:  # Markdown for it: raw HTML, or Markdown when the output is Markdown
    "Render one stored output as Quarto does: streams and plain text in `<pre>`, pictures inline, HTML as it is."
    opts = opts or {}
    kind = out.get("output_type")
    if kind == "stream":
        text = ANSI.sub("", "".join(out.get("text", "")) if isinstance(out.get("text"), list) else out.get("text", ""))
        cls = "cell-output-stderr" if out.get("name") == "stderr" else "cell-output-stdout"
        return raw_html(f'<div class="cell-output {cls}">\n<pre><code>{html.escape(text.rstrip(chr(10)))}</code></pre>\n</div>')
    if kind == "error":
        tb = ANSI.sub("", "\n".join(out.get("traceback") or [f"{out.get('ename')}: {out.get('evalue')}"]))
        return raw_html(f'<div class="cell-output cell-output-error">\n<pre><code>{html.escape(tb)}</code></pre>\n</div>')
    data = out.get("data") or {}
    mime = next((m for m in DISPLAY_ORDER if m in data), None)
    if mime is None:
        return ""
    value = data[mime]
    value = "".join(value) if isinstance(value, list) else value
    if mime == "text/markdown":
        return f"::: {{.cell-output .cell-output-display .cell-output-markdown}}\n{value}\n:::\n"
    if mime == "text/plain":
        return raw_html(f'<div class="cell-output cell-output-display">\n<pre><code>{html.escape(value)}</code></pre>\n</div>')
    if mime == "text/latex":
        return f"::: {{.cell-output .cell-output-display}}\n{value}\n:::\n"
    if mime == "text/html":
        cap = opts.get("tbl-cap")
        if isinstance(cap, str) and re.search(r"<table\b[^>]*>", value):
            value = re.sub(r"(<table\b[^>]*>)", lambda m: f"{m.group(1)}\n<caption>{html.escape(cap)}</caption>", value, count=1)
        return raw_html(f'<div class="cell-output cell-output-display">\n{value}\n</div>')
    if mime == "image/svg+xml":
        fig = figure(value.strip(), opts, n)
        return raw_html(f'<div class="cell-output cell-output-display">\n{value if fig == value.strip() else fig}\n</div>')
    b64 = value if isinstance(value, str) else base64.b64encode(value).decode()
    img = f'<img src="data:{mime};base64,{b64.strip()}" class="img-fluid">'
    return raw_html(f'<div class="cell-output cell-output-display">\n{figure(img, opts, n)}\n</div>')


COLUMN = re.compile(r"(body|body-outset|page|page-inset|screen|screen-inset|margin)(-left|-right)?|screen-inset-shaded")


def code_attrs(
    own: dict,  # The cell's own `#|` options
) -> str:  # Attributes for the cell's code block, empty when the cell sets none of them
    "Pass a cell's own `code-fold`, `code-summary`, `code-line-numbers` and `code-overflow` to its code block."
    out = ""
    for k in ("code-fold", "code-summary", "code-line-numbers", "code-overflow"):
        if k in own and own[k] is not None:
            v = str(own[k]).lower() if isinstance(own[k], bool) else str(own[k])
            q = "'" if '"' in v else '"'
            out += f" {k}={q}{v.replace(q, '')}{q}"
    return out


def wrap_outputs(
    outs: list[str],  # The Markdown of a cell's outputs
    opts: dict,  # The cell's `#|` options: `column`, `fig-column`, `tbl-column`, `layout-ncol` and `layout-nrow`
) -> list[str]:  # The outputs, in a div when an option asks for one
    "Put a cell's outputs in a column or a grid when its options ask for one; with none, the outputs are as they were."
    # `column` puts the outputs, and not the code, in a column, as Quarto does
    cls = [f".column-{opts[k]}" for k in ("column", "fig-column", "tbl-column") if isinstance(opts.get(k), str) and COLUMN.fullmatch(opts[k])]
    ncol, nrow = (str(opts.get(k, "")).strip() for k in ("layout-ncol", "layout-nrow"))
    attrs = [f"layout-ncol={int(ncol)}"] if ncol.isdigit() and int(ncol) > 0 else []
    attrs += [f"layout-nrow={int(nrow)}"] if nrow.isdigit() and int(nrow) > 0 else []
    if not outs or not (cls or attrs):
        return outs
    fence = ":" * 4
    return [f"{fence} {{{' '.join(cls[:1] + attrs)}}}", *outs, fence]


def to_markdown(
    text: str,  # The notebook's JSON
    defaults: dict | None = None,  # The page's `echo`, `output` and `include`, which a cell's `#|` options override
) -> tuple[dict, str]:  # Its front matter, and its body as Markdown
    "Turn a notebook into front matter and Markdown, as Quarto renders a notebook without running it."
    nb = json.loads(text)
    if not isinstance(nb, dict):
        raise ValueError("not a notebook: the top level is not an object")
    if int(nb.get("nbformat") or 4) < 4:
        raise ValueError(f"nbformat {nb.get('nbformat')} is too old; open and save the notebook in Jupyter to make it nbformat 4")
    lang = ((nb.get("metadata") or {}).get("kernelspec") or {}).get("language") or ((nb.get("metadata") or {}).get("language_info") or {}).get("name") or "python"
    meta: dict = {}
    parts: list[str] = []
    for n, cell in enumerate(nb.get("cells", [])):
        src = source(cell)
        kind = cell.get("cell_type")
        tags = set((cell.get("metadata") or {}).get("tags") or [])
        if "remove-cell" in tags:
            continue
        if kind == "raw":
            front, rest = split_front_matter(src)
            if n == 0 and front:
                meta = front
                continue
            parts.append(rest)
        elif kind == "markdown":
            front, rest = split_front_matter(src) if n == 0 else ({}, src)
            meta = meta or front
            for name, bundle in (cell.get("attachments") or {}).items():
                mime, data = next(iter(bundle.items()), ("", ""))
                data = "".join(data) if isinstance(data, list) else data
                rest = rest.replace(f"attachment:{name}", f"data:{mime};base64,{data.strip()}")
            parts.append(rest.strip("\n") + "\n")
        elif kind == "code":
            own, code = cell_options(src)
            opts = {**(defaults or {}), **own}
            if opts.get("include") is False:
                continue
            cid = opts.get("label") or f"cell-{n}"
            block = [f'::: {{.cell #{cid}}}']
            if opts.get("echo", True) is not False and code.strip() and "remove-input" not in tags:
                f = fence_for(code)
                block.append(f"{f}{{.{lang} .cell-code{code_attrs(own)}}}\n{code.rstrip()}\n{f}")
            if opts.get("output", True) is not False and "remove-output" not in tags:
                outs, pics = [], 0
                for out in cell.get("outputs", []):
                    o = output_html(out, opts, pics)
                    data = out.get("data") or {}
                    pics += next((m for m in DISPLAY_ORDER if m in data), None) in IMAGES  # the next caption of a list goes to the next picture
                    if o:
                        outs.append(o)
                block += wrap_outputs(outs, opts)
            block.append(":::")
            parts.append("\n\n".join(block) + "\n")
    return meta, "\n".join(parts)
