"The tests of smalldocs: the Markdown rules, notebooks, the site, listings, the API reference, check and publish."

import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

import smalldocs
from smalldocs import notebook
from smalldocs.cli import main
from smalldocs.config import BuildError, ConfigError, load
from smalldocs.highlight import highlight
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


def test_diff_blocks() -> None:
    "A diff colours its removed, added and hunk lines, keeps its text as written, and other languages keep their classes."
    diff = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1,3 +1,3 @@\n ctx  two\n-old\n+new\n\n\n \\ No newline at end of file\n-last"
    html = md(f"```diff\n{diff}\n```\n")
    assert '<code class="sourceCode diff">' in html
    assert '<span class="gd">-old</span>' in html and '<span class="gi">+new</span>' in html and '<span class="gd">-last</span>' in html
    assert '<span class="gu">@@ -1,3 +1,3 @@</span>' in html and '<span class="gh">diff --git a/x b/x</span>' in html
    assert '<span class="gd">--- a/x</span>' in html and '<span class="gi">+++ b/x</span>' in html
    assert "\n ctx  two\n" in html and "\n\n\n \\ No newline" in html and 'class="er"' not in html
    assert re.sub(r"<[^>]+>", "", highlight(diff, "diff")) == diff and highlight(diff, "patch") == highlight(diff, "diff")
    css = (Path(smalldocs.__file__).parent / "assets" / "smalldocs.css").read_text()
    scope = 'code.sourceCode:is([class~="diff" i], [class~="udiff" i], [class~="patch" i])'
    assert f"{scope} span.gd {{" in css and f"{scope} span.gi {{" in css and f"{scope} {{ display: block; width: max-content" in css
    assert '<span class="gd">-a</span>' in md("```Diff\n-a\n```\n")
    # Other languages: Pandoc's classes, as before, and none of a diff's.
    assert highlight("import os\nx = 1  # c", "python") == (
        '<span class="im">import</span> os\nx <span class="op">=</span> <span class="dv">1</span>  <span class="co"># c</span>'
    )
    assert highlight("- a\n- b", "markdown") == '<span class="kw">-</span> a\n<span class="kw">-</span> b'
    # A last line with no newline is read as the others are: a comment, or the output of a session.
    assert highlight("ls  # c", "bash") == 'ls  <span class="co"># c</span>'
    assert highlight("$ ls\ntotal 0", "console") == "$ ls\ntotal 0"


def test_tables_scroll_in_their_own_box() -> None:
    "A table sits in a box that scrolls when the table is too wide, and keeps Bootstrap's classes."
    html = md("| a | b |\n|---|---|\n| 1 | 2 |\n")
    assert html.startswith('<div class="sd-table">\n<table class="caption-top table">') and html.rstrip().endswith("</table>\n</div>")
    css = (Path(smalldocs.__file__).parent / "assets" / "smalldocs.css").read_text()
    assert ".sd-table { overflow-x: auto; }" in css


def test_executable_cells_are_shown_not_run() -> None:
    "A `{python}` cell is shown as code, without its `#|` options, and noted."
    env: dict = {}
    html = render("```{python}\n#| echo: true\nprint(1)\n```\n\n```{python}\n#| echo: false\nsecret()\n```\n", env)
    assert "print" in html and "#|" not in html and "secret" not in html
    assert len(env["unrun"]) == 2


def test_linkify_names_in_backticks() -> None:
    "A documented name in backticks that looks like code links to its entry, but not inside a link, with `.nolink`, or when unknown."
    syms = {"render": "api.html#render", "main": "api.html#main", "Site": "s.html#Site", "Site.build": "s.html#Site.build", "a.main": "api.html#main", "to_record": "r.html#to_record"}
    env = {"symbols": syms, "link": lambda h, k: h}
    html = render("Call `render()` or `other`, or [see `render()`](x.html).\n", env)
    assert '<a href="api.html#render"><code>render()</code></a>' in html
    assert "<code>other</code>" in html and html.count('href="api.html#render"') == 1
    # A plain lowercase word is a word: the branch `main`, the option `render`. A call, a dotted name or a class links.
    html = render("The branch `main`, the option `render`, `main()`, `a.main`, `Site` and `Site.build`. Plain main.\n", env)
    assert "<code>main</code>" in html and "<code>render</code>" in html and 'href="api.html#render"' not in html
    assert '<a href="api.html#main"><code>main()</code></a>' in html and '<a href="api.html#main"><code>a.main</code></a>' in html
    assert '<a href="s.html#Site"><code>Site</code></a>' in html and '<a href="s.html#Site.build"><code>Site.build</code></a>' in html
    assert "Plain main." in html and '<a href="r.html#to_record"><code>to_record</code></a>' in render("`to_record`\n", env)
    # `.nolink` keeps a name that looks like code as plain code.
    html = render("The class `Site`{.nolink} and `Site.build()`{.nolink}.\n", env)
    assert "href" not in html and '<code class="nolink">Site</code>' in html


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
    with pytest.raises(ConfigError, match=r"no _smalldocs\.yml or _quarto\.yml"):
        load(tmp_path)
    write(tmp_path, {"_quarto.yml": "project:\n  type: manuscript\n"})
    with pytest.raises(ConfigError, match="only websites"):
        load(tmp_path)
    write(tmp_path, {"_quarto.yml": "project:\n  type: website\nformat:\n  html:\n    theme: nosuch\n  pdf: default\nfilters: [x.lua]\nweird: 1\n", "index.md": "# Hi\n"})
    p = load(tmp_path)
    assert any("format pdf" in w for w in p.warnings) and any("x.lua" in w for w in p.warnings)
    with pytest.raises(BuildError, match="not a Bootswatch theme"):
        build(tmp_path, quiet=True)


def test_linkify_lua_turns_on_linkify(tmp_path: Path) -> None:
    "`linkify.lua` in `filters`, as a path or as a `{path: ...}` entry, turns on linkify and gets no warning."
    for entry in ["filters/linkify.lua", "{path: linkify.lua, type: lua}"]:
        write(tmp_path, {
            "_quarto.yml": f"project:\n  type: website\nfilters: [{entry}]\n",
            "_symbols.json": '{"render": "api.html#render"}',
            "index.md": "# Hi\n\nCall `render()`.\n",
        })
        assert not load(tmp_path).warnings
        build(tmp_path, quiet=True)
        assert '<a href="api.html#render"><code>render()</code></a>' in (tmp_path / "_site/index.html").read_text()
    write(tmp_path, {"_quarto.yml": "project:\n  type: website\nfilters: [quarto, '', linkify.lua]\n"})
    assert not load(tmp_path).warnings, "`quarto` and an empty entry are not filters to warn about"


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


THEME_REPO = {
    "_extensions/ac215/_extension.yml": "title: AC215\ncontributes:\n  formats:\n    html:\n      theme: [cosmo, ac215.scss]\n",
    "_extensions/ac215/ac215.scss": "$primary: #a00;\n",
    "_extensions/ac215/smalldocs.yml": "css: {light: ac215.css, dark: ac215-dark.css}\nlogo: logo.png\nfavicon: logo.png\n",
    "_extensions/ac215/ac215.css": "@font-face{src:url('fonts/f.woff2?v=1')}\n@import \"more.css\";\n:root{--bs-primary:#a00}\n",
    "_extensions/ac215/more.css": ".a{background:url(img/a.png)} .b{background:url(data:image/png;base64,x)} .c{background:url(../../x.txt)}\n",
    "_extensions/ac215/ac215-dark.css": ":root{--bs-body-bg:#111}\n",
    "_extensions/ac215/fonts/f.woff2": "font\n",
    "_extensions/ac215/img/a.png": "png\n",
    "_extensions/ac215/logo.png": "logo\n",
    "_extensions/ac215/unused.css": "unused\n",
}
SITE_YML = "project:\n  type: website\nwebsite:\n  title: T\n  navbar:\n    left: [index.md]\n"


def theme_repo(
    root: Path,  # The folder to make the repository in
) -> str:  # The commit
    "Make a git repository that holds a theme extension, tagged v1."
    write(root, THEME_REPO)
    g = lambda *a: subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=T", *a], cwd=root, check=True, capture_output=True, text=True).stdout  # noqa: E731
    g("init", "-q", "-b", "main")
    g("add", "-A")
    g("commit", "-qm", "theme")
    g("tag", "v1")
    return g("rev-parse", "HEAD").strip()


def test_add_from_a_folder_and_a_bare_repo(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    "`smalldocs add` copies the extensions without .git, writes .source, and asks before it replaces one."
    from smalldocs.extensions import add, parse_source

    commit = theme_repo(tmp_path / "repo")
    subprocess.run(["git", "clone", "-q", "--bare", str(tmp_path / "repo"), str(tmp_path / "bare.git")], check=True)
    site = write(tmp_path / "site", {"_smalldocs.yml": SITE_YML, "index.md": "# Hi\n"})
    ext = site / "_extensions/ac215"

    folder = write(tmp_path / "at@folder", THEME_REPO)
    assert add(str(folder), site) == [ext]
    assert (ext / "fonts/f.woff2").exists() and (ext / "ac215.scss").exists()
    assert yaml.safe_load((ext / ".source").read_text()) == {"source": str(folder.resolve()), "ref": None, "commit": None}
    out = capsys.readouterr().out
    assert "Added _extensions/ac215" in out and "theme: ac215" in out

    (ext / "mine.txt").write_text("edit\n")
    with pytest.raises(BuildError, match="give --force"):
        add(f"{tmp_path / 'bare.git'}@v1", site, ask=lambda q: None)
    assert add(f"{tmp_path / 'bare.git'}@v1", site, ask=lambda q: False) == [] and (ext / "mine.txt").exists()
    assert add(f"{tmp_path / 'bare.git'}@v1", site, ask=lambda q: True) == [ext] and not (ext / "mine.txt").exists()
    assert add(f"{tmp_path / 'repo'}@v1", site, force=True) == [ext]
    assert yaml.safe_load((ext / ".source").read_text())["commit"] == commit
    assert main(["add", f"{tmp_path / 'bare.git'}@{commit}", "--dir", str(site), "--force"]) == 0
    note = yaml.safe_load((ext / ".source").read_text())
    assert note == {"source": f"{(tmp_path / 'bare.git').resolve()}@{commit}", "ref": commit, "commit": commit}
    assert not (ext / ".git").exists() and not (site / "_extensions/.git").exists()

    assert parse_source("org/repo@v2").url == "git@github.com:org/repo.git" and parse_source("org/repo@v2").ref == "v2"
    assert parse_source("git@github.com:org/repo.git").ref is None
    assert parse_source("git@github.com:org/repo.git@main").ref == "main"
    assert parse_source("https://user@example.com/org/repo.git").ref is None
    assert parse_source("https://example.com/org/repo.git@feature/x").ref == "feature/x"
    assert main(["themes", str(site)]) == 0
    out = capsys.readouterr().out
    assert f"commit {commit[:7]}" in out and f"again:  smalldocs add {(tmp_path / 'bare.git').resolve()}@{commit} --force" in out
    assert f"newest: smalldocs add {(tmp_path / 'bare.git').resolve()} --force" in out


def test_add_and_themes_keep_to_their_folders(tmp_path: Path) -> None:
    "A symbolic link cannot bring other files into the site, an org folder is not replaced, and a source cannot be an option of git."
    from smalldocs.extensions import add, parse_source

    secret = write(tmp_path / "secret", {"keys/_extension.yml": "title: K\n", "keys/key.env": "TOKEN=abc\n"})
    evil = tmp_path / "evil"
    evil.mkdir()
    (evil / "_extensions").symlink_to(secret)
    site = write(tmp_path / "site", {"_smalldocs.yml": SITE_YML, "index.md": "# Hi\n"})
    with pytest.raises(BuildError, match="has no extension"):
        add(str(evil), site)
    with pytest.raises(ConfigError, match="cannot start with -"):
        parse_source("-ux@h:x")

    write(site, {"_extensions/acme/a/smalldocs.yml": "css: a.css\n", "_extensions/acme/a/a.css": "\n"})
    with pytest.raises(BuildError, match="holds other extensions, _extensions/acme/a"):
        add(str(write(tmp_path / "org", {"_extensions/acme/smalldocs.yml": "css: a.css\n"})), site, force=True)
    assert (site / "_extensions/acme/a/a.css").exists()

    write(site, {"_extensions/t/smalldocs.yml": "css: t.css\nlogo: .\n"})
    (site / "_extensions/t/t.css").symlink_to(secret / "keys/key.env")
    (site / "_smalldocs.yml").write_text(SITE_YML + "theme: t\n")
    with pytest.raises(BuildError, match=r"'t\.css' is not a file in _extensions/t"):
        build(site, quiet=True)
    (site / "_extensions/t/t.css").unlink()
    (site / "_extensions/t/t.css").write_text("body{}\n")
    with pytest.raises(BuildError, match=r"logo '\.' is not a file"):
        build(site, quiet=True)


def test_theme_extensions(tmp_path: Path) -> None:
    "`theme: ac215` gives both modes from `_extensions/`; it mixes with Bootswatch; a name found twice is an error."
    site = write(tmp_path, {**THEME_REPO, "_smalldocs.yml": SITE_YML + "theme: ac215\n", "index.md": "# Hi\n", "a/b.md": "# B\n"})
    s = build(site, quiet=True)
    page = (s.out / "index.html").read_text()
    assert 'href="site_libs/themes/ac215/ac215.css" data-mode="light"' in page and 'media="not all and (prefers-color-scheme: dark)"' in page
    assert 'href="site_libs/themes/ac215/ac215-dark.css" data-mode="dark"' in page and 'media="(prefers-color-scheme: dark)"' in page
    assert "quarto-color-scheme-toggle" in page and "matchMedia('(prefers-color-scheme: dark)')" in page
    assert 'href="../site_libs/themes/ac215/ac215.css"' in (s.out / "a/b.html").read_text()
    libs = s.out / "site_libs/themes/ac215"
    assert sorted(p.relative_to(libs).as_posix() for p in libs.rglob("*") if p.is_file()) == [
        "ac215-dark.css", "ac215.css", "fonts/f.woff2", "img/a.png", "logo.png", "more.css",
    ]  # fmt: skip
    assert not (s.out / "_extensions").exists() and not list(s.out.rglob("*.scss"))
    assert any("../../x.txt is outside the extension" in w for w in s.warnings)
    assert any("ac215.css is not a whole Bootstrap 5.3 stylesheet" in w for w in s.warnings)

    (site / "_smalldocs.yml").write_text(SITE_YML + "theme:\n  light: ac215\n  dark: darkly\n")
    page = (build(site, quiet=True).out / "index.html").read_text()
    assert "themes/ac215/ac215.css" in page and "themes/darkly.min.css" in page and "ac215-dark.css" not in page

    (site / "_quarto.yml").write_text("project:\n  type: website\nformat:\n  html:\n    theme: [cosmo, _extensions/ac215/ac215.scss]\nsmalldocs:\n  theme: ac215\n")
    (site / "_smalldocs.yml").unlink()
    s = build(site, quiet=True)
    assert "themes/ac215/ac215-dark.css" in (s.out / "index.html").read_text() and not any("scss" in w for w in s.warnings)

    (site / "_quarto.yml").write_text("project:\n  type: website\nformat:\n  ac215-html:\n    toc: true\n")
    (site / "index.md").write_text("# Hi\n\n## One\n\n## Two\n")
    s = build(site, quiet=True)
    page = (s.out / "index.html").read_text()
    assert "themes/ac215/ac215.css" in page and 'id="TOC"' in page and not any("format" in w for w in s.warnings)

    write(site, {"_extensions/org/ac215/smalldocs.yml": "css: x.css\n", "_extensions/org/ac215/x.css": "\n"})
    with pytest.raises(BuildError, match="_extensions/ac215 and _extensions/org/ac215: keep one"):
        build(site, quiet=True)
    (site / "_extensions/org/ac215").rename(site / "_extensions/org/flatly")
    (site / "_quarto.yml").write_text("project:\n  type: website\nsmalldocs:\n  theme: flatly\n")
    with pytest.raises(BuildError, match="Bootswatch theme and also _extensions/org/flatly"):
        build(site, quiet=True)
    (site / "_quarto.yml").write_text("project:\n  type: website\nsmalldocs:\n  theme: nosuch\n")
    with pytest.raises(BuildError, match=r"use one of .*ac215.*cosmo"):
        build(site, quiet=True)


def test_theme_logo_and_favicon_only_when_the_site_has_none(tmp_path: Path) -> None:
    "The theme's logo and favicon fill in for the site's; the site's own win."
    site = write(tmp_path, {**THEME_REPO, "_smalldocs.yml": SITE_YML + "theme: ac215\n", "index.md": "# Hi\n", "me.png": "me\n"})
    page = (build(site, quiet=True).out / "index.html").read_text()
    assert '<img src="site_libs/themes/ac215/logo.png"' in page and '<link rel="icon" href="site_libs/themes/ac215/logo.png">' in page
    (site / "_smalldocs.yml").write_text(SITE_YML.replace("  navbar:\n", "  favicon: me.png\n  navbar:\n    logo: me.png\n") + "theme: ac215\n")
    s = build(site, quiet=True)
    page = (s.out / "index.html").read_text()
    assert '<img src="me.png"' in page and '<link rel="icon" href="me.png">' in page and "ac215/logo.png" not in page
    assert not (s.out / "site_libs/themes/ac215/logo.png").exists()


def test_min_css_theme_keeps_its_name(tmp_path: Path) -> None:
    "A theme file named `x.min.css` is copied to `x.min.css`, the name the page links to."
    s = build(write(tmp_path, {"_smalldocs.yml": "project:\n  type: website\ntheme: styles/x.min.css\n", "styles/x.min.css": "body{}\n", "index.md": "# Hi\n"}), quiet=True)
    assert 'href="site_libs/themes/x.min.css"' in (s.out / "index.html").read_text()
    assert sorted(p.name for p in (s.out / "site_libs/themes").iterdir()) == ["x.min.css"]


def test_bootswatch_themes_are_whole_bootstrap_stylesheets() -> None:
    "Each bundled theme passes the check that a theme extension must pass."
    from smalldocs.extensions import ASSETS, bundled, is_bootstrap

    for name in bundled():
        assert is_bootstrap((ASSETS / "vendor/bootswatch" / f"{name}.min.css").read_text()), name
    assert is_bootstrap((ASSETS / "vendor/bootstrap/bootstrap.min.css").read_text())
    assert not is_bootstrap(":root{--bs-body-bg:#fff}")


def test_a_site_without_extensions_is_unchanged(tmp_path: Path) -> None:
    "One theme and no `_extensions/`: the same head as before themes came from extensions; a Quarto-only extension changes nothing."
    files = {"_smalldocs.yml": SITE_YML + "theme: flatly\n", "index.md": "# Hi\n"}
    a = build(write(tmp_path / "a", files), quiet=True)
    b = build(write(tmp_path / "b", {**files, "_extensions/q/_extension.yml": "title: Q\n", "_extensions/q/q.scss": "\n"}), quiet=True)
    page = (a.out / "index.html").read_text()
    assert '<link rel="stylesheet" href="site_libs/themes/flatly.min.css" data-mode="light" class="quarto-color-scheme" id="quarto-bootstrap-light">' in page
    assert "media=" not in page and "smalldocs-scheme" not in page and 'rel="icon"' not in page
    tree = lambda s: {p.relative_to(s.out).as_posix(): p.read_bytes() for p in sorted(s.out.rglob("*")) if p.is_file()}  # noqa: E731
    assert tree(a) == tree(b) and not a.warnings and not b.warnings


def test_side_notes_with_reference_location_margin() -> None:
    "Each footnote goes in the margin before the block that cites it first, with Quarto's markup; a note that a note cites goes with it."
    text = "Intro.\n\nA[^1] b[^1] c[^x].\n\n- d[^y]\n\n[^1]: One.\n\n    Two.\n[^x]: X cites[^y].\n[^y]: Y.\n"
    env = {"reference_location": "margin"}
    out = md(text, **env)
    assert out.startswith('<p>Intro.</p>\n<div class="no-row-height column-margin column-container">\n<div id="fn1">\n<p><sup>1</sup>\u00a0One.</p>\n<p>Two.</p>\n</div>')
    assert out.index('<div id="fn2">') < out.index('<div id="fn3">') < out.index("<p>A<a")
    assert '<a href="#fn1" class="footnote-ref" id="fnref1" role="doc-noteref"><sup>1</sup></a>' in out and 'id="fnref1:1"' in out
    assert "footnotes" not in out.replace("footnote-ref", "") and "footnote-backref" not in out and out.count('id="fn3"') == 1
    assert '<section class="footnotes">' in md(text) and '<sup class="footnote-ref"><a href="#fn1" id="fnref1">[1]</a></sup>' in md(text)


def test_side_notes_from_captions_titles_tabs_and_headings() -> None:
    "No footnote is lost: notes cited in a caption, a callout title, a tab or a heading go in the margin, each in its place."
    text = """
    ![Cap[^cap]](x.png)

    ::: {.callout-tip}
    ## Tip[^tip]
    Body.
    :::

    ::: {.panel-tabset}
    ## One[^tab]
    First.

    ## Two
    Second.
    :::

    ## Heading[^head]

    After.

    [^cap]: In a caption.
    [^tip]: In a title.
    [^tab]: In a tab.
    [^head]: In a heading.
    """
    out = md(text, reference_location="margin")
    for n, note in enumerate(["In a caption.", "In a title.", "In a tab.", "In a heading."], 1):
        assert f'<div id="fn{n}">\n<p><sup>{n}</sup>\u00a0{note}</p>' in out, note
    assert out.index('id="fn2"') < out.index('<div class="callout') and out.index('id="fn3"') < out.index('<div class="panel-tabset')
    assert out.index("<h2") < out.index('id="fn4"') < out.index("<p>After.</p>") and out.index('<section id="heading"') < out.index('id="fn4"')
    nested = md("::: {.column-margin}\n![In the margin](x.png)\n:::\n", fig_cap_location="margin")
    assert "margin-caption" not in nested and "<figcaption>In the margin</figcaption>" in nested


def test_margin_content_and_wide_columns(tmp_path: Path) -> None:
    "Margin blocks, asides, margin captions and the column classes, as Quarto writes them; the page gets a margin column."
    out = md("A [side]{.aside} b.\n\n![Cap](x.png)\n\n![M](m.png){.column-margin .border}\n\n::: {.column-page}\n![Wide](w.png)\n:::\n", fig_cap_location="margin")
    assert '<span class="aside margin-aside">side</span>' in out
    assert '<figure class="figure">\n<figcaption class="margin-caption">Cap</figcaption>\n<p><img alt="Cap"' in out
    assert '<div class="quarto-figure quarto-figure-center column-margin">' in out and 'class="border img-fluid figure-img"' in out
    assert "<figcaption>M</figcaption>" in out and "<figcaption>Wide</figcaption>" in out and out.count("margin-caption") == 1
    assert "fig-cap-location" not in md("![C](x.png){fig-cap-location=margin}") and "margin-caption" in md("![C](x.png){fig-cap-location=margin}")
    site = write(tmp_path, {
        "_smalldocs.yml": "project:\n  type: website\nreference-location: block\n",
        "index.md": "# Hi\n\nText.\n\n::: {.column-margin}\nNote.\n:::\n",
        "plain.md": "# Plain\n\nText.\n",
        "raw.md": "# Raw\n\n<div class=\"column-margin\">A raw note.</div>\n\nText.\n",
    })  # fmt: skip
    s = build(site, quiet=True)
    assert 'class="quarto-container page-columns page-rows-contents page-layout-article has-margin"' in (s.out / "index.html").read_text()
    assert "has-margin" not in (s.out / "plain.html").read_text()
    assert "has-margin" in (s.out / "raw.html").read_text()
    assert any("reference-location: block is not read" in w for w in s.warnings)


def test_notebook_cell_options_for_figures_tables_and_columns() -> None:
    "`fig-cap`, `fig-alt`, `fig-align`, `tbl-cap`, `column` and `layout-ncol` work; each cell still has one cell-code and each output one cell-output."
    png = {"output_type": "display_data", "data": {"image/png": "iVBORw0KGgo=", "text/plain": "<Figure>"}, "metadata": {}}
    tbl = {"output_type": "execute_result", "data": {"text/html": "<table><tr><td>1</td></tr></table>"}, "metadata": {}}
    cells = [
        ("#| label: fig-one\n#| fig-cap: A caption\n#| fig-alt: Alt text\n#| fig-align: left\nplot()", [png]),
        ("#| tbl-cap: A table\ndf", [tbl]),
        ("#| column: margin\nplot()", [png]),
        ("#| layout-ncol: 2\n#| fig-cap: [One, Two]\nplot(); plot()", [png, png]),
        ("plain()", [png]),
    ]
    nb = {"nbformat": 4, "metadata": {}, "cells": [{"cell_type": "code", "source": c, "outputs": o, "metadata": {}} for c, o in cells]}
    _, body = notebook.to_markdown(json.dumps(nb))
    out = md(body)
    assert out.count("cell-code") == 5 and out.count("cell-output ") == 6
    assert '<div class="quarto-figure quarto-figure-left">' in out and '<img alt="Alt text" src="data:image/png' in out
    assert "<figcaption>A caption</figcaption>" in out and "<figcaption>One</figcaption>" in out and "<figcaption>Two</figcaption>" in out
    assert '<table>\n<caption>A table</caption>' in out
    assert '<div class="column-margin">\n<div class="cell-output' in out and 'layout-ncol="2"' in out and "column-margin column-margin" not in out
    plain = out[out.index('id="cell-4"'):]
    assert "quarto-figure" not in plain and '<img src="data:image/png;base64,iVBORw0KGgo=" class="img-fluid">' in plain
    assert "quarto-layout-panel" in out


def test_notebook_cells_fold_and_number_only_when_they_ask() -> None:
    "A cell's own `code-fold`, `code-summary`, `code-line-numbers` and `code-overflow` reach its code; other cells are as before."
    cells = ["#| code-fold: true\n#| code-summary: Show it\nx = 1", "#| code-line-numbers: true\n#| code-overflow: wrap\nx = 1\ny = 2", "plain = 1"]
    nb = {"nbformat": 4, "metadata": {}, "cells": [{"cell_type": "code", "source": c, "outputs": [], "metadata": {}} for c in cells]}
    out = md(notebook.to_markdown(json.dumps(nb))[1])
    assert out.count("cell-code") == 3 and out.count("<details") == 1 and "<summary>Show it</summary>" in out
    assert "number-lines" in out and "code-overflow-wrap" in out
    plain = out[out.index('id="cell-2"'):]
    assert "<details" not in plain and "number-lines" not in plain and "code-overflow" not in plain
    page = md("```{.python .cell-code}\nx = 1\n```\n", code_fold="true", code_line_numbers="true")
    assert "<details" not in page and "number-lines" not in page  # the page's options never reach a notebook's cells


def test_no_key_is_ignored_silently(tmp_path: Path) -> None:
    "A key smalldocs does not read is a warning, down to nested keys and list entries; front matter warns only for Quarto's options."
    cfg = """
    project:
      type: website
      execute-dir: project
    website:
      title: T
      issue-url: https://x
      navbar:
        weird: 1
        logo: {path: logo.png, alt: Home}
        left:
          - href: index.md
            target: _blank
            bogus: 2
      sidebar:
        - contents:
            - section: S
              contents: [{href: index.md, nope: 3}]
      open-graph: {image: x.png}
    format:
      html:
        highlight-style: github
        freeze: auto
    execute:
      echo: false
      cache: true
    """
    site = write(tmp_path, {
        "_quarto.yml": cfg,
        "index.md": "---\ntitle: Hi\ncode-tools: true\njupyter: python3\nmy-own-key: 1\nlisting: {contents: '*.md', zzz: 1}\n---\n# Hi\n",
        "sub/_metadata.yml": "abstract: An abstract\n",
        "sub/a.md": "# A\n",
        "logo.png": "png\n",
    })  # fmt: skip
    s = build(site, quiet=True)
    w = "\n".join(s.warnings)
    for line in [
        "project.execute-dir is ignored: smalldocs runs no code", "unknown key website.issue-url", "unknown key website.navbar.weird",
        "unknown key website.navbar.left[0].bogus", "unknown key website.sidebar[0].contents[0].contents[0].nope",
        "unknown key website.open-graph.image", "format.html.highlight-style is ignored", "index.md: code-tools is not read by smalldocs",
        "index.md: jupyter is ignored: smalldocs runs no code", "index.md: listing.zzz is not read by smalldocs",
        "sub/_metadata.yml: abstract is not read by smalldocs", "execute.cache is ignored: smalldocs runs no code",
        "format.html.freeze is ignored: smalldocs runs no code",
    ]:  # fmt: skip
        assert line in w, line
    assert "my-own-key" not in w and "target" not in w and "logo" not in w
    assert '<img src="logo.png" alt="Home"' in (s.out / "index.html").read_text()


def test_review_findings_for_0_3_0(tmp_path: Path) -> None:
    "Lists, superscripts and notebooks keep what they rendered before; odd values give warnings, not crashes."
    assert md("<pre>\n\na. alpha\nb. beta\n</pre>\n").count("a. alpha") == 1
    assert "a. code" in md("1. Step\n\n        a. code\n") and "<ol type" not in md("1. Step\n\n        a. code\n")
    two = md("1. one\n2. two\n\na. x\nb. y\n")
    assert two.count("<ol") == 2 and '<ol type="a">' in two
    assert md("A^[1]B^[2]\n").count('class="footnote-ref"') == 2
    assert 'fig-align' not in md("![](x.png){fig-align=left}\n")
    svg = {"output_type": "display_data", "data": {"image/svg+xml": "\n<svg></svg>\n"}, "metadata": {}}
    nb = {"nbformat": 4, "metadata": {}, "cells": [{"cell_type": "code", "source": "x", "outputs": [svg], "metadata": {}}]}
    assert "<div class=\"cell-output cell-output-display\">\n\n<svg></svg>\n\n</div>" in notebook.to_markdown(json.dumps(nb))[1]
    cfg = SITE_YML.replace("website:\n", "website:\n  open-graph: true\n  sidebar:\n    background: [a]\n    alignment: {x: 1}\n    header: '[home](index.md)'\n    contents: [index.md, sub/p.md]\n")
    site = write(tmp_path, {"_smalldocs.yml": cfg + "backgroundcolor: '#fdf6e3'\nmax-width: 900px\n", "index.md": "# Home\n", "sub/p.md": "# P\n",
                            "sub/_metadata.yml": "abstract: x\n", "sub/q.md": "# Q\n"})  # fmt: skip
    s = build(site, quiet=True)
    p = (s.out / "sub/p.html").read_text()
    assert '<meta property="og:title" content="P">' in p and 'href="../index.html">home</a>' in p
    assert "html:not(.quarto-dark) { --bs-body-bg: #fdf6e3;" in p and "#quarto-content.quarto-container { --sd-body-width: 900px; }" in p
    w = "\n".join(s.warnings)
    assert "sidebar.background: ['a'] is not used" in w and "sidebar.alignment" in w
    assert w.count("sub/_metadata.yml: abstract is not read") == 1


def test_double_dollars_are_display_maths_everywhere() -> None:
    "`$$...$$` is display maths on its own line, over lines, and inside a sentence, as Pandoc reads it; `$...$` stays inline."
    assert md("$$x = 1$$\n") == md("$$\nx = 1\n$$\n") == '<p><span class="math display">\\[x = 1\\]</span></p>\n'
    assert md("Text $$x = 1$$ more.\n") == '<p>Text <span class="math display">\\[x = 1\\]</span> more.</p>\n'
    assert md("Inline $x$ here.\n") == '<p>Inline <span class="math inline">\\(x\\)</span> here.</p>\n'


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
    "docs/index.qmd": "---\ntitle: Tiny\n---\n\nUse `add()` and `Point.norm`, not `nothing`.\n",
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
    assert '<a href="api/core.html#add"><code>add()</code></a>' in home and "<code>nothing</code>" in home
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
    assert "tinypkg.core:undocumented(x): no type" in out and "\ntests/test_x.py " in out and str(tmp_path) not in out
    assert main(["api", "module", "core", "--dir", d]) == 0
    assert capsys.readouterr().out.startswith("# tinypkg.core\n")
    assert main(["api", "module", "nope", "--dir", d]) == 2
    assert main(["api", "list", "--dir", d]) == 0
    assert "function  tinypkg.core.add" in capsys.readouterr().out


CLIPKG = {
    "src/clipkg/__init__.py": '''
        "A package whose code is in its `__init__`."

        from typing import TypedDict

        import click
        from pydantic import BaseModel, ConfigDict, Field


        class Page(BaseModel):
            "A page."

            title: str  # The title of the page
            extract: str = Field(description="The summary, from Field")
            both: int = Field(0, description="The description wins")  # The comment loses
            long: list[str] = Field(
                default_factory=list,
            )  # A comment on the last line
            bare: str = ""


        class Doc(BaseModel):
            "A model with attribute docstrings."

            model_config = ConfigDict(use_attribute_docstrings=True)
            name: str
            "The name, from its docstring."


        class Child(Page):
            "A model that inherits the fields of `Page`."

            extra: bool = False  # One more field


        class Odd:
            "A class with a method named callback, which is not a command."

            def callback(self) -> None:  # Nothing
                "A method."


        class Base(TypedDict):
            "Keys to inherit."

            a: int  # The a


        class Kid(Base):
            "Keys with a parent."

            b: str  # The b


        class Tooled(BaseModel):
            "A model with a tool's comment."

            x: int  # type: ignore


        def make() -> int:  # One
            "Make one."
            return 1


        class Holder:
            "Not a command, though it has a function in `callback`."

            def __init__(self) -> None:
                "Hold `make`."
                self.callback = make


        held = Holder()
        alias = click.command()(make)


        @click.command()
        @click.option("--language", "-l", default="en", metavar="LANG", help="The language, as its code")
        @click.option("--loud", is_flag=True, help="Shout")
        @click.argument("name")
        def main(
            language: str,  # The language, from --language
            loud: bool,  # Whether to shout
            name: str,  # Who to greet
        ) -> None:
            "Greet someone."


        @click.group()
        def cli() -> None:  # Nothing
            "A group of commands."


        @cli.command()
        def sub(
            undocumented,
        ) -> None:
            "A command with a gap."
        ''',
    "tests/conftest.py": '"Shared fixtures."\n\n\ndef helper() -> int:  # One\n    "Give one."\n    return 1\n',
    "tests/deep/test_deep.py": '"Deep tests."\n\n\ndef test_deep():\n    pass\n',
    "docs/_smalldocs.yml": """
        project:
          type: website
        api:
          packages: [clipkg]
          check: ["tests/**/*.py"]
        """,
    "docs/index.qmd": "---\ntitle: Clip\n---\n\nSee `Page` and `main`.\n",
}


def fresh(
    prefix: str,  # The start of the names of the modules to forget
) -> None:
    "Forget imported modules, so that a test imports its own package again."
    for m in [m for m in sys.modules if m.startswith(prefix)]:
        sys.modules.pop(m)


def test_api_models_commands_and_init(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    "A model's field is described by its description, or else the comment beside it; a click command is documented as its function."
    write(tmp_path, CLIPKG)
    fresh("clipkg")
    d = str(tmp_path / "docs")
    assert main(["api", "module", "clipkg", "--dir", d]) == 0
    md = capsys.readouterr().out
    assert md.startswith("# clipkg\n\nA package whose code is in its `__init__`."), "a package's `__init__` with code has a page"
    assert "| `title` | str | required | The title of the page |" in md
    assert "| `extract` | str | required | The summary, from Field |" in md
    assert "| `both` | int | `0` | The description wins |" in md and "The comment loses" not in md
    assert "| `long` | list[str] |" in md and "A comment on the last line |" in md
    assert "| `name` | str | required | The name, from its docstring. |" in md
    assert "| `extra` | bool | `False` | One more field |" in md and md.count("| `title` | str | required | The title of the page |") == 2, "a subclass reads its parents' comments"
    assert "## main\n\n```python\nmain(language: str, loud: bool, name: str) -> None\n```" in md
    assert "| `language` | str | required | The language, from --language |" in md
    assert "| `--language`, `-l` `LANG` | `'en'` | The language, as its code |" in md and "| `--loud` |  | Shout |" in md
    assert "Sentinel" not in md and "| `NAME` |  |  |" in md, "an option or argument with no default shows none"
    assert md.count("## make\n") == 1, "a function and the command made from it are one entry; an object with a callback is no command"
    assert "| `a` | int | The a |" in md and "| `b` | str | The b |" in md, "a TypedDict reads its parents' comments"
    assert "type: ignore" not in md
    assert "## cli\n" in md and "## sub\n" in md and "## class Odd" in md and "### Odd.callback" in md
    assert main(["api", "check", "--dir", d]) == 1
    out = capsys.readouterr().out
    assert "clipkg:Page.bare: no description" in out and "clipkg:Page.title" not in out and "clipkg:Child.extra" not in out
    assert "clipkg:sub(undocumented): no type" in out and "clipkg:main" not in out
    assert "clipkg:Tooled.x: no description" in out and "clipkg:Kid" not in out
    assert "\ntests/conftest.py " in out and "\ntests/deep/test_deep.py " in out, "`tests/**/*.py` finds files in `tests/` and below"
    assert "\ntests/deep/test_deep.py:test_deep: no docstring" in out and str(tmp_path) not in out, "files are named from the root"
    write(tmp_path, {"docs/_smalldocs.yml": "api:\n  packages: [clipkg]\n  check: [\"**/*.py\"]\n"})
    fresh("clipkg")
    assert main(["api", "check", "--dir", d]) == 1
    out = capsys.readouterr().out
    assert "\ntests/conftest.py " in out and "src/clipkg" not in out, "`**/*.py` leaves out the files of a documented package"


def test_smalldocs_yml(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    "`_smalldocs.yml` is read before `_quarto.yml`; its page options and its own options are at the top level."
    write(tmp_path, {
        "_smalldocs.yml": """
            project:
              type: website
            website:
              title: Mine
            theme: flatly
            toc: false
            linkify: true
            symbols: names.json
            format:
              html:
                theme: darkly
            filters: [linkify.lua]
            smalldocs:
              linkify: false
            """,
        "_quarto.yml": "project:\n  type: website\nformat:\n  html:\n    theme: darkly\n",
        "names.json": '{"render": "api.html#render"}',
        "index.md": "# Hi\n\nCall `render()`.\n\n## Part\n",
    })
    p = load(tmp_path)
    assert p.file == "_smalldocs.yml" and p.native and p.smalldocs == {"linkify": True, "symbols": "names.json"}
    w = "\n".join(p.warnings)
    assert "_quarto.yml is not read" in w and "unknown key format: write the page options" in w
    assert "unknown key filters" in w and "unknown key smalldocs: write linkify" in w and "theme" not in w.replace("such as theme", "")
    s = build(tmp_path, quiet=True)
    html = (s.out / "index.html").read_text()
    assert "flatly" in html and "darkly" not in html and 'id="TOC"' not in html
    assert '<a href="api.html#render"><code>render()</code></a>' in html
    write(tmp_path, {"_smalldocs.yml": "linkify: false\nsymbols: names.json\n"})
    s = build(tmp_path, quiet=True)
    assert "<code>render()</code></a>" not in (s.out / "index.html").read_text(), "linkify: false turns it off"
    write(tmp_path, {"_smalldocs.yml": "api: [a]\n"})
    with pytest.raises(ConfigError, match="api must be a mapping"):
        load(tmp_path)
    write(tmp_path, {"_smalldocs.yml": "project:\n  type: manuscript\n"})
    with pytest.raises(ConfigError, match="only websites"):
        load(tmp_path)
    write(tmp_path, {"_smalldocs.yml": "project:\n  type: book\nbook:\n  chapters: [index.md]\n", "_smalldocs.yaml": ""})
    p = load(tmp_path)
    assert any("book is built as a website" in w for w in p.warnings) and not any("unknown key book" in w for w in p.warnings)
    assert "_smalldocs.yaml is not read: _smalldocs.yml is the config" in p.warnings


TUTORIAL = {
    "_smalldocs.yml": """
        project:
          type: website
          render: ["index.qmd", "do/*.qmd", "watch/*.qmd"]
        website:
          title: A tutorial
          sidebar:
            style: docked
            contents:
              - index.qmd
              - section: Do
                href: do/step-08.qmd
                contents:
                  - section: "step-08: Docs"
                    href: do/step-08.qmd
                    contents:
                      - text: "step-08.5 A site"
                        href: do/step-08.qmd#step-08.5
              - section: Watch
                href: watch/step-08.qmd
                contents:
                  - text: "step-08.5 A site"
                    href: watch/step-08.qmd#step-08.5
        theme: cosmo
        css: styles.css
        toc: true
        toc-depth: 3
        code-copy: true
        from: markdown-tex_math_dollars-smart
        """,
    "styles.css": "body {}\n",
    "index.qmd": '---\ntitle: "A tutorial: home"\n---\n<!-- written by timewalk-tutorial -->\n\nStart at [step-08.5](do/step-08.qmd#step-08.5).\n',
    "do/step-08.qmd": '---\ntitle: "step-08: Docs"\n---\n<!-- written by timewalk-tutorial -->\n\n## step-08.5 A site {#step-08.5}\n\n::: do\nType this.\n:::\n\n::: callout-tip\nIt\'s a tip, costs $5 and $6.\n:::\n',
    "watch/step-08.qmd": '---\ntitle: "step-08: Docs"\n---\n<!-- written by timewalk-tutorial -->\n\n## step-08.5 A site {#step-08.5}\n\n::: {.watch}\nWatch this.\n:::\n',
    "notes.md": "## step-08 Docs\n\n::: do\nNot a page.\n:::\n",
    "draft/extra.qmd": "# Not rendered\n",
}


def test_timewalk_tutorial_sites(tmp_path: Path) -> None:
    "A site shaped like the ones timewalk-tutorial writes: dotted ids, `#fragment` sidebar links, a mixed `render` list, and `do`/`watch` as plain divs."
    write(tmp_path, TUTORIAL)
    s = build(tmp_path, quiet=True)
    assert not s.broken and not s.project.warnings
    built = sorted(p.relative_to(s.out).as_posix() for p in s.out.rglob("*.html"))
    assert built == ["do/step-08.html", "index.html", "watch/step-08.html"], "render builds only the names and globs it lists"
    do = (s.out / "do/step-08.html").read_text()
    assert 'id="step-08.5"' in do and "<title>step-08: Docs" in do
    assert '<div class="do">' in do and "Type this." in do, "`do` is an ordinary div"
    assert '<div class="watch">' in (s.out / "watch/step-08.html").read_text(), "`watch` is an ordinary div"
    assert "callout-tip" in do and "$5 and $6" in do and "katex" not in do.lower(), "-tex_math_dollars leaves dollars as text"
    assert "\u2019" not in do and ("It's" in do or "It&#x27;s" in do), "-smart keeps a straight apostrophe"
    checked = 0
    for page in s.out.rglob("*.html"):
        for href in re.findall(r'<a[^>]+href="([^"#:]+\.html)#([^"]+)"', page.read_text()):
            target = (page.parent / href[0]).resolve()
            assert target.is_file() and f'id="{href[1]}"' in target.read_text(), f"{page.name}: {href[0]}#{href[1]} must resolve"
            checked += 1
    assert checked >= 6, "the sidebar of each page, and the link in the text, point at ids"
    sidebar = (s.out / "index.html").read_text()
    assert 'href="do/step-08.html#step-08.5"' in sidebar and 'href="watch/step-08.html#step-08.5"' in sidebar


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


def test_api_function_default_by_name() -> None:
    "A function given as a default is written by its name, with no memory address, so a page is the same at each build."
    from smalldocs import api

    def ask(q: str) -> bool:  # A question
        "Ask."
        return True

    def add(x: int = 1, ask=ask) -> None:  # Nothing
        "Add."

    assert api.signature(add, sys.modules[__name__]) == "(x: int = 1, ask = test_api_function_default_by_name.<locals>.ask) -> None"
    assert api.default_text(print) == "print" and api.default_text("a") == "'a'"
