"Pandoc-flavoured Markdown to the HTML that Quarto makes, with markdown-it-py and a few rules of our own."

import html
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import yaml
from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from markdown_it.rules_block import StateBlock
from markdown_it.rules_core import StateCore
from markdown_it.token import Token
from markdown_it.utils import OptionsDict
from mdit_py_plugins.attrs import attrs_plugin
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

from .highlight import highlight

FRONT = re.compile(r"\A---[ \t]*\r?\n(.*?\r?\n)?(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)", re.S)
HEADING_ATTRS = re.compile(r"\s*\{([^{}]*)\}\s*$")
ATTR_ONLY = re.compile(r"""\s*(?:(?:[#.][^\s#{}"'=]+|[^\s=#.{}"']+=(?:"(?:[^"\\]|\\.)*"|'[^']*'|[^\s"'{}]+)|-)\s*)+""")
LINK_WITH_SPACES = re.compile(r"\]\(([^()<>\"'\s][^()<>\"'\n]*?\s[^()<>\"'\n]*?)\)")
ATTR_TOKEN = re.compile(r"""([#.][^\s#{}"'=]+)|([^\s=]+)=("(?:[^"\\]|\\.)*"|'[^']*'|[^\s]+)|(-)""")
CALLOUTS = {"note": "Note", "tip": "Tip", "warning": "Warning", "important": "Important", "caution": "Caution"}
EXECUTABLE = {"python", "r", "julia", "ojs", "bash", "sql"}


@dataclass
class Attrs:
    "Pandoc attributes: `{#id .class key=value}`."

    id: str = ""  # The identifier, without the `#`
    classes: list[str] = field(default_factory=list)  # The classes, without the dots
    kv: dict[str, str] = field(default_factory=dict)  # The other key and value pairs

    def html(self) -> str:  # The attributes as they go in an HTML tag, with a leading space, or empty
        "Write the attributes as HTML."
        out = f' id="{html.escape(self.id)}"' if self.id else ""
        if self.classes:
            out += f' class="{html.escape(" ".join(self.classes))}"'
        for k, v in self.kv.items():
            out += f' {html.escape(k)}="{html.escape(v)}"'
        return out


def parse_attrs(
    text: str,  # What is between the braces, or a bare word such as `callout-note`
) -> Attrs:  # The identifier, classes and pairs
    "Parse Pandoc attributes; a bare word with no `#` or `.` is a class, as in `::: warning`."
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1]
    elif text and not text.startswith(("#", ".")) and "=" not in text:
        return Attrs(classes=text.split())
    a = Attrs()
    for m in ATTR_TOKEN.finditer(text):
        if m.group(1):
            if m.group(1)[0] == "#":
                a.id = m.group(1)[1:]
            else:
                a.classes.append(m.group(1)[1:])
        elif m.group(2):
            v = m.group(3)
            if v[:1] in "\"'":
                v = v[1:-1].replace('\\"', '"')
            if m.group(2) == "class":
                a.classes += v.split()
            else:
                a.kv[m.group(2)] = v
        elif m.group(4):
            a.classes.append("unnumbered")
    return a


def split_front_matter(
    text: str,  # The whole source of a page
) -> tuple[dict, str]:  # The YAML front matter as a dict (empty when there is none), and the rest
    "Take the YAML front matter off the top of a page."
    m = FRONT.match(text)
    if not m:
        return {}, text
    meta = yaml.safe_load(m.group(1) or "") or {}
    if not isinstance(meta, dict):
        return {}, text
    rest = text[m.end() :]
    return meta, "\n" * text[: m.end()].count("\n") + rest  # keep line numbers right for messages


def pandoc_id(
    text: str,  # The plain text of a heading
) -> str:  # Its identifier, as Pandoc makes it
    "Make a heading's identifier by Pandoc's rules: lower case, punctuation gone, spaces to hyphens, from the first letter."
    kept = "".join(c.lower() for c in text if c.isalnum() or c.isspace() or c in "_-.")
    out = "-".join(kept.split())
    i = next((i for i, c in enumerate(out) if c.isalpha()), len(out))
    return out[i:] or "section"


def plain(
    tokens: list[Token] | None,  # The children of an inline token
) -> str:  # The text without its formatting
    "The plain text of an inline run: text and code, without links' targets or footnotes."
    out = []
    for t in tokens or []:
        if t.type in ("text", "code_inline", "math_inline"):
            out.append(t.content)
        elif t.type in ("softbreak", "hardbreak"):
            out.append(" ")
        elif t.type == "image":
            out.append(plain(t.children))
    return "".join(out)


# ---------------------------------------------------------------- block rule: fenced divs


def is_fence_line(
    line: str,  # One line of source
) -> str | None:  # The text after the colons, or None when the line is no div fence
    "Say whether a line opens or closes a fenced div, and give what follows the colons."
    m = re.match(r"^ {0,3}(:{3,})(.*)$", line)
    if not m:
        return None
    return m.group(2).strip().rstrip(":").strip()


def fenced_div(
    state: StateBlock,  # The block parser's state
    start: int,  # The line to try
    end: int,  # The line after the last one
    silent: bool,  # Only say whether a div starts here
) -> bool:  # Whether a div starts here
    "Parse `::: {.class}` ... `:::` into div tokens; a fence with no attributes closes the innermost div."
    if state.sCount[start] - state.blkIndent >= 4:
        return False
    first = state.src[state.bMarks[start] : state.eMarks[start]]
    params = is_fence_line(first)
    if not params:
        return False
    if silent:
        return True
    depth, line, code = 1, start, None
    while True:
        line += 1
        if line >= end:
            break
        text = state.src[state.bMarks[line] : state.eMarks[line]]
        if state.sCount[line] < state.blkIndent and text.strip():
            break
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})", text)
        if code:
            if fence and fence.group(1)[0] == code[0] and len(fence.group(1)) >= len(code) and not text.strip()[len(fence.group(1)) :].strip():
                code = None
            continue
        if fence:
            code = fence.group(1)
            continue
        p = is_fence_line(text)
        if p is None:
            continue
        depth += 1 if p else -1
        if depth == 0:
            break
    old_parent, old_max = state.parentType, state.lineMax
    state.parentType, state.lineMax = "div", line
    tok = state.push("div_open", "div", 1)
    tok.info, tok.map, tok.block = params, [start, line], True
    attrs = parse_attrs(params)
    tok.meta = {"attrs": attrs}
    state.md.block.tokenize(state, start + 1, line)
    close = state.push("div_close", "div", -1)
    close.block = True
    state.parentType, state.lineMax = old_parent, old_max
    state.line = line + 1
    return True


# ---------------------------------------------------------------- core rules


def heading_attrs(
    state: StateCore,  # The core parser's state
) -> None:  # Nothing; the headings are changed in place
    "Take `{#id .class}` off the end of each heading, before inline parsing, and keep it on the heading."
    toks = state.tokens
    for i, t in enumerate(toks):
        if t.type == "heading_open" and i + 1 < len(toks) and toks[i + 1].type == "inline":
            inl = toks[i + 1]
            m = HEADING_ATTRS.search(inl.content)
            a = Attrs()
            if m and not inl.content.rstrip().endswith("\\}") and ATTR_ONLY.fullmatch(m.group(1)):
                a = parse_attrs("{" + m.group(1) + "}")
                inl.content = inl.content[: m.start()].rstrip()
            t.meta = {**(t.meta or {}), "attrs": a}


INLINE_ATTRS = re.compile(r"(?<=[)\]`])\{([^{}\n]*)\}")
BARE_VALUE = re.compile(r"""(?<=[\s{])([\w:-]+)=([^\s"'{}]*[^\w:\s"'{}-][^\s"'{}]*)""")


def links_with_spaces(
    state: StateCore,  # The core parser's state
) -> None:  # Nothing; the inline tokens are changed in place
    "Let a link's target hold spaces, as Pandoc does: `[x](a b.qmd)` is read as `[x](<a b.qmd>)`."
    for t in state.tokens:
        if t.type == "inline" and "](" in t.content:
            parts = re.split(r"((`+).*?(?<!`)\2(?!`))", t.content, flags=re.S)  # code spans, kept as they are
            out = []
            for n, part in enumerate(parts):
                if n % 3 == 0:
                    out.append(LINK_WITH_SPACES.sub(lambda m: f"](<{m.group(1)}>)", part))
                elif n % 3 == 1:
                    out.append(part)
            t.content = "".join(out)


def quote_attr_values(
    state: StateCore,  # The core parser's state
) -> None:  # Nothing; the inline tokens are changed in place
    "Quote bare attribute values such as `width=50%`, which Pandoc reads and the attrs plugin does not."
    for t in state.tokens:
        if t.type == "inline" and "{" in t.content:
            t.content = INLINE_ATTRS.sub(lambda m: "{" + BARE_VALUE.sub(r'\1="\2"', " " + m.group(1))[1:] + "}", t.content)


def matching_close(
    toks: list[Token],  # The token list
    i: int,  # The index of an opening token
) -> int:  # The index of the token that closes it
    "Find the closing token of the block that opens at `i`."
    depth = 0
    for j in range(i, len(toks)):
        depth += toks[j].nesting
        if depth == 0:
            return j
    return len(toks) - 1


def raw(
    content: str,  # HTML
) -> Token:  # A token that renders the HTML as it is
    "Make a token of raw HTML."
    t = Token("html_block", "", 0)
    t.content = content
    return t


class Rules:
    "The core rules that run after inline parsing; each reads and writes `env`."

    def __init__(
        self,
        md: MarkdownIt,  # The parser they belong to
    ):
        self.md = md

    def ids(
        self,
        state: StateCore,  # The core parser's state
    ) -> None:  # Nothing; the headings and `env` are changed in place
        "Give every heading an identifier, as Pandoc does, unique on the page; note its text for the table of contents."
        env = state.env
        used: set[str] = env.setdefault("_ids", set())
        heads = env.setdefault("headings", [])
        for i, t in enumerate(state.tokens):
            if t.type != "heading_open":
                continue
            a: Attrs = (t.meta or {}).get("attrs") or Attrs()
            text = plain(state.tokens[i + 1].children)
            ident = a.id or pandoc_id(text)
            if not a.id:
                base, n = ident, 0
                while ident in used:
                    n += 1
                    ident = f"{base}-{n}"
            used.add(ident)
            a.id = ident
            t.meta = {**(t.meta or {}), "attrs": a, "text": text}
            heads.append({"level": int(t.tag[1]), "id": ident, "text": text, "classes": a.classes, "top": t.level == 0})

    def title(
        self,
        state: StateCore,  # The core parser's state
    ) -> None:  # Nothing; the tokens and `env` are changed in place
        "When the page has no title, a level-one heading at the very top becomes it, as in Quarto."
        env, toks = state.env, state.tokens
        if env.get("title") or not toks or toks[0].type != "heading_open" or toks[0].tag != "h1":
            return
        env["title"] = plain(toks[1].children)
        env["title_html"] = self.md.renderer.renderInline(toks[1].children or [], self.md.options, env)
        del toks[0:3]
        if env.get("headings"):
            env["headings"].pop(0)

    def callouts(
        self,
        state: StateCore,  # The core parser's state
    ) -> None:  # Nothing; the tokens are changed in place
        "Turn `::: {.callout-note}` divs into Quarto's callout markup, with a title from `title=` or a first heading."
        toks = state.tokens
        i = 0
        while i < len(toks):
            t = toks[i]
            a = (t.meta or {}).get("attrs") if t.type == "div_open" else None
            kind = next((c[8:] for c in a.classes if c.startswith("callout-") and c[8:] in CALLOUTS), None) if a else None
            if not kind:
                i += 1
                continue
            j = matching_close(toks, i)
            title = html.escape(a.kv.get("title", ""))
            if i + 1 < j and toks[i + 1].type == "heading_open":
                title = self.md.renderer.renderInline(toks[i + 2].children or [], self.md.options, state.env)
                gone = toks[i + 1].meta["attrs"].id
                state.env["headings"] = [h for h in state.env.get("headings", []) if h["id"] != gone]
                del toks[i + 1 : i + 4]
                j -= 3
            collapse = a.kv.get("collapse")
            appearance = a.kv.get("appearance", "default")
            icon = a.kv.get("icon", "true") != "false"
            titled = bool(title) or appearance != "minimal"
            title = title or CALLOUTS[kind]
            cid = a.id or f"callout-{state.env.setdefault('_callouts', [0])[0] + 1}"
            state.env["_callouts"][0] += 1
            classes = ["callout", f"callout-style-{appearance}", f"callout-{kind}", *(["callout-titled"] if titled else [])]
            classes += [c for c in a.classes if not c.startswith("callout-")]
            head = ""
            if titled:
                toggle = f' data-bs-toggle="collapse" data-bs-target="#{cid}-contents" aria-expanded="{str(collapse != "true").lower()}"' if collapse else ""
                chevron = '<div class="callout-btn-toggle d-inline-block border-0 py-1 ps-1 pe-0 float-end"><i class="callout-toggle"></i></div>' if collapse else ""
                head = (
                    f'<div class="callout-header d-flex align-content-center{" collapsed" if collapse == "true" else ""}"{toggle}>'
                    + ('<div class="callout-icon-container"><i class="callout-icon"></i></div>' if icon else "")
                    + f'<div class="callout-title-container flex-fill">{title}</div>{chevron}</div>'
                )
            body_cls = "callout-body-container callout-body"
            body_open = f'<div id="{cid}-contents" class="callout-collapse collapse{"" if collapse == "true" else " show"}"><div class="{body_cls}">' if collapse else f'<div class="{body_cls}">'
            toks[i] = raw(f'<div class="{" ".join(classes)}">{head}{body_open}\n')
            toks[j] = raw("</div></div></div>\n" if collapse else "</div></div>\n")
            i += 1

    def tabsets(
        self,
        state: StateCore,  # The core parser's state
    ) -> None:  # Nothing; the tokens are changed in place
        "Turn `::: {.panel-tabset}` divs into Bootstrap tabs, one tab for each heading at the first level found."
        toks = state.tokens
        n = 0
        i = 0
        while i < len(toks):
            t = toks[i]
            a = (t.meta or {}).get("attrs") if t.type == "div_open" else None
            if not (a and "panel-tabset" in a.classes):
                i += 1
                continue
            n += 1
            j = matching_close(toks, i)
            inner_level = t.level + 1
            heads = [k for k in range(i + 1, j) if toks[k].type == "heading_open" and toks[k].level == inner_level]
            if not heads:
                i += 1
                continue
            tag = toks[heads[0]].tag
            heads = [k for k in heads if toks[k].tag == tag]
            names = [self.md.renderer.renderInline(toks[k + 1].children or [], self.md.options, state.env) for k in heads]
            ids = [f"tabset-{n}-{m + 1}" for m in range(len(heads))]
            nav = "".join(
                f'<li class="nav-item" role="presentation"><a class="nav-link{" active" if m == 0 else ""}" id="{ids[m]}-tab" data-bs-toggle="tab"'
                f' data-bs-target="#{ids[m]}" role="tab" aria-controls="{ids[m]}" aria-selected="{str(m == 0).lower()}" href="">{name}</a></li>'
                for m, name in enumerate(names)
            )
            for state_head in state.env.get("headings", []):
                if state_head["id"] in {toks[k].meta["attrs"].id for k in heads}:
                    state_head["tab"] = True
            new = [raw(f'<div class="panel-tabset{"".join(" " + c for c in a.classes if c != "panel-tabset")}"><ul class="nav nav-tabs" role="tablist">{nav}</ul><div class="tab-content">\n')]
            for m, k in enumerate(heads):
                end = heads[m + 1] if m + 1 < len(heads) else j
                new.append(raw(f'<div id="{ids[m]}" class="tab-pane{" active" if m == 0 else ""}" role="tabpanel" aria-labelledby="{ids[m]}-tab">\n'))
                new += toks[k + 3 : end]
                new.append(raw("</div>\n"))
            new.append(raw("</div></div>\n"))
            toks[i : j + 1] = new
            i += len(new)

    def figures(
        self,
        state: StateCore,  # The core parser's state
    ) -> None:  # Nothing; the tokens are marked in place
        "An image alone in its paragraph, with alt text, becomes a figure with a caption, as Pandoc's implicit figures."
        toks = state.tokens
        for i in range(len(toks) - 2):
            if toks[i].type == "paragraph_open" and toks[i + 1].type == "inline" and toks[i + 2].type == "paragraph_close":
                kids = [c for c in toks[i + 1].children or [] if not (c.type == "text" and not c.content.strip())]
                if len(kids) == 1 and kids[0].type == "image" and kids[0].children:
                    toks[i].meta = {**(toks[i].meta or {}), "figure": kids[0]}
                    kids[0].meta = {**(kids[0].meta or {}), "figure": True}

    def sections(
        self,
        state: StateCore,  # The core parser's state
    ) -> None:  # Nothing; the tokens are changed in place
        "Wrap each top-level heading and what follows in `<section>`, as Pandoc's section divs."
        out, stack = [], []
        for t in state.tokens:
            if t.type == "heading_open" and t.level == 0:
                lvl = int(t.tag[1])
                while stack and stack[-1] >= lvl:
                    stack.pop()
                    out.append(raw("</section>\n"))
                a: Attrs = t.meta["attrs"]
                cls = " ".join([f"level{lvl}", *a.classes])
                kv = "".join(f' data-{html.escape(k)}="{html.escape(v)}"' for k, v in a.kv.items())
                out.append(raw(f'<section id="{html.escape(a.id)}" class="{html.escape(cls)}"{kv}>\n'))
                stack.append(lvl)
            out.append(t)
        out += [raw("</section>\n") for _ in stack]
        state.tokens[:] = out

    def typography(
        self,
        state: StateCore,  # The core parser's state
    ) -> None:  # Nothing; the text is changed in place
        "Dashes and ellipses as Pandoc's `smart` makes them: `---`, `--` and `...`."
        for t in state.tokens:
            for c in (t.children or []) if t.type == "inline" else []:
                if c.type == "text":
                    c.content = c.content.replace("---", "—").replace("--", "–").replace("...", "…")

    def search_text(
        self,
        state: StateCore,  # The core parser's state
    ) -> None:  # Nothing; the text goes in `env`
        "Note the text under each heading, for the search index."
        parts: list[dict] = []
        cur = {"id": "", "title": "", "text": []}
        parts.append(cur)
        for i, t in enumerate(state.tokens):
            if t.type == "heading_open":
                a = (t.meta or {}).get("attrs")
                cur = {"id": a.id if a else "", "title": (t.meta or {}).get("text", ""), "text": []}
                parts.append(cur)
            elif t.type == "inline" and not (i and state.tokens[i - 1].type == "heading_open"):
                cur["text"].append(plain(t.children))
            elif t.type in ("fence", "code_block") and not t.info.strip().startswith("{="):
                cur["text"].append(t.content)
        state.env["search"] = [{**p, "text": " ".join(" ".join(p["text"]).split())} for p in parts if p["text"] or p["id"]]


# ---------------------------------------------------------------- render rules


def heading_open(
    self: RendererHTML,  # The renderer
    tokens: Sequence[Token],  # The tokens of the page
    idx: int,  # The index of the token to render
    options: OptionsDict,  # The parser's options
    env: dict,  # The render environment
) -> str:  # The opening tag of the heading
    "Render a heading as Quarto does: the id is on the section; the heading has `anchored` and `data-anchor-id`."
    t = tokens[idx]
    a: Attrs = (t.meta or {}).get("attrs") or Attrs()
    if t.level == 0:
        num = ""
        if env.get("number_sections") and "unnumbered" not in a.classes:
            counts = env.setdefault("_counts", [0] * 7)
            lvl = int(t.tag[1])
            counts[lvl] += 1
            counts[lvl + 1 :] = [0] * (6 - lvl)
            first = env.get("_numfrom") or lvl
            env["_numfrom"] = first
            num = f'<span class="header-section-number">{".".join(str(c) for c in counts[first : lvl + 1])}</span> '
        return f'<{t.tag} class="anchored" data-anchor-id="{html.escape(a.id)}">{num}'
    cls = " ".join(["anchored", *a.classes])
    return f'<{t.tag} id="{html.escape(a.id)}" class="{html.escape(cls)}" data-anchor-id="{html.escape(a.id)}">'


def div_open(
    self: RendererHTML,  # The renderer
    tokens: Sequence[Token],  # The tokens of the page
    idx: int,  # The index of the token to render
    options: OptionsDict,  # The parser's options
    env: dict,  # The render environment
) -> str:  # The opening tag of the div
    "Render a fenced div with its attributes; `.cell` and other Quarto classes pass through."
    a: Attrs = tokens[idx].meta["attrs"]
    if "hidden" in a.classes:
        a.kv.setdefault("hidden", "")
    if "column-margin" in a.classes or "aside" in a.classes:
        a.classes.append("column-margin")
    return f"<div{a.html()}>\n"


def div_close(
    self: RendererHTML,  # The renderer
    tokens: Sequence[Token],  # The tokens of the page
    idx: int,  # The index of the token to render
    options: OptionsDict,  # The parser's options
    env: dict,  # The render environment
) -> str:  # The closing tag
    "Close a fenced div."
    return "</div>\n"


def paragraph_open(
    self: RendererHTML,  # The renderer
    tokens: Sequence[Token],  # The tokens of the page
    idx: int,  # The index of the token to render
    options: OptionsDict,  # The parser's options
    env: dict,  # The render environment
) -> str:  # The opening tag of the paragraph, or of the figure
    "Open a paragraph, or the figure that wraps a lone image."
    fig = (tokens[idx].meta or {}).get("figure")
    if fig is None:
        return self.renderToken(tokens, idx, options, env)
    return '<div class="quarto-figure quarto-figure-center">\n<figure class="figure">\n<p>'


def paragraph_close(
    self: RendererHTML,  # The renderer
    tokens: Sequence[Token],  # The tokens of the page
    idx: int,  # The index of the token to render
    options: OptionsDict,  # The parser's options
    env: dict,  # The render environment
) -> str:  # The closing tag of the paragraph, or the caption and the end of the figure
    "Close a paragraph, or the figure with its caption."
    open_ = tokens[idx - 2] if idx >= 2 else None
    fig = (open_.meta or {}).get("figure") if open_ is not None else None
    if fig is None:
        return self.renderToken(tokens, idx, options, env)
    cap = self.renderInline(fig.children or [], options, env)
    return f"</p>\n<figcaption>{cap}</figcaption>\n</figure>\n</div>\n"


def image(
    self: RendererHTML,  # The renderer
    tokens: Sequence[Token],  # The tokens of the page
    idx: int,  # The index of the token to render
    options: OptionsDict,  # The parser's options
    env: dict,  # The render environment
) -> str:  # The `<img>` tag
    "Render an image with Bootstrap's `img-fluid`, and its source rewritten for the page."
    t = tokens[idx]
    src = t.attrGet("src") or ""
    t.attrSet("src", env["link"](src, "src") if env.get("link") else src)
    cls = (t.attrGet("class") or "").split()
    cls += ["img-fluid"] + (["figure-img"] if (t.meta or {}).get("figure") else [])
    t.attrSet("class", " ".join(dict.fromkeys(cls)))
    for k in ("width", "height"):
        v = t.attrGet(k)
        if v and not v.isdigit():
            t.attrs.pop(k)
            t.attrSet("style", f"{t.attrGet('style') or ''}{k}: {v};")
    alt = plain(t.children)
    attrs = "".join(f' {k}="{html.escape(str(v))}"' for k, v in t.attrs.items() if k != "alt")
    return f'<img alt="{html.escape(alt)}"{attrs}>'


def link_open(
    self: RendererHTML,  # The renderer
    tokens: Sequence[Token],  # The tokens of the page
    idx: int,  # The index of the token to render
    options: OptionsDict,  # The parser's options
    env: dict,  # The render environment
) -> str:  # The opening tag of the link
    "Rewrite a link for the page: `.qmd`, `.md` and `.ipynb` to `.html`, and links from the root to relative ones."
    t = tokens[idx]
    href = t.attrGet("href") or ""
    if env.get("link"):
        t.attrSet("href", env["link"](href, "href"))
    if re.match(r"^https?://", href) and env.get("external_new_window"):
        t.attrSet("target", "_blank")
    env["_in_link"] = env.get("_in_link", 0) + 1
    return self.renderToken(tokens, idx, options, env)


def link_close(
    self: RendererHTML,  # The renderer
    tokens: Sequence[Token],  # The tokens of the page
    idx: int,  # The index of the token to render
    options: OptionsDict,  # The parser's options
    env: dict,  # The render environment
) -> str:  # The closing tag
    "Close a link."
    env["_in_link"] = max(0, env.get("_in_link", 0) - 1)
    return self.renderToken(tokens, idx, options, env)


def code_inline(
    self: RendererHTML,  # The renderer
    tokens: Sequence[Token],  # The tokens of the page
    idx: int,  # The index of the token to render
    options: OptionsDict,  # The parser's options
    env: dict,  # The render environment
) -> str:  # The `<code>` element, linked when it names a documented symbol
    "Render inline code; a documented name in backticks, outside a link, links to its reference entry."
    t = tokens[idx]
    attrs = "".join(f' {k}="{html.escape(str(v))}"' for k, v in t.attrs.items())
    code = f"<code{attrs}>{html.escape(t.content)}</code>"
    symbols = env.get("symbols") or {}
    key = re.sub(r"\(\)$", "", t.content)
    if key in symbols and not env.get("_in_link"):
        target = env["link"](symbols[key], "href") if env.get("link") else symbols[key]
        return f'<a href="{html.escape(target)}">{code}</a>'
    return code


def table_open(
    self: RendererHTML,  # The renderer
    tokens: Sequence[Token],  # The tokens of the page
    idx: int,  # The index of the token to render
    options: OptionsDict,  # The parser's options
    env: dict,  # The render environment
) -> str:  # The opening tag of the table
    "Render a table with Bootstrap's classes, as Quarto does."
    return '<table class="caption-top table">\n'


def fence(
    self: RendererHTML,  # The renderer
    tokens: Sequence[Token],  # The tokens of the page
    idx: int,  # The index of the token to render
    options: OptionsDict,  # The parser's options
    env: dict,  # The render environment
) -> str:  # The HTML of the block, or nothing
    "Render a fenced code block: raw `{=html}`, mermaid, or highlighted code with a copy button."
    t = tokens[idx]
    info = t.info.strip()
    body = t.content
    if re.fullmatch(r"\{=html\}", info):
        return body
    if re.fullmatch(r"\{=\w+\}", info):
        return ""
    lang, a = "", Attrs()
    m = re.fullmatch(r"\{([^{}]*)\}", info)
    if m:
        inner = m.group(1).strip()
        if inner and not inner.startswith(("#", ".")) and not re.match(r"^\w+=", inner):
            word, _, rest = inner.partition(" ")
            a = parse_attrs("{" + rest.replace(",", " ") + "}")
            lang = word.strip(",")
            if lang.lower() in EXECUTABLE:
                a.kv["_cell"] = "1"
        else:
            a = parse_attrs(inner)
            lang = a.classes.pop(0) if a.classes else ""
    elif info:
        lang, _, rest = info.partition(" ")
        if rest.strip().startswith("{"):
            a = parse_attrs(rest.strip())
    if lang == "mermaid":
        env["mermaid"] = True
        return f'<pre class="mermaid">{html.escape(body.rstrip())}</pre>\n'
    if "_cell" in a.kv:
        opts = {k: str(v).lower() for k, v in (env.get("cell_defaults") or {}).items()}
        lines = body.split("\n")
        while lines and lines[0].startswith("#|"):
            k, _, v = lines.pop(0)[2:].partition(":")
            opts[k.strip()] = v.strip()
        body = "\n".join(lines)
        env.setdefault("unrun", []).append(t.map[0] + 1 if t.map else 0)
        if opts.get("echo") == "false" or opts.get("include") == "false":
            return ""
    return code_block_html(body, lang, a, env)


def code_block_html(
    body: str,  # The code
    lang: str,  # Its language, or empty
    a: Attrs,  # Its attributes: `filename=`, classes, an id
    env: dict,  # The render environment, which counts the blocks
    extra: str = "",  # More classes on the outer div, such as `cell-code`
) -> str:  # The HTML of the block
    "Highlight a code block with Pygments, in Quarto's markup with a copy button."
    n = env.setdefault("_cb", [0])
    n[0] += 1
    cid = a.id or f"cb{n[0]}"
    code = highlight(body.rstrip("\n"), lang)
    cls = " ".join(["sourceCode", *([lang] if lang else []), "code-with-copy", *[c for c in a.classes if c != "_cell"]])
    copy = env.get("code_copy", True)
    pre = f'<div class="sourceCode{(" " + extra) if extra else ""}" id="{html.escape(cid)}"><pre class="{html.escape(cls)}"><code class="sourceCode {html.escape(lang)}">{code}</code></pre></div>'
    if copy:
        pre = f'<div class="code-copy-outer-scaffold">{pre}<button title="Copy to Clipboard" class="code-copy-button"><i class="bi"></i></button></div>'
    if a.kv.get("filename"):
        pre = f'<div class="code-with-filename"><div class="code-with-filename-file"><pre><strong>{html.escape(a.kv["filename"])}</strong></pre></div>{pre}</div>'
    return pre + "\n"


def code_block(
    self: RendererHTML,  # The renderer
    tokens: Sequence[Token],  # The tokens of the page
    idx: int,  # The index of the token to render
    options: OptionsDict,  # The parser's options
    env: dict,  # The render environment
) -> str:  # The HTML of the block
    "Render an indented code block like a fence with no language."
    return code_block_html(tokens[idx].content, "", Attrs(), env)


def math_renderer(
    content: str,  # The TeX
    opts: dict,  # `display_mode`: whether it is display maths
) -> str:  # The TeX between the delimiters that KaTeX's auto-render finds
    "Write maths as Pandoc does for KaTeX or MathJax: `\\(...\\)` inline and `\\[...\\]` for display."
    c = html.escape(content)
    return f"\\[{c}\\]" if opts.get("display_mode") else f"\\({c}\\)"


def math_inline(
    self: RendererHTML,  # The renderer
    tokens: Sequence[Token],  # The tokens of the page
    idx: int,  # The index of the token to render
    options: OptionsDict,  # The parser's options
    env: dict,  # The render environment
) -> str:  # The maths, in a span
    "Render inline maths."
    env["math"] = True
    return f'<span class="math inline">{math_renderer(tokens[idx].content.strip(), {})}</span>'


def math_block(
    self: RendererHTML,  # The renderer
    tokens: Sequence[Token],  # The tokens of the page
    idx: int,  # The index of the token to render
    options: OptionsDict,  # The parser's options
    env: dict,  # The render environment
) -> str:  # The maths, in a paragraph
    "Render display maths."
    env["math"] = True
    return f'<p><span class="math display">{math_renderer(tokens[idx].content.strip(), {"display_mode": True})}</span></p>\n'


def make_parser(
    extensions: str = "",  # Pandoc's reader with extensions, such as `markdown-tex_math_dollars-smart`
) -> MarkdownIt:  # The parser, with every rule in place
    "Make a markdown-it parser that reads Pandoc's Markdown as far as Quarto sites use it."
    off = set(re.findall(r"-(\w+)", extensions or ""))
    smart = "smart" not in off
    md = MarkdownIt("commonmark", {"html": True, "typographer": smart})
    md.enable(["table", "strikethrough"])
    md.disable("replacements")
    if smart:
        md.enable("smartquotes")
    md.use(footnote_plugin).use(deflist_plugin).use(tasklists_plugin)
    md.use(attrs_plugin, spans=True)
    if "tex_math_dollars" not in off:
        md.use(dollarmath_plugin, allow_space=False, allow_digits=False, double_inline=True)
        for name in ("math_inline", "math_inline_double"):
            md.add_render_rule(name, math_inline)
        for name in ("math_block", "math_block_label"):
            md.add_render_rule(name, math_block)
    md.block.ruler.before("fence", "fenced_div", fenced_div, {"alt": ["paragraph", "reference", "blockquote", "list"]})
    md.core.ruler.after("block", "heading_attrs", heading_attrs)
    md.core.ruler.after("heading_attrs", "quote_attr_values", quote_attr_values)
    md.core.ruler.after("quote_attr_values", "links_with_spaces", links_with_spaces)
    rules = Rules(md)
    if smart:
        md.core.ruler.push("typography", rules.typography)  # before ids: Pandoc makes ids from the smart text
    md.core.ruler.push("ids", rules.ids)
    md.core.ruler.push("title", rules.title)
    md.core.ruler.push("callouts", rules.callouts)
    md.core.ruler.push("tabsets", rules.tabsets)
    md.core.ruler.push("figures", rules.figures)
    md.core.ruler.push("search_text", rules.search_text)
    md.core.ruler.push("sections", rules.sections)
    render: dict[str, Callable] = {
        "heading_open": heading_open,
        "div_open": div_open,
        "div_close": div_close,
        "paragraph_open": paragraph_open,
        "paragraph_close": paragraph_close,
        "image": image,
        "link_open": link_open,
        "link_close": link_close,
        "code_inline": code_inline,
        "table_open": table_open,
        "fence": fence,
        "code_block": code_block,
    }
    for k, f in render.items():
        md.add_render_rule(k, f)
    return md


def render(
    text: str,  # Markdown, without its front matter
    env: dict,  # In: `title`, `link`, `symbols`, `code_copy`, `number_sections`. Out: `headings`, `search`, `math`, ...
    extensions: str = "",  # Pandoc's reader with extensions, from `from:` in the config
) -> str:  # The HTML of the body
    "Render a page's Markdown to HTML, filling `env` with what the layout needs."
    return make_parser(extensions).render(text, env)
