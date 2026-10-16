"The tests of the page and site options that come from Quarto: the table of contents, fonts and colours, navigation, search, meta tags, drafts and comments."

import json
import re
import textwrap
from pathlib import Path

import pytest

from smalldocs.site import Site, build


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


def site(
    tmp_path: Path,  # A folder for the project
    config: str,  # The `_quarto.yml`
    pages: dict[str, str] | None = None,  # More files, such as pages; `index.qmd` is written when it is not given
) -> Site:  # The built site
    "Write a project and build it."
    files = {"_quarto.yml": config, "index.qmd": "---\ntitle: Home\n---\n\n## One\n\n### One a\n\n## Two\n\n### Two a\n"}
    files.update(pages or {})
    write(tmp_path, files)
    return build(tmp_path, quiet=True)


def out(
    tmp_path: Path,  # The project folder
    page: str = "index.html",  # A page of the site
) -> str:  # The page's HTML
    "Read a built page."
    return (tmp_path / "_site" / page).read_text(encoding="utf-8")


# ---------------------------------------------------------------- the table of contents


def test_toc_location_left_puts_the_toc_in_the_sidebar(tmp_path: Path) -> None:
    "`toc-location: left` puts the table of contents in the sidebar, after the pages, as Quarto does."
    site(tmp_path, "project: {type: website}\nwebsite:\n  sidebar:\n    contents: [index.qmd]\nformat:\n  html:\n    toc: true\n    toc-location: left\n")
    h = out(tmp_path)
    side = re.search(r'<nav id="quarto-sidebar".*?</nav><div id="quarto-sidebar-glass"', h, re.S).group(0)
    assert '<nav id="TOC" role="doc-toc" class="toc-active">' in side
    assert side.index("sidebar-menu-container") < side.index('id="TOC"')
    assert 'id="quarto-margin-sidebar"' not in h


def test_toc_location_left_without_a_sidebar(tmp_path: Path) -> None:
    "With no sidebar, `toc-location: left` makes a sidebar that holds only the table of contents."
    site(tmp_path, "project: {type: website}\nformat:\n  html:\n    toc: true\n    toc-location: left\n")
    h = out(tmp_path)
    assert 'class="sidebar collapse collapse-horizontal sidebar-navigation floating overflow-auto sd-toc-sidebar"><h2 id="toc-title">' not in h
    assert re.search(r'<nav id="quarto-sidebar" class="[^"]*sd-toc-sidebar"><nav id="TOC"', h)
    assert "has-sidebar" in h


@pytest.mark.parametrize("loc,side,body_id", [("body", None, "TOC"), ("left-body", "left", "TOC-body"), ("right-body", "right", "TOC-body")])
def test_toc_location_body(tmp_path: Path, loc: str, side: str | None, body_id: str) -> None:
    "`body` puts the table of contents after the title; `left-body` and `right-body` show it twice, with ids only once."
    site(tmp_path, f"project: {{type: website}}\nwebsite:\n  sidebar:\n    contents: [index.qmd]\nformat:\n  html:\n    toc: true\n    toc-location: {loc}\n")
    h = out(tmp_path)
    main = re.search(r"<main.*?</main>", h, re.S).group(0)
    assert f'<nav id="{body_id}" role="doc-toc">' in main
    assert main.index("</header>") < main.index(f'id="{body_id}"')
    assert '<a href="#one"' in main and 'class="nav-link"' not in main
    assert h.count('id="toc-one"') == 1
    if side == "left":
        assert re.search(r'<nav id="quarto-sidebar".*<nav id="TOC" role="doc-toc" class="toc-active">', h, re.S)
    elif side == "right":
        assert '<div id="quarto-margin-sidebar" class="sidebar margin-sidebar"><nav id="TOC"' in h
    else:
        assert 'class="toc-active"' not in h


def test_toc_expand(tmp_path: Path) -> None:
    "`toc-expand: 1` folds the levels below the first; with no `toc-expand`, every level shows."
    site(tmp_path, "project: {type: website}\nformat:\n  html:\n    toc: true\n    toc-expand: 1\n", {"b.qmd": "---\ntitle: B\n---\n\n## X\n\n### Y\n"})
    h = out(tmp_path)
    assert 'data-toc-expanded="1"' in h
    assert h.count('<ul class="collapse">') == 2
    write(tmp_path, {"_quarto.yml": "project: {type: website}\nformat:\n  html:\n    toc: true\n"})
    build(tmp_path, quiet=True)
    assert "collapse" not in re.search(r'<nav id="TOC".*?</nav>', out(tmp_path), re.S).group(0)
    write(tmp_path, {"_quarto.yml": "project: {type: website}\nformat:\n  html:\n    toc: true\n    toc-expand: true\n"})
    build(tmp_path, quiet=True)
    assert 'data-toc-expanded="99"' in out(tmp_path) and '<ul class="collapse">' not in out(tmp_path)


# ---------------------------------------------------------------- fonts, colours and width


def test_fonts_colours_and_width(tmp_path: Path) -> None:
    "The font, colour and width options set Bootstrap's variables, after smalldocs' stylesheet; links get the colour's RGB too."
    cfg = """
    project: {type: website}
    format:
      html:
        css: my.css
        mainfont: "Georgia, serif"
        monofont: Menlo
        fontsize: 1.1em
        linestretch: 1.7
        linkcolor: "#f00"
        backgroundcolor: "rgb(250, 250, 250)"
        fontcolor: "#222222"
        max-width: 1200px
    """
    site(tmp_path, cfg, {"my.css": "a {}\n"})
    h = out(tmp_path)
    style = re.search(r'<style id="smalldocs-page-style">(.*?)</style>', h).group(1)
    for decl in ("--bs-body-font-family: Georgia, serif;", "--bs-font-monospace: Menlo;", "--sd-root-font-size: 1.1em;", "--bs-body-line-height: 1.7;",
                 "--sd-body-width: 1200px;", "--bs-link-color: #f00;", "--bs-link-color-rgb: 255, 0, 0;", "--bs-body-bg-rgb: 250, 250, 250;",
                 "--bs-body-color: #222222;", "--bs-link-hover-color-rgb: 204, 0, 0;"):  # fmt: skip
        assert decl in style
    assert h.index("smalldocs.css") < h.index("smalldocs-page-style") < h.index("my.css")


def test_css_values_are_checked(tmp_path: Path) -> None:
    "A value that could break out of the style block is left out, with a warning."
    from smalldocs.layout import css_value, rgb_of

    assert css_value("red;} body{display:none") is None and css_value("</style>") is None and css_value("1.2em") == "1.2em"
    assert rgb_of("#abc") == (170, 187, 204) and rgb_of("rgb(1, 2, 3)") == (1, 2, 3) and rgb_of("red") is None
    s = site(tmp_path, 'project: {type: website}\nformat:\n  html:\n    mainfont: "x}</style><script>alert(1)</script>"\n    linkcolor: red\n')
    h = out(tmp_path)
    assert "alert" not in h and "--bs-link-color: red;" in h
    assert any("mainfont" in w for w in s.warnings) and any("linkcolor: red is not a hex" in w for w in s.warnings)


# ---------------------------------------------------------------- navigation entries and logos


def test_nav_entry_attributes(tmp_path: Path) -> None:
    "`target`, `rel`, `aria-label` and `id` reach the links of the navbar, menus, tools, sidebar and footer; `url` is `href`."
    cfg = """
    project: {type: website}
    website:
      navbar:
        left:
          - {text: Ext, href: "https://example.com", target: _blank, rel: noopener, aria-label: External, id: ext}
          - {text: B, url: b.qmd}
          - text: Menu
            menu:
              - {text: M, href: b.qmd, target: _self}
        tools:
          - {icon: github, url: "https://github.com", target: _blank, aria-label: GH}
      sidebar:
        contents:
          - index.qmd
          - {text: B, href: b.qmd, rel: nofollow}
        tools:
          - {icon: twitter, href: "https://twitter.com", target: _blank}
      page-footer:
        left:
          - {text: F, href: "https://example.org", target: _blank}
    """
    site(tmp_path, cfg, {"b.qmd": "# B\n"})
    h = out(tmp_path)
    assert '<a class="nav-link" href="https://example.com" target="_blank" rel="noopener" aria-label="External" id="ext">' in h
    assert '<a class="nav-link" href="b.html"><span class="menu-text">B</span></a>' in h
    assert '<a class="dropdown-item" href="b.html" target="_self">' in h
    assert '<a class="nav-link" href="https://github.com" aria-label="GH" target="_blank">' in h
    assert '<a href="b.html" class="sidebar-item-text sidebar-link" rel="nofollow">' in h
    assert '<a class="nav-link" href="https://example.org" target="_blank">' in h


def test_logo_mappings(tmp_path: Path) -> None:
    "A logo may be `{path, alt}` or `{light, dark}`; two modes give two images, which the dark mode switches."
    from smalldocs.layout import logo_images

    assert logo_images({"light": "a.png", "dark": {"path": "b.png", "alt": "B"}}, "L") == [("a.png", "L", "light-content"), ("b.png", "B", "dark-content")]
    assert logo_images({"path": "a.png", "alt": "A"}) == [("a.png", "A", "")]
    assert logo_images("a.png", "L") == [("a.png", "L", "")]
    cfg = """
    project: {type: website}
    website:
      navbar:
        logo: {light: a.svg, dark: {path: b.svg, alt: Dark}}
        logo-alt: The logo
        logo-href: "https://example.net"
      sidebar:
        contents: [index.qmd]
    """
    site(tmp_path, cfg, {"a.svg": "<svg/>", "b.svg": "<svg/>"})
    h = out(tmp_path)
    assert '<a class="navbar-brand" href="https://example.net"><img src="a.svg" alt="The logo" class="navbar-logo light-content"><img src="b.svg" alt="Dark" class="navbar-logo dark-content">' in h
    assert (tmp_path / "_site" / "b.svg").exists()


def test_sidebar_logo_mapping_and_logo_href(tmp_path: Path) -> None:
    "With no navbar, the sidebar's logo may be a mapping; `logo-href` links the logo, and the title still links to the front page."
    cfg = """
    project: {type: website}
    website:
      title: S
      sidebar:
        logo: {path: a.svg, alt: Side}
        logo-href: b.qmd
        contents: [index.qmd, b.qmd]
    """
    site(tmp_path, cfg, {"a.svg": "<svg/>", "b.qmd": "# B\n", "sub/c.qmd": "# C\n"})
    h = out(tmp_path, "sub/c.html")
    assert '<a href="../b.html" class="sidebar-logo-link"><img src="../a.svg" alt="Side" class="sidebar-logo img-fluid"></a>' in h
    assert '<div class="sidebar-title mb-0 py-0"><a href="../">S</a></div>' in h


# ---------------------------------------------------------------- navbar, sidebar and footer options


def test_navbar_collapse_options(tmp_path: Path) -> None:
    "`collapse-below` names the breakpoint, `collapse: false` never folds, `toggle-position` and `tools-collapse: false` move the parts."
    base = "project: {type: website}\nwebsite:\n  navbar:\n    left: [index.qmd]\n    tools: [{icon: github, href: 'https://github.com'}]\n"
    site(tmp_path, base + "    collapse-below: md\n    toggle-position: left\n    tools-collapse: false\n")
    h = out(tmp_path)
    assert 'class="navbar navbar-expand-md sd-navbar-default sd-toggle-left"' in h
    assert re.search(r'</div><ul class="navbar-nav sd-navbar-tools"><li class="nav-item compact"><a class="nav-link" href="https://github.com"', h)
    write(tmp_path, {"_quarto.yml": base + "    collapse: false\n"})
    build(tmp_path, quiet=True)
    h = out(tmp_path)
    assert 'class="navbar navbar-expand sd-navbar-default"' in h and "navbar-toggler" not in h and "navbarCollapse" not in h


def test_pinned(tmp_path: Path) -> None:
    "The header stays on the screen; `navbar.pinned: false`, or `sidebar.pinned: false` with no navbar, lets it hide on the way down."
    site(tmp_path, "project: {type: website}\nwebsite:\n  navbar:\n    left: [index.qmd]\n")
    assert 'class="headroom sticky-top"' in out(tmp_path)
    write(tmp_path, {"_quarto.yml": "project: {type: website}\nwebsite:\n  navbar:\n    pinned: false\n    left: [index.qmd]\n"})
    build(tmp_path, quiet=True)
    assert 'class="headroom sticky-top sd-headroom"' in out(tmp_path)
    write(tmp_path, {"_quarto.yml": "project: {type: website}\nwebsite:\n  sidebar:\n    pinned: false\n    contents: [index.qmd]\n"})
    build(tmp_path, quiet=True)
    assert 'class="headroom sticky-top sd-headroom"' in out(tmp_path)


def test_sidebar_look_header_and_footer(tmp_path: Path) -> None:
    "The sidebar's colours, border and alignment become classes and variables; `header` and `footer` are Markdown, or a file of it."
    cfg = """
    project: {type: website}
    website:
      title: S
      sidebar:
        background: dark
        foreground: "#eeeeee"
        border: false
        alignment: center
        header: "Side **header**"
        footer: foot.md
        contents: [index.qmd]
    """
    site(tmp_path, cfg, {"foot.md": "From *a file*\n", "_x.md": ""})
    h = out(tmp_path)
    assert re.search(r'<nav id="quarto-sidebar" class="[^"]*sd-sidebar-bg sd-sidebar-fg sd-sidebar-noborder" data-bs-theme="dark" style="--sd-sidebar-bg: var\(--bs-dark\); --sd-sidebar-fg: #eeeeee">', h)
    assert '<div class="quarto-sidebar-header"><div class="sidebar-header-item"><p>Side <strong>header</strong></p></div></div>' in h
    assert '<div class="quarto-sidebar-footer"><div class="sidebar-footer-item"><p>From <em>a file</em></p></div></div></nav>' in h
    assert 'class="pt-lg-2 mt-2 text-center sd-align-center sidebar-header"' in h


def test_page_footer_look(tmp_path: Path) -> None:
    "`page-footer` takes `background`, `foreground` and `border`."
    site(tmp_path, "project: {type: website}\nwebsite:\n  page-footer:\n    background: dark\n    border: false\n    center: Hi\n")
    assert '<footer class="footer sd-footer-bg sd-footer-noborder" data-bs-theme="dark" style="--sd-footer-bg: var(--bs-dark)">' in out(tmp_path)
    write(tmp_path, {"_quarto.yml": "project: {type: website}\nwebsite:\n  page-footer:\n    background: '#123}body{x'\n    center: Hi\n"})
    s = build(tmp_path, quiet=True)
    assert '<footer class="footer">' in out(tmp_path) and any("page-footer.background" in w for w in s.warnings)


# ---------------------------------------------------------------- search


def test_search_options(tmp_path: Path) -> None:
    "`location: sidebar` moves search out of the navbar; `type: overlay` is an icon; `limit` and `keyboard-shortcut` go to the script."
    cfg = """
    project: {type: website}
    website:
      navbar:
        left: [index.qmd]
      sidebar:
        contents: [index.qmd]
      search:
        location: sidebar
        type: overlay
        limit: 7
        keyboard-shortcut: [k, "/"]
    """
    site(tmp_path, cfg)
    h = out(tmp_path)
    assert "quarto-navbar-tools" not in h
    box = re.search(r'<div class="sidebar-search"><div class="smalldocs-search sd-search-overlay" id="quarto-search"([^>]*)><button type="button" class="btn sd-search-toggle"', h)
    assert box and 'data-limit="7"' in box.group(1)
    assert json.loads(re.search(r"data-keyboard-shortcut='([^']*)'", h).group(1)) == ["k", "/"]


def test_search_default_is_unchanged(tmp_path: Path) -> None:
    "With no search options, the box is the navbar's text box, with no data attributes."
    site(tmp_path, "project: {type: website}\nwebsite:\n  navbar:\n    left: [index.qmd]\n")
    assert '<div class="quarto-navbar-tools"><div class="smalldocs-search" id="quarto-search"><i class="bi bi-search"' in out(tmp_path)


# ---------------------------------------------------------------- the head: titles, meta tags, analytics


def test_title_prefix_and_pagetitle(tmp_path: Path) -> None:
    "`title-prefix` replaces the site's title after the page's; `pagetitle` replaces the page's title, and Open Graph shows it bare."
    cfg = "project: {type: website}\nwebsite:\n  title: Site\n  open-graph: true\n  twitter-card: true\n"
    site(tmp_path, cfg, {"a.qmd": "---\ntitle: A\ntitle-prefix: Pre\n---\n", "b.qmd": "---\ntitle: B\npagetitle: Bee\n---\n",
                         "c.qmd": "---\ntitle: Pre\ntitle-prefix: Pre\n---\n", "sub/_metadata.yml": "title-prefix: Sub\n", "sub/d.qmd": "---\ntitle: D\n---\n"})  # fmt: skip
    a = out(tmp_path, "a.html")
    assert "<title>A – Pre</title>" in a and '<meta property="og:title" content="A – Pre">' in a and '<meta name="twitter:title" content="A – Pre">' in a
    assert '<meta property="og:site_name" content="Site">' in a
    b = out(tmp_path, "b.html")
    assert "<title>Bee – Site</title>" in b and '<meta property="og:title" content="Bee">' in b and '<meta name="twitter:title" content="Bee">' in b
    assert "<title>Pre</title>" in out(tmp_path, "c.html")
    assert "<title>D – Sub</title>" in out(tmp_path, "sub/d.html")
    assert "<title>Home – Site</title>" in out(tmp_path)


def test_open_graph_twitter_and_keywords(tmp_path: Path) -> None:
    "`open-graph` takes `locale` and `site-name`; `twitter-card` its tags; `keywords` a meta tag and the title block."
    cfg = """
    project: {type: website}
    website:
      title: Site
      site-url: https://example.com/
      open-graph: {locale: fr_FR, site-name: The Site}
      twitter-card: {creator: "@me", site: "@site"}
    format:
      html:
        keywords: [alpha, beta]
    """
    site(tmp_path, cfg, {"index.qmd": "---\ntitle: Home\nimage: pic.png\n---\n", "pic.png": ""})
    h = out(tmp_path)
    assert '<meta name="keywords" content="alpha, beta">' in h and '<div class="block-title">Keywords</div><p>alpha, beta</p>' in h
    assert '<meta property="og:site_name" content="The Site"><meta property="og:locale" content="fr_FR">' in h
    for tag in ('name="twitter:title" content="Home – Site"', 'name="twitter:image" content="https://example.com/pic.png"', 'name="twitter:creator" content="@me"',
                'name="twitter:site" content="@site"', 'name="twitter:card" content="summary_large_image"'):  # fmt: skip
        assert tag in h


def test_google_analytics(tmp_path: Path) -> None:
    "`google-analytics` adds gtag; `anonymize-ip` and `storage: none` change its config; a bad id is refused."
    site(tmp_path, "project: {type: website}\nwebsite:\n  google-analytics: {tracking-id: G-ABC123, anonymize-ip: true, storage: none}\n")
    h = out(tmp_path)
    assert '<script src="https://www.googletagmanager.com/gtag/js?id=G-ABC123" async></script>' in h
    assert "gtag('config', 'G-ABC123', { 'anonymize_ip': true});" in h and "'analytics_storage': 'denied'" in h
    write(tmp_path, {"_quarto.yml": "project: {type: website}\nwebsite:\n  google-analytics: \"G-1');alert(1)//\"\n"})
    s = build(tmp_path, quiet=True)
    assert "googletagmanager" not in out(tmp_path) and any("google-analytics" in w for w in s.warnings)


# ---------------------------------------------------------------- the page: back to top, links, appendix


def test_back_to_top_other_and_code_links(tmp_path: Path) -> None:
    "`back-to-top-navigation` adds Quarto's link; `other-links` and `code-links` go under the table of contents."
    cfg = """
    project: {type: website}
    website:
      repo-url: https://github.com/me/repo
      back-to-top-navigation: true
      other-links:
        - {text: Other, href: "https://example.org", icon: link}
        - {text: Local, href: b.qmd}
      code-links:
        - repo
        - {text: Code, href: "https://github.com/x", rel: me}
    format:
      html:
        toc: true
    """
    site(tmp_path, cfg, {"b.qmd": "# B\n"})
    h = out(tmp_path)
    assert '<a onclick="window.scrollTo(0, 0); return false;" role="button" id="quarto-back-to-top"><i class="bi bi-arrow-up"></i> Back to top</a>' in h
    toc = re.search(r'<nav id="TOC".*?</nav>', h, re.S).group(0)
    assert '<div class="quarto-other-links"><h2>Other Links</h2><ul><li><a href="https://example.org"><i class="bi bi-link"></i>Other</a></li>' in toc
    assert '<a href="b.html"><i class="bi bi-link-45deg"></i>Local</a>' in toc
    assert '<a href="https://github.com/me/repo"><i class="bi bi-github"></i>GitHub Repo</a>' in toc
    assert '<a href="https://github.com/x" rel="me"><i class="bi bi-file-code"></i>Code</a>' in toc


@pytest.mark.parametrize(
    "lic,html",
    [
        ("CC BY", '<a rel="license" href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>'),
        ("CC BY-SA 3.0", '<a rel="license" href="https://creativecommons.org/licenses/by-sa/3.0/">CC BY-SA 3.0</a>'),
        ("CC0", '<a rel="license" href="https://creativecommons.org/publicdomain/zero/1.0/">CC0 1.0</a>'),
        ("{text: Mine, url: 'https://example.com/l'}", 'Mine <a rel="license" href="https://example.com/l">(View License)</a>'),
        ("All rights *reserved*", "All rights <em>reserved</em>"),
    ],
)
def test_license_and_copyright(tmp_path: Path, lic: str, html: str) -> None:
    "`license` and `copyright` make Quarto's appendix at the end of the page."
    site(tmp_path, f"project: {{type: website}}\nformat:\n  html:\n    license: {lic}\n    copyright: {{holder: Me, year: 2024}}\n")
    h = out(tmp_path)
    assert f'<div id="quarto-appendix" class="default"><section class="quarto-appendix-contents" id="quarto-reuse"><h2 class="anchored quarto-appendix-heading">Reuse</h2><div class="quarto-appendix-contents"><div>{html}</div></div></section>' in h
    assert '<section class="quarto-appendix-contents" id="quarto-copyright"><h2 class="anchored quarto-appendix-heading">Copyright</h2><div class="quarto-appendix-contents"><div>© 2024 Me</div>' in h


def test_external_links_and_smooth_scroll(tmp_path: Path) -> None:
    "`link-external-icon` and `link-external-filter` go to the script on `<main>`; `smooth-scroll` adds Quarto's style."
    site(tmp_path, "project: {type: website}\nformat:\n  html:\n    link-external-icon: true\n    link-external-filter: '^https://mine\\.org'\n    smooth-scroll: true\n")
    h = out(tmp_path)
    assert '<main class="content" id="quarto-document-content" data-external-icon="true" data-external-filter="^https://mine\\.org">' in h
    assert "<style>html{ scroll-behavior: smooth; }</style>" in h


# ---------------------------------------------------------------- drafts


DRAFTS = {
    "index.qmd": "---\ntitle: Home\nlisting:\n  contents: posts\n  feed: true\n---\n",
    "posts/a.qmd": "---\ntitle: A\n---\n\nText of a.\n",
    "posts/d1.qmd": "---\ntitle: Done\ndraft: true\n---\n\nSecret one.\n",
    "posts/d2.qmd": "---\ntitle: Two\n---\n\nSecret two.\n",
}


@pytest.mark.parametrize("mode", ["gone", "unlinked", "visible", None])
def test_draft_modes(tmp_path: Path, mode: str | None) -> None:
    "`gone` leaves drafts out; `unlinked` builds them but nothing lists them; `visible` lists them. `drafts` names more."
    line = f"  draft-mode: {mode}\n" if mode else ""
    cfg = f"project: {{type: website}}\nwebsite:\n  site-url: https://example.com/\n{line}  drafts: [posts/d2.qmd]\n  sidebar:\n    contents: [index.qmd, posts/a.qmd, posts/d1.qmd, posts/d2.qmd]\n"
    site(tmp_path, cfg, DRAFTS)
    built = (tmp_path / "_site/posts/d1.html").exists(), (tmp_path / "_site/posts/d2.html").exists()
    # the listing and the sidebar; in `gone` mode a sidebar entry for a draft is a broken link, as before
    shown = out(tmp_path) if mode in ("unlinked", "visible") else re.search(r'<div class="quarto-listing.*', out(tmp_path), re.S).group(0)
    listed = [x in shown for x in ("d1.html", "d2.html")]
    found = [x in (tmp_path / "_site" / p).read_text() for p in ("search.json", "sitemap.xml", "index.xml") for x in ("d1.html", "d2.html")]
    if mode in ("gone", None):
        assert built == (False, False) and not any(listed) and not any(found)
    elif mode == "unlinked":
        assert built == (True, True) and not any(listed) and not any(found)
        assert '<a href="a.html" class="sidebar-item-text sidebar-link">' in out(tmp_path, "posts/d1.html")
    else:
        assert built == (True, True) and all(listed) and all(found)


# ---------------------------------------------------------------- comments


def test_giscus(tmp_path: Path) -> None:
    "giscus writes Quarto's loader, with each option and the theme of each mode."
    cfg = """
    project: {type: website}
    website:
      comments:
        giscus: {repo: me/repo, repo-id: R_1, category: General, category-id: C_1, reactions-enabled: false, loading: lazy, theme: {light: light, dark: dark_dimmed}, language: fr}
    """
    site(tmp_path, cfg, {"b.qmd": "---\ntitle: B\ncomments: false\n---\n"})
    h = out(tmp_path)
    assert '<input type="hidden" id="giscus-base-theme" value="light"><input type="hidden" id="giscus-alt-theme" value="dark_dimmed">' in h
    for line in ('script.dataset.repo = "me/repo";', 'script.dataset.repoId = "R_1";', 'script.dataset.categoryId = "C_1";', 'script.dataset.mapping = "title";',
                 'script.dataset.reactionsEnabled = "0";', 'script.dataset.inputPosition = "top";', 'script.dataset.lang = "fr";', 'script.dataset.loading = "lazy";'):  # fmt: skip
        assert line in h
    assert h.index("</main>") < h.index("loadGiscus") < h.index("</div><footer") if "<footer" in h else h.index("</main>") < h.index("loadGiscus")
    assert "giscus" not in out(tmp_path, "b.html")


def test_utterances_and_hypothesis(tmp_path: Path) -> None:
    "utterances writes its script tag with its options; Hypothesis its config as JSON, in the head."
    cfg = """
    project: {type: website}
    format:
      html:
        comments:
          utterances: {repo: me/repo, label: talk, theme: github-dark}
          hypothesis: {theme: clean, openSidebar: true}
    """
    site(tmp_path, cfg)
    h = out(tmp_path)
    assert '<script src="https://utteranc.es/client.js" repo="me/repo" issue-term="pathname" label="talk" theme="github-dark" crossorigin="anonymous" async></script>' in h
    head = h[: h.index("</head>")]
    assert '<script type="application/json" class="js-hypothesis-config">' in head and json.loads(re.search(r"js-hypothesis-config\">(.*?)</script>", head, re.S).group(1)) == {"theme": "clean", "openSidebar": True}
    assert '<script src="https://hypothes.is/embed.js" async></script>' in head
