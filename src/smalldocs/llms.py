"Write the Markdown copy of each page, `page.llms.md`, and the index `llms.txt`, as Quarto's `website.llms-txt` does."

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
BLOCK = {
    "address", "article", "aside", "blockquote", "details", "dd", "div", "dl", "dt", "figcaption", "figure", "footer",
    "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section",
    "summary", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
}  # fmt: skip
DROP_TAGS = {"script", "style", "noscript", "template", "button", "select", "option", "nav", "head", "title", "meta", "link"}
# As Quarto's `llms.lua`: the parts of a page that are not its content
DROP_CLASSES = {
    "listing-actions-group", "listing-no-matching", "listing-categories", "quarto-listing-category", "listing-category",
    "quarto-page-breadcrumbs", "code-with-filename-file", "llms-hidden-content", "callout-header", "visually-hidden",
    "code-copy-button", "listing-pagination", "footnotes-sep",
}  # fmt: skip
CALLOUT_KINDS = ("note", "tip", "important", "warning", "caution")
RULE = "-" * 72  # Pandoc's thematic break


@dataclass
class Node:
    "An element of the page: its tag, its attributes, and its children, which are nodes or text."

    tag: str  # The tag, such as `p`
    attrs: dict = field(default_factory=dict)  # Its attributes
    children: list = field(default_factory=list)  # Nodes and strings

    @property
    def classes(self) -> set[str]:  # Its classes
        "The element's classes."
        return set((self.attrs.get("class") or "").split())

    def text(self) -> str:  # All the text under it, as it is
        "Join the text of the element and of everything under it."
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)

    def find(
        self,
        pred: Callable[["Node"], bool],  # A test of a node
    ) -> "Node | None":  # The first node under this one that passes, depth first
        "Find the first element under this one that passes a test."
        for c in self.children:
            if isinstance(c, Node):
                if pred(c):
                    return c
                hit = c.find(pred)
                if hit is not None:
                    return hit
        return None


class TreeBuilder(HTMLParser):
    "Read HTML into a tree of `Node`s."

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]

    def handle_starttag(
        self,
        tag: str,  # The element's tag
        attrs: list[tuple[str, str | None]],  # Its attributes
    ) -> None:
        "Open an element; one that cannot hold content is closed at once."
        node = Node(tag, {k: (v or "") for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(
        self,
        tag: str,  # The element's tag
        attrs: list[tuple[str, str | None]],  # Its attributes
    ) -> None:
        "Add an element written as `<tag/>`."
        self.stack[-1].children.append(Node(tag, {k: (v or "") for k, v in attrs}))

    def handle_endtag(
        self,
        tag: str,  # The tag that ends
    ) -> None:
        "Close the nearest open element with this tag, and any left open inside it; an end tag with none open is ignored."
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(
        self,
        data: str,  # Text
    ) -> None:
        "Add text to the open element."
        self.stack[-1].children.append(data)


def parse(
    text: str,  # HTML
) -> Node:  # Its tree, under a node called `root`
    "Read HTML into a tree."
    b = TreeBuilder()
    b.feed(text)
    b.close()
    return b.root


def is_block(
    n: object,  # A node or a string
) -> bool:  # Whether it is a block, or an inline element that holds a block
    "Say whether a child starts its own block."
    if not isinstance(n, Node):
        return False
    return n.tag in BLOCK or any(is_block(c) for c in n.children)


def dropped(
    n: Node,  # An element
) -> bool:  # Whether it is not content: navigation, buttons, scripts, the listing's controls
    "Say whether an element is left out of the Markdown."
    return n.tag in DROP_TAGS or bool(n.classes & DROP_CLASSES) or n.attrs.get("id") in ("quarto-header", "quarto-search-results")


def esc(
    text: str,  # Text from the page
) -> str:  # The text, with the characters that Markdown would read escaped
    "Escape text for Markdown, as Pandoc does, but leave an underscore inside a word alone."
    text = re.sub(r"([\\`*\[\]<$])", r"\\\1", text)
    text = re.sub(r"&(?=#?\w+;)", r"\\&", text)  # text that a reader would take for an entity, such as `&copy;`
    return re.sub(r"(?<![A-Za-z0-9])_|_(?![A-Za-z0-9])", r"\\_", text)


def ticks(
    code: str,  # Inline code
) -> str:  # The code between backticks that it cannot close
    "Put inline code between enough backticks."
    longest = max((len(m) for m in re.findall(r"`+", code)), default=0)
    t = "`" * (longest + 1)
    pad = " " if code.startswith("`") or code.endswith("`") else ""
    return f"{t}{pad}{code}{pad}{t}"


def md_link(
    href: str,  # A link of the page
) -> str:  # The link to the other page's Markdown copy, when it goes to a page of the site
    "Point a link to another page at that page's `.llms.md`, as Quarto does."
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:|^//", href):
        return href
    href = re.sub(r"\.html(?=#|$)", ".llms.md", href, count=1)
    href = href[2:] if href.startswith("./") else href
    return f"<{href}>" if re.search(r"[\s()<>]", href) else href


class Writer:
    "Write the content of a page as GitHub-flavoured Markdown."

    def __init__(self):
        self.notes: list[tuple[str, str]] = []  # The footnotes: their number and their text

    # ---- inline

    def inline(
        self,
        nodes: list,  # Nodes and strings
    ) -> str:  # Their Markdown, on one line but for hard breaks
        "Write inline content."
        parts: list[str] = []
        for c in nodes:
            md = self.one_inline(c)
            if md.startswith("["):
                before = "".join(parts)
                bangs = re.search(r"(\\*)!$", before)
                if bangs and len(bangs.group(1)) % 2 == 0:  # a `!` that no backslash escapes, so `![` would be a picture
                    parts = [before[:-1] + "\\!"]
            parts.append(md)
        return re.sub(r"[ \t]+", " ", "".join(parts))

    def one_inline(
        self,
        n: object,  # A node or a string
    ) -> str:  # Its Markdown
        "Write one inline element."
        if isinstance(n, str):
            return esc(re.sub(r"\s+", " ", n))
        if dropped(n):
            return ""
        t, cls = n.tag, n.classes
        if t == "br":
            return "\\\n"
        if t == "img":
            return self.image(n.attrs.get("alt", ""), n.attrs.get("src", ""))
        if t == "svg":
            return "[Image]"
        if t in ("iframe", "video"):
            src = n.attrs.get("src") or (n.find(lambda c: c.tag == "source") or Node("x")).attrs.get("src", "")
            return f"[Video]({src})" if src else ""
        if t == "input":
            return ""
        if t == "code":
            return ticks(n.text())
        if t == "span" and "math" in cls:
            return self.math(n.text(), "display" in cls)
        if t == "sup" and "footnote-ref" in cls:
            a = n.find(lambda c: c.tag == "a")
            num = re.sub(r"\D", "", (a or n).text())
            return f"[^{num}]" if num else ""
        if t == "a":
            if "footnote-backref" in cls or "footnote-back" in cls:
                return ""
            if n.attrs.get("role") == "doc-noteref" or (n.attrs.get("href", "").startswith("#fn") and n.attrs.get("id", "").startswith("fnref")):
                num = re.sub(r"\D", "", n.text())
                return f"[^{num}]" if num else ""
            text = self.inline(n.children).strip()
            href = n.attrs.get("href", "")
            if not text:
                return ""
            if href in ("", "#"):
                return text
            return f"[{text}]({md_link(href)})"
        inner = self.inline(n.children)
        if not inner.strip():
            return inner if t in ("span", "kbd") else ""
        if t in ("em", "i", "cite", "var", "dfn"):
            return self.wrap(inner, "*")
        if t in ("strong", "b"):
            return self.wrap(inner, "**")
        if t in ("s", "del", "strike"):
            return self.wrap(inner, "~~")
        return inner

    @staticmethod
    def wrap(
        inner: str,  # Inline Markdown
        mark: str,  # `*`, `**` or `~~`
    ) -> str:  # The text between the marks, with its outer spaces outside them
        "Put emphasis around text, keeping the spaces at its ends outside the marks."
        lead, core, trail = re.match(r"(\s*)(.*?)(\s*)$", inner, re.S).groups()
        return f"{lead}{mark}{core}{mark}{trail}"

    @staticmethod
    def image(
        alt: str,  # The picture's alt text
        src: str,  # Its address
    ) -> str:  # A Markdown image, or a note that the picture is in the page
        "Write a picture; one held inside the page, as a `data:` address, is named, not copied."
        if src.startswith("data:"):
            return f"[Image: {esc(alt)}]" if alt else "[Image]"
        return f"![{esc(alt)}]({md_link(src)})"

    @staticmethod
    def math(
        text: str,  # The text of a maths span: `\(...\)` or `\[...\]`
        display: bool,  # Whether it is display maths
    ) -> str:  # The maths between dollars
        "Write maths as `$...$` or `$$...$$`, as Quarto does."
        m = re.match(r"^\s*\\[(\[](.*)\\[)\]]\s*$", text, re.S)
        tex = (m.group(1) if m else text).strip()
        return f"$${tex}$$" if display else f"${tex}$"

    # ---- blocks

    def blocks(
        self,
        nodes: list,  # Nodes and strings
    ) -> list[str]:  # The Markdown of each block
        "Write a run of content as blocks; inline content between blocks becomes a paragraph."
        out, run = [], []

        def flush():
            para = self.inline(run).strip()
            if para:
                out.append(self.para(para))
            run.clear()

        for c in nodes:
            if is_block(c):
                flush()
                out += self.block(c)
            else:
                run.append(c)
        flush()
        return out

    @staticmethod
    def para(
        text: str,  # A paragraph's inline Markdown
    ) -> str:  # The paragraph, with a line start that Markdown would misread escaped
        "Escape what would start a heading, a quote or a list at the start of a line of a paragraph."
        text = re.sub(r"(?m)^(\s*)([#>+=-])", r"\1\\\2", text)
        return re.sub(r"(?m)^(\s*)(\d+)([.)])(?=\s)", r"\1\2\\\3", text)  # `6\.`, as Pandoc escapes it

    def block(
        self,
        n: Node,  # A block element
    ) -> list[str]:  # Its Markdown, as blocks
        "Write one block element."
        if dropped(n):
            return []
        t, cls = n.tag, n.classes
        if t == "div" and "callout" in cls:
            return [self.callout(n)]
        if t == "div" and "panel-tabset" in cls:
            return self.tabset(n)
        if t == "section" and "footnotes" in cls:
            self.footnotes(n)
            return []
        if t == "div" and "column-margin" in cls and any(isinstance(c, Node) and re.fullmatch(r"fn\d+", c.attrs.get("id", "")) for c in n.children):
            out = []
            for c in n.children:
                if isinstance(c, Node) and re.fullmatch(r"fn\d+", c.attrs.get("id", "")):
                    self.margin_note(c)
                elif is_block(c):
                    out += self.block(c)
            return out
        if t in ("h1", "h2", "h3", "h4", "h5", "h6"):
            text = self.inline(n.children).strip()
            return [f"{'#' * int(t[1])} {text}"] if text else []
        if t == "p":
            text = self.inline(n.children).strip()
            return [self.para(text)] if text else []
        if t == "pre":
            return [self.code(n)]
        if t in ("ul", "ol"):
            return [self.items(n)]
        if t == "blockquote":
            return [self.quote(self.blocks(n.children))]
        if t == "table":
            return self.table(n)
        if t == "figure":
            return self.figure(n)
        if t == "hr":
            return [RULE]
        if t == "dl":
            return self.deflist(n)
        if t == "summary":
            return []
        if t == "a" and n.attrs.get("href"):
            # a link around blocks, as in a listing: the heading keeps the link, and the rest is text, as Quarto writes it
            heads = ("h1", "h2", "h3", "h4", "h5", "h6")
            inner = [Node(c.tag, c.attrs, [Node("a", n.attrs, c.children)]) if isinstance(c, Node) and c.tag in heads else c for c in n.children]
            return self.blocks(inner)
        return self.blocks(n.children)

    def code(
        self,
        pre: Node,  # A `<pre>`
    ) -> str:  # A fenced code block
        "Write a code block, with its language, as a fence its code cannot close."
        code = pre.find(lambda c: c.tag == "code")
        text = (code or pre).text().rstrip("\n")
        lang = ""
        if "mermaid" in pre.classes:
            lang = "mermaid"
        else:
            written = ((code.attrs.get("class") or "") if code else "").split() + (pre.attrs.get("class") or "").split()
            for c in written:  # in the order written, so the language comes first
                if c not in ("sourceCode", "numberSource", "number-lines", "cell-code") and not c.startswith("code-"):
                    lang = c
                    break
        longest = max((len(m) for m in re.findall(r"`{3,}", text)), default=2)
        fence = "`" * (longest + 1)
        return f"{fence} {lang}\n{text}\n{fence}" if lang else f"{fence}\n{text}\n{fence}"

    @staticmethod
    def indent(
        text: str,  # Markdown
        first: str,  # What the first line starts with, such as `- `
    ) -> str:  # The text, its first line after `first` and the others indented to match
        "Indent a block under a list marker."
        pad = " " * len(first)
        lines = text.split("\n")
        return "\n".join([first + lines[0]] + [(pad + ln) if ln else "" for ln in lines[1:]])

    def items(
        self,
        n: Node,  # A `<ul>` or `<ol>`
    ) -> str:  # The list
        "Write a list; a task list keeps its boxes."
        items = [c for c in n.children if isinstance(c, Node) and c.tag == "li"]
        try:
            start = int(n.attrs.get("start", "1"))
        except ValueError:
            start = 1
        out = []
        for k, li in enumerate(items):
            box = li.find(lambda c: c.tag == "input" and c.attrs.get("type") == "checkbox")
            parts = self.blocks(li.children)
            tight = not any(isinstance(c, Node) and c.tag == "p" for c in li.children)
            body = parts[0] if parts else ""
            prev = parts[0] if parts else ""
            for part in parts[1:]:
                # only a list that may break into text, `- x` or `1. x`, follows text on the next line, or a list after a list
                listy = re.match(r"(- |1[.)] )\S", part) or (re.match(r"(- |\d+[.)] )\S", part) and re.match(r"(- |\d+[.)] )", prev))
                body += ("\n" if tight and listy else "\n\n") + part
                prev = part
            if box is not None:
                body = ("[x] " if "checked" in box.attrs else "[ ] ") + body
            mark = f"{start + k}. " if n.tag == "ol" else "- "
            out.append(self.indent(body, mark))
        loose = any(isinstance(c, Node) and c.tag == "p" for li in items for c in li.children)  # Pandoc's loose lists have paragraphs
        return ("\n\n" if loose else "\n").join(out)

    def quote(
        self,
        blocks: list[str],  # The blocks inside the quote
    ) -> str:  # The quote
        "Write blocks as a block quote."
        text = "\n\n".join(blocks)
        return "\n".join(f"> {ln}" if ln else ">" for ln in text.split("\n"))

    def callout(
        self,
        n: Node,  # A callout's div
    ) -> str:  # The callout as a quote that starts with its kind, as Quarto writes it
        "Write a callout as Quarto does: a block quote that starts with **NOTE:**, **TIP:** and so on."
        kind = next((k for k in CALLOUT_KINDS if f"callout-{k}" in n.classes), "note").upper()
        body = n.find(lambda c: "callout-body-container" in c.classes)
        return self.quote([f"**{kind}:**", *self.blocks(body.children if body else [])])

    def tabset(
        self,
        n: Node,  # A tabset's div
    ) -> list[str]:  # Each tab's title as a heading, then its content, as Quarto writes it
        "Write a tabset as Quarto does: a level-2 heading for each tab, then the tab's content."
        nav = n.find(lambda c: c.tag == "ul" and "nav-tabs" in c.classes)
        titles = [self.inline(a.children).strip() for li in (nav.children if nav else []) if isinstance(li, Node) for a in [li.find(lambda c: c.tag == "a")] if a]
        content = n.find(lambda c: "tab-content" in c.classes)
        panes = [c for c in (content.children if content else []) if isinstance(c, Node) and "tab-pane" in c.classes]
        out = []
        for k in range(max(len(titles), len(panes))):
            if k < len(titles) and titles[k]:
                out.append(f"## {titles[k]}")
            if k < len(panes):
                out += self.blocks(panes[k].children)
        return out

    def footnotes(
        self,
        n: Node,  # The page's footnotes section
    ) -> None:
        "Keep the footnotes, to write them at the end of the page."
        for li in n.children:
            if isinstance(li, Node) and li.tag == "ol":
                for item in li.children:
                    if isinstance(item, Node) and item.tag == "li":
                        num = re.sub(r"\D", "", item.attrs.get("id", "")) or str(len(self.notes) + 1)
                        self.notes.append((num, "\n\n".join(self.blocks(item.children))))

    def margin_note(
        self,
        n: Node,  # A footnote in the margin, `<div id="fnN">`, whose text starts with its number
    ) -> None:
        "Keep a footnote from the margin, without its number, to write it at the end of the page."
        num = n.attrs["id"][2:]

        def drop_mark(e: Node) -> bool:  # Whether the note's own number was found and removed under `e`
            "Remove the note's number, which smalldocs writes before the note's first text, wherever that text is."
            for k, c in enumerate(e.children):
                if isinstance(c, str):
                    if c.strip():
                        return False
                    continue
                after = e.children[k + 1] if k + 1 < len(e.children) else None
                own = isinstance(after, str) and after.startswith("\u00a0")  # smalldocs writes its number, then a no-break space
                if c.tag == "sup" and own and c.text().strip() == num and all(isinstance(x, str) and not x.strip() for x in e.children[:k]):
                    del e.children[k]
                    if k < len(e.children) and isinstance(e.children[k], str):
                        e.children[k] = e.children[k].lstrip("\u00a0 ")
                    return True
                if c.tag in ("a", "pre", "code"):
                    continue
                if drop_mark(c):
                    return True
            return False

        drop_mark(n)
        self.notes.append((num, "\n\n".join(self.blocks(n.children))))

    def cell(
        self,
        c: Node,  # A table cell
    ) -> str:  # Its content, on one line
        "Write a table cell on one line."
        text = " ".join(self.blocks(c.children)).replace("\n", " ")
        return text.replace("|", "\\|").strip()

    def table(
        self,
        n: Node,  # A `<table>`
    ) -> list[str]:  # Its caption, then the table as a pipe table
        "Write a table as a pipe table, its first row the header and its caption after it."
        rows: list[list[Node]] = []

        def walk(e: Node):
            for c in e.children:
                if isinstance(c, Node):
                    if c.tag == "tr":
                        rows.append([d for d in c.children if isinstance(d, Node) and d.tag in ("td", "th")])
                    elif c.tag in ("thead", "tbody", "tfoot"):
                        walk(c)

        walk(n)
        caption = n.find(lambda c: c.tag == "caption")
        cap = [self.para(self.inline(caption.children).strip())] if caption is not None and caption.text().strip() else []
        if not rows:
            return cap
        width = max(len(r) for r in rows)
        cells = [[self.cell(c) for c in r] + [""] * (width - len(r)) for r in rows]
        aligns = []
        for c in rows[0] + [Node("td")] * (width - len(rows[0])):
            a = c.attrs.get("align") or (re.search(r"text-align:\s*(\w+)", c.attrs.get("style", "")) or [None, ""])[1]
            aligns.append({"left": ":---", "center": ":---:", "right": "---:"}.get(a, "---"))
        lines = ["| " + " | ".join(cells[0]) + " |", "|" + "|".join(aligns) + "|"]
        lines += ["| " + " | ".join(r) + " |" for r in cells[1:]]
        return ["\n".join(lines), *cap]  # the caption after the table, as Quarto writes it

    def figure(
        self,
        n: Node,  # A `<figure>`
    ) -> list[str]:  # The figure: one picture with its caption as alt text, else its parts
        "Write a figure; a single picture takes its caption as its alt text, as Quarto does."
        cap = n.find(lambda c: c.tag == "figcaption")
        imgs = []

        def collect(e: Node):
            for c in e.children:
                if isinstance(c, Node):
                    if c.tag == "img":
                        imgs.append(c)
                    elif c.tag != "figcaption":
                        collect(c)

        collect(n)
        only_img = len(imgs) == 1 and not n.find(lambda c: c.tag in ("table", "pre", "svg"))
        if only_img and cap is not None:
            alt = re.sub(r"\s+", " ", cap.text()).strip() or imgs[0].attrs.get("alt", "")
            return [self.image(alt, imgs[0].attrs.get("src", ""))]
        body = [c for c in n.children if not (isinstance(c, Node) and c.tag == "figcaption")]
        out = self.blocks(body)
        if cap is not None:
            text = self.inline(cap.children).strip()
            if text:
                out = [*out, self.para(text)]  # after the figure or the table, as Quarto writes it
        return out

    def deflist(
        self,
        n: Node,  # A `<dl>`
    ) -> list[str]:  # Each term in bold, then its definition
        "Write a definition list as terms in bold, each followed by its definition."
        out = []
        for c in n.children:
            if isinstance(c, Node) and c.tag == "dt":
                out.append(f"**{self.inline(c.children).strip()}**")
            elif isinstance(c, Node) and c.tag == "dd":
                out += self.blocks(c.children)
        return out


def page_markdown(
    page_html: str,  # The whole HTML page, as written to the site
) -> str:  # The Markdown of its content: the `<main>` element, without navigation
    "Turn a built page into the Markdown copy that `llms-txt` writes beside it."
    root = parse(page_html)
    main = root.find(lambda c: c.tag == "main") or root.find(lambda c: c.tag == "body") or root
    w = Writer()
    blocks = [b for b in w.blocks(main.children) if b.strip()]
    if w.notes:
        blocks.append("## Footnotes")  # as Quarto writes it
    for num, text in w.notes:
        blocks.append(Writer.indent(text, f"[^{num}]: "))
    out = "\n\n".join(blocks)
    return re.sub(r"\n{3,}", "\n\n", out).strip() + "\n"


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
