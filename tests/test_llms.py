"The tests of `website.llms-txt`: a Markdown copy of each page, `page.llms.md`, made from its own Markdown, and the index `llms.txt`."

import json
import textwrap
from pathlib import Path

from smalldocs.site import build


def write(
    root: Path,  # A folder
    files: dict[str, str],  # Each file's path and text
) -> Path:  # The folder
    "Write files under a folder, the text without its common indentation."
    for name, text in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    return root


PAGE = """
---
title: Guide
---

Intro with a [link](other.qmd#part), an [outside link](https://example.com/a.html) and `code`.

::: {.callout-tip}
## Its own title
Tip body.
:::

::: {.panel-tabset}
## One
First tab.

## Two
Second tab.
:::

```python
print("hi")
```

Maths $x^2$ and a note[^1]. It costs $5 and $10.

| A | B |
|---|---|
| 1 | 2 |

- [x] done
- [ ] open

![A picture](pic.svg)

[^1]: The note.
"""

CONFIG = """
project: {type: website}
website:
  title: Site
  description: A small site
  llms-txt: true
  page-navigation: true
  sidebar:
    contents: [index.qmd, guide.qmd, other.qmd]
"""


def site(
    tmp_path: Path,  # A folder for the project
    config: str = CONFIG,  # The `_quarto.yml`
    more: dict[str, str] | None = None,  # More files
) -> Path:  # The output folder
    "Write a small project and build it with `--strict`'s rule: no warning."
    write(tmp_path, {"_quarto.yml": config, "index.qmd": "---\ntitle: Home\n---\n\nHello.\n", "guide.qmd": PAGE,
                     "other.qmd": "---\ntitle: Other\n---\n\n## Part\n\nText.\n", "pic.svg": "<svg/>", **(more or {})})  # fmt: skip
    s = build(tmp_path, quiet=True)
    assert s.warnings == [], s.warnings
    return tmp_path / "_site"


def test_off_by_default(tmp_path: Path) -> None:
    "Without `llms-txt`, a site has no Markdown copies and no `llms.txt`, and its pages are as before."
    out = site(tmp_path, CONFIG.replace("  llms-txt: true\n", ""))
    assert not list(out.rglob("*.llms.md")) and not (out / "llms.txt").exists()


def test_html_does_not_change(tmp_path: Path) -> None:
    "Turning `llms-txt` on adds files and changes no page of the site."
    a, b = tmp_path / "a", tmp_path / "b"
    site(a, CONFIG.replace("  llms-txt: true\n", ""))
    site(b)
    for f in (a / "_site").rglob("*"):
        if f.is_file():
            assert f.read_bytes() == (b / "_site" / f.relative_to(a / "_site")).read_bytes(), f


def test_page_copy(tmp_path: Path) -> None:
    "A copy is the page's own Markdown: divs become HTML divs, links go to the other pages' copies, and code, maths and notes stay."
    md = (site(tmp_path) / "guide.llms.md").read_text(encoding="utf-8")
    assert md.startswith("# Guide\n\nIntro with a [link](other.llms.md#part), an [outside link](https://example.com/a.html) and `code`.")
    assert '<div class="callout-tip">\n\n## Its own title\nTip body.\n\n</div>' in md
    assert '<div class="panel-tabset">\n\n## One\nFirst tab.\n\n## Two\nSecond tab.\n\n</div>' in md
    assert '```python\nprint("hi")\n```' in md
    assert "Maths $x^2$ and a note[^1]. It costs $5 and $10." in md and md.rstrip().endswith("[^1]: The note.")
    assert "![A picture](pic.svg)" in md and ":::" not in md and "title: Guide" not in md


def test_divs_spans_and_code(tmp_path: Path) -> None:
    "Nested divs and spans become HTML with their id, classes and attributes; inside code, nothing changes."
    page = """---
title: D
description: About divs.
---

::: {#box .a .b k="v & w"}
:::: inner
Text [small]{.smallcaps} and [a link](guide.qmd){target=_blank}.
::::
:::

```markdown
::: {.callout-note}
[x](guide.qmd) and [s]{.y}
:::
```

`[x](guide.qmd)` stays.

[ref]: guide.qmd
"""
    md = (site(tmp_path, more={"d.qmd": page}) / "d.llms.md").read_text(encoding="utf-8")
    assert md.startswith("# D\n\nAbout divs.\n\n")
    assert '<div id="box" class="a b" k="v &amp; w">\n\n<div class="inner">\n\n' in md
    assert 'Text <span class="smallcaps">small</span> and [a link](guide.llms.md){target=_blank}.\n\n</div>\n\n</div>' in md
    assert "```markdown\n::: {.callout-note}\n[x](guide.qmd) and [s]{.y}\n:::\n```" in md
    assert "`[x](guide.qmd)` stays." in md and "[ref]: guide.llms.md" in md


def test_llms_txt(tmp_path: Path) -> None:
    "`llms.txt` names the site and lists each page's copy, in the order of the files; with `site-url`, the links are absolute."
    out = site(tmp_path)
    assert (out / "llms.txt").read_text(encoding="utf-8") == (
        "# Site\n\n> A small site\n\n## Pages\n\n- [Guide](guide.llms.md)\n- [Home](index.llms.md)\n- [Other](other.llms.md)\n"
    )
    out = site(tmp_path, CONFIG.replace("  llms-txt: true\n", "  llms-txt: true\n  site-url: https://x.org/docs\n"))
    assert "- [Guide](https://x.org/docs/guide.llms.md)" in (out / "llms.txt").read_text(encoding="utf-8")


def test_drafts_and_404(tmp_path: Path) -> None:
    "An unlinked draft has no copy and no line in `llms.txt`; the 404 page has a copy but no line, as in Quarto."
    cfg = CONFIG.replace("  llms-txt: true\n", "  llms-txt: true\n  draft-mode: unlinked\n")
    out = site(tmp_path, cfg, {"draft.qmd": "---\ntitle: Draft\ndraft: true\n---\n\nSoon.\n", "404.qmd": "---\ntitle: Lost\n---\n\nNot here.\n"})
    assert (out / "draft.html").exists() and not (out / "draft.llms.md").exists()
    assert (out / "404.llms.md").exists()
    txt = (out / "llms.txt").read_text(encoding="utf-8")
    assert "Draft" not in txt and "Lost" not in txt


def test_conditional_content(tmp_path: Path) -> None:
    "In the copy, a condition on `llms-txt` decides alone, as in Quarto; any other decides as on the HTML page."
    page = """---
title: C
---

::: {.content-visible when-format="llms-txt"}
For agents.
:::

::: {.content-hidden when-format="llms-txt"}
For people.

::: {.callout-note}
Nested, for people.
:::
:::

::: {.content-visible when-format="html"}
On the web.
:::

::: {.content-visible when-format="pdf"}
In print.
:::

A [span for agents]{.content-visible when-format="llms-txt"}.
"""
    out = site(tmp_path, more={"c.qmd": page})
    html, md = (out / "c.html").read_text(encoding="utf-8"), (out / "c.llms.md").read_text(encoding="utf-8")
    assert "For people." in html and "For agents." not in html and "span for agents" not in html
    assert md == "# C\n\nFor agents.\n\n\nOn the web.\n\n\nA span for agents.\n"


def test_links_to_the_copies(tmp_path: Path) -> None:
    "A page may link to `llms.txt` and to a copy; neither is a broken link, and the HTML links to them as written."
    out = site(tmp_path, more={"links.qmd": "---\ntitle: L\n---\n\nSee [the index](llms.txt) and [a copy](guide.llms.md).\n"})
    html = (out / "links.html").read_text(encoding="utf-8")
    assert 'href="llms.txt"' in html and 'href="guide.llms.md"' in html


def test_copies_are_not_pages(tmp_path: Path) -> None:
    "A second build does not read the copies as pages, even with an output folder that does not start with `_`."
    cfg = CONFIG.replace("project: {type: website}", "project: {type: website, output-dir: site}")
    site(tmp_path, cfg)
    s = build(tmp_path, quiet=True)
    assert s.warnings == [] and len(s.pages) == 3
    assert not (tmp_path / "site" / "guide.llms.llms.md").exists()


def test_notebook_copy(tmp_path: Path) -> None:
    "A notebook's copy follows nbconvert: fenced code, indented text, pictures saved beside it; cells the page hides are left out."
    nb = {"nbformat": 4, "nbformat_minor": 5, "metadata": {"kernelspec": {"language": "python"}}, "cells": [
        {"cell_type": "markdown", "metadata": {}, "source": "---\ntitle: NB\n---\n\nSee [the guide](guide.qmd).\n\n::: {.callout-note}\nA note.\n:::"},
        {"cell_type": "code", "metadata": {}, "execution_count": 1, "source": "#| label: one\nprint(1)", "outputs": [{"output_type": "stream", "name": "stdout", "text": "1\n2\n"}]},
        {"cell_type": "code", "metadata": {}, "execution_count": 2, "source": "#| echo: false\nplot()",
         "outputs": [{"output_type": "display_data", "metadata": {}, "data": {"image/png": "iVBORw0KGgo=", "text/plain": "<Figure>"}}]},
        {"cell_type": "code", "metadata": {"tags": ["remove-cell"]}, "source": "secret()", "outputs": []},
        {"cell_type": "code", "metadata": {}, "source": "#| output: false\nquiet()", "outputs": [{"output_type": "stream", "name": "stdout", "text": "hidden\n"}]},
        {"cell_type": "code", "metadata": {}, "source": "1/0", "outputs": [{"output_type": "error", "ename": "ZeroDivisionError", "evalue": "x",
         "traceback": ["\x1b[0;31mZeroDivisionError\x1b[0m: division by zero"]}]},
        {"cell_type": "code", "metadata": {}, "source": "t", "outputs": [{"output_type": "execute_result", "metadata": {}, "execution_count": 3,
         "data": {"text/html": "<table><tr><td>1</td></tr></table>", "text/plain": "t"}}]},
    ]}  # fmt: skip
    out = site(tmp_path, more={"nb.ipynb": json.dumps(nb)})
    md = (out / "nb.llms.md").read_text(encoding="utf-8")
    assert md == (
        "# NB\n\nSee [the guide](guide.llms.md).\n\n<div class=\"callout-note\">\n\nA note.\n\n</div>\n\n"
        "```python\nprint(1)\n```\n\n    1\n    2\n\n![png](nb_files/nb_2_0.png)\n\n```python\nquiet()\n```\n\n"
        "```python\n1/0\n```\n\n    ZeroDivisionError: division by zero\n\n```python\nt\n```\n\n<table><tr><td>1</td></tr></table>\n"
    )
    assert (out / "nb_files" / "nb_2_0.png").read_bytes() == b"\x89PNG\r\n\x1a\n"


def test_a_source_named_llms_md(tmp_path: Path) -> None:
    "A page whose source is named `x.llms.md` is a page: a link to it goes to its HTML, with the option on or off."
    more = {"notes.llms.md": "# Notes\n\nNotes.\n", "links.qmd": "---\ntitle: L\n---\n\n[notes](notes.llms.md)\n"}
    for cfg in (CONFIG, CONFIG.replace("  llms-txt: true\n", "")):
        out = site(tmp_path, cfg, more)
        assert 'href="notes.llms.html"' in (out / "links.html").read_text(encoding="utf-8")


def test_link_to_an_unlinked_drafts_copy(tmp_path: Path) -> None:
    "An unlinked draft has no copy, so a link to its copy is reported as broken."
    cfg = CONFIG.replace("  llms-txt: true\n", "  llms-txt: true\n  draft-mode: unlinked\n")
    write(tmp_path, {"_quarto.yml": cfg, "index.qmd": "---\ntitle: Home\n---\n\n[d](draft.llms.md)\n", "guide.qmd": "# G\n", "other.qmd": "# O\n",
                     "draft.qmd": "---\ntitle: D\ndraft: true\n---\n\nSoon.\n"})  # fmt: skip
    s = build(tmp_path, quiet=True)
    assert any("draft.llms.md" in w for w in s.warnings), s.warnings


def test_a_page_called_x_llms_qmd(tmp_path: Path) -> None:
    "With `foo.qmd` and `foo.llms.qmd`, a link to `foo.llms.md` goes to the page `foo.llms.html`, with the option on or off."
    more = {"foo.qmd": "# Foo\n", "foo.llms.qmd": "# Foo notes\n", "links.qmd": "---\ntitle: L\n---\n\n[notes](foo.llms.md)\n"}
    for cfg in (CONFIG, CONFIG.replace("  llms-txt: true\n", "")):
        out = site(tmp_path, cfg, more)
        assert 'href="foo.llms.html"' in (out / "links.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------- what the adversarial review found


def test_no_file_is_published_by_a_copy(tmp_path: Path) -> None:
    "A link in a comment, in code or anywhere in a copy adds no file to the site; a footnote's first word is not a link."
    page = "---\ntitle: S\n---\n\n<!-- [hidden](secret.txt) -->\n\n    [code](secret2.txt)\n\nA note[^1].\n\n[^1]: word here\n"
    out = site(tmp_path, more={"s.qmd": page, "secret.txt": "x", "secret2.txt": "y"})
    assert not (out / "secret.txt").exists() and not (out / "secret2.txt").exists()
    assert "[^1]: word here" in (out / "s.llms.md").read_text(encoding="utf-8")


def test_hidden_div_across_notebook_cells(tmp_path: Path) -> None:
    "A hidden div that opens in one cell and closes in a later one hides the cells between, as on the page."
    nb = {"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": [
        {"cell_type": "markdown", "metadata": {}, "source": "# N\n\n::: {.content-hidden when-format=\"llms-txt\"}\nsecret prose"},
        {"cell_type": "code", "metadata": {}, "source": "password = 'hunter2'", "outputs": [{"output_type": "stream", "name": "stdout", "text": "hunter2\n"}]},
        {"cell_type": "markdown", "metadata": {}, "source": ":::\n\n::: {.callout-note}\nopen"},
        {"cell_type": "code", "metadata": {}, "source": "x = 1\n```\ny", "outputs": []},
    ]}  # fmt: skip
    md = (site(tmp_path, more={"nb.ipynb": json.dumps(nb)}) / "nb.llms.md").read_text(encoding="utf-8")
    assert "hunter2" not in md and "secret" not in md and ":::" not in md
    assert md.endswith('<div class="callout-note">\n\nopen\n\n````python\nx = 1\n```\ny\n````\n\n</div>\n')


def test_maths_is_not_a_span() -> None:
    "LaTeX's optional arguments are not Pandoc spans."
    from smalldocs.llms import Prose, prose

    md = prose("$\\sqrt[3]{x}$ and $\\begin{array}[t]{cc}$ and [s]{.c}", Prose(lambda h: h, {}))
    assert md == '$\\sqrt[3]{x}$ and $\\begin{array}[t]{cc}$ and <span class="c">s</span>'


def test_hidden_qmd_cells(tmp_path: Path) -> None:
    "A `.qmd` cell hidden on the page by `include: false` or `echo: false` is hidden in the copy; a plain code block stays."
    page = "---\ntitle: Q\n---\n\n```{python}\n#| include: false\nsecret = 1\n```\n\n```{python}\n#| echo: false\nshh = 2\n```\n\n```{python}\nshown = 3\n```\n\n```python\n#| echo: false\nplain = 4\n```\n"
    write(tmp_path, {"_quarto.yml": "project: {type: website}\nwebsite:\n  title: S\n  llms-txt: true\n", "index.qmd": "# Home\n", "q.qmd": page})
    assert [w for w in build(tmp_path, quiet=True).warnings if "not run" not in w] == []
    md = (tmp_path / "_site" / "q.llms.md").read_text(encoding="utf-8")
    assert "secret" not in md and "shh" not in md and "shown = 3" in md and "plain = 4" in md


def test_markdown_after_a_div(tmp_path: Path) -> None:
    "Text right after a div's end is still Markdown, and a div left open is closed."
    from markdown_it import MarkdownIt

    from smalldocs.llms import Prose, prose

    md = prose("::: {.a}\nIn.\n:::\nAfter *emph*.\n\n::: {.b}\nopen", Prose(lambda h: h, {}))
    assert "<em>emph</em>" in MarkdownIt("commonmark").render(md)
    assert md.endswith('<div class="b">\n\nopen\n\n</div>') and md.count("</div>") == 2


def test_notebook_figure_captions(tmp_path: Path) -> None:
    "A picture with `fig-cap` is followed by its caption in a div; a list gives each picture its own, and `fig-alt` is the alt text."
    png = {"output_type": "display_data", "metadata": {}, "data": {"image/png": "iVBORw0KGgo="}}
    nb = {"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": [
        {"cell_type": "markdown", "metadata": {}, "source": "# F"},
        {"cell_type": "code", "metadata": {}, "source": "#| fig-cap: [One, Two]\n#| fig-alt: A dot\nplot()",
         "outputs": [png, {"output_type": "stream", "name": "stdout", "text": "between\n"}, png]},
    ]}  # fmt: skip
    md = (site(tmp_path, more={"nb.ipynb": json.dumps(nb)}) / "nb.llms.md").read_text(encoding="utf-8")
    cap = '![A dot](nb_files/nb_1_{}.png)\n\n<div class="figure-caption">\n\n{}\n\n</div>'
    assert cap.format(0, "One") + "\n\n    between\n\n" + cap.format(2, "Two") in md


# ---------------------------------------------------------------- what the second review found


SMALL = "project: {type: website}\nwebsite:\n  title: S\n  llms-txt: true\n"


def copy_of(tmp_path: Path, files: dict[str, str], name: str) -> str:  # The copy's text
    "Build a small site, allowing the warning for cells that are not run, and read one copy."
    write(tmp_path, {"_quarto.yml": SMALL, "other.qmd": "---\ntitle: O\n---\n\nO.\n", **files})
    assert [w for w in build(tmp_path, quiet=True).warnings if "not run" not in w] == []
    return (tmp_path / "_site" / name).read_text(encoding="utf-8")


def test_comment_mark_in_a_code_span(tmp_path: Path) -> None:
    "`<!--` inside a code span opens no comment, so what follows is still hidden and rewritten."
    page = '---\ntitle: P\n---\n\nType `<!--` to start one.\n\n::: {.content-hidden when-format="llms-txt"}\nSECRET\n:::\n\n[o](other.qmd)\n'
    md = copy_of(tmp_path, {"index.qmd": page}, "index.llms.md")
    assert "SECRET" not in md and ":::" not in md and "[o](other.llms.md)" in md


def test_hidden_cells_in_a_list_or_quote(tmp_path: Path) -> None:
    "A hidden cell inside a list item or a quote is hidden in the copy, as on the page."
    page = "---\ntitle: P\n---\n\n- item\n\n    ```{python}\n    #| echo: false\n    IN_LIST = 2\n    ```\n\n> ```{python}\n> #| echo: false\n> IN_QUOTE = 3\n> ```\n"
    md = copy_of(tmp_path, {"index.qmd": page}, "index.llms.md")
    assert "IN_LIST" not in md and "IN_QUOTE" not in md and "- item" in md


def test_no_attachment_of_a_hidden_cell(tmp_path: Path) -> None:
    "An attachment of a Markdown cell that the copy leaves out is not saved."
    att = {"s.png": {"image/png": "iVBORw0KGgo="}}
    nb = {"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": [
        {"cell_type": "markdown", "metadata": {}, "source": "---\ntitle: N\n---\n\n::: {.content-hidden when-format=\"llms-txt\"}"},
        {"cell_type": "markdown", "metadata": {}, "attachments": att, "source": "![s](attachment:s.png)"},
        {"cell_type": "markdown", "metadata": {}, "source": ":::"},
        {"cell_type": "markdown", "metadata": {}, "attachments": att, "source": "![t](attachment:s.png)"},
    ]}  # fmt: skip
    md = copy_of(tmp_path, {"index.ipynb": json.dumps(nb)}, "index.llms.md")
    assert "![t](index_files/index_3_s.png)" in md and "index_1_s" not in md
    assert sorted(f.name for f in (tmp_path / "_site" / "index_files").iterdir()) == ["index_3_s.png"]


def test_title_from_the_first_heading_once(tmp_path: Path) -> None:
    "A page with no `title:` takes its first heading as its title, and the copy has that heading once."
    md = copy_of(tmp_path, {"index.qmd": "# Heading Title\n\nText.\n"}, "index.llms.md")
    assert md == "# Heading Title\n\nText.\n"


def test_caption_details(tmp_path: Path) -> None:
    "Alt text is escaped, a caption's links go to copies, captions are counted as the page counts pictures, and bad data is skipped."
    gif = {"output_type": "display_data", "metadata": {}, "data": {"image/gif": "R0lGOA==", "text/plain": "<gif>"}}
    png = {"output_type": "display_data", "metadata": {}, "data": {"image/png": "iVBORw0KGgo="}}
    bad = {"output_type": "display_data", "metadata": {}, "data": {"image/png": "not base64!"}}
    nb = {"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": [
        {"cell_type": "markdown", "metadata": {}, "source": "---\ntitle: N\n---\n"},
        {"cell_type": "code", "metadata": {}, "source": '#| fig-cap: [Gif, "See [o](other.qmd)"]\n#| fig-alt: "a ]bad[\\n alt"\nplot()', "outputs": [gif, png, bad]},
    ]}  # fmt: skip
    md = copy_of(tmp_path, {"index.ipynb": json.dumps(nb)}, "index.llms.md")
    assert '![a \\]bad\\[ alt](index_files/index_1_1.png)\n\n<div class="figure-caption">\n\nSee [o](other.llms.md)\n\n</div>' in md
    assert "index_1_2" not in md


# ---------------------------------------------------------------- what the third review found


def test_code_blocks_as_commonmark_reads_them(tmp_path: Path) -> None:
    "An indented example of a cell stays; a fence that a quote's end closes ends there; a comment closes at `-->` in backticks."
    from smalldocs.llms import Prose, prose

    p = Prose(lambda h: h.replace(".qmd", ".llms.md"), {})
    md = prose("To hide a cell:\n\n    ```{python}\n    #| echo: false\n    1 + 1\n    ```\n\nDone [o](o.qmd).", p)
    assert md == "To hide a cell:\n\n    ```{python}\n    #| echo: false\n    1 + 1\n    ```\n\nDone [o](o.llms.md)."
    md = prose('> ```{python}\n> #| echo: false\n> x=1\n\n::: {.content-hidden when-format="llms-txt"}\nSECRET\n:::\n\nAfter.', p)
    assert md == "After."
    md = prose('<!-- a\n`-->`\n\n::: {.content-hidden when-format="llms-txt"}\nSECRET\n:::\n\nAfter.', p)
    assert "SECRET" not in md and md.endswith("After.")


def test_title_kept_without_a_heading(tmp_path: Path) -> None:
    "A page with no `title:` and no first heading keeps the title the HTML page shows."
    md = copy_of(tmp_path, {"index.qmd": "---\npagetitle: Tab name\n---\n\nText.\n"}, "index.llms.md")
    assert md == "# Tab name\n\nText.\n"


def test_bad_attachment_is_skipped(tmp_path: Path) -> None:
    "An attachment whose data is broken is skipped, and the build goes on."
    nb = {"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": [
        {"cell_type": "markdown", "metadata": {}, "attachments": {"s.png": {"image/png": "not base64!"}}, "source": "---\ntitle: N\n---\n\n![s](attachment:s.png)"},
    ]}  # fmt: skip
    assert copy_of(tmp_path, {"index.ipynb": json.dumps(nb)}, "index.llms.md").startswith("# N")


def test_html_blocks_as_written() -> None:
    "An HTML block, such as an indented comment or `<details>`, is copied as written, and the page's text after it stays."
    from smalldocs.llms import Prose, prose

    p = Prose(lambda h: h, {})
    assert prose("   <!--\n::: {.content-hidden}\n-->\npublic", p) == "   <!--\n::: {.content-hidden}\n-->\npublic"
    assert prose("<details>\n:::\nshown\n</details>\n\nAfter.", p) == "<details>\n:::\nshown\n</details>\n\nAfter."


def test_html_line_before_a_divs_end() -> None:
    "An HTML line right before a div's `:::` does not hide the div's end, as on the page."
    from smalldocs.llms import Prose, prose

    p = Prose(lambda h: h, {})
    assert prose("::: {.content-hidden}\nSECRET\n<div>x</div>\n:::\n\nAFTER", p) == "AFTER"
    md = prose("::: {.callout-note}\nIn.\n<div>x</div>\n:::\n\nAFTER", p)
    assert md == '<div class="callout-note">\n\nIn.\n<div>x</div>\n\n</div>\n\n\nAFTER'


def test_divs_where_the_page_has_them() -> None:
    "Divs, code and HTML are found by the page's own parser, so a `:::` in code inside HTML, or after it, ends no div early."
    from smalldocs.llms import Prose, prose

    p = Prose(lambda h: h, {})
    assert prose("::: {.content-hidden}\n<div>\n```\n:::\n```\nSECRET\n</div>\n:::\n\nAFTER", p) == "AFTER"
    assert prose("::: {.content-hidden}\n::: inner\n<div>\n:::\n```\n:::\n```\nSECRET\n:::\n\nAFTER", p) == "AFTER"


def test_divs_in_a_quote() -> None:
    "A div in a quote ends where the page ends it, with its own classes, and its lines stay in the quote."
    from smalldocs.llms import Prose, prose

    p = Prose(lambda h: h, {})
    assert prose("> ::: {.content-hidden}\n> secret\n> :::\n\nafter", p) == "after"
    note = '> <div class="callout-note">\n>\n> note\n>\n> </div>\n>\n\nafter'
    assert prose("> ::: {.callout-note}\n> note\n> :::\n\nafter", p) == note
    assert prose("> ::: {.callout-note}\n> note\n\nafter", p) == note  # the quote's end ends the div


def test_divs_ending_together() -> None:
    "Divs that end on the same line all close; a div left open in a quote ends with its cell, as on the page."
    from smalldocs.llms import Prose, prose

    p = Prose(lambda h: h, {})
    assert prose("> ::: {.content-hidden}\n> ::: {.b}\n> SEC\n\nBB", p) == "BB"
    assert prose("> ::: {.a}\n> ::: {.b}\n> AA\n\nBB", p).endswith("> </div>\n>\n> </div>\n>\n\nBB")
    assert prose("::: {.a}\nAA\n> ::: {.b}\n> XX\n:::\nCC", p) == '<div class="a">\n\nAA\n> <div class="b">\n>\n> XX\n>\n> </div>\n>\n\n</div>\n\nCC'
    q = Prose(lambda h: h, {})
    assert q.feed("> ::: {.content-hidden}\n> SEC").strip() == "" and q.feed("YY").strip() == "YY" and not q.dropping


def test_nested_divs_across_notebook_cells(tmp_path: Path) -> None:
    "A div opened inside another and closed in a later cell hides or holds the code cells between, as on the page."
    cells = [
        {"cell_type": "markdown", "metadata": {}, "source": '---\ntitle: N\n---\n\n::: {.callout-tip}\nTry it.\n\n::: {.content-hidden when-format="llms-txt"}\nSolution:'},
        {"cell_type": "code", "metadata": {}, "source": "SECRETCODE", "outputs": []},
        {"cell_type": "markdown", "metadata": {}, "source": ":::\n:::\n\n:::: {.columns}\n::: {.column}\nLeft"},
        {"cell_type": "code", "metadata": {}, "source": "left()", "outputs": []},
        {"cell_type": "markdown", "metadata": {}, "source": ":::\n::: {.column}\nRight\n:::\n::::\n\nAfter."},
    ]
    nb = {"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": cells}
    md = copy_of(tmp_path, {"index.ipynb": json.dumps(nb)}, "index.llms.md")
    assert "SECRET" not in md and "Solution" not in md and ":::" not in md
    assert '<div class="column">\n\nLeft\n\n```python\nleft()\n```\n\n</div>' in md
    assert md.endswith("Right\n\n</div>\n\n</div>\n\n\nAfter.\n")


def test_indented_div_across_cells() -> None:
    "A top-level div whose `:::` is indented a little still goes on into the next cell."
    from smalldocs.llms import Prose

    q = Prose(lambda h: h, {})
    assert q.feed(" ::: {.callout-note}\n Note") == ' <div class="callout-note">\n\n Note' and q.stack == ["div"]
    assert q.feed(":::\n\nAfter.") == "\n</div>\n\n\nAfter."


def test_cells_ending_with_a_newline() -> None:
    "A div left open in a cell that ends with a newline goes on into the next cell."
    from smalldocs.llms import Prose

    q = Prose(lambda h: h, {})
    q.feed('::: {.content-hidden when-format="llms-txt"}\nSolution:\n  \n\n')
    assert q.dropping
    assert q.feed(":::\n\nAfter.\n").strip() == "After." and not q.stack
