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


def output_html(
    out: dict,  # One output of a code cell
) -> str:  # Markdown for it: raw HTML, or Markdown when the output is Markdown
    "Render one stored output as Quarto does: streams and plain text in `<pre>`, pictures inline, HTML as it is."
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
        return raw_html(f'<div class="cell-output cell-output-display">\n{value}\n</div>')
    if mime == "image/svg+xml":
        return raw_html(f'<div class="cell-output cell-output-display">\n{value}\n</div>')
    b64 = value if isinstance(value, str) else base64.b64encode(value).decode()
    return raw_html(f'<div class="cell-output cell-output-display">\n<img src="data:{mime};base64,{b64.strip()}" class="img-fluid">\n</div>')


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
                block.append(f"{f}{{.{lang} .cell-code}}\n{code.rstrip()}\n{f}")
            if opts.get("output", True) is not False and "remove-output" not in tags:
                block += [o for o in (output_html(out) for out in cell.get("outputs", [])) if o]
            block.append(":::")
            parts.append("\n\n".join(block) + "\n")
    return meta, "\n".join(parts)
