"The tests of the Quarto features of the Markdown: captions, conditions, shortcodes, tabs, code, sub- and superscripts, lists, figures, callouts and headings."

import json
import re
from pathlib import Path

import pytest
from test_smalldocs import md, write

from smalldocs.markdown import letter_lists, page_options, render
from smalldocs.site import build

TABLE = "| A | B |\n|---|---|\n| 1 | 2 |\n"


def page(
    text: str,  # Markdown
    **opts: object,  # The page's options, with `-` as `_`: `code_fold="true"`
) -> str:  # The HTML
    "Render Markdown with page options, as a build gives them."
    return md(text, **page_options({k.replace("_", "-"): v for k, v in opts.items()}))


# ---------------------------------------------------------------- table captions


def test_table_caption_after_and_before() -> None:
    "A paragraph that starts with `: ` or `Table: `, just after or just before a table, is its caption, in the table."
    html = md(TABLE + "\n: The caption {.striped}\n")
    assert '<table class="table-striped caption-top table">\n<caption>The caption</caption>' in html
    assert "<dl>" not in html and "{.striped}" not in html
    html = md("Table: Before it\n\n" + TABLE)
    assert "<caption>Before it</caption>" in html
    assert md("Term\n\n: not a caption\n\n" + TABLE).count("<dl>") == 1  # after a term, it is a definition, as before


def test_table_caption_with_an_id_and_its_place() -> None:
    "With an id, the table goes in Quarto's figure with the id; the caption goes at the top, at the bottom or in the margin."
    html = md(TABLE + "\n: Top {#tbl-one}\n")
    assert '<div id="tbl-one" class="quarto-float quarto-figure quarto-figure-center anchored">' in html
    assert html.index('<figcaption class="quarto-float-caption-top') < html.index("<table")
    assert 'aria-describedby="tbl-one-caption"' in html and 'id="tbl-one-caption"' in html
    html = md(TABLE + "\n: Low {#tbl-two tbl-cap-location=bottom}\n")
    assert html.index("</table>") < html.index('<figcaption class="quarto-float-caption-bottom')
    html = page(TABLE + "\n: Side {#tbl-m}\n", tbl_cap_location="margin")
    assert "quarto-float-caption-margin quarto-float-caption quarto-float-tbl margin-caption" in html
    html = page(TABLE + "\n: Plain low\n", tbl_cap_location="bottom")
    assert '<table class="table">\n<caption>Plain low</caption>' in html


def test_table_caption_page_option_reaches_the_margin(tmp_path: Path) -> None:
    "`tbl-cap-location: margin` in front matter puts the caption in the margin, and the page makes room for it."
    write(tmp_path, {"_smalldocs.yml": "project:\n  type: website\n", "index.qmd": "---\ntitle: T\ntbl-cap-location: margin\n---\n\n" + TABLE + "\n: Side\n"})
    out = (build(tmp_path, quiet=True).out / "index.html").read_text()
    assert "margin-caption" in out and "has-margin" in out


# ---------------------------------------------------------------- conditional content


def test_conditional_divs_and_spans(monkeypatch: pytest.MonkeyPatch) -> None:
    "`.content-visible` and `.content-hidden` keep or drop content by format, by an option of the page, and by profile."
    monkeypatch.setenv("QUARTO_PROFILE", "teacher,draft")
    text = """
    ::: {.content-visible when-format="html"}
    Shown html.
    :::

    ::: {.content-hidden when-format="html"}
    ## Gone heading

    Hidden html.
    :::

    ::: {.content-visible when-format="pdf"}
    Hidden pdf.
    :::

    ::: {.content-visible unless-format="pdf"}
    Shown unless pdf.
    :::

    ::: {.content-visible when-meta="flags.on"}
    Shown meta.
    :::

    ::: {.content-hidden when-profile="teacher"}
    Hidden teacher.
    :::

    ::: {.content-visible when-profile="student"}
    Hidden student.
    :::

    A [web]{.content-visible when-format="html:js"} and [print]{.content-visible when-format="pdf"} end.
    """
    env = {"meta": {"flags": {"on": True}}}
    html = md(text, **env)
    for s in ("Shown html.", "Shown unless pdf.", "Shown meta.", "<span>web</span>"):
        assert s in html
    for s in ("Hidden", "Gone heading", "print", "content-visible", "content-hidden"):
        assert s not in html
    out: dict = {"meta": {}}
    render("::: {.content-hidden when-format=\"html\"}\nsecret words\n:::\n\nOpen words.\n", out)
    assert "secret" not in json.dumps(out["search"]) and "Open words." in json.dumps(out["search"])


# ---------------------------------------------------------------- shortcodes


def test_kbd_video_lipsum_and_placeholder(tmp_path: Path) -> None:
    "The `kbd`, `video`, `lipsum` and `placeholder` shortcodes make Quarto's markup, and a video file is copied."
    write(
        tmp_path,
        {
            "_smalldocs.yml": "project:\n  type: website\n",
            "clip.mp4": "",
            "index.qmd": """
            ---
            title: T
            ---

            Press {{< kbd Shift-Ctrl-P mac=Shift-Command-P win=Shift-Control-P >}} now.

            {{< video https://www.youtube.com/watch?v=abc123 title="A talk" start=10 >}}

            {{< video https://vimeo.com/548291297 width=400 height=300 >}}

            {{< video clip.mp4 >}}

            {{< lipsum 2 >}}

            {{< placeholder 120 60 >}}
            """,
        },
    )
    site = build(tmp_path, quiet=True)
    out = (site.out / "index.html").read_text()
    assert (
        '<kbd title="Shift-Ctrl-P, mac: Shift-Command-P, windows: Shift-Control-P" aria-hidden="true" data-mac="Shift-Command-P"'
        ' data-windows="Shift-Control-P">Shift-Ctrl-P</kbd><span class="visually-hidden">Shift-Ctrl-P</span>'
    ) in out
    assert '<div class="quarto-video ratio ratio-16x9"><iframe data-external="1" src="https://www.youtube.com/embed/abc123?start=10"' in out
    assert 'title="A talk"' in out
    assert 'src="https://player.vimeo.com/video/548291297" width="400" height="300"' in out
    assert '<video id="video_shortcode_videojs_video1"' in out and '<source src="clip.mp4">' in out
    assert (site.out / "clip.mp4").exists()
    assert out.count("Lorem ipsum") == 1 and out.count("<p>Nunc ac") == 1
    assert re.search(r'<img src="data:image/svg\+xml;base64,[^"]+" class="img-fluid" alt="" width="120" height="60">', out)
    assert not [w for w in site.warnings if "shortcode" in w]


# ---------------------------------------------------------------- tabset groups


def test_tabset_groups() -> None:
    "A tabset with `group=` carries it as `data-group`, as Quarto marks the tabsets that switch together."
    html = md("::: {.panel-tabset group=\"lang\"}\n## R\n\nr\n\n## Python\n\npy\n:::\n")
    assert '<div class="panel-tabset" data-group="lang">' in html and '<div class="tab-content" data-group="lang">' in html
    assert "data-group" not in md("::: {.panel-tabset}\n## R\n\nr\n:::\n")


# ---------------------------------------------------------------- code


def test_code_line_numbers() -> None:
    "`code-line-numbers` numbers the lines: a span with an id and an anchor for each line, also for a token over two lines."
    html = md('```{.python code-line-numbers="true"}\na = 1\nb = """x\ny"""\n```\n')
    assert '<pre class="sourceCode numberSource python number-lines code-with-copy">' in html
    assert '<span id="cb1-1"><a href="#cb1-1"></a>a ' in html
    line2 = re.search(r'<span id="cb1-2">.*?</span>\n', html).group(0)
    assert line2.count("<span") == line2.count("</span>")
    assert '<span id="cb1-3"><a href="#cb1-3"></a><span class="st">' in html
    html = page("```python\nx = 1\n```\n\n```{.python code-line-numbers=\"false\"}\ny = 2\n```\n", code_line_numbers=True)
    assert 'id="cb1-1"' in html and 'id="cb2-1"' not in html
    assert 'id="cb1-1"' not in md("```python\nx = 1\n```\n")


def test_notebook_cells_keep_their_markup() -> None:
    "The page's code options leave a notebook's cells, `.cell-code`, as they are."
    text = "```{.python .cell-code}\nx = 1\n```\n"
    assert page(text, code_line_numbers=True, code_overflow="wrap", code_fold=True) == md(text)


def test_code_fold_and_summary() -> None:
    "`code-fold` folds the code of a cell, `show` opens it, and `code-summary` names it; a plain block is not folded."
    text = "```{python}\nx = 1\n```\n\n```{python}\n#| code-fold: show\n#| code-summary: \"See it\"\ny = 2\n```\n\n```{python}\n#| code-fold: false\nz = 3\n```\n\n```python\nw = 4\n```\n"
    html = page(text, code_fold=True)
    assert html.count("<details") == 2
    assert '<details class="code-fold">\n<summary>Code</summary>\n<div class="code-copy-outer-scaffold">' in html
    assert '<details open="" class="code-fold">\n<summary>See it</summary>' in html
    assert html.index("z <span") > html.rindex("</details>")
    assert md(text).count("<details") == 1  # without the page's option, only the cell that asks is folded
    assert "<summary>Show it</summary>" in page("```{python}\nx = 1\n```\n", code_fold="true", code_summary="Show it")


def test_code_overflow() -> None:
    "`code-overflow` wraps or scrolls long lines, for the page or for one block."
    assert '<pre class="sourceCode python code-overflow-wrap code-with-copy">' in page("```python\nx\n```\n", code_overflow="wrap")
    html = md('```{.python code-overflow="scroll"}\nx\n```\n')
    assert 'data-code-overflow="scroll"' in html and "code-overflow-scroll" in html


# ---------------------------------------------------------------- subscripts and superscripts


def test_subscript_and_superscript() -> None:
    "`H~2~O` and `x^2^` as Pandoc reads them: no space inside unless escaped; `~~` is still struck out."
    html = md("H~2~O, x^2^, ~~gone~~, a~b c~, 2^10^, P~a\\ b~ and `a~b~`.")
    assert "H<sub>2</sub>O" in html and "x<sup>2</sup>" in html and "<s>gone</s>" in html
    assert "a~b c~" in html and "2<sup>10</sup>" in html and "P<sub>a b</sub>" in html and "<code>a~b~</code>" in html


# ---------------------------------------------------------------- lists with letters and roman numerals


def test_lists_with_letters_and_roman_numerals() -> None:
    "Lists numbered `a.`, `A.`, `i.`, `c)` and `(a)` become `<ol type=...>`, each its own list, as Pandoc makes them."
    html = md("a. one\nb. two\n\nA.  Cap\nB.  Cap2\n\ni. r1\nii. r2\n\nI. Smith\nII. Jones\n\nc) c1\nd) c2\n\n(a) p1\n(b) p2\n\n3. three\n4. four\n")
    lists = re.findall(r"<ol[^>]*>", html)
    assert lists == ['<ol type="a">', '<ol type="A">', '<ol type="i">', '<ol start="3" type="a">', '<ol type="a">', '<ol start="3">']
    assert "<p>I. Smith\nII. Jones</p>" in html  # a capital letter and a period need two spaces
    assert "<li>one</li>" in html  # still a tight list


def test_letter_lists_skip_code_and_text() -> None:
    "Code blocks and a sentence that is not a list stay as they are."
    text = "```\na. code\n```\n\nSome text\nb. continues it\n"
    assert letter_lists(text) == (text, {})
    html = md("1. one\n   a. sub\n   b. sub2\n")
    assert '<ol type="a">' in html


# ---------------------------------------------------------------- figures and layouts


def test_fig_align_and_fig_alt() -> None:
    "`fig-align` places a figure, from the page or the picture; `fig-alt` is the alt text, and the caption stays."
    html = page("![Cap](a.png)\n\n![Right](a.png){fig-align=right fig-alt=\"Alt text\"}\n\n![Def](a.png){fig-align=default}\n", fig_align="left")
    assert html.count("quarto-figure quarto-figure-left") == 2 and html.count("quarto-figure-right") == 1
    assert '<img alt="Alt text" src="a.png"' in html and "<figcaption>Right</figcaption>" in html and "fig-alt" not in html
    assert "quarto-figure-center" in md("![Cap](a.png)\n")


def test_layout_ncol_nrow_and_layout() -> None:
    "`layout-ncol`, `layout-nrow` and `layout` put the blocks of a div in rows of cells, in Quarto's markup."
    pics = "![A](a.png)\n\n![B](a.png)\n\n![C](a.png)\n"
    html = md("::: {layout-ncol=2}\n" + pics + ":::\n")
    assert '<div class="quarto-layout-panel" data-layout-ncol="2">' in html
    assert html.count('<div class="quarto-layout-row">') == 2 and html.count("flex-basis: 50.0%") == 3
    html = md("::: {layout-nrow=1}\n" + pics + ":::\n")
    assert html.count('<div class="quarto-layout-row">') == 1 and html.count("flex-basis: 33.3%") == 3
    html = md('::: {layout="[[1,1],[1]]"}\n' + pics + ":::\n")
    assert html.count("flex-basis: 50.0%") == 2 and html.count("flex-basis: 100.0%") == 1
    assert html.count("<figure") == 3


# ---------------------------------------------------------------- callouts and headings


def test_callout_defaults_from_the_page() -> None:
    "`callout-appearance` and `callout-icon` set the default of each callout; a callout's own attributes still win."
    html = page("::: {.callout-note}\nA.\n:::\n\n::: {.callout-tip appearance=\"default\" icon=\"true\"}\nB.\n:::\n", callout_appearance="simple", callout_icon=False)
    assert 'class="callout callout-style-simple callout-note callout-titled"><div class="callout-header d-flex align-content-center"><div class="callout-title' in html
    assert "callout-style-default callout-tip" in html and html.count("callout-icon-container") == 1


def test_anchor_sections_and_number_depth() -> None:
    "`anchor-sections: false` drops the `anchored` class that the anchors need; `number-depth` numbers only the top levels."
    html = md("Intro.\n\n# One\n\n## Two\n\n### Three\n", number_sections=True, **page_options({"number-depth": 2, "anchor-sections": False}))
    assert '<h1 data-anchor-id="one"><span class="header-section-number">1</span> One</h1>' in html
    assert '<h2 data-anchor-id="two"><span class="header-section-number">1.1</span> Two</h2>' in html
    assert '<h3 data-anchor-id="three">Three</h3>' in html and "anchored" not in html
    assert '<h1 class="anchored"' in md("# One\n\nText.\n\n# Two\n")
