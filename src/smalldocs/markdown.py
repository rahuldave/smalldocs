"Pandoc-flavoured Markdown to the HTML that Quarto makes, with markdown-it-py and a few rules of our own."

import html
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import yaml
from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from markdown_it.rules_block import StateBlock
from markdown_it.rules_core import StateCore
from markdown_it.rules_inline import StateInline
from markdown_it.token import Token
from markdown_it.utils import OptionsDict
from mdit_py_plugins.attrs import attrs_plugin
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.footnote.index import render_footnote_ref as FOOTNOTE_REF
from mdit_py_plugins.tasklists import tasklists_plugin

from .highlight import highlight

FRONT = re.compile(r"\A---[ \t]*\r?\n(.*?\r?\n)?(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)", re.S)
HEADING_ATTRS = re.compile(r"\s*\{([^{}]*)\}\s*$")
ATTR_ONLY = re.compile(r"""\s*(?:(?:[#.][^\s#{}"'=]+|[^\s=#.{}"']+=(?:"(?:[^"\\]|\\.)*"|'[^']*'|[^\s"'{}]+)|-)\s*)+""")
LINK_WITH_SPACES = re.compile(r"\]\(([^()<>\"'\s][^()<>\"'\n]*?\s[^()<>\"'\n]*?)\)")
ATTR_TOKEN = re.compile(r"""([#.][^\s#{}"'=]+)|([^\s=]+)=("(?:[^"\\]|\\.)*"|'[^']*'|[^\s]+)|(-)""")
CALLOUTS = {"note": "Note", "tip": "Tip", "warning": "Warning", "important": "Important", "caution": "Caution"}
EXECUTABLE = {"python", "r", "julia", "ojs", "bash", "sql"}
HTML_FORMATS = {"html", "html:js", "html5"}  # the formats that `when-format` matches for a website
CONDITION = re.compile(r"(when|unless)-(format|meta|profile)")
CAPTION = re.compile(r"^ {0,3}(?:[Tt]able)?:[ \t]+(\S.*)$")  # a table's caption: `: text` or `Table: text`
DELIM_ROW = re.compile(r"^ {0,3}\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")  # the row of dashes under a table's headings
# The classes that Quarto turns into Bootstrap's table classes: `.striped` is `table-striped`
TABLE_CLASSES = {"primary", "secondary", "success", "danger", "warning", "info", "light", "dark", "striped", "hover", "active", "bordered", "borderless", "sm"}
LIST_MARK = re.compile(r"^( *)(\(?)([A-Za-z]+)([.)])( +|\t)(?=\S)")
ROMAN = re.compile(r"^M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")
OTHER_ITEM = re.compile(r"^( *)([-*+]|\d{1,9}[.)])( +|\t|$)")


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


MARGIN_HTML = re.compile(r"""class=["'][^"']*\b(column-margin|aside)\b""")  # raw HTML that puts content in the margin


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


def table_caption(
    state: StateBlock,  # The block parser's state
    start: int,  # The line to try
    end: int,  # The line after the last one
    silent: bool,  # Only say whether a caption starts here
) -> bool:  # Whether a caption starts here
    "Parse a table's caption, `: text` or `Table: text`, in the paragraph just after a table or just before one."
    if state.sCount[start] - state.blkIndent >= 4:
        return False
    m = CAPTION.match(state.src[state.bMarks[start] : state.eMarks[start]])
    if not m:
        return False
    line = start + 1
    while line < end and not state.isEmpty(line):
        line += 1
    prev = state.tokens[-1] if state.tokens else None
    after = prev is not None and prev.type == "table_close" and prev.level == state.level
    nxt = line
    while nxt < end and state.isEmpty(nxt):
        nxt += 1
    head = state.src[state.bMarks[nxt] : state.eMarks[nxt]] if nxt + 1 < end else ""
    before = "|" in head and bool(DELIM_ROW.match(state.src[state.bMarks[nxt + 1] : state.eMarks[nxt + 1]])) if head else False
    if not (after or before):
        return False
    if silent:
        return True
    text = " ".join([m.group(1), *(state.src[state.bMarks[k] : state.eMarks[k]].strip() for k in range(start + 1, line))]).strip()
    a = Attrs()
    am = HEADING_ATTRS.search(text)
    if am and ATTR_ONLY.fullmatch(am.group(1)):
        a, text = parse_attrs("{" + am.group(1) + "}"), text[: am.start()].rstrip()
    tok = state.push("table_caption_open", "", 1)
    tok.map, tok.block, tok.meta = [start, line], True, {"attrs": a, "after": after}
    inl = state.push("inline", "", 0)
    inl.content, inl.map, inl.children = text, [start, line], []
    state.push("table_caption_close", "", -1).block = True
    state.line = line
    return True


# ---------------------------------------------------------------- inline rules: subscript and superscript


def sub_sup(
    mark: str,  # `~` for a subscript, `^` for a superscript
    tag: str,  # `sub` or `sup`
) -> Callable:  # The inline rule
    "Make an inline rule for Pandoc's `H~2~O` and `x^2^`: no space inside, unless escaped as `\\ `; `~~` stays strikethrough."

    def rule(
        state: StateInline,  # The inline parser's state
        silent: bool,  # Only say whether one starts here
    ) -> bool:  # Whether a subscript or a superscript starts here
        "Parse one subscript or superscript."
        start, top = state.pos, state.posMax
        src = state.src
        if silent or src[start] != mark or start + 2 >= top or src[start + 1] == mark or (start and src[start - 1] == mark):
            return False
        if mark == "^" and src[start + 1] == "[":  # `^[note]` is an inline footnote, as Pandoc reads it first
            return False
        state.pos = start + 1
        found = False
        while state.pos < top:
            if src[state.pos] == mark:
                found = True
                break
            state.md.inline.skipToken(state)
        inner = src[start + 1 : state.pos]
        if not found or not inner or re.search(r"(?<!\\)\s", inner) or (state.pos + 1 < top and src[state.pos + 1] == mark):
            state.pos = start
            return False
        state.posMax, state.pos = state.pos, start + 1
        state.push(f"{tag}_open", tag, 1).markup = mark
        state.md.inline.tokenize(state)
        state.push(f"{tag}_close", tag, -1).markup = mark
        state.pos, state.posMax = state.posMax + 1, top
        return True

    return rule


# ---------------------------------------------------------------- lists numbered with letters or roman numerals


def roman(
    s: str,  # Letters such as `iv` or `XII`
) -> int | None:  # Their value, or None when they are no roman numeral
    "Read a roman numeral, in lower or upper case."
    if not s or not (s.islower() or s.isupper()) or not ROMAN.match(s.upper()):
        return None
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    n = [vals[c] for c in s.upper()]
    return sum(-v if i + 1 < len(n) and v < n[i + 1] else v for i, v in enumerate(n))


def marker_value(
    tok: str,  # The letters of a list marker, such as `b` or `iv`
    style: str | None,  # The style of the list it continues: `a`, `A`, `i` or `I`; None for a new list
) -> tuple[str, int] | None:  # The style and the number, or None when the marker is not one
    "Read a list marker by Pandoc's rules: a lone `i` starts a roman list, another lone letter a lettered one."
    if style in ("a", "A"):
        return (style, ord(tok) - ord(style) + 1) if len(tok) == 1 and (tok.islower() == (style == "a")) else None
    if style in ("i", "I"):
        n = roman(tok)
        return (style, n) if n and (tok.islower() == (style == "i")) else None
    if tok in ("i", "I"):
        return tok, 1
    if len(tok) == 1:
        return ("a" if tok.islower() else "A"), ord(tok.lower()) - ord("a") + 1
    n = roman(tok)
    return (("i" if tok.islower() else "I"), n) if n else None


def letter_lists(
    text: str,  # Markdown
) -> tuple[str, dict[int, str]]:  # The text with the markers as numbers, and the list type of each item's line
    "Rewrite list markers such as `a.`, `(b)`, `iv)` and `A.` to numbers, which markdown-it reads, and note each list's type."
    if not re.search(r"(?m)^ *\(?[A-Za-z]+[.)][ \t]", text):
        return text, {}
    lines = text.split("\n")
    types: dict[int, str] = {}
    # The open list at each indent: its style, its delimiter as written, and its delimiter as rewritten. markdown-it joins two
    # lists with the same delimiter, and Pandoc starts a new list when the style changes; so a new list after another at the
    # same indent takes the other delimiter, which the HTML does not show.
    lists: dict[int, tuple[str, str, str]] = {}
    fence, prev_blank, prev_item = None, True, None
    html_end: re.Pattern | str | None = None  # the end of a raw HTML block: a closing tag, or a blank line
    content = None  # the column where the text of the last list item starts; four more is indented code
    for n, line in enumerate(lines):
        if html_end is not None:
            if (html_end == "blank" and not line.strip()) or (html_end != "blank" and html_end.search(line)):
                html_end, prev_blank = None, not line.strip()
            continue
        hb = re.match(r"^ {0,3}<(/?)([A-Za-z][\w-]*)", line)
        if hb and not fence:
            tag = hb.group(2).lower()
            html_end = re.compile(rf"</{tag}>", re.I) if tag in ("pre", "script", "style", "textarea") else "blank"
            if html_end != "blank" and html_end.search(line[hb.end() :]):
                html_end = None
            continue
        fm = re.match(r"^ *(`{3,}|~{3,})", line)
        if fence:
            if fm and fm.group(1)[0] == fence[0] and len(fm.group(1)) >= len(fence) and not line.strip()[len(fm.group(1)) :].strip():
                fence = None
            continue
        if fm:
            fence, prev_blank, prev_item = fm.group(1), False, None
            continue
        if not line.strip():
            prev_blank = True
            continue
        m = LIST_MARK.match(line)
        hit, cont = None, None
        if m and content is not None and len(m.group(1)) >= content + 4:
            m = None  # indented code inside a list item
        if m and (m.group(2) != "(" or m.group(4) == ")"):
            indent, delim = len(m.group(1)), ("()" if m.group(2) else m.group(4))
            cont = lists.get(indent)
            cont = cont if cont and cont[1] == delim and cont[0] != "1" else None
            hit = marker_value(m.group(3), cont[0]) if cont else None
            if hit is None:
                cont = None
                if (prev_blank or (prev_item is not None and indent > prev_item)) and (indent <= 3 or prev_item is not None):
                    hit = marker_value(m.group(3), None)
            if hit and delim == "." and (hit[0] == "A" or (hit[0] == "I" and hit[1] in (1, 5, 10, 50, 100, 500, 1000))) and m.group(5) == " ":
                hit = None  # Pandoc: a capital letter and a period need two spaces after them, so `A. Smith` stays text
        if hit:
            out = cont[2] if cont else ("." if delim == "." else ")")
            if not cont and indent in lists and lists[indent][2] == out:
                out = "." if out == ")" else ")"
            new = f"{hit[1]}{out}"
            gap = m.group(5) if m.group(5) == "\t" else " " * max(1, len(m.group(2) + m.group(3) + m.group(4) + m.group(5)) - len(new))
            lines[n] = m.group(1) + new + gap + line[m.end() :]
            content = len(m.group(1) + new + gap)
            types[n] = hit[0]
            lists = {k: v for k, v in lists.items() if k < indent}
            lists[indent] = (hit[0], delim, out)
            prev_item = indent
        else:
            other = OTHER_ITEM.match(line)
            indent = len(line) - len(line.lstrip())
            if other and content is not None and len(other.group(1)) >= content + 4:
                other = None  # indented code inside a list item
            if other:
                content = other.end()
            if other and other.group(2)[0].isdigit():  # a list of numbers, so that a list of letters after it is a new list
                k, delim = len(other.group(1)), other.group(2)[-1]
                prior = lists.get(k)
                out = prior[2] if prior and prior[0] == "1" and prior[1] == delim else delim
                if prior and prior[0] != "1" and prior[2] == out:
                    out = "." if out == ")" else ")"
                lines[n] = line[: other.end(2) - 1] + out + line[other.end(2) :]
                lists = {i: v for i, v in lists.items() if i < k}
                lists[k] = ("1", delim, out)
                prev_item = k
            elif other:
                prev_item = len(other.group(1))
                lists = {k: v for k, v in lists.items() if k < prev_item}
            elif prev_blank:
                lists = {k: v for k, v in lists.items() if k < indent}
                prev_item = prev_item if prev_item is not None and indent > prev_item else None
        prev_blank = False
    return "\n".join(lines), types


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


def holds(
    kind: str,  # `format`, `meta` or `profile`
    value: str,  # What the attribute names: a format, a dotted key of the page's options, or profiles, with commas
    env: dict,  # The render environment, with the page's options in `meta`
) -> bool:  # Whether the page is built in that format, has that option, or runs in that profile
    "Test one condition of `.content-visible` or `.content-hidden`."
    if kind == "format":
        return value.strip() in HTML_FORMATS
    if kind == "meta":
        cur: object = env.get("meta") or {}
        for part in value.strip().split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        return bool(cur) and str(cur).lower() != "false"
    active = {p.strip() for p in os.environ.get("QUARTO_PROFILE", "").split(",") if p.strip()}
    return any(p.strip() in active for p in value.split(","))


def shown(
    classes: list[str],  # The classes of a div or a span
    kv: dict[str, str],  # Its other attributes
    env: dict,  # The render environment
) -> bool | None:  # Whether to keep it; None when it is not conditional
    "Decide whether conditional content stays: `.content-visible` when every condition holds, `.content-hidden` unless every one does."
    visible, hidden = "content-visible" in classes, "content-hidden" in classes
    if not (visible or hidden):
        return None
    met = True
    for k, v in kv.items():
        m = CONDITION.fullmatch(k)
        if m:
            met = met and holds(m.group(2), v, env) == (m.group(1) == "when")
    return met if visible else not met


def table_classes(
    a: Attrs,  # The caption's attributes
) -> list[str]:  # Bootstrap's classes for the table, such as `table-striped`
    "Turn Quarto's table classes, such as `.striped`, into Bootstrap's."
    return [f"table-{c}" for c in a.classes if c in TABLE_CLASSES]


def layout_rows(
    kv: dict[str, str],  # The div's attributes: `layout-ncol`, `layout-nrow` or `layout`
    n: int,  # How many blocks the div holds
) -> list[list[float]] | None:  # The width of each cell of each row, as a share of the row; None when the layout cannot be read
    "Read a div's layout into rows of widths, as Quarto does: `layout-ncol=2`, `layout-nrow=2` or `layout=\"[[1,1],[1]]\"`."
    try:
        if "layout" in kv:
            rows = yaml.safe_load(kv["layout"])
            if not (isinstance(rows, list) and rows and all(isinstance(r, list) and r for r in rows)):
                return None
            rows = [[float(x) for x in r] for r in rows]
        else:
            ncol = int(kv["layout-ncol"]) if "layout-ncol" in kv else -(-n // max(1, int(kv["layout-nrow"])))
            rows = [[1.0] * max(1, ncol)]
    except (ValueError, TypeError, yaml.YAMLError):
        return None
    if any(w <= 0 for row in rows for w in row):
        return None
    out = [[w / sum(row) * 100 for w in row] for row in rows]
    while sum(len(r) for r in out) < n:
        out.append(out[-1])
    return out


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

    def conditions(
        self,
        state: StateCore,  # The core parser's state
    ) -> None:  # Nothing; the tokens are changed in place
        "Keep or drop `.content-visible` and `.content-hidden` divs and spans; what is dropped is gone from the page and from search."
        toks, env = state.tokens, state.env
        i = 0
        while i < len(toks):
            t = toks[i]
            a = (t.meta or {}).get("attrs") if t.type == "div_open" else None
            keep = shown(a.classes, a.kv, env) if a else None
            if keep is None:
                if t.type == "inline" and t.children:
                    t.children = self.inline_conditions(t.children, env)
                i += 1
                continue
            j = matching_close(toks, i)
            if keep:
                del toks[j]
                del toks[i]
            else:
                del toks[i : j + 1]

    def inline_conditions(
        self,
        kids: list[Token],  # The children of an inline token
        env: dict,  # The render environment
    ) -> list[Token]:  # The children, without the spans that are hidden
        "Keep or drop the conditional spans of an inline run; a span that stays loses its condition, as in Quarto."
        out: list[Token] = []
        skip = 0
        for c in kids:
            if skip:
                skip += c.nesting if c.type.startswith("span_") else 0
                continue
            if c.type == "span_open":
                attrs = {str(k): str(v) for k, v in c.attrs.items()}
                classes = attrs.get("class", "").split()
                keep = shown(classes, attrs, env)
                if keep is False:
                    skip = 1
                    continue
                if keep:
                    rest = [x for x in classes if x not in ("content-visible", "content-hidden")]
                    c.attrs = {k: v for k, v in c.attrs.items() if k != "class" and not CONDITION.fullmatch(str(k))}
                    if rest:
                        c.attrSet("class", " ".join(rest))
            out.append(c)
        return out

    def table_captions(
        self,
        state: StateCore,  # The core parser's state
    ) -> None:  # Nothing; the tokens are moved in place
        "Join each caption to its table: in the table as `<caption>`, or, with an id or in the margin, in a figure around it, as Quarto does."
        toks, env = state.tokens, state.env
        i = 0
        while i < len(toks):
            if toks[i].type != "table_caption_open":
                i += 1
                continue
            cap = toks[i : i + 3]
            meta = cap[0].meta
            if meta["after"]:
                end = i - 1
                depth, start = 0, end
                while start >= 0:
                    depth += toks[start].nesting
                    if depth == 0:
                        break
                    start -= 1
            else:
                start = i + 3
                end = matching_close(toks, start)
            if start < 0 or toks[start].type != "table_open" or (toks[start].meta or {}).get("caption"):
                po, pc = Token("paragraph_open", "p", 1), Token("paragraph_close", "p", -1)
                po.block = pc.block = True
                toks[i : i + 3] = [po, cap[1], pc]  # a second caption for one table stays a paragraph
                i += 3
                continue
            a: Attrs = meta["attrs"]
            where = a.kv.get("tbl-cap-location") or env.get("tbl_cap_location") or "top"
            where = where if where in ("top", "bottom", "margin") else "top"
            float_ = bool(a.id) or where == "margin"
            info = {"attrs": a, "where": where, "float": float_}
            toks[start].meta = {**(toks[start].meta or {}), "caption": info}
            toks[end].meta = {**(toks[end].meta or {}), "caption": info}
            cap[0].meta, cap[2].meta = {**meta, "caption": info}, {"caption": info}
            if where == "margin":
                env["margin_notes"] = True
            del toks[i : i + 3]
            if not meta["after"]:
                start, end = start - 3, end - 3
            at = start + 1 if not float_ else (end + 1 if where == "bottom" else start)
            toks[at:at] = cap
            i = end + 4

    def escaped_spaces(
        self,
        state: StateCore,  # The core parser's state
    ) -> None:  # Nothing; the text is changed in place
        "Turn `\\ ` in a subscript or a superscript into a space that does not break, as Pandoc does."
        for t in state.tokens:
            depth = 0
            for c in (t.children or []) if t.type == "inline" else []:
                depth += c.nesting if c.type in ("sub_open", "sub_close", "sup_open", "sup_close") else 0
                if depth and c.type == "text":
                    c.content = c.content.replace("\\ ", " ")

    def list_types(
        self,
        state: StateCore,  # The core parser's state
    ) -> None:  # Nothing; the lists are changed in place
        "Give a list numbered with letters or roman numerals its `type`, from the lines that `letter_lists` noted."
        types = state.env.get("_list_types") or {}
        for t in state.tokens:
            if t.type == "ordered_list_open" and t.map and t.map[0] in types:
                t.attrSet("type", types[t.map[0]])

    def layouts(
        self,
        state: StateCore,  # The core parser's state
    ) -> None:  # Nothing; the tokens are changed in place
        "Put the blocks of a div with `layout-ncol`, `layout-nrow` or `layout` side by side, in Quarto's rows and cells."
        toks = state.tokens
        i = 0
        while i < len(toks):
            t = toks[i]
            a = (t.meta or {}).get("attrs") if t.type == "div_open" else None
            if not (a and {"layout", "layout-ncol", "layout-nrow"} & set(a.kv)):
                i += 1
                continue
            j = matching_close(toks, i)
            blocks, k = [], i + 1
            while k < j:
                end = matching_close(toks, k) if toks[k].nesting == 1 else k
                blocks.append(toks[k : end + 1])
                k = end + 1
            rows = layout_rows(a.kv, len(blocks))
            if rows is None or not blocks:
                i += 1
                continue
            key = next(k for k in ("layout", "layout-ncol", "layout-nrow") if k in a.kv)
            panel = Attrs(id=a.id, classes=["quarto-layout-panel", *a.classes], kv={f"data-{key}": a.kv[key]})
            new = [raw(f"<div{panel.html()}>\n")]
            for row in rows:
                if not blocks:
                    break
                new.append(raw('<div class="quarto-layout-row">\n'))
                for w in row:
                    if not blocks:
                        break
                    new.append(raw(f'<div class="quarto-layout-cell" style="flex-basis: {w:.1f}%;justify-content: flex-start;">\n'))
                    new += blocks.pop(0)
                    new.append(raw("</div>\n"))
                new.append(raw("</div>\n"))
            new.append(raw("</div>\n"))
            toks[i : j + 1] = new
            i += 1

    def video_sources(
        self,
        state: StateCore,  # The core parser's state
    ) -> None:  # Nothing; the raw HTML is changed in place
        "Rewrite the file of a `video` shortcode for the page, so the build copies it, as it does a picture."
        link = state.env.get("link")
        for t in state.tokens:
            if link and t.type == "html_block" and 'class="quarto-video"' in t.content:
                t.content = re.sub(r'(<source src=")([^"]*)(")', lambda m: m.group(1) + html.escape(link(html.unescape(m.group(2)), "src")) + m.group(3), t.content)

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
            appearance = a.kv.get("appearance", state.env.get("callout_appearance") or "default")
            icon = a.kv.get("icon", str(state.env.get("callout_icon", "true")).lower()) != "false"
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
            group = f' data-group="{html.escape(a.kv["group"])}"' if a.kv.get("group") else ""  # tabs of a group switch together
            new = [
                raw(f'<div class="panel-tabset{"".join(" " + c for c in a.classes if c != "panel-tabset")}"{group}><ul class="nav nav-tabs" role="tablist">{nav}</ul><div class="tab-content"{group}>\n')
            ]
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
        wide: list[bool] = []  # for each open div, whether it is wide or in the margin; a figure in it keeps its caption below
        for i in range(len(toks) - 2):
            if toks[i].type == "div_open":
                a = (toks[i].meta or {}).get("attrs")
                wide.append(any(c.startswith(("column-page", "column-screen", "column-body-outset", "column-margin")) or c == "aside" for c in (a.classes if a else [])))
            elif toks[i].type == "div_close" and wide:
                wide.pop()
            if toks[i].type == "paragraph_open" and toks[i + 1].type == "inline" and toks[i + 2].type == "paragraph_close":
                kids = [c for c in toks[i + 1].children or [] if not (c.type == "text" and not c.content.strip())]
                if len(kids) == 1 and kids[0].type == "image" and kids[0].children:
                    img = kids[0]
                    classes = (img.attrGet("class") or "").split()
                    cols = [c for c in classes if c.startswith("column-")]
                    if cols:
                        rest = [c for c in classes if c not in cols]
                        img.attrSet("class", " ".join(rest)) if rest else img.attrs.pop("class")
                    where = img.attrs.pop("fig-cap-location", None) or state.env.get("fig_cap_location")
                    margin_cap = where == "margin" and not cols and not any(wide)
                    if margin_cap or "column-margin" in cols:
                        state.env["margin_notes"] = True
                    align = img.attrs.pop("fig-align", None)
                    align = align if align and align != "default" else state.env.get("fig_align")
                    align = align if align in ("left", "right", "center") else "center"
                    toks[i].meta = {**(toks[i].meta or {}), "figure": img, "columns": cols, "margin_caption": margin_cap, "align": align}
                    img.meta = {**(img.meta or {}), "figure": True}

    def margins(
        self,
        state: StateCore,  # The core parser's state
    ) -> None:  # Nothing; the tokens and `env` are changed in place
        "Note margin content; with `reference-location: margin`, put each footnote in the margin beside the block that cites it."
        env, toks = state.env, state.tokens
        for t in toks:
            a = (t.meta or {}).get("attrs") if t.type == "div_open" else None
            if a and ("column-margin" in a.classes or "aside" in a.classes):
                env["margin_notes"] = True
            if t.type == "html_block" and MARGIN_HTML.search(t.content):
                env["margin_notes"] = True
            for c in (t.children or []) if t.type == "inline" else []:
                if c.type == "html_inline" and MARGIN_HTML.search(c.content):
                    env["margin_notes"] = True
                if c.type == "span_open" and "aside" in (c.attrGet("class") or "").split():
                    c.attrSet("class", c.attrGet("class") + " margin-aside")
                    env["margin_notes"] = True
        if env.get("reference_location") != "margin":
            return
        start = next((i for i, t in enumerate(toks) if t.type == "footnote_block_open"), None)
        if start is None:
            return
        end = next(i for i in range(start, len(toks)) if toks[i].type == "footnote_block_close")
        bodies: dict[int, list[Token]] = {}
        k = start + 1
        while k < end:
            j = next(m for m in range(k, end) if toks[m].type == "footnote_close")
            bodies[toks[k].meta["id"]] = [t for t in toks[k + 1 : j] if t.type != "footnote_anchor"]
            k = j + 1
        del toks[start : end + 1]

        def refs(tokens: list[Token]) -> list[int]:  # The footnotes that some tokens cite, in order, also in the caption of an image
            out = []
            for t in tokens:
                for c in t.children or []:
                    out += [c.meta["id"]] if c.type == "footnote_ref" else refs([c])
            return out

        placed: set[int] = set()
        notes: dict[int, list[int]] = {}  # the index of a top-level block, and the footnotes it cites first
        top = 0
        for i, t in enumerate(toks):
            if t.level == 0 and t.nesting >= 0:
                top = i
            for fid in refs([t]):
                todo = [fid]
                while todo:  # a footnote that a footnote cites goes in the same place
                    f = todo.pop(0)
                    if f not in placed and f in bodies:
                        placed.add(f)
                        notes.setdefault(top, []).append(f)
                        todo += refs(bodies[f])
        rest = [f for f in bodies if f not in placed]
        if rest:  # a footnote cited only where the rule cannot see, such as raw HTML: at the end of the page, not lost
            notes.setdefault(len(toks), []).extend(rest)
        for i in sorted(notes, reverse=True):
            at = i + 3 if i < len(toks) and toks[i].type == "heading_open" else i  # after a heading, so the note stays in its section
            new = [raw('<div class="no-row-height column-margin column-container">\n')]
            for fid in notes[i]:
                body = bodies[fid]
                first = next((t for t in body if t.type == "inline"), None)
                if first is not None:
                    mark = Token("html_inline", "", 0)
                    mark.content = f"<sup>{fid + 1}</sup>\u00a0"
                    first.children = [mark, *(first.children or [])]
                new += [raw(f'<div id="fn{fid + 1}">\n'), *body, raw("</div>\n")]
            new.append(raw("</div>\n"))
            toks[at:at] = new  # before the block, so the note starts level with it
        env["margin_notes"] = True

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
    anchored = ["anchored"] if env.get("anchor_sections", True) else []  # `anchor-sections: false`: no anchor links
    if t.level == 0:
        num = ""
        depth = env.get("number_depth")
        lvl = int(t.tag[1])
        if env.get("number_sections") and "unnumbered" not in a.classes and not (depth and lvl > depth):
            counts = env.setdefault("_counts", [0] * 7)
            counts[lvl] += 1
            counts[lvl + 1 :] = [0] * (6 - lvl)
            first = env.get("_numfrom") or lvl
            env["_numfrom"] = first
            num = f'<span class="header-section-number">{".".join(str(c) for c in counts[first : lvl + 1])}</span> '
        cls = ' class="anchored"' if anchored else ""
        return f'<{t.tag}{cls} data-anchor-id="{html.escape(a.id)}">{num}'
    cls = " ".join([*anchored, *a.classes])
    cls = f' class="{html.escape(cls)}"' if cls else ""
    return f'<{t.tag} id="{html.escape(a.id)}"{cls} data-anchor-id="{html.escape(a.id)}">'


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
    if "aside" in a.classes and "column-margin" not in a.classes:
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
    meta = tokens[idx].meta or {}
    fig = meta.get("figure")
    if fig is None:
        return self.renderToken(tokens, idx, options, env)
    cols = "".join(f" {c}" for c in meta.get("columns", []))
    cap = f'<figcaption class="margin-caption">{self.renderInline(fig.children or [], options, env)}</figcaption>\n' if meta.get("margin_caption") else ""
    return f'<div class="quarto-figure quarto-figure-{meta.get("align", "center")}{cols}">\n<figure class="figure">\n{cap}<p>'


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
    if open_.meta.get("margin_caption"):
        return "</p>\n</figure>\n</div>\n"
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
    t.attrs.pop("fig-align", None)  # an option of the figure, not an attribute of the picture
    t.attrSet("class", " ".join(dict.fromkeys(cls)))
    for k in ("width", "height"):
        v = t.attrGet(k)
        if v and not v.isdigit():
            t.attrs.pop(k)
            t.attrSet("style", f"{t.attrGet('style') or ''}{k}: {v};")
    alt = str(t.attrs.pop("fig-alt", None) or plain(t.children))  # `fig-alt` gives a figure alt text other than its caption
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


def looks_like_code(
    text: str,  # The text in backticks
) -> bool:  # Whether linkify may link it
    "Say whether a name in backticks looks like code: a call `f()`, a dotted name `a.b`, a name with `_`, or a class `Name`. A plain word such as `main` does not."
    return text.endswith("()") or "." in text or "_" in text or text[:1].isupper()


def code_inline(
    self: RendererHTML,  # The renderer
    tokens: Sequence[Token],  # The tokens of the page
    idx: int,  # The index of the token to render
    options: OptionsDict,  # The parser's options
    env: dict,  # The render environment
) -> str:  # The `<code>` element, linked when it names a documented symbol
    "Render inline code; a documented name in backticks that looks like code, outside a link and without `.nolink`, links to its entry."
    t = tokens[idx]
    attrs = "".join(f' {k}="{html.escape(str(v))}"' for k, v in t.attrs.items())
    code = f"<code{attrs}>{html.escape(t.content)}</code>"
    symbols = env.get("symbols") or {}
    key = re.sub(r"\(\)$", "", t.content)
    nolink = "nolink" in str(t.attrs.get("class", "")).split()
    if key in symbols and not env.get("_in_link") and not nolink and looks_like_code(t.content):
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
    "Render a table with Bootstrap's classes, as Quarto does, in a box that scrolls when the table is too wide."
    cap = (tokens[idx].meta or {}).get("caption")
    if not cap:
        return '<div class="sd-table">\n<table class="caption-top table">\n'
    a: Attrs = cap["attrs"]
    cls = " ".join([*table_classes(a), *(["caption-top"] if cap["float"] or cap["where"] == "top" else []), "table"])
    box = f'<div class="sd-table">\n<table class="{cls}">\n'
    if cap["float"] and cap["where"] == "bottom":
        return float_open(a) + f"<div{described(a)}>\n" + box
    return box


def table_close(
    self: RendererHTML,  # The renderer
    tokens: Sequence[Token],  # The tokens of the page
    idx: int,  # The index of the token to render
    options: OptionsDict,  # The parser's options
    env: dict,  # The render environment
) -> str:  # The closing tags of the table and its box
    "Close a table and the box that `table_open` opened."
    cap = (tokens[idx].meta or {}).get("caption")
    if cap and cap["float"]:
        return "</table>\n</div>\n</div>\n" + ("" if cap["where"] == "bottom" else "</figure>\n</div>\n")
    return "</table>\n</div>\n"


def float_open(
    a: Attrs,  # The caption's attributes
) -> str:  # The opening tags of the figure around a table
    "Open the figure that holds a table with an id, as Quarto's `quarto-float`, with the id where a link to `#tbl-...` lands."
    cls = [*a.classes, "quarto-float", "quarto-figure", "quarto-figure-center", "anchored"]
    kv = {f"data-{k}": v for k, v in a.kv.items()}
    return f'<div{Attrs(id=a.id, classes=cls, kv=kv).html()}>\n<figure class="quarto-float quarto-float-tbl figure">\n'


def described(
    a: Attrs,  # The caption's attributes
) -> str:  # The `aria-describedby` attribute, or nothing when the table has no id
    "Point a table at its caption, for screen readers."
    return f' aria-describedby="{html.escape(a.id)}-caption"' if a.id else ""


def table_caption_open(
    self: RendererHTML,  # The renderer
    tokens: Sequence[Token],  # The tokens of the page
    idx: int,  # The index of the token to render
    options: OptionsDict,  # The parser's options
    env: dict,  # The render environment
) -> str:  # The opening tag of the caption, after the figure's when the caption comes first
    "Open a table's caption: `<caption>` in the table, or Quarto's `<figcaption>` in a figure."
    cap = tokens[idx].meta["caption"]
    if not cap["float"]:
        return "<caption>"
    a: Attrs = cap["attrs"]
    cls = f"quarto-float-caption-{cap['where']} quarto-float-caption quarto-float-tbl" + (" margin-caption" if cap["where"] == "margin" else "")
    ident = f' id="{html.escape(a.id)}-caption"' if a.id else ""
    return ("" if cap["where"] == "bottom" else float_open(a)) + f'<figcaption class="{cls}"{ident}>\n'


def table_caption_close(
    self: RendererHTML,  # The renderer
    tokens: Sequence[Token],  # The tokens of the page
    idx: int,  # The index of the token to render
    options: OptionsDict,  # The parser's options
    env: dict,  # The render environment
) -> str:  # The closing tag of the caption, and of the figure when the caption comes last
    "Close a table's caption."
    cap = tokens[idx].meta["caption"]
    if not cap["float"]:
        return "</caption>\n"
    if cap["where"] == "bottom":
        return "\n</figcaption>\n</figure>\n</div>\n"
    return f"\n</figcaption>\n<div{described(cap['attrs'])}>\n"


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
        for k in ("code-line-numbers", "code-overflow"):
            if k in opts:
                a.kv[k] = opts[k]
        fold = str(opts.get("code-fold", a.kv.pop("code-fold", env.get("code_fold", "false")))).lower()
        summary = str(opts.get("code-summary", a.kv.pop("code-summary", env.get("code_summary") or "Code"))).strip().strip("\"'")
    elif "cell-code" in a.classes:  # a notebook's cell folds only when the cell itself sets code-fold
        fold, summary = str(a.kv.pop("code-fold", "false")).lower(), a.kv.pop("code-summary", "Code")
    else:
        fold, summary = "false", ""
    if fold in ("true", "show"):  # Quarto folds the code of a cell, never a plain code block
        opened = ' open=""' if fold == "show" else ""
        return f'<details{opened} class="code-fold">\n<summary>{html.escape(summary)}</summary>\n{code_block_html(body, lang, a, env)}</details>\n'
    return code_block_html(body, lang, a, env)


def numbered_lines(
    code: str,  # Highlighted code: escaped text and spans, which may run over several lines
    cid: str,  # The id of the block, such as `cb1`
) -> str:  # The code with each line in a span of its own, with an id and an anchor
    "Put each line of highlighted code in its own span, `cb1-1`, as Pandoc does for numbered lines."
    out, carry = [], []
    for n, line in enumerate(code.split("\n"), 1):
        line = "".join(carry) + line
        carry = []
        for tag in re.findall(r"<span[^>]*>|</span>", line):
            if tag == "</span>":
                carry = carry[:-1]
            else:
                carry.append(tag)
        line += "</span>" * len(carry)
        out.append(f'<span id="{cid}-{n}"><a href="#{cid}-{n}"></a>{line}</span>')
    return "\n".join(out)


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
    page = "cell-code" not in a.classes  # a notebook's cell keeps its markup; the page's options are for the page's own code
    lines = a.kv.get("code-line-numbers", env.get("code_line_numbers") if page else None)
    lines = bool(lines) and str(lines).lower() not in ("false", "0", "none")
    wrap = a.kv.get("code-overflow", env.get("code_overflow") if page else None)
    wrap = [f"code-overflow-{wrap}"] if wrap in ("wrap", "scroll") else []
    if lines:
        code = numbered_lines(code, html.escape(cid))
    cls = " ".join(
        [
            "sourceCode",
            *(["numberSource"] if lines else []),
            *([lang] if lang else []),
            *(["number-lines"] if lines else []),
            *wrap,
            "code-with-copy",
            *[c for c in a.classes if c != "_cell"],
        ]
    )
    copy = env.get("code_copy", True)
    data = f' data-code-overflow="{html.escape(a.kv["code-overflow"])}"' if a.kv.get("code-overflow") else ""
    pre = f'<div class="sourceCode{(" " + extra) if extra else ""}" id="{html.escape(cid)}"{data}><pre class="{html.escape(cls)}"><code class="sourceCode {html.escape(lang)}">{code}</code></pre></div>'
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


def math_display(
    self: RendererHTML,  # The renderer
    tokens: Sequence[Token],  # The tokens of the page
    idx: int,  # The index of the token to render
    options: OptionsDict,  # The parser's options
    env: dict,  # The render environment
) -> str:  # The maths, in a span of display maths
    "Render `$$...$$` inside a paragraph as display maths, on a line of its own, as Pandoc does."
    env["math"] = True
    return f'<span class="math display">{math_renderer(tokens[idx].content.strip(), {"display_mode": True})}</span>'


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


def footnote_ref(
    self: RendererHTML,  # The renderer
    tokens: Sequence[Token],  # The tokens of the page
    idx: int,  # The index of the token to render
    options: OptionsDict,  # The parser's options
    env: dict,  # The render environment
) -> str:  # The link to the footnote
    "Link to a footnote: markdown-it's markup at the end of the page, Quarto's with `reference-location: margin`."
    meta = tokens[idx].meta
    if env.get("reference_location") != "margin":
        return FOOTNOTE_REF(self, tokens, idx, options, env)
    n, sub = meta["id"] + 1, meta.get("subId", 0)
    return f'<a href="#fn{n}" class="footnote-ref" id="fnref{n}{f":{sub}" if sub else ""}" role="doc-noteref"><sup>{n}</sup></a>'


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
        md.add_render_rule("math_inline", math_inline)
        md.add_render_rule("math_inline_double", math_display)  # `$$x$$` inside a sentence is display maths, as in Pandoc
        for name in ("math_block", "math_block_label"):
            md.add_render_rule(name, math_block)
    md.block.ruler.before("fence", "fenced_div", fenced_div, {"alt": ["paragraph", "reference", "blockquote", "list"]})
    md.block.ruler.before("table", "table_caption", table_caption)  # before deflist, which reads `: text` as a definition
    md.inline.ruler.before("strikethrough", "subscript", sub_sup("~", "sub"))
    md.inline.ruler.before("strikethrough", "superscript", sub_sup("^", "sup"))
    md.core.ruler.after("block", "heading_attrs", heading_attrs)
    md.core.ruler.after("heading_attrs", "quote_attr_values", quote_attr_values)
    md.core.ruler.after("quote_attr_values", "links_with_spaces", links_with_spaces)
    rules = Rules(md)
    md.core.ruler.push("conditions", rules.conditions)  # first: what is hidden gets no id, no place in the contents and no search entry
    md.core.ruler.push("table_captions", rules.table_captions)
    md.core.ruler.push("list_types", rules.list_types)
    md.core.ruler.push("escaped_spaces", rules.escaped_spaces)
    md.core.ruler.push("video_sources", rules.video_sources)
    if smart:
        md.core.ruler.push("typography", rules.typography)  # before ids: Pandoc makes ids from the smart text
    md.core.ruler.push("ids", rules.ids)
    md.core.ruler.push("title", rules.title)
    md.core.ruler.push("layouts", rules.layouts)  # while the blocks are still divs and paragraphs
    md.core.ruler.push("margins", rules.margins)  # before callouts and tabsets, which turn titles into raw HTML
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
        "table_close": table_close,
        "fence": fence,
        "code_block": code_block,
        "footnote_ref": footnote_ref,
        "table_caption_open": table_caption_open,
        "table_caption_close": table_caption_close,
    }
    for k, f in render.items():
        md.add_render_rule(k, f)
    return md


def page_options(
    m: dict,  # A page's merged options
) -> dict:  # What the Markdown rules read from them, as keys of `env`; only the options that the page sets
    "Read the page options that change the Markdown: code, figures, tables, callouts, headings, and the options for `when-meta`."
    out: dict = {"meta": m}
    keys = {
        "tbl-cap-location": "tbl_cap_location",
        "code-line-numbers": "code_line_numbers",
        "code-fold": "code_fold",
        "code-summary": "code_summary",
        "code-overflow": "code_overflow",
        "fig-align": "fig_align",
        "callout-appearance": "callout_appearance",
        "callout-icon": "callout_icon",
        "anchor-sections": "anchor_sections",
        "number-depth": "number_depth",
    }
    for k, name in keys.items():
        if m.get(k) is not None:
            out[name] = m[k]
    if "code_fold" in out:
        out["code_fold"] = str(out["code_fold"]).lower()
    if "anchor_sections" in out:
        out["anchor_sections"] = out["anchor_sections"] is not False and str(out["anchor_sections"]).lower() != "false"
    if "number_depth" in out:
        try:
            if isinstance(out["number_depth"], bool):
                raise ValueError("number-depth is a number")
            out["number_depth"] = int(out["number_depth"])
        except (TypeError, ValueError):
            del out["number_depth"]
    return out


def render(
    text: str,  # Markdown, without its front matter
    env: dict,  # In: `title`, `link`, `symbols`, `code_copy`, `number_sections`, and `page_options`. Out: `headings`, `search`, `math`, ...
    extensions: str = "",  # Pandoc's reader with extensions, from `from:` in the config
) -> str:  # The HTML of the body
    "Render a page's Markdown to HTML, filling `env` with what the layout needs."
    text, types = letter_lists(text)
    if types:
        env["_list_types"] = types
    return make_parser(extensions).render(text, env)
