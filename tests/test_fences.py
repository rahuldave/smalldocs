"Fenced divs read as Pandoc reads them: each case in fence_cases.json, written by scripts/fence_cases.py from Quarto's Pandoc."

import json
import time
from html.parser import HTMLParser
from pathlib import Path

from smalldocs.llms import Prose, prose
from smalldocs.markdown import make_parser

CASES = Path(__file__).parent / "fence_cases.json"
VOID = ("br", "hr", "img", "input", "meta", "link", "wbr")  # tags with no end tag


def shape(
    html: str,  # HTML from Pandoc or smalldocs
    paras: bool = True,  # Whether to keep `<p>`, which differs between a tight list and a loose one
) -> str:  # The tags with their classes, and the text with its spaces collapsed
    "Reduce HTML to its structure, leaving out the markup that only Quarto adds: code-copy and table wrappers, and sections."
    out: list[str] = []
    skip: list[bool] = []

    class Reader(HTMLParser):
        def handle_starttag(self, t: str, a: list) -> None:
            cls = dict(a).get("class") or ""
            if t in VOID:
                return
            hide = t in ("button", "i") or (t == "p" and not paras) or (t == "div" and ("code-copy" in cls or cls in ("sourceCode", "sd-table"))) or cls.startswith("level")
            skip.append(hide)
            cls = "" if t in ("pre", "code", "h1", "table", "tr", "th", "td") else cls
            if not hide:
                out.append(f"<{'div' if t == 'section' else t}{'.' + cls if cls else ''}>")

        def handle_endtag(self, t: str) -> None:
            if t not in VOID and skip and not skip.pop():
                out.append(f"</{'div' if t == 'section' else t}>")

        def handle_data(self, d: str) -> None:
            d = " ".join(d.split())
            if d and out and out[-1].startswith("'"):
                out[-1] = out[-1][:-1] + " " + d + "'"
            elif d:
                out.append(f"'{d}'")

    Reader().feed(html)
    return " ".join(out)


def test_fences_as_pandoc_reads_them() -> None:
    "Each case builds as Pandoc builds it, or as the kept difference that the case gives a reason for."
    md = make_parser()
    wrong = [(c["md"], c.get("ours", c["pandoc"]), have) for c in json.loads(CASES.read_text()) if (have := shape(md.render(c["md"]))) != c.get("ours", c["pandoc"])]
    assert wrong == [], wrong


def test_copies_have_the_pages_divs() -> None:
    "Each case's Markdown copy, read back, has the page's structure: no line lost, doubled or moved out of its list."
    md = make_parser()
    md.core.ruler.disable("sections")  # sections would take in what follows a heading in the copy's HTML div
    # read back, the copy's HTML divs let an unclosed `$$` run on, and do not count toward markdown-it's 20 levels
    unread = ("$$x", "$$\n:::", "::: {.a}\n" * 18)
    cases = [c["md"] for c in json.loads(CASES.read_text()) if not any(u in c["md"] for u in unread)]
    # the copy's blank lines around a `<div>` make a tight list loose, so paragraphs are not compared
    wrong = [(c, copy) for c in cases if shape(md.render(copy := prose(c, Prose(lambda h: h, {}))), False) != shape(md.render(c), False)]
    assert wrong == [], wrong


def test_long_divs_take_linear_time() -> None:
    "Many HTML lines in one div, and many divs in one quote, render in about a tenth of a second each, not tens of seconds."
    md = make_parser()
    for text in ("::: {.a}\nLinks:\n" + "<span>s</span> and text\n" * 5000 + ":::\n", "> ::: {.b}\n> x\n> :::\n>\n" * 4000):
        start = time.perf_counter()
        md.render(text)
        assert time.perf_counter() - start < 2
