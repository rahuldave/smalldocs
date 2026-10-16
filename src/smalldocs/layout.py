"The page around the content, in Quarto's markup: head, navbar, sidebar, title block, table of contents, footer."

import datetime as dt
import html
import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import quote

from fastcore.xml import (
    H1,
    H2,
    A,
    Body,
    Button,
    Div,
    Footer,
    Head,
    Header,
    Html,
    I,
    Li,
    Link,
    Main,
    Meta,
    Nav,
    Ol,
    P,
    Safe,
    Script,
    Span,
    Title,
    Ul,
    to_xml,
)

from . import __version__
from .config import glob_match
from .markdown import render as md_render

if TYPE_CHECKING:
    from .site import Page, Site

KATEX = "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist"
MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.esm.min.mjs"
DARK_BG = {"primary", "dark", "secondary", "success", "danger", "info", "black"}
# Runs in the head, after the two theme links, before the page paints. A stored choice wins over the mode the browser prefers.
SCHEME_SCRIPT = (
    "(function(){var d=document.documentElement,s=null;try{s=localStorage.getItem('smalldocs-scheme')}catch(e){}"
    "var alt=s?s==='alternate':!!(window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches);"
    "var ls=document.querySelectorAll('link.quarto-color-scheme');if(alt)d.dataset.scheme='alternate';"
    "if(s)ls.forEach(function(l){var on=l.classList.contains('quarto-color-alternate')===alt;if(on)l.setAttribute('blocking','render');l.media=on?'all':'not all'});"
    "var on=ls[alt?1:0];if(on&&on.dataset.mode==='dark')d.classList.add('quarto-dark')})();"
)


def as_list(
    v: object,  # A config value
) -> list:  # The value as a list: None is empty, a single value is one item
    "Make a config value that may be one item or a list into a list."
    return [] if v is None else v if isinstance(v, list) else [v]


def inline_md(
    text: str,  # Markdown on one line, from the config
    site: "Site",  # The site, to rewrite links
    page: "Page | None",  # The page the text goes on
) -> str:  # HTML without the paragraph around it
    "Render a short piece of Markdown from the config, such as a footer."
    env = {"link": lambda h, k: site.resolve(h, page)}
    out = md_render(str(text), env).strip()
    m = re.fullmatch(r"<p>(.*)</p>", out, re.S)
    return m.group(1) if m else out


def format_date(
    d: dt.date | None,  # A date
    fmt: str | None = None,  # Quarto's `date-format`, such as `MMMM D, YYYY`, or None for that one
) -> str:  # The date as text
    "Write a date in one of Quarto's formats: the default is `MMMM D, YYYY`."
    if d is None:
        return ""
    fmt = fmt or "MMMM D, YYYY"
    named = {"iso": "YYYY-MM-DD", "full": "dddd, MMMM D, YYYY", "long": "MMMM D, YYYY", "medium": "MMM D, YYYY", "short": "M/D/YY"}
    fmt = named.get(fmt, fmt)
    parts = {
        "YYYY": f"{d.year}", "YY": f"{d.year % 100:02d}", "MMMM": d.strftime("%B"), "MMM": d.strftime("%b"),
        "MM": f"{d.month:02d}", "M": f"{d.month}", "DD": f"{d.day:02d}", "D": f"{d.day}", "dddd": d.strftime("%A"), "ddd": d.strftime("%a"),
    }  # fmt: skip
    return re.sub(r"YYYY|YY|MMMM|MMM|MM|M|DD|D|dddd|ddd", lambda m: parts[m.group(0)], fmt)


# ---------------------------------------------------------------- navigation


@dataclass
class Item:
    "One entry of a sidebar or navbar: a page, a link, a section or a separator."

    text: str  # What the entry says (HTML-safe text)
    href: str = ""  # Where it goes: an output path from the root, or a full URL; empty for a section with no page
    page: "Page | None" = None  # The page it is, if it is one
    children: list["Item"] = field(default_factory=list)  # The entries of a section or menu
    section: bool = False  # Whether it is a section
    icon: str = ""  # A Bootstrap icon name
    sep: bool = False  # Whether it is a separator line

    def pages(self) -> list["Page"]:  # Every page in this entry and below it, in order
        "List the pages under this entry, in order."
        out = [self.page] if self.page else []
        for c in self.children:
            out += c.pages()
        return out

    def contains(
        self,
        page: "Page",  # A page
    ) -> bool:  # Whether the page is here or below
        "Say whether a page is in this entry."
        return any(p is page for p in self.pages())


class SiteNav:
    "The site's navigation: its sidebars, its navbar, and the order of pages."

    def __init__(
        self,
        site: "Site",  # The site, with its pages read and rendered
    ):
        self.site = site
        web = site.project.website
        bars = as_list(web.get("sidebar"))
        if site.project.project.get("type") == "book" and not bars:
            bars = [{"contents": (site.project.config.get("book") or {}).get("chapters") or []}]
        self.sidebars = []
        for n, sb in enumerate(bars):
            sb = sb if isinstance(sb, dict) else {"contents": sb}
            contents = sb.get("contents") or []
            items = self.expand(as_list(contents)) if contents else []
            self.sidebars.append({**sb, "items": items, "id": sb.get("id") or f"sidebar-{n}"})
        nb = web.get("navbar")
        self.navbar = nb if isinstance(nb, dict) else ({} if nb else None)
        if self.navbar is not None:
            self.left = self.expand(as_list(self.navbar.get("left")), nav=True)
            self.right = self.expand(as_list(self.navbar.get("right")), nav=True)
        self._sections = 0

    # ---- reading `contents`

    def page_item(
        self,
        page: "Page",  # The page
        text: str | None = None,  # The text of the entry; None for the page's title
        icon: str = "",  # A Bootstrap icon name, or empty
    ) -> Item:  # An entry for a page
        "Make the entry for a page."
        return Item(text=html.escape(str(text)) if text else html.escape(page.title), href=str(page.out), page=page, icon=icon)

    def glob(
        self,
        pattern: str,  # A glob over source paths, from the config
    ) -> list["Page"]:  # The pages that match, in Quarto's order
        "Find the pages that match a glob, ordered by `order:`, then index first, then path."
        pat = pattern.lstrip("/")
        folder = not is_glob_str(pat)  # a bare folder name means the pages in it
        found = [p for s, p in self.site.pages.items() if glob_match(str(s), pat) or (folder and glob_match(str(s), pat.rstrip("/") + "/*"))]
        return sorted(found, key=lambda p: (p.front.get("order", 10**9) if isinstance(p.front.get("order"), int | float) else 10**9, p.src.stem != "index", str(p.src)))

    def auto(
        self,
        pattern: str = "*",  # A glob, or `*` for every page
    ) -> list[Item]:  # A tree of entries for the pages under a pattern
        "Make Quarto's `auto` tree: one section for each folder, titled by its index page."
        pages = self.glob(pattern if pattern != "*" else "**") if pattern not in ("*", "auto") else list(self.site.pages.values())
        if pattern in ("*", "auto"):
            pages = sorted(pages, key=lambda p: (p.front.get("order", 10**9) if isinstance(p.front.get("order"), int | float) else 10**9, len(p.src.parts), p.src.stem != "index", str(p.src)))
        tree: dict = {}
        for p in pages:
            node = tree
            for part in p.src.parent.parts:
                node = node.setdefault(part, {})
            node.setdefault("__pages__", []).append(p)
        return self.tree_items(tree, PurePosixPath("."))

    def tree_items(
        self,
        node: dict,  # One folder of the tree: its pages and its subfolders
        path: PurePosixPath,  # The folder's path
    ) -> list[Item]:  # The entries of one folder of the auto tree
        "Turn one folder of the auto tree into entries."
        out = [self.page_item(p) for p in node.get("__pages__", []) if not (p.src.stem == "index" and str(path) != ".")]
        for name in sorted(k for k in node if k != "__pages__"):
            sub = node[name]
            index = next((p for p in sub.get("__pages__", []) if p.src.stem == "index"), None)
            title = index.title if index else name.replace("-", " ").replace("_", " ").title()
            out.append(Item(text=html.escape(title), href=str(index.out) if index else "", page=index, section=True, children=self.tree_items(sub, path / name)))
        return out

    def expand(
        self,
        contents: list,  # The `contents:` of a sidebar or section, or a navbar side
        nav: bool = False,  # Whether these are navbar entries, where `menu:` makes a dropdown
    ) -> list[Item]:  # The entries
        "Read a `contents:` list: paths, globs, `auto`, sections, links and separators."
        out: list[Item] = []
        for c in contents:
            if isinstance(c, str):
                if c == "auto":
                    out += self.auto()
                elif is_glob_str(c):
                    out += [self.page_item(p) for p in self.glob(c)]
                elif (page := self.site.find_page(PurePosixPath(c.lstrip("/")))) is not None:
                    out.append(self.page_item(page))
                elif (self.site.root / c).is_dir():
                    out += self.auto(c.rstrip("/") + "/**")
                elif c.strip().startswith("---"):
                    out.append(Item(text="", sep=True))
                else:
                    out.append(Item(text=html.escape(c), href=c))
                continue
            if not isinstance(c, dict):
                continue
            text = c.get("text") or c.get("section") or c.get("part")
            if text and str(text).strip().startswith("---") and not c.get("href"):
                out.append(Item(text="", sep=True))
                continue
            if "section" in c or "part" in c or "chapters" in c:
                href = c.get("href") or c.get("file")
                page = self.site.find_page(PurePosixPath(str(href).lstrip("/"))) if href else None
                kids = c.get("contents", c.get("chapters"))
                if isinstance(kids, str):
                    kids = [kids]
                section = c.get("section") or c.get("part")
                out.append(Item(text=html.escape(str(section)) if section else (html.escape(page.title) if page else ""), href=str(page.out) if page else (href or ""), page=page, section=True, children=self.expand(kids or [])))
                continue
            if "auto" in c:
                for pat in as_list(c["auto"]):
                    out += self.auto(str(pat))
                continue
            if nav and "menu" in c:
                out.append(Item(text=html.escape(str(text or "")), icon=c.get("icon", ""), section=True, children=self.expand(as_list(c["menu"]), nav=True)))
                continue
            href = c.get("href") or c.get("file") or ""
            page = self.site.find_page(PurePosixPath(str(href).lstrip("/"))) if href and not re.match(r"^[a-z]+:", str(href)) else None
            if page:
                out.append(self.page_item(page, text, c.get("icon", "")))
            else:
                out.append(Item(text=html.escape(str(text or href)), href=str(href), icon=c.get("icon", "")))
        return out

    # ---- questions a page asks

    def sidebar_for(
        self,
        page: "Page",  # The page being laid out
    ) -> dict | None:  # The sidebar that holds the page, else the first, else None
        "Find the sidebar to show on a page."
        for sb in self.sidebars:
            if any(i.contains(page) for i in sb["items"]):
                return sb
        return self.sidebars[0] if self.sidebars else None

    def order(
        self,
        page: "Page",  # The page being laid out
    ) -> list["Page"]:  # The pages in the order of the page's sidebar
        "List the pages of the page's sidebar in order, for previous and next."
        sb = self.sidebar_for(page)
        seen, out = set(), []
        for item in sb["items"] if sb else []:
            for p in item.pages():
                if id(p) not in seen:
                    seen.add(id(p))
                    out.append(p)
        return out

    def crumbs(
        self,
        page: "Page",  # The page being laid out
    ) -> list[Item]:  # The sections above the page, then the page
        "Find the breadcrumbs of a page: the sections that hold it."
        sb = self.sidebar_for(page)

        def walk(items: list[Item], trail: list[Item]) -> list[Item] | None:
            for it in items:
                if it.page is page and not it.section:
                    return [*trail, it]
                if it.section:
                    if it.page is page:
                        return [*trail, it]
                    found = walk(it.children, [*trail, it])
                    if found:
                        return found
            return None

        return (walk(sb["items"], []) or []) if sb else []


def is_glob_str(
    s: str,  # A string from the config
) -> bool:  # Whether the string has glob characters
    "Say whether a string is a glob."
    return any(ch in s for ch in "*?[")


# ---------------------------------------------------------------- pieces of the page


class Layout:
    "Lay out one page."

    def __init__(
        self,
        site: "Site",  # The site
        nav: SiteNav,  # Its navigation
        page: "Page",  # The page to lay out
    ):
        self.site, self.nav, self.page = site, nav, page
        self.web = site.project.website
        self.meta = page.meta
        self.sidebar = nav.sidebar_for(page)
        self.n_section = 0

    def href(
        self,
        item_href: str,  # An entry's link: an output path, or a link from the config
    ) -> str:  # The link from this page
        "Write an entry's link from this page: an output path from the root, or a link as given in the config."
        from .site import rel

        if not item_href or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:|^//|^#", item_href):
            return item_href
        if (self.site.out / item_href).suffix == ".html" and PurePosixPath(item_href) in {p.out for p in self.site.pages.values()}:
            return rel(PurePosixPath(item_href), self.page)
        return self.site.resolve(self.root_rel(item_href), self.page)

    def root_rel(
        self,
        href: str,  # A link from the config
    ) -> str:  # A config link, made to start at the root
        "Make a link from the config start at the project root."
        return href if href.startswith("/") else "/" + href

    def logo(
        self,
        own: str | None,  # The logo that the site sets, if any
    ) -> str | None:  # The link to the logo: the site's, else the theme's, else None
        "Find the logo: the site's own, or else the one its theme extension gives."
        if own:
            return self.site.resolve(self.root_rel(own), self.page)
        extra = self.site.theme_extra("logo")
        return self.offset() + quote(str(extra[1])) if extra else None

    def icon(
        self,
        name: str,  # A Bootstrap icon name, or empty
    ) -> list:  # An icon element, or nothing
        "Make a Bootstrap icon."
        return [I(cls=f"bi bi-{name}", role="img"), " "] if name else []

    # ---- head

    def head(self) -> Head:  # The `<head>` element
        "Make the head: title, meta, the theme, icons, our CSS, the site's CSS, and maths when the page has some."
        site, page, m = self.site, self.page, self.meta
        site_title = self.web.get("title") or ""
        title = page.title
        full = title if not site_title or title == site_title else f"{title} – {site_title}"
        offset = self.offset()
        items: list = [
            Meta(charset="utf-8"),
            Meta(name="generator", content=f"smalldocs-{__version__}"),
            Meta(name="viewport", content="width=device-width, initial-scale=1.0, user-scalable=yes"),
        ]
        desc = page.front.get("description") or (self.web.get("description") if page.out.name == "index.html" and page.out.parent == PurePosixPath(".") else None)
        if desc:
            items.append(Meta(name="description", content=str(desc)))
        for a in as_list(m.get("author")):
            items.append(Meta(name="author", content=a.get("name", "") if isinstance(a, dict) else str(a)))
        items.append(Title(full))
        fav = self.web.get("favicon")
        theme_fav = site.theme_extra("favicon")
        if fav:
            items.append(Link(rel="icon", href=self.site.resolve(self.root_rel(fav), page)))
        elif theme_fav:
            items.append(Link(rel="icon", href=offset + quote(str(theme_fav[1]))))
        themes = site.theme_files()
        for n, t in enumerate(themes):
            attrs = {"rel": "stylesheet", "href": f"{offset}site_libs/{quote(t.href)}", "data-mode": t.mode, "cls": f"quarto-color-scheme{' quarto-color-alternate' if n else ''}", "id": f"quarto-bootstrap-{t.mode}"}
            if len(themes) > 1:
                # with no stored choice, the browser loads the mode it prefers before it paints; the script below reads a stored choice
                attrs["media"] = "(prefers-color-scheme: dark)" if n else "not all and (prefers-color-scheme: dark)"
            items.append(Link(**attrs))
        items.append(Link(rel="stylesheet", href=f"{offset}site_libs/bootstrap-icons/bootstrap-icons.min.css"))
        items.append(Link(rel="stylesheet", href=f"{offset}site_libs/smalldocs.css"))
        for css in as_list(m.get("css")):
            items.append(Link(rel="stylesheet", href=self.site.resolve(self.root_rel(str(css)), page)))
        if page.env.get("math"):
            items += [
                Link(rel="stylesheet", href=f"{KATEX}/katex.min.css"),
                Script(src=f"{KATEX}/katex.min.js", defer=True),
                Script(src=f"{KATEX}/contrib/auto-render.min.js", defer=True),
            ]
        if page.env.get("mermaid"):
            dark = "document.documentElement.classList.contains('quarto-dark')"
            items.append(Script(Safe(f"import mermaid from '{MERMAID}';mermaid.initialize({{startOnLoad:true,theme:{dark}?'dark':'default'}});"), type="module"))
        og = self.web.get("open-graph")
        if og:
            items += [Meta(property="og:title", content=title), Meta(property="og:site_name", content=site_title)]
            if desc:
                items.append(Meta(property="og:description", content=str(desc)))
            img = page.front.get("image") or self.web.get("image")
            base = self.web.get("site-url")
            if img and base:
                items.append(Meta(property="og:image", content=base.rstrip("/") + "/" + str(PurePosixPath(page.src.parent) / img).lstrip("./")))
        items.append(Meta(name="smalldocs:offset", content=offset or "./"))
        items.append(Script(src=f"{offset}site_libs/bootstrap/bootstrap.bundle.min.js"))
        if self.search_on():
            items.append(Script(src=f"{offset}site_libs/fuse/fuse.min.js"))
        items.append(Script(src=f"{offset}site_libs/smalldocs.js", defer=True))
        if len(themes) > 1:
            items.append(Script(Safe(SCHEME_SCRIPT)))
        items += [Safe(t) for t in self.includes("include-in-header")]
        return Head(*items)

    def offset(self) -> str:  # The path from the page up to the root, such as `../`
        "Find the path from the page's folder up to the root."
        depth = len(self.page.out.parent.parts)
        return "../" * depth

    def includes(
        self,
        key: str,  # `include-in-header`, `include-before-body` or `include-after-body`
    ) -> list[str]:  # The text of each include
        "Read `include-in-header`, `include-before-body` or `include-after-body`: files, or `text:` entries."
        out = []
        for inc in as_list(self.meta.get(key)):
            if isinstance(inc, dict) and "text" in inc:
                out.append(str(inc["text"]))
            elif isinstance(inc, dict) and "file" in inc:
                inc = inc["file"]
            if isinstance(inc, str):
                f = self.site.root / inc
                if f.is_file():
                    out.append(f.read_text(encoding="utf-8-sig"))
                else:
                    self.site.warn(f"{key}: {inc} is not a file; it is left out")
        return out

    def search_on(self) -> bool:  # Whether the site shows a search box
        "Say whether the site has search: on, unless `website.search: false`."
        s = self.web.get("search", True)
        if isinstance(s, dict):
            return True
        return s is not False

    # ---- navbar

    def nav_item(
        self,
        it: Item,  # The entry
        in_menu: bool = False,  # Whether it is inside a dropdown menu
    ) -> Li:  # The navbar entry
        "Make one navbar entry: a link, or a dropdown menu."
        active = it.page is self.page
        if it.sep:
            return Li(Safe('<hr class="dropdown-divider">'))
        if it.section and it.children:
            self.n_section += 1
            mid = f"nav-menu-{self.n_section}"
            return Li(
                A(*self.icon(it.icon), Span(Safe(it.text), cls="menu-text"), cls="nav-link dropdown-toggle", href="#", id=mid, role="link", data_bs_toggle="dropdown", aria_expanded="false"),
                Ul(*[self.nav_item(c, True) for c in it.children], cls="dropdown-menu", aria_labelledby=mid),
                cls="nav-item dropdown",
            )
        link_cls = ("dropdown-item" if in_menu else "nav-link") + (" active" if active else "")
        attrs = {"aria-current": "page"} if active else {}
        label = [Span(Safe(it.text), cls="menu-text")] if it.text else []
        return Li(A(*self.icon(it.icon), *label, cls=link_cls, href=self.href(it.href), **attrs), cls="" if in_menu else "nav-item")

    def navbar(self) -> list:  # The navbar's elements, or nothing when there is none
        "Make the navbar: the title, the left and right entries, tools, the theme toggle and search."
        if self.nav.navbar is None:
            return []
        nb = self.nav.navbar
        bg = nb.get("background")
        dark = bg in DARK_BG or nb.get("foreground") == "light"
        nav_cls = f"navbar navbar-expand-lg bg-{bg}" if bg else "navbar navbar-expand-lg sd-navbar-default"
        theme = {"data_bs_theme": "dark"} if dark else ({"data_bs_theme": "light"} if bg == "light" else {})
        title = nb.get("title", self.web.get("title"))
        logo = self.logo(nb.get("logo") or self.web.get("logo"))
        brand = []
        if logo:
            brand.append(Safe(f'<img src="{html.escape(logo)}" alt="" class="navbar-logo">'))
        if title is not False and title:
            brand.append(Span(title, cls="navbar-title"))
        home = self.site.resolve("/index.qmd", self.page, record=False) if self.site.find_page(PurePosixPath("index.qmd")) else self.offset() or "./"
        tools = [
            Li(A(I(cls=f"bi bi-{t.get('icon', 'link')}", role="img"), cls="nav-link", href=self.href(str(t.get("href", ""))), aria_label=t.get("text") or t.get("icon")), cls="nav-item compact")
            for t in as_list(nb.get("tools"))
            if isinstance(t, dict)
        ]
        if len(self.site.theme_files()) > 1:
            tools.append(Li(A(I(cls="bi"), cls="quarto-color-scheme-toggle nav-link", href="", title="Toggle dark mode", onclick="window.smalldocsToggleScheme(); return false;"), cls="nav-item compact"))
        search = [Div(self.search_box(), cls="quarto-navbar-tools")] if self.search_on() and nb.get("search", True) is not False else []
        return [
            Nav(
                Div(
                    Div(A(*brand, cls="navbar-brand", href=home), cls="navbar-brand-container mx-auto"),
                    Button(Span(cls="navbar-toggler-icon"), cls="navbar-toggler", type="button", data_bs_toggle="collapse", data_bs_target="#navbarCollapse", aria_controls="navbarCollapse", aria_expanded="false", aria_label="Toggle navigation"),
                    Div(
                        Ul(*[self.nav_item(i) for i in self.nav.left], cls="navbar-nav navbar-nav-scroll me-auto"),
                        Ul(*[self.nav_item(i) for i in self.nav.right], *tools, cls="navbar-nav navbar-nav-scroll ms-auto"),
                        *search,
                        cls="collapse navbar-collapse",
                        id="navbarCollapse",
                    ),
                    cls="navbar-container container-fluid",
                ),
                cls=nav_cls,
                **theme,
            )
        ]

    def search_box(self) -> Div:  # The search box
        "Make the search box; `smalldocs.js` fills the results."
        return Div(
            Safe('<i class="bi bi-search" aria-hidden="true"></i>'),
            Safe('<input type="search" class="form-control form-control-sm" placeholder="Search" aria-label="Search" autocomplete="off">'),
            Div(cls="smalldocs-search-results dropdown-menu"),
            cls="smalldocs-search",
            id="quarto-search",
        )

    # ---- sidebar

    def side_item(
        self,
        it: Item,  # The entry
        depth: int,  # How deep it sits in the sidebar
    ) -> Li:  # The sidebar entry
        "Make one sidebar entry: a page, a link, or a section that folds."
        if it.sep:
            return Li(Div(cls="sidebar-divider"), cls="sidebar-item")
        if it.section:
            self.n_section += 1
            sid = f"quarto-sidebar-section-{self.n_section}"
            level = self.sidebar.get("collapse-level", 2) if self.sidebar else 2
            open_ = depth < level or it.contains(self.page)
            head = (
                A(Span(Safe(it.text), cls="menu-text"), cls=f"sidebar-item-text sidebar-link{' active' if it.page is self.page else ''}", href=self.href(it.href))
                if it.href
                else A(Span(Safe(it.text), cls="menu-text"), cls="sidebar-item-text sidebar-link text-start", data_bs_toggle="collapse", data_bs_target=f"#{sid}", role="navigation", aria_expanded=str(open_).lower())
            )
            toggle = A(I(cls="bi bi-chevron-right ms-2"), cls=f"sidebar-item-toggle text-start{'' if open_ else ' collapsed'}", data_bs_toggle="collapse", data_bs_target=f"#{sid}", role="navigation", aria_expanded=str(open_).lower(), aria_label="Toggle section")
            return Li(
                Div(head, toggle, cls="sidebar-item-container"),
                Ul(*[self.side_item(c, depth + 1) for c in it.children], id=sid, cls=f"collapse list-unstyled sidebar-section depth{depth}{' show' if open_ else ''}"),
                cls="sidebar-item sidebar-item-section",
            )
        active = it.page is self.page
        attrs = {"aria-current": "page"} if active else {}
        return Li(Div(A(*self.icon(it.icon), Span(Safe(it.text), cls="menu-text"), href=self.href(it.href), cls=f"sidebar-item-text sidebar-link{' active' if active else ''}", **attrs), cls="sidebar-item-container"), cls="sidebar-item")

    def sidebar_html(self) -> list:  # The sidebar's elements, or nothing when there is none
        "Make the sidebar, with the site title and search when there is no navbar."
        sb = self.sidebar
        if not sb:
            return []
        style = sb.get("style", "floating")
        header = []
        if self.nav.navbar is None:
            title = sb.get("title", self.web.get("title"))
            logo = self.logo(sb.get("logo") or self.web.get("logo"))
            home = self.offset() or "./"
            bits = []
            if logo:
                bits.append(A(Safe(f'<img src="{html.escape(logo)}" alt="" class="sidebar-logo img-fluid">'), href=home, cls="sidebar-logo-link"))
            if title:
                bits.append(Div(A(title, href=home), cls="sidebar-title mb-0 py-0"))
            tools = []
            if len(self.site.theme_files()) > 1:
                tools.append(A(I(cls="bi"), cls="quarto-color-scheme-toggle sidebar-tool px-1", href="", title="Toggle dark mode", onclick="window.smalldocsToggleScheme(); return false;"))
            for t in as_list(sb.get("tools")):
                if isinstance(t, dict):
                    tools.append(A(I(cls=f"bi bi-{t.get('icon', 'link')}"), href=self.href(str(t.get("href", ""))), cls="sidebar-tool px-1", aria_label=t.get("text") or t.get("icon")))
            if tools:
                bits.append(Div(*tools, cls="sidebar-tools-main"))
            header.append(Div(*bits, cls="pt-lg-2 mt-2 text-left sidebar-header"))
            if self.search_on() and sb.get("search", True) is not False:
                header.append(Div(Div(self.search_box(), cls="sidebar-search"), cls="mt-2 flex-shrink-0 align-items-center"))
        return [
            Nav(
                *header,
                Div(Ul(*[self.side_item(i, 1) for i in sb["items"]], cls="list-unstyled mt-1"), cls="sidebar-menu-container"),
                id="quarto-sidebar",
                cls=f"sidebar collapse collapse-horizontal quarto-sidebar-collapse-item sidebar-navigation {style} overflow-auto",
            ),
            Div(id="quarto-sidebar-glass", cls="quarto-sidebar-collapse-item"),
        ]

    def secondary_nav(self) -> list:  # The bar's elements, or nothing when there is no sidebar
        "Make the narrow-screen bar that opens the sidebar, with the breadcrumbs."
        if not self.sidebar:
            return []
        crumbs = self.crumbs_html("quarto-page-breadcrumbs")
        return [
            Nav(
                Div(
                    Button(I(cls="bi bi-layout-text-sidebar-reverse"), type="button", cls="quarto-btn-toggle btn", aria_controls="quarto-sidebar", aria_label="Toggle sidebar navigation"),
                    *crumbs,
                    cls="container-fluid d-flex",
                ),
                cls="quarto-secondary-nav",
            )
        ]

    def crumbs_html(
        self,
        cls: str,  # The classes of the list
    ) -> list:  # The breadcrumbs' elements, or nothing
        "Make the breadcrumbs: the sections that hold the page."
        if self.web.get("bread-crumbs") is False:
            return []
        trail = self.nav.crumbs(self.page)
        if len(trail) < 2 and cls != "quarto-page-breadcrumbs":
            return []
        lis = []
        for it in trail:
            target = it.href or next((p.out for p in it.pages()), "")
            lis.append(Li(A(Safe(it.text), href=self.href(str(target))) if target else Safe(it.text), cls="breadcrumb-item"))
        return [Nav(Ol(*lis, cls="breadcrumb"), cls=cls, aria_label="breadcrumb")] if lis else []

    # ---- title block, table of contents, page navigation

    def title_block(self) -> list:  # The title block's elements
        "Make the title block: title, subtitle, categories, description, authors and date."
        page, m = self.page, self.meta
        if m.get("title-block-style") == "none" or (not page.front.get("title") and not page.env.get("title")):
            return []
        title_html = page.env.get("title_html") or html.escape(str(page.front["title"]))
        parts = [H1(Safe(title_html), cls="title")]
        if page.front.get("subtitle"):
            parts.append(P(page.front["subtitle"], cls="subtitle lead"))
        cats = as_list(page.front.get("categories"))
        if cats:
            parts.append(Div(*[Div(Safe(self.category_link(str(c))), cls="quarto-category") for c in cats], cls="quarto-categories"))
        block: list = [*self.crumbs_html("quarto-page-breadcrumbs quarto-title-breadcrumbs d-none d-lg-block"), Div(*parts, cls="quarto-title")]
        if page.front.get("description"):
            block.append(Div(Div(Safe(inline_md(str(page.front["description"]), self.site, page)), cls="description")))
        meta = []
        authors = [a.get("name", "") if isinstance(a, dict) else str(a) for a in as_list(m.get("author"))]
        if authors:
            meta.append(Div(Div("Author" if len(authors) == 1 else "Authors", cls="quarto-title-meta-heading"), Div(*[P(a) for a in authors], cls="quarto-title-meta-contents")))
        if page.date:
            meta.append(Div(Div("Published", cls="quarto-title-meta-heading"), Div(P(format_date(page.date, m.get("date-format")), cls="date"), cls="quarto-title-meta-contents")))
        if m.get("date-modified"):
            from .site import parse_date

            meta.append(Div(Div("Modified", cls="quarto-title-meta-heading"), Div(P(format_date(parse_date(m["date-modified"], page.mtime), m.get("date-format")), cls="date-modified"), cls="quarto-title-meta-contents")))
        block.append(Div(*meta, cls="quarto-title-meta"))
        banner = m.get("title-block-banner")
        cls = "quarto-title-block default" + (" quarto-title-banner page-columns page-full" if banner else "")
        return [Header(*block, id="title-block-header", cls=cls)]

    def category_link(
        self,
        cat: str,  # A category of the page
    ) -> str:  # HTML: the category, linked to the listing that shows it
        "Link a category to the listing page that lists this page, filtered to it, as Quarto does."
        hosts = [o for o in self.site.pages.values() if any(p is self.page for p in o.env.get("listing_pages", []))]
        hosts.sort(key=lambda o: not o.env.get("listing_categories"))
        for other in hosts[:1]:
                from .site import rel

                return f'<a href="{html.escape(rel(other.out, self.page))}#category={html.escape(cat)}">{html.escape(cat)}</a>'
        return html.escape(cat)

    def toc(self) -> list:  # The table of contents' elements, or nothing
        "Make the table of contents from the page's headings, to `toc-depth` (3)."
        m = self.meta
        if not m.get("toc"):
            return []
        depth = int(m.get("toc-depth", 3))
        heads = [h for h in self.page.env.get("headings", []) if h["level"] <= depth and not h.get("tab") and "unlisted" not in h["classes"]]
        if not heads:
            return []
        top = min(h["level"] for h in heads)
        root: list = []
        stack: list[tuple[int, list]] = [(top - 1, root)]
        for h in heads:
            while stack[-1][0] >= h["level"]:
                stack.pop()
            kids: list = []
            text = html.escape(h["text"])
            stack[-1][1].append((A(Safe(text), href=f"#{h['id']}", id=f"toc-{h['id']}", cls="nav-link", data_scroll_target=f"#{h['id']}"), kids))
            stack.append((h["level"], kids))

        def ul(items: list) -> Ul:
            return Ul(*[Li(a, *([ul(k)] if k else [])) for a, k in items])

        title = m.get("toc-title", "On this page")
        return [Nav(H2(title, id="toc-title"), ul(root), id="TOC", role="doc-toc", cls="toc-active")]

    def repo_actions(self) -> list:  # The links' elements, or nothing
        "Make the repository links under the table of contents: edit, source, issue."
        acts = as_list(self.web.get("repo-actions"))
        url = self.web.get("repo-url")
        if not acts or not url or acts == ["none"]:
            return []
        url = url.rstrip("/")
        branch = self.web.get("repo-branch", "main")
        sub = (self.web.get("repo-subdir") or "").strip("/")
        path = f"{sub}/{self.page.src}" if sub else str(self.page.src)
        links = {
            "edit": ("Edit this page", f"{url}/edit/{branch}/{path}", "pencil"),
            "source": ("View source", f"{url}/blob/{branch}/{path}", "code"),
            "issue": ("Report an issue", f"{url}/issues/new", "chat-right"),
        }
        return [Div(*[Div(A(I(cls=f"bi bi-{links[a][2]}"), " ", links[a][0], href=links[a][1], cls="toc-action"), cls="action-links") for a in acts if a in links], cls="toc-actions")]

    def page_navigation(self) -> list:  # The links' elements, or nothing
        "Make the links to the previous and next pages of the sidebar, when `page-navigation` is on."
        if not self.web.get("page-navigation") or self.meta.get("page-navigation") is False:
            return []
        order = self.nav.order(self.page)
        idx = next((i for i, p in enumerate(order) if p is self.page), None)
        if idx is None:
            return []
        prev = order[idx - 1] if idx > 0 else None
        nxt = order[idx + 1] if idx + 1 < len(order) else None
        from .site import rel

        def link(p: "Page | None", side: str) -> Div:
            if not p:
                return Div(cls=f"nav-page nav-page-{side}")
            arrow = I(cls=f"bi bi-arrow-{'left' if side == 'previous' else 'right'}-short")
            text = Span(Safe(html.escape(p.title)), cls="nav-page-text")
            inner = [arrow, " ", text] if side == "previous" else [text, " ", arrow]
            return Div(A(*inner, href=rel(p.out, self.page), cls="pagination-link"), cls=f"nav-page nav-page-{side}")

        return [Nav(link(prev, "previous"), link(nxt, "next"), cls="page-navigation")]

    def footer(self) -> list:  # The footer's elements, or nothing
        "Make the footer from `website.page-footer`: one text, or left, center and right."
        pf = self.web.get("page-footer")
        if not pf:
            return []
        if isinstance(pf, str | list):
            pf = {"center": pf}
        if not isinstance(pf, dict):
            return []

        def side(v: object) -> list:
            if v is None:
                return []
            if isinstance(v, list):
                items = self.nav.expand(v, nav=True)
                return [Ul(*[self.nav_item(i) for i in items], cls="footer-items list-unstyled")]
            return [Safe(inline_md(str(v), self.site, self.page))]

        return [
            Footer(
                Div(*[Div(*side(pf.get(k)), cls=f"nav-footer-{k}") for k in ("left", "center", "right")], cls="nav-footer"),
                cls="footer",
            )
        ]

    # ---- the whole page

    def body_classes(
        self,
        has_toc: bool,  # Whether the page shows a table of contents
    ) -> str:  # The classes of `<body>`
        "Name the layout in the body's classes, as Quarto does."
        cls = []
        if self.sidebar:
            cls += ["nav-sidebar", self.sidebar.get("style", "floating")]
        if self.nav.navbar is not None:
            cls.append("nav-fixed")
        if not has_toc and not self.page.env.get("margin") and not self.page.env.get("margin_notes"):
            cls.append("fullcontent")
        if self.page.env.get("listing"):
            cls.append("listing")
        return " ".join(cls)

    def render(self) -> str:  # The whole HTML document
        "Put the page together."
        page, m = self.page, self.meta
        toc = self.toc()
        margin = toc + ([Safe(page.env["margin"])] if page.env.get("margin") else []) + self.repo_actions()
        layout_name = m.get("page-layout", "article")
        before = [Safe(t) for t in self.includes("include-before-body")]
        after = [Safe(t) for t in self.includes("include-after-body")]
        header = self.navbar() + self.secondary_nav()
        content_cls = f"quarto-container page-columns page-rows-contents page-layout-{layout_name}"
        content_cls += " has-sidebar" if self.sidebar else ""
        content_cls += " has-margin" if margin or page.env.get("margin_notes") else ""
        main = Main(
            *self.title_block(),
            Safe(page.html),
            *self.page_navigation(),
            cls="content",
            id="quarto-document-content",
        )
        body = Body(
            *before,
            Header(*header, id="quarto-header", cls="headroom sticky-top") if header else "",
            Div(
                *self.sidebar_html(),
                Div(*margin, id="quarto-margin-sidebar", cls="sidebar margin-sidebar") if margin else "",
                main,
                id="quarto-content",
                cls=content_cls,
            ),
            *self.footer(),
            *after,
            Script(Safe(self.preview_script())) if self.site.preview else "",
            cls=self.body_classes(bool(toc)),
        )
        lang = m.get("lang", "en")
        return to_xml(Html(self.head(), body, lang=lang), indent=False)

    def preview_script(self) -> str:  # JavaScript that reloads the page when the site is rebuilt
        "Make the script that `smalldocs preview` adds: it asks for the build number and reloads when it changes."
        return (
            "(()=>{let v=null;const o=document.querySelector('meta[name=\"smalldocs:offset\"]').content;"
            "setInterval(async()=>{try{const r=await fetch(o+'__smalldocs__/version',{cache:'no-store'});const t=await r.text();"
            "if(v!==null&&t!==v){location.reload()}v=t}catch(e){}},700)})();"
        )


def page(
    site: "Site",  # The site
    nav: SiteNav,  # Its navigation
    p: "Page",  # The page to lay out
) -> str:  # The whole HTML document
    "Lay out one page."
    return Layout(site, nav, p).render()


def search_options(
    site: "Site",  # The site
) -> str:  # The options for the search script, as JSON
    "Write the search options."
    return json.dumps({"limit": 20})
