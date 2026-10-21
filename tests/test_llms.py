"The tests of `website.llms-txt`: a Markdown copy of each page, `page.llms.md`, and the index `llms.txt`, as Quarto writes them."

import json
import textwrap
from pathlib import Path

from smalldocs.llms import page_markdown
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
    "Each page has a Markdown copy beside it: its content, with no navigation, as Quarto writes it."
    md = (site(tmp_path) / "guide.llms.md").read_text(encoding="utf-8")
    assert md.startswith("# Guide\n\nIntro with a [link](other.llms.md#part), an [outside link](https://example.com/a.html) and `code`.")
    assert "> **TIP:**\n>\n> Tip body." in md and "Its own title" not in md
    assert "## One\n\nFirst tab.\n\n## Two\n\nSecond tab." in md
    assert '``` python\nprint("hi")\n```' in md
    assert "Maths $x^2$ and a note[^1]. It costs \\$5 and \\$10." in md
    assert "| A | B |\n|---|---|\n| 1 | 2 |" in md
    assert "- [x] done\n- [ ] open" in md
    assert "![A picture](pic.svg)" in md
    assert md.rstrip().endswith("## Footnotes\n\n[^1]: The note.")
    for nav in ("Home", "Other", "breadcrumb", "Toggle"):
        assert nav not in md, nav


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
    "`when-format=\"llms-txt\"` content is only in the copy; `content-hidden` with it is only in the HTML."
    page = '---\ntitle: C\n---\n\n::: {.content-visible when-format="llms-txt"}\nFor agents.\n:::\n\n::: {.content-hidden when-format="llms-txt"}\nFor people.\n:::\n'
    out = site(tmp_path, more={"c.qmd": page})
    html, md = (out / "c.html").read_text(encoding="utf-8"), (out / "c.llms.md").read_text(encoding="utf-8")
    assert "For people." in html and "For agents." not in html
    assert "For agents." in md and "For people." not in md


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
    "A notebook's copy has its code and its saved output as code blocks; a picture held in the page is named."
    nb = {"nbformat": 4, "nbformat_minor": 5, "metadata": {"kernelspec": {"language": "python"}}, "cells": [
        {"cell_type": "markdown", "metadata": {}, "source": "# NB\n\nText."},
        {"cell_type": "code", "metadata": {}, "execution_count": 1, "source": "print(1)", "outputs": [{"output_type": "stream", "name": "stdout", "text": "1\n"}]},
        {"cell_type": "code", "metadata": {}, "execution_count": 2, "source": "#| fig-cap: A dot\nplot()",
         "outputs": [{"output_type": "display_data", "metadata": {}, "data": {"image/png": "iVBORw0KGgo="}}]},
    ]}  # fmt: skip
    out = site(tmp_path, more={"nb.ipynb": json.dumps(nb)})
    md = (out / "nb.llms.md").read_text(encoding="utf-8")
    assert "``` python\nprint(1)\n```\n\n```\n1\n```" in md
    assert "[Image: A dot]" in md and "base64" not in md


def test_writer_details() -> None:
    "The writer escapes what Markdown reads, keeps an underscore inside a word, gives code a fence it cannot close, and puts a caption after its table."
    md = page_markdown('<main><p>a *b* _c snake_case [d] &lt;e&gt;</p><pre><code class="sourceCode python">x = """\n```\n"""</code></pre></main>')
    assert "a \\*b\\* \\_c snake_case \\[d\\] \\<e>" in md
    assert '```` python\nx = """\n```\n"""\n````' in md
    md = page_markdown("<main><table><caption>Cap</caption><tr><th>A</th></tr><tr><td>1</td></tr></table></main>")
    assert md == "| A |\n|---|\n| 1 |\n\nCap\n"


# ---------------------------------------------------------------- what the adversarial review found


def test_listing_page_with_llms_content(tmp_path: Path) -> None:
    "A listing page with `when-format=\"llms-txt\"` content keeps its listing in the copy, and its feed is not doubled."
    cfg = CONFIG.replace("  llms-txt: true\n", "  llms-txt: true\n  site-url: https://x.org/\n")
    page = '---\ntitle: Posts\nlisting: {contents: posts, feed: true}\n---\n\n::: {.content-visible when-format="llms-txt"}\nAgents only.\n:::\n'
    posts = {"posts/a.qmd": "---\ntitle: Post A\ndate: 2026-01-02\n---\n\nA.\n", "posts/b.qmd": "---\ntitle: Post B\ndate: 2026-01-01\n---\n\nB.\n"}
    out = site(tmp_path, cfg, {"blog.qmd": page, **posts})
    md = (out / "blog.llms.md").read_text(encoding="utf-8")
    assert "Agents only." in md and "### [Post A](posts/a.llms.md)" in md and "### [Post B](posts/b.llms.md)" in md
    assert (out / "blog.xml").read_text(encoding="utf-8").count("<item>") == 2


def test_margin_footnotes(tmp_path: Path) -> None:
    "With `reference-location: margin`, the notes go to the end of the copy, under Footnotes, and not before the text."
    page = "---\ntitle: M\nreference-location: margin\n---\n\n## Sec\n\nText with note[^1] and another[^2].\n\n[^1]: Note one.\n[^2]: Note two.\n"
    md = (site(tmp_path, more={"m.qmd": page}) / "m.llms.md").read_text(encoding="utf-8")
    assert md == "# M\n\n## Sec\n\nText with note[^1] and another[^2].\n\n## Footnotes\n\n[^1]: Note one.\n\n[^2]: Note two.\n"


def test_a_source_named_llms_md(tmp_path: Path) -> None:
    "A page whose source is named `x.llms.md` is a page: a link to it goes to its HTML, with the option on or off."
    more = {"notes.llms.md": "# Notes\n\nNotes.\n", "links.qmd": "---\ntitle: L\n---\n\n[notes](notes.llms.md)\n"}
    for cfg in (CONFIG, CONFIG.replace("  llms-txt: true\n", "")):
        out = site(tmp_path, cfg, more)
        assert 'href="notes.llms.html"' in (out / "links.html").read_text(encoding="utf-8")


def test_broken_link_in_llms_content(tmp_path: Path) -> None:
    "A broken link inside `when-format=\"llms-txt\"` content is reported, as one elsewhere is."
    write(tmp_path, {"_quarto.yml": CONFIG, "index.qmd": "---\ntitle: Home\n---\n\nHi.\n", "guide.qmd": "# G\n", "other.qmd": "# O\n",
                     "c.qmd": '---\ntitle: C\n---\n\n::: {.content-visible when-format="llms-txt"}\n[gone](nowhere.qmd)\n:::\n'})  # fmt: skip
    s = build(tmp_path, quiet=True)
    assert any("nowhere.qmd" in w for w in s.warnings), s.warnings


def test_link_to_an_unlinked_drafts_copy(tmp_path: Path) -> None:
    "An unlinked draft has no copy, so a link to its copy is reported as broken."
    cfg = CONFIG.replace("  llms-txt: true\n", "  llms-txt: true\n  draft-mode: unlinked\n")
    write(tmp_path, {"_quarto.yml": cfg, "index.qmd": "---\ntitle: Home\n---\n\n[d](draft.llms.md)\n", "guide.qmd": "# G\n", "other.qmd": "# O\n",
                     "draft.qmd": "---\ntitle: D\ndraft: true\n---\n\nSoon.\n"})  # fmt: skip
    s = build(tmp_path, quiet=True)
    assert any("draft.llms.md" in w for w in s.warnings), s.warnings


def test_escapes_and_tight_lists() -> None:
    "A `!` before a link and a literal entity are escaped; a list with a nested list stays tight, as Pandoc writes it."
    md = page_markdown('<main><p>Wow!<a href="x.html">link</a> and &amp;copy;</p><ol><li>first<ul><li>inner</li></ul></li><li>second</li></ol></main>')
    assert "Wow\\![link](x.llms.md) and \\&copy;" in md
    assert "1. first\n   - inner\n2. second" in md


# ---------------------------------------------------------------- what the second review found


def test_rebuild_warns_as_the_html_build(tmp_path: Path) -> None:
    "A page with content for agents that links to a file the build makes, such as a feed, warns on a rebuild as it does with the option off."
    page = '---\ntitle: Posts\nlisting: {contents: posts, feed: true}\n---\n\n[feed](blog.xml)\n\n::: {.content-visible when-format="llms-txt"}\nAgents.\n:::\n'
    files = {"index.qmd": "# Home\n", "blog.qmd": page, "posts/a.qmd": "---\ntitle: A\ndate: 2026-01-01\n---\n\nA.\n"}
    warnings = []
    for on in (True, False):
        root = tmp_path / str(on)
        cfg = "project: {type: website}\nwebsite:\n  title: S\n  site-url: https://x.org/\n" + ("  llms-txt: true\n" if on else "")
        write(root, {"_quarto.yml": cfg, **files})
        build(root, quiet=True)
        warnings.append(build(root, quiet=True).warnings)
    assert warnings[0] == warnings[1] == []


def test_bang_before_a_link() -> None:
    "A `!` before a link is escaped after a literal backslash and across an empty element, so the link is not read as a picture."
    md = page_markdown('<main><p>a\\!<a href="x.html">l</a></p><p>wow!<span></span><a href="x.html">m</a></p></main>')
    assert "a\\\\\\![l](x.llms.md)" in md
    assert "wow\\![m](x.llms.md)" in md


def test_a_div_called_fn1_is_not_a_note() -> None:
    "Only a note in the margin is moved to the footnotes, and only its own number is dropped."
    md = page_markdown('<main><div id="fn1"><p>E = mc<sup>2</sup> is a user div.</p></div></main>')
    assert md == "E = mc2 is a user div.\n"


def test_table_after_text_in_a_list() -> None:
    "A table after text in a tight list item gets a blank line before it, so that a reader takes it for a table."
    md = page_markdown("<main><ul><li>text<table><tr><th>a</th></tr><tr><td>1</td></tr></table></li></ul></main>")
    assert md == "- text\n\n  | a |\n  |---|\n  | 1 |\n"


def test_a_page_called_x_llms_qmd(tmp_path: Path) -> None:
    "With `foo.qmd` and `foo.llms.qmd`, a link to `foo.llms.md` goes to the page `foo.llms.html`, with the option on or off."
    more = {"foo.qmd": "# Foo\n", "foo.llms.qmd": "# Foo notes\n", "links.qmd": "---\ntitle: L\n---\n\n[notes](foo.llms.md)\n"}
    for cfg in (CONFIG, CONFIG.replace("  llms-txt: true\n", "")):
        out = site(tmp_path, cfg, more)
        assert 'href="foo.llms.html"' in (out / "links.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------- what the third review found


def test_margin_note_numbers_in_any_block(tmp_path: Path) -> None:
    "A note in the margin loses its number wherever its first text is: after code, in a quote, a list or a table."
    page = """---
title: M
reference-location: margin
---

One[^1] two[^2] three[^3] four[^4].

[^1]:
    ```
    code
    ```

    After the code.

[^2]: > A quote.

[^3]: 1. first

[^4]:
    | h |
    |---|
    | x |
"""
    md = (site(tmp_path, more={"m.qmd": page}) / "m.llms.md").read_text(encoding="utf-8")
    notes = md.split("## Footnotes", 1)[1]
    assert "After the code." in notes and "> A quote." in notes and "1. first" in notes and "| h |" in notes
    for n in "1234":
        assert f" {n} " not in notes.replace(f"[^{n}]: ", ""), notes


def test_rule_after_text_in_a_list() -> None:
    "Only a nested list follows text on the next line in a tight item; a rule gets a blank line, so it is not read as a heading."
    md = page_markdown("<main><ul><li>text<hr></li><li>two</li></ul></main>")
    assert md.startswith("- text\n\n  ---")


# ---------------------------------------------------------------- what the fourth review found


def test_nested_lists_that_cannot_break_text() -> None:
    "A nested list that starts at a number other than 1, or an empty one, gets a blank line, so it stays a list."
    from markdown_it import MarkdownIt

    md = page_markdown('<main><ol start="3"><li>three<ol start="7"><li>seven</li><li>eight</li></ol></li></ol></main>')
    toks = [t.type for t in MarkdownIt("commonmark").parse(md)]
    assert toks.count("ordered_list_open") == 2, md
    assert "- a\n  -" not in page_markdown("<main><ul><li>a<ul><li></li></ul></li></ul></main>")


def test_text_that_starts_with_a_number() -> None:
    "Text that starts like a numbered item has its dot or bracket escaped, as Pandoc writes it, not a backslash a reader sees."
    md = page_markdown("<main><p>6. not a list</p><p>1) nor this</p></main>")
    assert md == "6\\. not a list\n\n1\\) nor this\n"


def test_a_raw_block_with_the_notes_number() -> None:
    "A note's own `<sup>N</sup>` in the user's raw HTML stays; only smalldocs' number, with its no-break space, is dropped."
    note = '<div class="column-margin"><div id="fn4"><div><sup>4</sup> raw block</div><p><sup>4</sup>\u00a0Para.</p></div></div>'
    md = page_markdown(f"<main><p>Text.</p>{note}</main>")
    assert "[^4]: 4 raw block\n\n      Para." in md, md
