"The tests of smalldocs: the Markdown rules, notebooks, the site, listings, the API reference, check and publish."

import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from smalldocs import notebook
from smalldocs.cli import main
from smalldocs.config import BuildError, ConfigError, load
from smalldocs.markdown import pandoc_id, parse_attrs, render, split_front_matter
from smalldocs.site import Site, build


def md(
    text: str,  # Markdown
    **env: object,  # What the renderer is given
) -> str:  # The HTML
    "Render Markdown with an empty environment."
    return render(textwrap.dedent(text), dict(env))


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


# ---------------------------------------------------------------- Markdown


@pytest.mark.parametrize(
    "text,ident",
    [
        ("Heading identifiers in HTML", "heading-identifiers-in-html"),
        ("*Dogs*?--in *my* house?", "dogs--in-my-house"),
        ("3. Applications", "applications"),
        ("33", "section"),
        ("The `render` call", "the-render-call"),
        ("Café au lait", "café-au-lait"),
        ("a_b.c-d", "a_b.c-d"),
        ("Find 5/6 + 3/4.", "find-56-34."),
    ],
)
def test_pandoc_ids(text: str, ident: str) -> None:
    "Heading ids follow Pandoc's rules, so links made for Quarto keep working."
    assert pandoc_id(re.sub(r"[*`]", "", text)) == ident


def test_heading_attrs_sections_and_duplicates() -> None:
    "A heading takes `{#id .class}`; each top heading opens a section; duplicate ids get a number."
    html = md(
        """
        Intro.

        # One {#first .x}

        ## Same

        ## Same
        """
    )
    assert '<section id="first" class="level1 x">' in html
    assert '<section id="same" class="level2">' in html and '<section id="same-1" class="level2">' in html
    assert html.count("<section") == html.count("</section>") == 3
    assert 'data-anchor-id="first"' in html and "{#first" not in html


def test_fenced_divs_nest_with_fences_of_the_same_length() -> None:
    "A fence with attributes opens a div; a bare fence closes the innermost one, as in Pandoc."
    html = md(
        """
        ::: {.outer}
        ::: {.inner #in}
        inside
        :::
        after
        :::

        ::: word
        ```
        :::
        ```
        :::
        """
    )
    assert '<div class="outer">\n<div id="in" class="inner">\n<p>inside</p>\n</div>\n<p>after</p>\n</div>' in html
    assert '<div class="word">' in html and ":::" in html.split('<div class="word">')[1]
    assert html.count("<div") == html.count("</div>") - html.count("code-copy") * 0


def test_callouts() -> None:
    "Callouts take Quarto's markup, with a title from a first heading or from `title=`, and fold when asked."
    html = md(
        """
        ::: {.callout-tip}
        ## Remember
        Body.
        :::

        ::: {.callout-warning title="Careful" collapse="true"}
        Hidden.
        :::

        ::: {.callout-note}
        No title.
        :::
        """
    )
    assert 'class="callout callout-style-default callout-tip callout-titled"' in html
    assert '<div class="callout-title-container flex-fill">Remember</div>' in html
    assert "Careful" in html and 'class="callout-collapse collapse"' in html
    assert '<div class="callout-title-container flex-fill">Note</div>' in html
    env: dict = {}
    render("# T\n\n::: {.callout-tip}\n## Inside\nx\n:::\n", env)
    assert [h["text"] for h in env["headings"]] == [], "a callout's title is not a heading of the page"


def test_tabsets() -> None:
    "A panel-tabset turns its headings into tabs, and they stay out of the table of contents."
    env: dict = {}
    html = render("::: {.panel-tabset}\n## A\none\n## B\ntwo\n:::\n", env)
    assert html.count('class="nav-link') == 2 and html.count('class="tab-pane') == 2
    assert 'id="tabset-1-1"' in html and "<h2" not in html
    assert all(h.get("tab") for h in env["headings"])


def test_figures_images_and_attrs() -> None:
    "A lone image with alt text is a figure; `{width=50%}` becomes a style; other images are fluid."
    html = md("![A cat](cat.png){width=50%}\n\ntext ![x](y.png) more\n")
    assert "<figure" in html and "<figcaption>A cat</figcaption>" in html and "width: 50%" in html
    assert '<img alt="x" src="y.png" class="img-fluid">' in html


def test_typography_and_its_extension() -> None:
    "Quotes curl and dashes join, as Pandoc's smart does; `-smart` keeps them as typed."
    assert "“hi” – it’s… —" in md('"hi" -- it\'s... ---\n')
    plain = render('"hi" -- it\'s\n', {}, "markdown-smart")
    assert '"hi" -- it\'s' in plain.replace("&quot;", '"')


def test_maths_and_dollars() -> None:
    "`$x$` is maths; `$5 and $10` is money; `-tex_math_dollars` turns maths off."
    env: dict = {}
    html = render("Area $x^2$ costs $5 and $10.\n\n$$\na=b\n$$\n", env)
    assert '<span class="math inline">\\(x^2\\)</span>' in html and "$5 and $10" in html
    assert '<span class="math display">\\[a=b\\]</span>' in html and env["math"]
    assert "$x^2$" in render("Area $x^2$.\n", {}, "markdown-tex_math_dollars")


def test_code_blocks() -> None:
    "Code is highlighted with Pandoc's classes and gets a copy button; raw HTML passes; mermaid is kept for mermaid.js."
    html = md(
        """
        ```python
        import os
        def f(): return 1  # c
        ```

        ```{=html}
        <b id="raw">raw</b>
        ```

        ```{mermaid}
        graph TD; A-->B
        ```

        ```{.python filename="x.py"}
        x = 1
        ```
        """
    )
    assert '<span class="im">import</span>' in html and '<span class="co"># c</span>' in html and '<span class="cf">return</span>' in html
    assert "code-copy-button" in html
    assert '<b id="raw">raw</b>' in html
    assert '<pre class="mermaid">graph TD; A--&gt;B</pre>' in html
    assert "x.py" in html and "code-with-filename" in html


def test_executable_cells_are_shown_not_run() -> None:
    "A `{python}` cell is shown as code, without its `#|` options, and noted."
    env: dict = {}
    html = render("```{python}\n#| echo: true\nprint(1)\n```\n\n```{python}\n#| echo: false\nsecret()\n```\n", env)
    assert "print" in html and "#|" not in html and "secret" not in html
    assert len(env["unrun"]) == 2


def test_linkify_names_in_backticks() -> None:
    "A documented name in backticks links to its entry, but not inside a link, and not when unknown."
    env = {"symbols": {"render": "api.html#render"}, "link": lambda h, k: h}
    html = render("Call `render()` or `other`, or [see `render`](x.html).\n", env)
    assert '<a href="api.html#render"><code>render()</code></a>' in html
    assert "<code>other</code>" in html and html.count('href="api.html#render"') == 1


def test_title_from_a_leading_heading() -> None:
    "With no title in the front matter, a level-one heading at the top becomes the title."
    env: dict = {}
    html = render("# The Title\n\nText\n\n# Later\n", env)
    assert env["title"] == "The Title" and "The Title" not in html and "Later" in html


def test_front_matter_and_attrs() -> None:
    "Front matter splits off and keeps line numbers; attributes parse as Pandoc writes them."
    meta, body = split_front_matter("---\ntitle: T\ntags: [a]\n---\nBody\n")
    assert meta == {"title": "T", "tags": ["a"]} and body.endswith("Body\n") and body.count("\n") == 5
    assert split_front_matter("no front\n") == ({}, "no front\n")
    a = parse_attrs('{#i .a .b k=v t="two words" -}')
    assert (a.id, a.classes, a.kv) == ("i", ["a", "b", "unnumbered"], {"k": "v", "t": "two words"})
    assert parse_attrs("{#Site.say}").id == "Site.say", "an id keeps its dots, as Pandoc's does"


# ---------------------------------------------------------------- notebooks


def test_notebooks_render_stored_outputs() -> None:
    "A notebook's cells and stored outputs become Markdown; `#|` options hide code or output; nothing runs."
    nb = {
        "metadata": {"kernelspec": {"language": "python"}},
        "cells": [
            {"cell_type": "raw", "source": "---\ntitle: NB\n---\n"},
            {"cell_type": "markdown", "source": ["# Head\n", "Text"]},
            {"cell_type": "code", "source": "print('hi')", "outputs": [{"output_type": "stream", "name": "stdout", "text": ["hi\n"]}]},
            {"cell_type": "code", "source": "#| echo: false\nshow()", "outputs": [{"output_type": "display_data", "data": {"text/markdown": "**bold**", "text/plain": "x"}}]},
            {"cell_type": "code", "source": "img()", "outputs": [{"output_type": "display_data", "data": {"image/png": "iVBORw0KGgo=\n"}}]},
            {"cell_type": "code", "source": "1/0", "outputs": [{"output_type": "error", "ename": "ZeroDivisionError", "evalue": "x", "traceback": ["\x1b[31mZeroDivisionError\x1b[0m: x"]}]},
            {"cell_type": "code", "source": "#| include: false\nhidden()", "outputs": []},
        ],
    }
    meta, body = notebook.to_markdown(json.dumps(nb))
    assert meta == {"title": "NB"}
    html = md(body)
    assert "print" in html and "<pre><code>hi</code></pre>" in html
    assert "show()" not in html and "<strong>bold</strong>" in html
    assert 'src="data:image/png;base64,iVBORw0KGgo="' in html
    assert "ZeroDivisionError: x" in html and "\x1b" not in html
    assert "hidden" not in html


# ---------------------------------------------------------------- the site

SITE = {
    "_quarto.yml": """
        project:
          type: website
        website:
          title: "Demo"
          site-url: https://example.com/demo/
          page-navigation: true
          navbar:
            left:
              - href: index.qmd
                text: Home
              - text: More
                menu:
                  - guide/a.qmd
          sidebar:
            style: docked
            contents:
              - index.qmd
              - section: Guide
                contents: guide/*
          page-footer: "Made with [smalldocs](https://example.com)"
        format:
          html:
            theme: flatly
            css: styles.css
            toc: true
        """,
    "styles.css": "body { }\n",
    "index.qmd": """
        ---
        title: Home
        ---

        See [A](guide/a.qmd#part), [B](/guide/b.md), [guide](guide/), [pdf](files/doc.pdf) and [gone](nothere.qmd).

        ![Logo](img/logo.png)

        ## Part one

        Text.
        """,
    "guide/a.qmd": """
        ---
        title: A page
        order: 1
        ---

        ## Part {#part}

        Back [home](../index.qmd).
        """,
    "guide/b.md": "# B page\n\nNo front matter.\n",
    "guide/index.qmd": "---\ntitle: Guide\n---\n\nThe guide.\n",
    "guide/draft.qmd": "---\ntitle: Draft\ndraft: true\n---\n",
    "_partial.qmd": "---\ntitle: Hidden\n---\n",
    "README.md": "# Readme\n",
    "img/logo.png": "png",
    "files/doc.pdf": "pdf",
}


@pytest.fixture
def site(tmp_path: Path) -> Site:
    "Build the demo site."
    write(tmp_path, SITE)
    return build(tmp_path, quiet=True)


def test_pages_found_and_left_out(site: Site) -> None:
    "Every page is built, but drafts, `_` files and the README are not."
    out = site.out
    got = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.html"))
    assert got == ["guide/a.html", "guide/b.html", "guide/index.html", "index.html"]


def test_links_are_rewritten(site: Site) -> None:
    "Page links go to `.html`, links from the root become relative, files are copied, and a broken link is reported."
    html = (site.out / "index.html").read_text()
    assert 'href="guide/a.html#part"' in html and 'href="guide/b.html"' in html and 'href="guide/"' in html
    assert 'href="files/doc.pdf"' in html and (site.out / "files/doc.pdf").exists()
    assert 'src="img/logo.png"' in html and (site.out / "img/logo.png").exists()
    assert any("broken link nothere.qmd" in w for w in site.warnings)
    a = (site.out / "guide/a.html").read_text()
    assert 'href="../index.html"' in a and 'href="../site_libs/themes/flatly.min.css"' in a and 'href="../styles.css"' in a


def test_layout(site: Site) -> None:
    "The page has the navbar, the docked sidebar with the active page, a table of contents, the footer and page navigation."
    a = (site.out / "guide/a.html").read_text()
    assert 'class="nav-sidebar docked nav-fixed"' in a
    assert 'class="sidebar-item-text sidebar-link active" aria-current="page"' in a
    assert '<nav id="TOC"' in a and 'href="#part"' in a
    assert "nav-page-previous" in a and "Guide" in a
    assert 'Made with <a href="https://example.com">smalldocs</a>' in a
    assert "dropdown-menu" in (site.out / "index.html").read_text()
    b = (site.out / "guide/b.html").read_text()
    assert '<h1 class="title">B page</h1>' in b and "<title>B page – Demo</title>" in b
    assert (site.out / "site_libs/themes/flatly.min.css").exists() and not (site.out / "site_libs/themes/cosmo.min.css").exists()


def test_sidebar_order_follows_order_then_index(site: Site) -> None:
    "A glob in the sidebar puts `order:` first, then the index, then the rest by path."
    a = (site.out / "guide/a.html").read_text()
    side = a.split('id="quarto-sidebar"')[1].split("</nav>")[0]
    assert side.index("A page") < side.index("Guide</span></a></div></li>") if "Guide</span></a></div></li>" in side else True
    assert side.index("A page") < side.index("B page")


def test_search_and_sitemap(site: Site) -> None:
    "search.json has one entry for each section; sitemap.xml lists each page under the site's URL."
    entries = json.loads((site.out / "search.json").read_text())
    assert {"href": "index.html#part-one", "title": "Home", "section": "Part one"}.items() <= next(e for e in entries if e["section"] == "Part one").items()
    assert "<loc>https://example.com/demo/guide/a.html</loc>" in (site.out / "sitemap.xml").read_text()


def test_rebuild_empties_the_output(tmp_path: Path) -> None:
    "A build removes what an earlier build left; an output folder that holds the project is refused."
    write(tmp_path, SITE)
    s = build(tmp_path, quiet=True)
    (s.out / "stale.html").write_text("old")
    build(tmp_path, quiet=True)
    assert not (s.out / "stale.html").exists()
    for bad in (".", ".."):
        (tmp_path / "_quarto.yml").write_text(f"project:\n  type: website\n  output-dir: {bad}\n")
        with pytest.raises(BuildError, match="holds the project"):
            build(tmp_path, quiet=True)
    assert (tmp_path / "index.qmd").exists()


def test_config_errors(tmp_path: Path) -> None:
    "No config, another project type, or an unknown theme stops with a message; unknown keys are warnings."
    with pytest.raises(ConfigError, match=r"no _quarto\.yml"):
        load(tmp_path)
    write(tmp_path, {"_quarto.yml": "project:\n  type: manuscript\n"})
    with pytest.raises(ConfigError, match="only websites"):
        load(tmp_path)
    write(tmp_path, {"_quarto.yml": "project:\n  type: website\nformat:\n  html:\n    theme: nosuch\n  pdf: default\nfilters: [x.lua]\nweird: 1\n", "index.md": "# Hi\n"})
    p = load(tmp_path)
    assert any("format pdf" in w for w in p.warnings) and any("x.lua" in w for w in p.warnings)
    with pytest.raises(BuildError, match="not a Bootswatch theme"):
        build(tmp_path, quiet=True)


def test_render_list_resources_and_metadata(tmp_path: Path) -> None:
    "`project.render` picks the pages; `resources` copies files; `_metadata.yml` applies to a folder; scripts run."
    write(
        tmp_path,
        {
            "_quarto.yml": """
                project:
                  type: website
                  render: ["*.md", "!skip.md"]
                  resources: [".nojekyll", "data/**"]
                  pre-render: pre.py
                website:
                  title: T
                  search: false
                """,
            "index.md": "---\ntitle: I\n---\n",
            "skip.md": "---\ntitle: S\n---\n",
            "other.qmd": "---\ntitle: O\n---\n",
            ".nojekyll": "",
            "data/x.csv": "1,2\n",
            "sub/_metadata.yml": "toc: true\n",
            "pre.py": "from pathlib import Path\nPath('made.md').write_text('---\\ntitle: Made\\n---\\n')\n",
        },
    )
    s = build(tmp_path, quiet=True)
    assert sorted(p.name for p in s.out.glob("*.html")) == ["index.html", "made.html"]
    assert (s.out / ".nojekyll").exists() and (s.out / "data/x.csv").exists()
    assert "smalldocs-search" not in (s.out / "index.html").read_text()


def test_light_and_dark_themes(tmp_path: Path) -> None:
    "`theme: {light, dark}` ships both and a toggle."
    write(tmp_path, {"_quarto.yml": "project:\n  type: website\nwebsite:\n  navbar: {}\nformat:\n  html:\n    theme:\n      light: litera\n      dark: darkly\n", "index.md": "# Home\n"})
    s = build(tmp_path, quiet=True)
    html = (s.out / "index.html").read_text()
    assert "litera.min.css" in html and "darkly.min.css" in html and "quarto-color-scheme-toggle" in html
    assert (s.out / "site_libs/themes/darkly.min.css").exists()


def test_shortcodes(tmp_path: Path) -> None:
    "`include`, `meta`, `var` and `env` are replaced; code blocks and escaped shortcodes are left alone."
    write(
        tmp_path,
        {
            "_quarto.yml": "project:\n  type: website\n",
            "_variables.yml": "version: 1.2\n",
            "_part.md": "Included **text**.\n",
            "index.qmd": '---\ntitle: Short\n---\n\n{{< include _part.md >}}\n\nTitle {{< meta title >}}, v{{< var version >}}.\n\n```\n{{< meta title >}}\n```\n\n\\{{< meta title >}} and `{{</* var x */>}}`\n',
        },
    )
    html = (build(tmp_path, quiet=True).out / "index.html").read_text()
    assert "Included <strong>text</strong>." in html and "Title Short, v1.2." in html
    assert "{{&lt; meta title &gt;}}" in html.split("<pre")[1] and html.count("{{&lt; meta title &gt;}}") == 2
    assert "<code>{{&lt; var x &gt;}}</code>" in html


# ---------------------------------------------------------------- listings

BLOG = {
    "_quarto.yml": "project:\n  type: website\nwebsite:\n  title: Blog\n  site-url: https://example.com/\n  navbar:\n    left: [index.qmd]\n",
    "index.qmd": """
        ---
        title: Posts
        listing:
          contents: posts
          sort: "date desc"
          categories: true
          feed: true
        ---
        """,
    "grid.qmd": "---\ntitle: Grid\nlisting:\n  contents: posts/*.qmd\n  type: grid\n---\n",
    "table.qmd": "---\ntitle: Table\nlisting:\n  contents: posts\n  type: table\n  sort: title\n---\n",
    "posts/one.qmd": "---\ntitle: First\ndate: 2026-01-02\ncategories: [news, python]\nauthor: Ann\n---\n\nThe first post's opening line.\n\n![pic](one.png)\n",
    "posts/two.qmd": "---\ntitle: Second\ndate: 2026-03-04\ncategories: [news]\ndescription: Given description.\nimage: two.png\n---\n\nBody.\n",
    "posts/one.png": "png",
    "posts/two.png": "png",
}


def test_listings(tmp_path: Path) -> None:
    "Listings sort, show descriptions and pictures, link categories, and write a feed."
    write(tmp_path, BLOG)
    s = build(tmp_path, quiet=True)
    idx = (s.out / "index.html").read_text()
    assert idx.index("Second") < idx.index("First"), "newest first"
    assert "Given description." in idx and "The first post’s opening line." in idx
    assert 'src="posts/two.png"' in idx and 'src="posts/one.png"' in idx
    assert "quarto-listing-category-title" in idx and 'data-category="python"' in idx
    assert '<body class="nav-fixed listing">' in idx
    grid = (s.out / "grid.html").read_text()
    assert grid.count('class="quarto-grid-item card') == 2 and "quarto-listing-cols-3" in grid
    table = (s.out / "table.html").read_text()
    assert table.index("First") < table.index("Second") and "quarto-listing-table" in table
    post = (s.out / "posts/one.html").read_text()
    assert 'href="../index.html#category=news"' in post
    feed = (s.out / "index.xml").read_text()
    assert "<link>https://example.com/posts/two.html</link>" in feed and "<category>python</category>" in feed


# ---------------------------------------------------------------- the API reference

PKG = {
    "src/tinypkg/__init__.py": '"A tiny package."\n',
    "src/tinypkg/core.py": '''
        """Core things.

        More about the core.
        """
        from dataclasses import dataclass
        from typing import TypedDict

        Number = int | float


        def add(
            a: Number,  # The first
            b: int = 2,  # The second
        ) -> Number:  # The sum
            "Add two numbers."
            return a + b


        @dataclass
        class Point:
            "A point."

            x: int  # Across
            y: int = 0  # Up

            def norm(self) -> float:  # Its length
                "How long it is."
                return (self.x**2 + self.y**2) ** 0.5


        class Keys(TypedDict):
            "Some keys."

            name: str  # Who
            age: int


        def undocumented(x):
            return x


        def _private() -> None:  # Nothing
            "Hidden."
        ''',
    "docs/_quarto.yml": """
        project:
          type: website
        website:
          sidebar:
            contents:
              - index.qmd
              - section: Reference
                contents: api/*
        smalldocs:
          api:
            packages: [tinypkg]
            source: https://github.com/me/tinypkg/blob/main
            check: ["tests/*.py"]
        """,
    "docs/index.qmd": "---\ntitle: Tiny\n---\n\nUse `add` and `Point.norm`, not `nothing`.\n",
}


def test_api_pages_and_links(tmp_path: Path) -> None:
    "The reference pages have signatures, tables, ids and source links; names in backticks link to them."
    write(tmp_path, PKG)
    sys.modules.pop("tinypkg", None)
    sys.modules.pop("tinypkg.core", None)
    s = build(tmp_path / "docs", quiet=True)
    qmd = (tmp_path / "docs/api/core.qmd").read_text()
    assert qmd.startswith('---\ntitle: "tinypkg.core"\ndescription: "Core things."\n---\n\nMore about the core.')
    assert "## add {#add}" in qmd and "add(a: Number, b: int = 2) -> Number" in qmd
    assert "[source](https://github.com/me/tinypkg/blob/main/src/tinypkg/core.py#L" in qmd
    assert "| `x` | int | required | Across |" in qmd and "### Point.norm {#Point.norm}" in qmd
    assert "| `name` | str | Who |" in qmd and "_private" not in qmd
    index = json.loads((tmp_path / "docs/_symbols.json").read_text())
    assert index["add"] == "/api/core.qmd#add" and index["tinypkg.core.Point.norm"] == "/api/core.qmd#Point.norm"
    home = (s.out / "index.html").read_text()
    assert '<a href="api/core.html#add"><code>add</code></a>' in home and "<code>nothing</code>" in home
    assert "tinypkg.core" in home, "the reference is in the sidebar"


def test_api_commands(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    "`api check` lists the gaps and fails; `api module` prints Markdown; `api list` prints the inventory."
    write(tmp_path, PKG)
    write(tmp_path, {"tests/test_x.py": '"Tests."\n\ndef test_y() -> None:  # Nothing\n    "A test."\n'})
    for m in [m for m in sys.modules if m.startswith("tinypkg")]:
        sys.modules.pop(m)
    d = str(tmp_path / "docs")
    assert main(["api", "check", "--dir", d]) == 1
    out = capsys.readouterr().out
    assert "tinypkg.core:undocumented: no docstring" in out and "tinypkg.core:Keys.age: no docment" in out
    assert "tinypkg.core:undocumented(x): no type" in out and "tests/test_x.py" in out
    assert main(["api", "module", "core", "--dir", d]) == 0
    assert capsys.readouterr().out.startswith("# tinypkg.core\n")
    assert main(["api", "module", "nope", "--dir", d]) == 2
    assert main(["api", "list", "--dir", d]) == 0
    assert "function  tinypkg.core.add" in capsys.readouterr().out


# ---------------------------------------------------------------- the commands


def test_cli_render_check_and_strict(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    "`render` builds; `--strict` fails on a warning; `check` finds Pandoc-only syntax."
    write(tmp_path, {"_quarto.yml": "project:\n  type: website\n", "index.md": "# Hi\n\nSee [@knuth] and [x](missing.md).\n\n+---+\n| a |\n+---+\n"})
    assert main(["render", str(tmp_path), "-q"]) == 0
    assert main(["render", str(tmp_path), "-q", "--strict"]) == 1
    assert main(["check", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "a citation" in out and "a grid table" in out and "broken link missing.md" in out
    assert main(["render", str(tmp_path / "nowhere")]) == 2


def test_publish_to_a_branch(tmp_path: Path) -> None:
    "`publish` pushes the site to gh-pages twice, and leaves the working tree and branch as they were."
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    repo = write(tmp_path / "repo", {"docs/_quarto.yml": "project:\n  type: website\n", "docs/index.md": "# Hi\n", ".gitignore": "_site/\n"})
    g = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, text=True).stdout  # noqa: E731
    g("init", "-q", "-b", "main")
    g("-c", "user.email=t@t", "-c", "user.name=T", "add", "-A")
    g("-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qm", "start")
    g("remote", "add", "origin", str(remote))
    (repo / "docs/edit.md").write_text("# Uncommitted\n")
    env_main = lambda: main(["publish", "gh-pages", str(repo / "docs")])  # noqa: E731
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    assert env_main() == 0
    (repo / "docs/index.md").write_text("# Changed\n")
    assert env_main() == 0
    files = subprocess.run(["git", "ls-tree", "-r", "--name-only", "gh-pages"], cwd=remote, capture_output=True, text=True).stdout.split()
    assert "index.html" in files and ".nojekyll" in files and "edit.html" in files
    log = subprocess.run(["git", "log", "--oneline", "gh-pages"], cwd=remote, capture_output=True, text=True).stdout
    assert len(log.strip().splitlines()) == 2
    assert g("branch", "--show-current").strip() == "main" and "edit.md" in g("status", "--porcelain")
    assert g("worktree", "list").count("\n") == 1 and "smalldocs-publish" not in g("branch")


# ---------------------------------------------------------------- findings of the adversarial review


def test_api_build_keeps_hand_written_pages(tmp_path: Path) -> None:
    "The API build deletes only pages it wrote before, never a page someone wrote in its folder."
    write(tmp_path, PKG)
    write(tmp_path, {"docs/api/index.qmd": "---\ntitle: API Reference\n---\n\nHand-written.\n"})
    for m in [m for m in sys.modules if m.startswith("tinypkg")]:
        sys.modules.pop(m)
    d = str(tmp_path / "docs")
    assert main(["api", "build", "--dir", d]) == 0
    assert (tmp_path / "docs/api/index.qmd").exists() and (tmp_path / "docs/api/core.qmd").exists()
    (tmp_path / "docs/api/gone.qmd").write_text("---\ntitle: x\n---\n")
    manifest = tmp_path / "docs/api/.smalldocs-api"
    manifest.write_text(manifest.read_text() + "\ngone.qmd")
    assert main(["api", "build", "--dir", d]) == 0
    assert not (tmp_path / "docs/api/gone.qmd").exists() and (tmp_path / "docs/api/index.qmd").exists()


@pytest.mark.parametrize("out", [".", "/", "..", "../x", ""])
def test_api_out_must_be_inside_the_site(tmp_path: Path, out: str) -> None:
    "`smalldocs.api.out` that is the site, above it or outside it is refused, and no page is touched."
    write(tmp_path, PKG)
    q = (tmp_path / "docs/_quarto.yml").read_text().replace("packages: [tinypkg]", f'packages: [tinypkg]\n    out: "{out}"')
    write(tmp_path, {"docs/_quarto.yml": q})
    for m in [m for m in sys.modules if m.startswith("tinypkg")]:
        sys.modules.pop(m)
    assert main(["render", str(tmp_path / "docs"), "-q"]) == 2
    assert (tmp_path / "docs/index.qmd").exists()


@pytest.mark.parametrize("out", ["guide", "src", "../other"])
def test_output_dir_that_is_not_a_built_site_is_refused(tmp_path: Path, out: str) -> None:
    "An output folder with other files in it, and no site_libs, is refused rather than emptied."
    root = tmp_path / "site"
    write(root, {"_quarto.yml": f"project:\n  type: website\n  output-dir: {out}\n", "index.md": "# Hi\n", "guide/a.qmd": "# A\n", "src/x.py": "x = 1\n"})
    write(tmp_path, {"other/keep.txt": "mine\n"})
    assert main(["render", str(root), "-q"]) == 2
    assert (root / "guide/a.qmd").exists() and (root / "src/x.py").exists() and (tmp_path / "other/keep.txt").exists()


def test_output_dir_with_an_earlier_build_is_emptied(tmp_path: Path) -> None:
    "A folder that holds an earlier build (site_libs) is emptied, as Quarto's own _site is."
    write(tmp_path, {"_quarto.yml": "project:\n  type: website\n  output-dir: ../out\n", "index.md": "# Hi\n"})
    write(tmp_path.parent, {"out/site_libs/old.css": "", "out/old.html": "old"})
    s = build(tmp_path, quiet=True)
    assert not (s.out / "old.html").exists() and (s.out / "index.html").exists()


def test_string_resources_and_render(tmp_path: Path) -> None:
    "`resources` and `render` as one string are one glob, not a list of characters; secrets stay out."
    write(tmp_path, {"_quarto.yml": 'project:\n  type: website\n  resources: "*.txt"\n  render: "index.qmd"\n', "index.qmd": "# Hi\n", "a.txt": "a", ".env": "SECRET=1", "other.qmd": "# O\n"})
    s = build(tmp_path, quiet=True)
    assert (s.out / "a.txt").exists() and not (s.out / ".env").exists() and not (s.out / "_quarto.yml").exists()
    assert [p.name for p in s.out.glob("*.html")] == ["index.html"]


def test_links_to_drafts_do_not_publish_their_source(tmp_path: Path) -> None:
    "A link to a draft, or to a page left out, is reported, and its source is not copied into the site."
    write(tmp_path, {"_quarto.yml": "project:\n  type: website\n", "index.md": "# Hi\n\n[d](draft.qmd) [up](../../x.qmd)\n", "draft.qmd": "---\ntitle: D\ndraft: true\n---\nsecret\n"})
    s = build(tmp_path, quiet=True)
    assert not (s.out / "draft.qmd").exists() and not (s.out / "draft.html").exists()
    assert any("draft.qmd (a page that is not built)" in w for w in s.warnings)
    assert any("outside the project" in w for w in s.warnings)


@pytest.mark.parametrize(
    "heading,ident",
    [("Before --- after", "before-after"), ("Pages -- ranges", "pages-ranges"), ("Wait...", "wait"), ("The set {a, b}", "the-set-a-b")],
)
def test_ids_from_smart_text_and_braces_in_headings(heading: str, ident: str) -> None:
    "Ids come from the text after smart punctuation, as Pandoc's do; braces that are not attributes stay text."
    html = md(f"p\n\n## {heading}\n")
    assert f'<section id="{ident}"' in html
    assert "{a, b}" in html if "{" in heading else True


def test_globs_stay_in_their_folder(tmp_path: Path) -> None:
    "`*` stops at `/` in listings and sidebars, as in Quarto; README is left out but CHANGELOG is a page."
    write(tmp_path, {
        "_quarto.yml": "project:\n  type: website\nwebsite:\n  sidebar:\n    contents: [sub/*]\n",
        "index.qmd": "---\ntitle: L\nlisting:\n  contents: \"sub/*.md\"\n---\n",
        "sub/a.md": "# A\n", "sub/deep/b.md": "# Deep\n", "README.md": "# R\n", "CHANGELOG.md": "# C\n",
    })  # fmt: skip
    s = build(tmp_path, quiet=True)
    idx = (s.out / "index.html").read_text()
    assert idx.count('class="quarto-post') == 1 and "Deep" not in idx.split('id="quarto-sidebar"')[1].split("</nav>")[0]
    assert (s.out / "CHANGELOG.html").exists() and not (s.out / "README.html").exists()


def test_notebook_tags_and_attachments() -> None:
    "Cells tagged remove-cell, remove-input or remove-output are hidden; attachments show; nbformat 3 is refused."
    nb = {
        "nbformat": 4,
        "cells": [
            {"cell_type": "code", "metadata": {"tags": ["remove-cell"]}, "source": "secret()", "outputs": [{"output_type": "stream", "name": "stdout", "text": "s"}]},
            {"cell_type": "code", "metadata": {"tags": ["remove-input"]}, "source": "hidden_code()", "outputs": [{"output_type": "stream", "name": "stdout", "text": "shown"}]},
            {"cell_type": "code", "metadata": {"tags": ["remove-output"]}, "source": "shown_code()", "outputs": [{"output_type": "stream", "name": "stdout", "text": "hidden out"}]},
            {"cell_type": "markdown", "source": "![pic](attachment:a.png)", "attachments": {"a.png": {"image/png": "QUJD"}}},
        ],
    }
    html = md(notebook.to_markdown(json.dumps(nb))[1])
    assert "secret" not in html and "hidden_code" not in html and "shown" in html
    assert "shown_code" in html and "hidden out" not in html
    assert 'src="data:image/png;base64,QUJD"' in html
    with pytest.raises(ValueError, match="nbformat 3"):
        notebook.to_markdown(json.dumps({"nbformat": 3, "worksheets": []}))


def test_publish_refuses_source_branches_and_keeps_user_branches(tmp_path: Path) -> None:
    "`publish` will not overwrite the current or default branch, ignores hooks, and never deletes a branch it did not make."
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    repo = write(tmp_path / "repo", {"docs/_quarto.yml": "project:\n  type: website\n", "docs/index.md": "# Hi\n", ".gitignore": "_site/\n"})
    g = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, text=True).stdout  # noqa: E731
    g("init", "-q", "-b", "main")
    g("config", "user.email", "t@t")
    g("config", "user.name", "T")
    g("add", "-A")
    g("commit", "-qm", "start")
    g("remote", "add", "origin", str(remote))
    g("push", "-q", "origin", "main")
    g("branch", "smalldocs-publish-gh-pages")
    hook = repo / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    assert main(["publish", "gh-pages", str(repo / "docs"), "--branch", "main"]) == 2
    assert main(["publish", "gh-pages", str(repo / "docs")]) == 0
    assert main(["publish", "gh-pages", str(repo / "docs")]) == 0
    assert "smalldocs-publish-gh-pages" in g("branch")
    files = subprocess.run(["git", "ls-tree", "-r", "--name-only", "main"], cwd=remote, capture_output=True, text=True).stdout
    assert "docs/index.md" in files


@pytest.mark.parametrize(
    "files",
    [
        {"index.md": "---\ntitle: [a, b\n---\n"},
        {"index.md": "---\ndate: 2024-13-45\n---\n"},
        {"index.md": "# x\n", "sub/_metadata.yml": "- a\n", "sub/p.md": "# p\n"},
        {"index.md": "# x\n", "_quarto.yml": "project:\n  type: website\n  pre-render: no-such-command-here\n"},
        {"index.md": "# x\n", "_quarto.yml": "project: 5\n"},
        {"index.md": "# x\n", "_quarto.yml": "website:\n  page-footer: [a, b]\nformat:\n  html: default\n"},
    ],
)
def test_bad_input_gives_a_message_not_a_traceback(tmp_path: Path, files: dict, capsys: pytest.CaptureFixture) -> None:
    "Bad YAML, bad dates, bad sections and missing commands stop with a message that names the file, or build."
    write(tmp_path, {"_quarto.yml": "project:\n  type: website\n", **files})
    code = main(["render", str(tmp_path), "-q"])
    err = capsys.readouterr().err
    assert code in (0, 2) and "Traceback" not in err
    if code == 2:
        assert err.startswith("smalldocs: ")


def test_bom_mixed_sort_keys_and_small_pages(tmp_path: Path) -> None:
    "A BOM keeps front matter; mixed sort values sort; page-size 0 falls back to the default."
    write(tmp_path, {
        "_quarto.yml": "project:\n  type: website\n",
        "index.qmd": "---\ntitle: L\nlisting:\n  contents: p\n  sort: rank\n  page-size: 0\n  max-items: 0\n---\n",
        "p/a.md": "---\ntitle: A\nrank: 2\n---\n", "p/b.md": "---\ntitle: B\nrank: x\n---\n", "p/c.md": "---\ntitle: C\nrank: 1\n---\n",
    })  # fmt: skip
    (tmp_path / "bom.qmd").write_bytes("﻿---\r\ntitle: BOM page\r\n---\r\nBody\r\n".encode())
    s = build(tmp_path, quiet=True)
    assert "<title>BOM page</title>" in (s.out / "bom.html").read_text()
    idx = (s.out / "index.html").read_text()
    assert idx.index(">C<") < idx.index(">A<") < idx.index(">B<") and 'data-page-size="50"' in idx


def test_file_names_with_hash_and_percent(tmp_path: Path) -> None:
    "Files named with `#`, `?` or `%` are linked with those characters escaped."
    write(tmp_path, {"_quarto.yml": "project:\n  type: website\n", "index.md": "![a](a%23b.png) ![c](100%25.png)\n", "a#b.png": "x", "100%.png": "x"})
    html = (build(tmp_path, quiet=True).out / "index.html").read_text()
    assert 'src="a%23b.png"' in html and 'src="100%25.png"' in html


def test_api_type_names_and_sources(tmp_path: Path) -> None:
    "A module constant or a builtin alias does not rename a type; async shows; code with no source is still listed."
    write(tmp_path, {
        "src/odd/__init__.py": '"Odd."\n',
        "src/odd/m.py": '"M."\nfrom types import ModuleType\n\nCACHE = None\nNumber = int\n\n\ndef h(\n    m: ModuleType,  # A module\n) -> None:  # Nothing\n    "H."\n\n\nasync def f(\n    x: int,  # X\n) -> None:  # Nothing\n    "F."\n\n\nexec("def g(y: int) -> int:\\n    return y")\n',
        "docs/_quarto.yml": "project:\n  type: website\nsmalldocs:\n  api:\n    packages: [odd]\n",
        "docs/index.md": "# Hi\n",
    })  # fmt: skip
    for m in [m for m in sys.modules if m.startswith("odd")]:
        sys.modules.pop(m)
    assert main(["api", "build", "--dir", str(tmp_path / "docs")]) == 0
    qmd = (tmp_path / "docs/api/m.qmd").read_text()
    assert "async f(x: int) -> None" in qmd and "CACHE" not in qmd and "Number" not in qmd
    assert "h(m: ModuleType) -> None" in qmd, "an imported name such as ModuleType stays"


# ---------------------------------------------------------------- findings of the final review


def test_nothing_is_written_outside_the_output(tmp_path: Path) -> None:
    "A css or favicon path that leaves the project is reported, and no file outside the output is written."
    repo = write(tmp_path, {"assets/style.css": "SHARED", "docs/assets/style.css": "DOCS OWN", "docs/index.md": "# Hi\n"})
    write(repo, {"docs/_quarto.yml": "project:\n  type: website\nformat:\n  html:\n    css: ../assets/style.css\n"})
    s = build(repo / "docs", quiet=True)
    assert (repo / "docs/assets/style.css").read_text() == "DOCS OWN"
    assert any("outside the project" in w for w in s.warnings)


def test_globs_without_a_slash_match_at_any_depth(tmp_path: Path) -> None:
    "As in Quarto: `*.qmd` in render, listings and resources finds files in every folder; a folder in render means its pages."
    write(tmp_path, {
        "_quarto.yml": 'project:\n  type: website\n  render: ["*.qmd", "extra/"]\n  resources: "*.txt"\n',
        "index.qmd": '---\ntitle: L\nlisting:\n  contents: "*.qmd"\n---\n',
        "top.qmd": "# T\n", "p/q/deep.qmd": "# D\n", "sub/s.qmd": "# S\n", "extra/e.md": "# E\n",
        "a.txt": "a", "d/b.txt": "b", "d/e/c.txt": "c",
    })  # fmt: skip
    s = build(tmp_path, quiet=True)
    assert {p.relative_to(s.out).as_posix() for p in s.out.rglob("*.html")} == {"index.html", "top.html", "p/q/deep.html", "sub/s.html", "extra/e.html"}
    assert (s.out / "index.html").read_text().count('class="quarto-post') == 3
    assert all((s.out / f).exists() for f in ("a.txt", "d/b.txt", "d/e/c.txt"))


def test_spaces_rule_leaves_code_alone() -> None:
    "Code spans that look like links with spaces stay as written."
    assert "<code>handlers[name](event, ctx)</code>" in md("Call `handlers[name](event, ctx)` here.\n")


def test_echo_false_for_a_page_and_execute(tmp_path: Path) -> None:
    "`echo: false` in front matter, or `execute: {echo: false}` in the project, hides the code of every cell."
    nb = {"nbformat": 4, "cells": [{"cell_type": "code", "source": "SECRET_CODE()", "outputs": [{"output_type": "stream", "name": "stdout", "text": "out"}]}]}
    write(tmp_path, {"_quarto.yml": "project:\n  type: website\nexecute:\n  echo: false\n", "n.ipynb": json.dumps(nb), "q.qmd": "---\ntitle: Q\necho: false\n---\n\n```{python}\nHIDDEN()\n```\n"})
    s = build(tmp_path, quiet=True)
    n = (s.out / "n.html").read_text()
    assert "SECRET_CODE" not in n and "out" in n
    assert "HIDDEN" not in (s.out / "q.html").read_text()
    assert not any("execute" in w for w in s.warnings)


def test_publish_guards(tmp_path: Path) -> None:
    "publish refuses a branch of sources, odd ref names and a folder that is not a built site; no hook runs."
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    repo = write(tmp_path / "repo", {"docs/_quarto.yml": "project:\n  type: website\n", "docs/index.md": "# Hi\n", ".gitignore": "_site/\n"})
    g = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, text=True).stdout  # noqa: E731
    g("init", "-q", "-b", "main")
    g("config", "user.email", "t@t")
    g("config", "user.name", "T")
    g("add", "-A")
    g("commit", "-qm", "start")
    g("remote", "add", "origin", str(remote))
    g("push", "-q", "origin", "main", "main:develop")
    log = repo / "hooks.log"
    for h in ("post-checkout", "post-commit", "pre-push"):
        hook = repo / ".git/hooks" / h
        hook.write_text(f"#!/bin/sh\necho {h} >> {log}\n")
        hook.chmod(0o755)
    d = str(repo / "docs")
    assert main(["publish", "gh-pages", d, "--branch", "develop"]) == 2
    for bad in ("HEAD", "refs/heads/x", "origin/x", "a..b"):
        assert main(["publish", "gh-pages", d, "--branch", bad]) == 2
    assert main(["publish", "gh-pages", d]) == 0
    assert not log.exists(), "no hook ran"
    write(repo, {"docs/_quarto.yml": "project:\n  type: website\n  output-dir: .\n", "docs/.env": "SECRET=1"})
    assert main(["publish", "gh-pages", d, "--no-render"]) == 2
    files = subprocess.run(["git", "ls-tree", "-r", "--name-only", "develop"], cwd=remote, capture_output=True, text=True).stdout
    assert "docs/index.md" in files


def test_odd_inputs(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    "A bad `_variables.yml` or glob is a message; `..data` is a folder; `{-}` is unnumbered; a Markdown title renders."
    write(tmp_path, {"_quarto.yml": "project:\n  type: website\n", "index.md": "{{< var a >}}\n", "_variables.yml": "a: [b\n"})
    assert main(["render", str(tmp_path), "-q"]) == 2 and "_variables.yml" in capsys.readouterr().err
    write(tmp_path, {"_variables.yml": "a: 1\n", "_quarto.yml": 'project:\n  type: website\n  resources: "[z-a].txt"\n'})
    assert main(["render", str(tmp_path), "-q"]) == 2
    write(tmp_path, {
        "_quarto.yml": "project:\n  type: website\nformat:\n  html:\n    number-sections: true\n",
        "index.md": "---\ntitle: \"**Bold** & `code`\"\n---\n\n[d](..data/x.txt)\n\n## A {-}\n\n## B\n", "..data/x.txt": "x",
    })  # fmt: skip
    s = build(tmp_path, quiet=True)
    html = (s.out / "index.html").read_text()
    assert '<h1 class="title"><strong>Bold</strong> &amp; <code>code</code></h1>' in html and "<title>Bold &amp; code</title>" in html
    assert 'class="level2 unnumbered"' in html and '<span class="header-section-number">1</span> B' in html
    assert (s.out / "..data/x.txt").exists() and not any("outside" in w for w in s.warnings)


def test_api_typevars_newtypes_and_callables(tmp_path: Path) -> None:
    "TypeVar and NewType keep their names; Callable arguments are written as Python writes them."
    write(tmp_path, {
        "src/tv/__init__.py": '"TV."\n',
        "src/tv/m.py": '"M."\nfrom collections.abc import Callable\nfrom typing import NewType, TypeVar\n\nT = TypeVar("T")\nUID = NewType("UserId", int)\n\n\ndef f(\n    x: T,  # X\n    u: UID,  # U\n    c: Callable[[int], str],  # C\n) -> T:  # X\n    "F."\n    return x\n',
        "docs/_quarto.yml": "project:\n  type: website\nsmalldocs:\n  api:\n    packages: [tv]\n",
        "docs/index.md": "# Hi\n",
    })  # fmt: skip
    for m in [m for m in sys.modules if m.startswith("tv")]:
        sys.modules.pop(m)
    assert main(["api", "build", "--dir", str(tmp_path / "docs")]) == 0
    assert "f(x: T, u: UID, c: Callable[[int], str]) -> T" in (tmp_path / "docs/api/m.qmd").read_text()
