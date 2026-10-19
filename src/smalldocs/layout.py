"The page around the content, in Quarto's markup: head, navbar, sidebar, title block, table of contents, footer."

import datetime as dt
import html
import json
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import quote, urlencode

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
    Section,
    Span,
    Style,
    Title,
    Ul,
    to_xml,
)

from . import __version__
from .config import glob_match, merge
from .markdown import render as md_render

if TYPE_CHECKING:
    from .site import Page, Site

KATEX = "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist"
MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.esm.min.mjs"
DARK_BG = {"primary", "dark", "secondary", "success", "danger", "info", "black"}
LIGHT_BG = {"light", "white"}
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


# Bootstrap's colour names: a value such as `light` in `background` reads the theme's colour, `var(--bs-light)`
PALETTE = {"primary", "secondary", "success", "info", "warning", "danger", "light", "dark", "white", "black", "body"}
NAV_ATTRS = ("target", "rel", "aria-label", "id")
BREAKPOINTS = ("sm", "md", "lg", "xl", "xxl")
SEARCH_KEYS = ("f", "/", "s")
GTAG = "https://www.googletagmanager.com/gtag/js"
GISCUS = "https://giscus.app/client.js"
UTTERANCES = "https://utteranc.es/client.js"
HYPOTHESIS = "https://hypothes.is/embed.js"
CC_LICENSES = {"cc by": "by", "cc by-sa": "by-sa", "cc by-nd": "by-nd", "cc by-nc": "by-nc", "cc by-nc-sa": "by-nc-sa", "cc by-nc-nd": "by-nc-nd"}


def nav_attrs(
    c: dict,  # An entry of a navbar, sidebar, footer or tools, from the config
) -> dict:  # Its `target`, `rel`, `aria-label` and `id`, the ones it sets
    "Read the link attributes of a navigation entry."
    return {k: str(c[k]) for k in NAV_ATTRS if c.get(k) not in (None, "", False)}


def css_value(
    v: object,  # A value from the config, for a CSS property
) -> str | None:  # The value, or None when it could break out of a style block
    "Check a value before it goes into CSS: no `<`, `>`, `{`, `}`, `;`, backslash or line break."
    if v is None or isinstance(v, bool | dict | list):
        return None
    s = str(v).strip()
    return None if not s or re.search(r"[<>{};\\\n\r]|/\*", s) else s


def css_color(
    v: object,  # A colour from the config: a Bootstrap name such as `light`, or a CSS colour
) -> str | None:  # The CSS colour, or None
    "Turn a colour of the config into CSS: a Bootstrap name reads the theme's variable."
    s = css_value(v)
    if s is None:
        return None
    if s == "body":
        return "var(--bs-body-bg)"
    return f"var(--bs-{s})" if s in PALETTE else s


def rgb_of(
    color: str,  # A CSS colour: `#rgb`, `#rrggbb`, or `rgb(r, g, b)`
) -> tuple[int, int, int] | None:  # Its red, green and blue, or None for another form
    "Read the red, green and blue of a hex or `rgb()` colour."
    s = color.strip().lower()
    m = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", s)
    if m:
        h = m.group(1)
        h = "".join(c * 2 for c in h) if len(h) == 3 else h
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    m = re.fullmatch(r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*[\d.]+%?\s*)?\)", s)
    if m and all(int(x) < 256 for x in m.groups()):
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return None


def logo_images(
    logo: object,  # `logo` from the config: a path, `{path, alt}`, or `{light, dark}` where each is a path or `{path, alt}`
    alt: str = "",  # `logo-alt`, for an image with no `alt` of its own
) -> list[tuple[str, str, str]]:  # (path, alt text, extra class) for each image: `light-content` and `dark-content` for two modes
    "Read a logo of the config: one image, or one for the light mode and one for the dark mode."

    def one(v: object) -> tuple[str, str] | None:
        if isinstance(v, dict):
            return (str(v["path"]), str(v.get("alt") or alt)) if v.get("path") else None
        return (str(v), alt) if v else None

    if isinstance(logo, dict) and ("light" in logo or "dark" in logo):
        light, dark = one(logo.get("light")), one(logo.get("dark"))
        light, dark = light or dark, dark or light
        return [(*light, "light-content"), (*dark, "dark-content")] if light else []
    img = one(logo)
    return [(*img, "")] if img else []


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
    attrs: dict = field(default_factory=dict)  # The link's `target`, `rel`, `aria-label` and `id`, from the config

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
        attrs: dict | None = None,  # The link's `target`, `rel`, `aria-label` and `id`
    ) -> Item:  # An entry for a page
        "Make the entry for a page."
        return Item(text=html.escape(str(text)) if text else html.escape(page.title), href=str(page.out), page=page, icon=icon, attrs=attrs or {})

    def listed(self) -> list["Page"]:  # The pages that navigation may show
        "List the pages that the sidebar and the navbar may show: every page but an unlinked draft."
        return [p for p in self.site.pages.values() if not self.site.hidden(p)]

    def glob(
        self,
        pattern: str,  # A glob over source paths, from the config
    ) -> list["Page"]:  # The pages that match, in Quarto's order
        "Find the pages that match a glob, ordered by `order:`, then index first, then path."
        pat = pattern.lstrip("/")
        folder = not is_glob_str(pat)  # a bare folder name means the pages in it
        found = [p for p in self.listed() if glob_match(str(p.src), pat) or (folder and glob_match(str(p.src), pat.rstrip("/") + "/*"))]
        return sorted(found, key=lambda p: (p.front.get("order", 10**9) if isinstance(p.front.get("order"), int | float) else 10**9, p.src.stem != "index", str(p.src)))

    def auto(
        self,
        pattern: str = "*",  # A glob, or `*` for every page
    ) -> list[Item]:  # A tree of entries for the pages under a pattern
        "Make Quarto's `auto` tree: one section for each folder, titled by its index page."
        pages = self.glob(pattern if pattern != "*" else "**") if pattern not in ("*", "auto") else self.listed()
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
                    if not self.site.hidden(page):
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
                href = c.get("href") or c.get("url") or c.get("file")
                page = self.site.find_page(PurePosixPath(str(href).lstrip("/"))) if href else None
                kids = c.get("contents", c.get("chapters"))
                if isinstance(kids, str):
                    kids = [kids]
                section = c.get("section") or c.get("part")
                out.append(Item(text=html.escape(str(section)) if section else (html.escape(page.title) if page else ""), href=str(page.out) if page else (href or ""), page=page, section=True, children=self.expand(kids or []), attrs=nav_attrs(c)))
                continue
            if "auto" in c:
                for pat in as_list(c["auto"]):
                    out += self.auto(str(pat))
                continue
            if nav and "menu" in c:
                out.append(Item(text=html.escape(str(text or "")), icon=c.get("icon", ""), section=True, children=self.expand(as_list(c["menu"]), nav=True)))
                continue
            href = c.get("href") or c.get("url") or c.get("file") or ""
            page = self.site.find_page(PurePosixPath(str(href).lstrip("/"))) if href and not re.match(r"^[a-z]+:", str(href)) else None
            if page and self.site.hidden(page):
                continue
            if page:
                out.append(self.page_item(page, text, c.get("icon", ""), nav_attrs(c)))
            else:
                out.append(Item(text=html.escape(str(text or href)), href=str(href), icon=c.get("icon", ""), attrs=nav_attrs(c)))
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
        own: object,  # The logo that the site sets, if any: a path, or a mapping such as `{light, dark}`
        alt: str = "",  # `logo-alt`, the text of an image with no `alt` of its own
    ) -> list[tuple[str, str, str]]:  # (link, alt text, extra class) for each image: the site's, else the theme's; empty when there is none
        "Find the logo: the site's own, or else the one its theme extension gives."
        if own:
            return [(self.site.resolve(self.root_rel(p), self.page), a, c) for p, a, c in logo_images(own, alt)]
        extra = self.site.theme_extra("logo")
        return [(self.offset() + quote(str(extra[1])), alt, "")] if extra else []

    def logo_html(
        self,
        own: object,  # The logo that the site sets, if any
        alt: str,  # `logo-alt`
        cls: str,  # The class of each image, such as `navbar-logo`
    ) -> str:  # The images, or empty when there is no logo
        "Write the logo: one image, or an image for the light mode and one for the dark mode."
        return "".join(f'<img src="{html.escape(s)}" alt="{html.escape(a)}" class="{cls}{" " + c if c else ""}">' for s, a, c in self.logo(own, alt))

    def icon(
        self,
        name: str,  # A Bootstrap icon name, or empty
    ) -> list:  # An icon element, or nothing
        "Make a Bootstrap icon."
        return [I(cls=f"bi bi-{name}", role="img"), " "] if name else []

    def option(
        self,
        key: str,  # An option that a page or `website:` can set, such as `back-to-top-navigation`
    ) -> object:  # The page's value, else the website's
        "Read an option of the page, or else of `website:`."
        v = self.meta.get(key)
        return self.web.get(key) if v is None else v

    # ---- head

    def head(self) -> Head:  # The `<head>` element
        "Make the head: title, meta, the theme, icons, our CSS, the site's CSS, and maths when the page has some."
        site, page, m = self.site, self.page, self.meta
        site_title = self.web.get("title") or ""
        title = page.title
        # As Quarto: `pagetitle` replaces the title, and `title-prefix` replaces the site's title after it
        first = str(m["pagetitle"]) if m.get("pagetitle") else title
        suffix = str(m["title-prefix"]) if m.get("title-prefix") else site_title
        full = first if not suffix or first == suffix else f"{first} – {suffix}"
        shared = first if m.get("pagetitle") else full  # the title that Twitter shows, as Quarto
        # Open Graph keeps the page's title, as smalldocs always wrote it, unless the page sets `pagetitle` or `title-prefix`
        og_title = first if m.get("pagetitle") else (full if m.get("title-prefix") else title)
        offset = self.offset()
        items: list = [
            Meta(charset="utf-8"),
            Meta(name="generator", content=f"smalldocs-{__version__}"),
            Meta(name="viewport", content="width=device-width, initial-scale=1.0, user-scalable=yes"),
        ]
        if m.get("keywords"):
            items.append(Meta(name="keywords", content=", ".join(str(k) for k in as_list(m["keywords"]))))
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
        if page.env.get("notebook_bundle") or page.env.get("notebook_loader"):
            items.append(Link(rel="stylesheet", href=f"{offset}site_libs/notebooks.css"))
        if page.env.get("notebook_loader"):
            items += [
                Script(src="https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js", defer=True),
                Script(src=f"{offset}site_libs/notebook-loader.js", defer=True),
            ]
        own_style = self.page_style()
        if own_style:
            items.append(Style(Safe(own_style), id="smalldocs-page-style"))
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
        img = page.front.get("image") or self.web.get("image")
        base = self.web.get("site-url")
        if og:
            ogd = og if isinstance(og, dict) else {}
            items += [Meta(property="og:title", content=og_title), Meta(property="og:site_name", content=str(ogd.get("site-name") or site_title))]
            if ogd.get("locale"):
                items.append(Meta(property="og:locale", content=str(ogd["locale"])))
            if desc:
                items.append(Meta(property="og:description", content=str(desc)))
            if img and base:
                items.append(Meta(property="og:image", content=self.absolute(img)))
        items += self.twitter_card(shared, desc, img)
        if m.get("smooth-scroll"):
            items.append(Style(Safe("html{ scroll-behavior: smooth; }")))
        items += self.analytics()
        items += self.hypothesis()
        items.append(Meta(name="smalldocs:offset", content=offset or "./"))
        items.append(Script(src=f"{offset}site_libs/bootstrap/bootstrap.bundle.min.js"))
        if self.search_on():
            items.append(Script(src=f"{offset}site_libs/fuse/fuse.min.js"))
        items.append(Script(src=f"{offset}site_libs/smalldocs.js", defer=True))
        if len(themes) > 1:
            items.append(Script(Safe(SCHEME_SCRIPT)))
        items += [Safe(t) for t in self.includes("include-in-header")]
        return Head(*items)

    def absolute(
        self,
        img: object,  # An image path from the front matter or the config
    ) -> str:  # Its full URL, from `website.site-url`
        "Write the full URL of the page's image, for Open Graph and Twitter."
        return str(self.web.get("site-url")).rstrip("/") + "/" + str(PurePosixPath(self.page.src.parent) / str(img)).lstrip("./")

    def page_style(self) -> str:  # CSS that sets the page's fonts, colours and width, or empty
        "Turn `mainfont`, `monofont`, `fontsize`, `linestretch`, `linkcolor`, `backgroundcolor`, `fontcolor` and `max-width` into CSS variables."
        m, decls, light, width = self.meta, [], [], None
        plain = (("mainfont", "--bs-body-font-family"), ("monofont", "--bs-font-monospace"), ("fontsize", "--sd-root-font-size"), ("linestretch", "--bs-body-line-height"), ("max-width", "--sd-body-width"))
        for key, var in plain:
            if m.get(key) is None:
                continue
            v = css_value(m[key])
            if v is None:
                self.site.warn(f"{self.page.src}: {key}: {m[key]!r} is not used; a value for CSS has no <, >, {{, }}, ; or \\")
                continue
            if key == "max-width":
                width = v
                continue
            decls.append(f"{var}: {v};")
        for key, var in (("linkcolor", "--bs-link-color"), ("backgroundcolor", "--bs-body-bg"), ("fontcolor", "--bs-body-color")):
            if m.get(key) is None:
                continue
            v = css_value(m[key])
            if v is None:
                self.site.warn(f"{self.page.src}: {key}: {m[key]!r} is not used; a value for CSS has no <, >, {{, }}, ; or \\")
                continue
            rgb = rgb_of(v)
            into = decls if key == "linkcolor" else light
            into.append(f"{var}: {v};")
            if rgb:
                into.append(f"{var}-rgb: {rgb[0]}, {rgb[1]}, {rgb[2]};")
                if key == "linkcolor":
                    dark = tuple(round(c * 0.8) for c in rgb)
                    decls.append(f"--bs-link-hover-color: rgb({dark[0]}, {dark[1]}, {dark[2]}); --bs-link-hover-color-rgb: {dark[0]}, {dark[1]}, {dark[2]};")
            else:
                self.site.warn(f"{self.page.src}: {key}: {v} is not a hex or rgb() colour; write one such as #1a5fb4, so that Bootstrap can use it")
        rules = [f":root {{ {' '.join(decls)} }}"] if decls else []
        if light:  # the page's colours are for the light mode; a dark theme keeps its own
            rules.append(f"html:not(.quarto-dark) {{ {' '.join(light)} }}")
        if width:  # the docked and listing layouts set their own width; the page's option wins
            rules.append(f"html body #quarto-content.quarto-container {{ --sd-body-width: {width}; }}")
        return " ".join(rules)

    def twitter_card(
        self,
        full: str,  # The title of the page, as the browser tab shows it
        desc: object,  # The description of the page, or None
        img: object,  # The image of the page, or None
    ) -> list:  # The `twitter:` meta tags, or nothing
        "Make the Twitter card tags from `website.twitter-card`: `true`, or `card-style`, `creator`, `site`, `title`, `description` and `image`."
        tc = self.web.get("twitter-card")
        if not tc:
            return []
        tc = tc if isinstance(tc, dict) else {}
        img = tc.get("image") or img
        url = self.absolute(img) if img and self.web.get("site-url") else None
        out = [Meta(name="twitter:title", content=str(tc.get("title") or full))]
        if tc.get("description") or desc:
            out.append(Meta(name="twitter:description", content=str(tc.get("description") or desc)))
        if url:
            out.append(Meta(name="twitter:image", content=url))
        for k in ("creator", "site"):
            if tc.get(k):
                out.append(Meta(name=f"twitter:{k}", content=str(tc[k])))
        out.append(Meta(name="twitter:card", content=str(tc.get("card-style") or ("summary_large_image" if url else "summary"))))
        return out

    def analytics(self) -> list:  # The Google Analytics scripts, or nothing
        "Make Google Analytics' gtag scripts from `website.google-analytics`: a tracking id, or `tracking-id`, `anonymize-ip` and `storage`."
        ga = self.web.get("google-analytics")
        if not ga:
            return []
        cfg = ga if isinstance(ga, dict) else {"tracking-id": ga}
        tid = str(cfg.get("tracking-id") or "")
        if not re.fullmatch(r"[A-Za-z0-9-]+", tid):
            self.site.warn(f"google-analytics: tracking id {tid!r} is not used; it has letters, digits and - only, such as G-ABC123")
            return []
        consent = "gtag('consent', 'default', {\n  'ad_storage': 'denied',\n  'analytics_storage': 'denied'\n});\n" if cfg.get("storage") == "none" else ""
        anon = ", { 'anonymize_ip': true}" if cfg.get("anonymize-ip") else ""
        js = f"\nwindow.dataLayer = window.dataLayer || [];\nfunction gtag(){{dataLayer.push(arguments);}}\ngtag('js', new Date());\n{consent}gtag('config', '{tid}'{anon});\n"
        return [Script(src=f"{GTAG}?id={tid}", **{"async": True}), Script(Safe(js), type="text/javascript")]

    def comments(self) -> dict:  # The comment services of the page: `giscus`, `utterances`, `hypothesis`
        "Read `comments`: the website's, merged with the page's; `comments: false` on a page turns them off."
        page, web = self.meta.get("comments"), self.web.get("comments")
        if page is False:
            return {}
        return merge(web if isinstance(web, dict) else {}, page if isinstance(page, dict) else {})

    def hypothesis(self) -> list:  # The scripts of Hypothesis, in the head, or nothing
        "Make the scripts of Hypothesis, the annotation service: `comments.hypothesis` is `true` or its options."
        h = self.comments().get("hypothesis")
        if not h:
            return []
        out = []
        src = HYPOTHESIS
        if isinstance(h, dict):
            src = str(h.get("client-url") or HYPOTHESIS)
            cfg = json.dumps(h, indent=2, default=str).replace("</", "<\\/")
            out.append(Script(Safe(f"\n{cfg}\n"), type="application/json", cls="js-hypothesis-config"))
        out.append(Script(src=src, **{"async": True}))
        out.append(Script(Safe("window.document.addEventListener('DOMContentLoaded', function () { document.body.classList.add('hypothesis-enabled'); });")))
        return out

    def comment_threads(self) -> list:  # The scripts of giscus and utterances, after the page's content, or nothing
        "Make the comment threads of giscus or utterances, with their options."
        c, out = self.comments(), []
        g = c.get("giscus")
        if isinstance(g, dict):
            if not (g.get("repo") and g.get("repo-id") and g.get("category-id")):
                self.site.warn("comments.giscus needs repo, repo-id and category-id; smalldocs does not look them up")
            theme = g.get("theme")
            if isinstance(theme, str) and theme:
                base, alt = theme, theme
            else:
                theme = theme if isinstance(theme, dict) else {}
                base, alt = str(theme.get("light") or "light"), str(theme.get("dark") or "dark")
            data = {
                "repo": g.get("repo"), "repoId": g.get("repo-id"), "category": g.get("category"), "categoryId": g.get("category-id"),
                "mapping": g.get("mapping") or "title", "reactionsEnabled": "1" if g.get("reactions-enabled", True) else "0", "emitMetadata": "0",
                "inputPosition": g.get("input-position") or "top", "lang": g.get("language") or "en", "loading": g.get("loading"),
            }  # fmt: skip
            sets = "".join(f"    script.dataset.{k} = {json.dumps(str(v))};\n" for k, v in data.items() if v is not None and v != "")
            js = (
                "\n  function loadGiscus() {\n    const getTheme = () => {\n"
                "      let baseTheme = document.getElementById('giscus-base-theme').value;\n"
                "      let altTheme = document.getElementById('giscus-alt-theme').value;\n"
                "      return document.documentElement.classList.contains('quarto-dark') ? altTheme : baseTheme;\n    };\n"
                f'    const script = document.createElement("script");\n    script.src = "{GISCUS}";\n    script.async = true;\n{sets}'
                '    script.dataset.theme = getTheme();\n    script.crossOrigin = "anonymous";\n'
                '    document.getElementById("quarto-content").appendChild(script);\n  }\n  loadGiscus();\n'
            ).replace("</", "<\\/")
            out += [
                Safe(f'<input type="hidden" id="giscus-base-theme" value="{html.escape(base)}">'),
                Safe(f'<input type="hidden" id="giscus-alt-theme" value="{html.escape(alt)}">'),
                Script(Safe(js)),
            ]
        u = c.get("utterances")
        if isinstance(u, dict):
            if not u.get("repo"):
                self.site.warn("comments.utterances needs repo")
            attrs = {"repo": str(u.get("repo") or ""), "issue-term": str(u.get("issue-term") or "pathname")}
            if u.get("label"):
                attrs["label"] = str(u["label"])
            attrs |= {"theme": str(u.get("theme") or "github-light"), "crossorigin": "anonymous", "async": True}
            out.append(Script(src=UTTERANCES, **attrs))
        return out

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

    def search_opts(self) -> dict:  # The options of `website.search`, or an empty dict
        "Read the options of `website.search`, when it is a mapping."
        s = self.web.get("search")
        return s if isinstance(s, dict) else {}

    def search_where(self) -> str | None:  # `navbar`, `sidebar`, or None for no search box
        "Find where the search box goes: the navbar, unless `search.location: sidebar` or the site has no navbar."
        if not self.search_on():
            return None
        loc = self.search_opts().get("location")
        if loc not in (None, "navbar", "sidebar"):
            self.site.warn(f"search.location: {loc} is not read; smalldocs reads navbar and sidebar")
        nb, sb = self.nav.navbar, self.sidebar
        if nb is not None and not (loc == "sidebar" and sb):
            return "navbar" if nb.get("search", True) is not False else None
        return "sidebar" if sb and sb.get("search", True) is not False else None

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
        attrs = {**it.attrs, **({"aria-current": "page"} if active else {})}
        label = [Span(Safe(it.text), cls="menu-text")] if it.text else []
        return Li(A(*self.icon(it.icon), *label, cls=link_cls, href=self.href(it.href), **attrs), cls="" if in_menu else "nav-item")

    def tool_attrs(
        self,
        t: dict,  # A tool from the config: `icon`, `href` or `url`, `text`, and link attributes
    ) -> dict:  # The tool link's `aria-label`, `target`, `rel` and `id`
        "Read the attributes of a tool's link: its label, from `aria-label`, `text` or `icon`, and `target`, `rel` and `id`."
        return {"aria-label": t.get("text") or t.get("icon"), **nav_attrs(t)}

    def navbar(self) -> list:  # The navbar's elements, or nothing when there is none
        "Make the navbar: the title, the left and right entries, tools, the theme toggle and search."
        if self.nav.navbar is None:
            return []
        nb = self.nav.navbar
        bg = nb.get("background")
        dark = bg in DARK_BG or nb.get("foreground") == "light"
        collapse = nb.get("collapse", True) is not False
        below = nb.get("collapse-below", "lg")
        if below not in BREAKPOINTS:
            self.site.warn(f"navbar.collapse-below: {below} is not read; smalldocs reads {', '.join(BREAKPOINTS)}")
            below = "lg"
        expand = f"navbar-expand-{below}" if collapse else "navbar-expand"
        nav_cls = f"navbar {expand} bg-{bg}" if bg else f"navbar {expand} sd-navbar-default"
        toggle = nb.get("toggle-position")
        if toggle in ("left", "right"):
            nav_cls += f" sd-toggle-{toggle}"
        elif toggle is not None:
            self.site.warn(f"navbar.toggle-position: {toggle} is not read; smalldocs reads left and right")
        theme = {"data_bs_theme": "dark"} if dark else ({"data_bs_theme": "light"} if bg == "light" else {})
        title = nb.get("title", self.web.get("title"))
        brand = []
        logo = self.logo_html(nb.get("logo") or self.web.get("logo"), str(nb.get("logo-alt") or ""), "navbar-logo")
        if logo:
            brand.append(Safe(logo))
        own = self.sidebar_title() if title is not False and title != "" else None
        if own:
            title = own[0]
        if title is not False and title:
            brand.append(Span(title, cls="navbar-title"))
        if nb.get("logo-href"):
            home = self.href(str(nb["logo-href"]))
        else:
            home = self.site.resolve("/index.qmd", self.page, record=False) if self.site.find_page(PurePosixPath("index.qmd")) else self.offset() or "./"
        if own:
            # The sidebar's title goes to its first page; the logo, in a link of its own, still goes to the site's root
            title_link = A(brand[-1], cls="navbar-brand", href=own[1])
            # The logo's link no longer holds the title, so it needs a name of its own when the image has no alt text
            name = {} if nb.get("logo-alt") else {"aria_label": str(nb.get("title") or self.web.get("title") or "Home")}
            brand_html = [A(brand[0], cls="navbar-brand navbar-brand-logo", href=home, **name), title_link] if logo else [title_link]
            brand_cls = "navbar-brand-container sd-brand-split mx-auto"
        else:
            brand_html = [A(*brand, cls="navbar-brand", href=home)]
            brand_cls = "navbar-brand-container mx-auto"
        tools = [
            Li(A(I(cls=f"bi bi-{t.get('icon', 'link')}", role="img"), cls="nav-link", href=self.href(str(t.get("href") or t.get("url") or "")), **self.tool_attrs(t)), cls="nav-item compact")
            for t in as_list(nb.get("tools"))
            if isinstance(t, dict)
        ]
        if len(self.site.theme_files()) > 1:
            tools.append(Li(A(I(cls="bi"), cls="quarto-color-scheme-toggle nav-link", href="", title="Toggle dark mode", onclick="window.smalldocsToggleScheme(); return false;"), cls="nav-item compact"))
        search = [Div(self.search_box(), cls="quarto-navbar-tools")] if self.search_where() == "navbar" else []
        # `tools-collapse: false` keeps the tools out of the menu that folds on a narrow screen
        out_tools = [Ul(*tools, cls="navbar-nav sd-navbar-tools")] if nb.get("tools-collapse") is False and tools else []
        items = [
            Ul(*[self.nav_item(i) for i in self.nav.left], cls="navbar-nav navbar-nav-scroll me-auto"),
            Ul(*[self.nav_item(i) for i in self.nav.right], *([] if out_tools else tools), cls="navbar-nav navbar-nav-scroll ms-auto"),
            *search,
        ]
        if collapse:
            button = Button(Span(cls="navbar-toggler-icon"), cls="navbar-toggler", type="button", data_bs_toggle="collapse", data_bs_target="#navbarCollapse", aria_controls="navbarCollapse", aria_expanded="false", aria_label="Toggle navigation")
            body = [button, Div(*items, cls="collapse navbar-collapse", id="navbarCollapse")]
        else:
            body = items
        return [
            Nav(
                Div(
                    Div(*brand_html, cls=brand_cls),
                    *body,
                    *out_tools,
                    cls="navbar-container container-fluid",
                ),
                cls=nav_cls,
                **theme,
            )
        ]

    def sidebar_title(self) -> tuple[str, str] | None:  # The title of the page's sidebar and the link to its first page, or None
        "Find the title of the page's own sidebar, in a site with several sidebars; a site with one keeps the site's title."
        sb = self.sidebar
        if len(self.nav.sidebars) < 2 or not sb or not isinstance(sb.get("title"), str) or not sb["title"]:
            return None
        if not any(i.contains(self.page) for i in sb["items"]):
            return None
        first = next((p for i in sb["items"] for p in i.pages()), None)
        if first is None:
            return None
        from .site import rel

        return sb["title"], rel(first.out, self.page)

    def search_box(self) -> Div:  # The search box
        "Make the search box; `smalldocs.js` fills the results. `search.type: overlay` shows an icon that opens the box."
        so = self.search_opts()
        attrs = {}
        if so.get("limit") is not None:
            try:
                attrs["data-limit"] = str(max(1, int(so["limit"])))
            except (TypeError, ValueError):
                self.site.warn(f"search.limit: {so['limit']!r} is not a number")
        if so.get("keyboard-shortcut") is not None:
            attrs["data-keyboard-shortcut"] = json.dumps([str(k) for k in as_list(so["keyboard-shortcut"])])
        kind = so.get("type", "textbox")
        if kind not in ("textbox", "overlay"):
            self.site.warn(f"search.type: {kind} is not read; smalldocs reads textbox and overlay")
        field = Safe('<input type="search" class="form-control form-control-sm" placeholder="Search" aria-label="Search" autocomplete="off">')
        results = Div(cls="smalldocs-search-results dropdown-menu")
        if kind == "overlay":
            button = Button(I(cls="bi bi-search"), type="button", cls="btn sd-search-toggle", aria_label="Search", aria_expanded="false")
            return Div(button, field, results, cls="smalldocs-search sd-search-overlay", id="quarto-search", **attrs)
        return Div(Safe('<i class="bi bi-search" aria-hidden="true"></i>'), field, results, cls="smalldocs-search", id="quarto-search", **attrs)

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
                A(Span(Safe(it.text), cls="menu-text"), cls=f"sidebar-item-text sidebar-link{' active' if it.page is self.page else ''}", href=self.href(it.href), **it.attrs)
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
        attrs = {**it.attrs, **({"aria-current": "page"} if active else {})}
        return Li(Div(A(*self.icon(it.icon), Span(Safe(it.text), cls="menu-text"), href=self.href(it.href), cls=f"sidebar-item-text sidebar-link{' active' if active else ''}", **attrs), cls="sidebar-item-container"), cls="sidebar-item")

    def sidebar_part(
        self,
        key: str,  # `header` or `footer`
    ) -> list:  # The part's element, or nothing
        "Make `sidebar.header` or `sidebar.footer`: Markdown, or a file of Markdown, rendered."
        v = self.sidebar.get(key) if self.sidebar else None
        if not v:
            return []
        parts = []
        for text in as_list(v):
            text, base = str(text), ""
            f = self.site.root / text.lstrip("/")
            if len(text) < 256 and "\n" not in text and f.is_file():
                text, base = f.read_text(encoding="utf-8-sig"), posixpath.dirname(str(PurePosixPath(text.lstrip("/"))))

            def link(h: str, kind: str, base: str = base) -> str:  # A link in the header or footer, from the root or from its file
                local = not re.match(r"^([a-zA-Z][\w+.-]*:|/|#|\?)", h)
                return self.site.resolve("/" + posixpath.join(base, h) if local else h, self.page)

            env = {"link": link}
            parts.append(Div(Safe(md_render(text, env).strip()), cls=f"sidebar-{key}-item"))
        return [Div(*parts, cls=f"quarto-sidebar-{key}")]

    def panel_look(
        self,
        opts: dict,  # `website.sidebar` or `website.page-footer`
        name: str,  # `sidebar` or `footer`, for the classes and the variables
        where: str,  # The option's name in a warning, such as `page-footer`
    ) -> tuple[str, dict]:  # Classes to add to the panel, and its attributes
        "Read `background`, `foreground` and `border` of the sidebar or the footer: CSS variables on it, and its classes."
        cls, style, attrs = "", [], {}
        for key, var in (("background", f"--sd-{name}-bg"), ("foreground", f"--sd-{name}-fg")):
            if opts.get(key) is None:
                continue
            if not isinstance(opts[key], str):
                self.site.warn(f"{where}.{key}: {opts[key]!r} is not used; give a colour name or a CSS colour")
                continue
            c = css_color(opts[key])
            if c is None:
                self.site.warn(f"{where}.{key}: {opts[key]!r} is not used; a value for CSS has no <, >, {{, }}, ; or \\")
                continue
            style.append(f"{var}: {c}")
            cls += f" sd-{name}-{var[-2:]}"
        bg = opts.get("background") if isinstance(opts.get("background"), str) else None
        if bg in DARK_BG or opts.get("foreground") == "light":
            attrs["data-bs-theme"] = "dark"
        elif bg in LIGHT_BG:
            # a light panel keeps dark text in a dark theme too
            style.append("--bs-body-color: var(--bs-dark); --bs-emphasis-color: var(--bs-black); --sd-muted: rgba(var(--bs-dark-rgb), .7)")
        if opts.get("border") is True:
            cls += f" sd-{name}-border"
        elif opts.get("border") is False:
            cls += f" sd-{name}-noborder"
        if style:
            attrs["style"] = "; ".join(style)
        return cls, attrs

    def sidebar_html(
        self,
        toc: list | None = None,  # A table of contents to put in the sidebar, for `toc-location: left`
    ) -> list:  # The sidebar's elements, or nothing when there is none
        "Make the sidebar, with the site title and search when there is no navbar."
        sb = self.sidebar
        toc = toc or []
        if not sb:
            if not toc:
                return []
            return [Nav(*toc, id="quarto-sidebar", cls="sidebar collapse collapse-horizontal sidebar-navigation floating overflow-auto sd-toc-sidebar")]
        style = sb.get("style", "floating")
        align = sb.get("alignment")
        if align is not None and (not isinstance(align, str) or align not in ("left", "center", "right")):
            self.site.warn(f"sidebar.alignment: {align!r} is not read; smalldocs reads left, center and right")
            align = None
        align_cls = {"center": "text-center sd-align-center", "right": "text-end sd-align-right"}.get(align, "text-left")
        header = []
        if self.nav.navbar is None:
            title = sb.get("title", self.web.get("title"))
            logo = self.logo_html(sb.get("logo") or self.web.get("logo"), str(sb.get("logo-alt") or ""), "sidebar-logo img-fluid")
            home = self.offset() or "./"
            bits = []
            if logo:
                bits.append(A(Safe(logo), href=self.href(str(sb["logo-href"])) if sb.get("logo-href") else home, cls="sidebar-logo-link"))
            if title:
                own = self.sidebar_title()
                bits.append(Div(A(title, href=own[1] if own else home), cls="sidebar-title mb-0 py-0"))
            tools = []
            if len(self.site.theme_files()) > 1:
                tools.append(A(I(cls="bi"), cls="quarto-color-scheme-toggle sidebar-tool px-1", href="", title="Toggle dark mode", onclick="window.smalldocsToggleScheme(); return false;"))
            for t in as_list(sb.get("tools")):
                if isinstance(t, dict):
                    tools.append(A(I(cls=f"bi bi-{t.get('icon', 'link')}"), href=self.href(str(t.get("href") or t.get("url") or "")), cls="sidebar-tool px-1", **self.tool_attrs(t)))
            if tools:
                bits.append(Div(*tools, cls="sidebar-tools-main"))
            header.append(Div(*bits, cls=f"pt-lg-2 mt-2 {align_cls} sidebar-header"))
        if self.search_where() == "sidebar":
            header.append(Div(Div(self.search_box(), cls="sidebar-search"), cls="mt-2 flex-shrink-0 align-items-center"))
        look, attrs = self.panel_look(sb, "sidebar", "sidebar")
        return [
            Nav(
                *self.sidebar_part("header"),
                *header,
                Div(Ul(*[self.side_item(i, 1) for i in sb["items"]], cls="list-unstyled mt-1"), cls="sidebar-menu-container"),
                *toc,
                *self.sidebar_part("footer"),
                id="quarto-sidebar",
                cls=f"sidebar collapse collapse-horizontal quarto-sidebar-collapse-item sidebar-navigation {style} overflow-auto{look}",
                **attrs,
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
        "Make the title block: title, subtitle, categories, description, authors, date and keywords."
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
        if m.get("keywords"):
            words = ", ".join(str(k) for k in as_list(m["keywords"]))
            block.append(Div(Div(Div("Keywords", cls="block-title"), P(words), cls="keywords")))
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

    def toc_location(self) -> tuple[str | None, bool]:  # `left`, `right` or None for the table beside the text; whether one is in the body too
        "Read `toc-location`: `right`, `left`, `body`, `left-body` or `right-body`."
        loc = str(self.meta.get("toc-location") or "right")
        if loc not in ("right", "left", "body", "left-body", "right-body"):
            self.site.warn(f"{self.page.src}: toc-location: {loc} is not read; smalldocs reads right, left, body, left-body and right-body")
            loc = "right"
        side = "left" if loc.startswith("left") else "right" if loc.startswith("right") else None
        return side, loc.endswith("body")

    def toc_expand(self) -> int | None:  # How many levels show before the reader scrolls to a section; None shows every level
        "Read `toc-expand`: `true` shows every level, `false` the top level, a number that many levels."
        v = self.meta.get("toc-expand")
        if v is None:
            return None
        if v is True:
            return 99
        if v is False:
            return 1
        try:
            return max(1, int(v))
        except (TypeError, ValueError):
            self.site.warn(f"{self.page.src}: toc-expand: {v!r} is not read; write true, false or a number")
            return None

    def toc(
        self,
        body: bool = False,  # The table in the text, `toc-location: body`, with plain links
        ids: bool = True,  # Give the links their `toc-` ids; a second table on the page has none
        extra: list | None = None,  # More elements at its end, such as `other-links`
    ) -> list:  # The table of contents' elements, or nothing
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
            if body:
                a = A(Safe(text), href=f"#{h['id']}", **({"id": f"toc-{h['id']}"} if ids else {}))
            else:
                a = A(Safe(text), href=f"#{h['id']}", id=f"toc-{h['id']}", cls="nav-link", data_scroll_target=f"#{h['id']}")
            stack[-1][1].append((a, kids))
            stack.append((h["level"], kids))
        expand = None if body else self.toc_expand()

        def ul(items: list, level: int = 1) -> Ul:
            lis = [Li(a, *([ul(k, level + 1)] if k else [])) for a, k in items]
            return Ul(*lis, cls="collapse") if expand is not None and level > expand else Ul(*lis)

        title = m.get("toc-title", "On this page")
        if body:
            return [Nav(H2(title, **({"id": "toc-title"} if ids else {})), ul(root), *(extra or []), id="TOC" if ids else "TOC-body", role="doc-toc")]
        more = {"data-toc-expanded": str(expand)} if expand is not None else {}
        return [Nav(H2(title, id="toc-title"), ul(root), *(extra or []), id="TOC", role="doc-toc", cls="toc-active", **more)]

    def extra_links(self) -> list:  # The lists of `other-links` and `code-links`, or nothing
        "Make `other-links` and `code-links`: lists of links under the table of contents, as Quarto writes them."
        out = []
        for key, heading, default in (("other-links", "Other Links", "link-45deg"), ("code-links", "Code Links", "file-code")):
            lis = []
            for e in as_list(self.option(key)):
                if e == "repo" and self.web.get("repo-url"):
                    e = {"text": "GitHub Repo", "href": self.web["repo-url"], "icon": "github"}
                if not isinstance(e, dict) or not (e.get("href") or e.get("url")):
                    self.site.warn(f"{key}: {e!r} is not read; give each entry text and href")
                    continue
                href = self.href(str(e.get("href") or e.get("url")))
                lis.append(Li(A(I(cls=f"bi bi-{e.get('icon') or default}"), str(e.get("text") or href), href=href, **nav_attrs(e))))
            if lis:
                out.append(Div(H2(heading), Ul(*lis), cls=f"quarto-{key}"))
        return out

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

    def back_to_top(self) -> list:  # The link, or nothing
        "Make Quarto's Back to top link, when `back-to-top-navigation` is on; `smalldocs.js` shows it as the reader scrolls up."
        if not self.option("back-to-top-navigation"):
            return []
        return [A(I(cls="bi bi-arrow-up"), " Back to top", onclick="window.scrollTo(0, 0); return false;", role="button", id="quarto-back-to-top")]

    def license_html(
        self,
        lic: object,  # `license`: a Creative Commons name such as `CC BY`, a URL, text, or `{text, url}`
    ) -> str:  # HTML for the Reuse section
        "Write the licence: a Creative Commons name links to its deed, as Quarto does."
        if isinstance(lic, dict):
            text = html.escape(str(lic.get("text") or ""))
            url = lic.get("url")
            return text + (f'{" " if text else ""}<a rel="license" href="{html.escape(str(url))}">(View License)</a>' if url else "")
        s = str(lic).strip()
        m = re.fullmatch(r"(cc0|cc by(?:-(?:sa|nd|nc|nc-sa|nc-nd))?)(?:\s+(\d+(?:\.\d+)?))?", s.lower())
        if m and m.group(1) == "cc0":
            return '<a rel="license" href="https://creativecommons.org/publicdomain/zero/1.0/">CC0 1.0</a>'
        if m:
            ver = m.group(2) or "4.0"
            return f'<a rel="license" href="https://creativecommons.org/licenses/{CC_LICENSES[m.group(1)]}/{ver}/">{m.group(1).upper()} {ver}</a>'
        if re.match(r"^https?://", s):
            return f'<a rel="license" href="{html.escape(s)}">{html.escape(s)}</a>'
        return inline_md(s, self.site, self.page)

    def appendix(self) -> list:  # The appendix's elements, or nothing
        "Make Quarto's appendix at the end of the page: Reuse, from `license`, and Copyright, from `copyright`."
        m, secs = self.meta, []
        if m.get("license"):
            secs.append(("quarto-reuse", "Reuse", " ".join(self.license_html(x) for x in as_list(m["license"]))))
        cr = m.get("copyright")
        if cr:
            if isinstance(cr, dict):
                holder = ", ".join(str(h) for h in as_list(cr.get("holder")))
                text = html.escape(str(cr.get("statement") or " ".join(x for x in ("©", str(cr.get("year") or ""), holder) if x)))
            else:
                text = inline_md(str(cr), self.site, self.page)
            secs.append(("quarto-copyright", "Copyright", text))
        if not secs:
            return []
        return [
            Div(
                *[Section(H2(t, cls="anchored quarto-appendix-heading"), Div(Div(Safe(body)), cls="quarto-appendix-contents"), cls="quarto-appendix-contents", id=sid) for sid, t, body in secs],
                id="quarto-appendix",
                cls="default",
            )
        ]

    def footer(self) -> list:  # The footer's elements, or nothing
        "Make the footer from `website.page-footer`: one text, or left, center and right, with its `background`, `foreground` and `border`."
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

        look, attrs = self.panel_look(pf, "footer", "page-footer")
        return [
            Footer(
                Div(*[Div(*side(pf.get(k)), cls=f"nav-footer-{k}") for k in ("left", "center", "right")], cls="nav-footer"),
                cls="footer" + look,
                **attrs,
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

    def pinned(self) -> bool:  # Whether the header stays on the screen as the reader scrolls
        "Read `navbar.pinned`, or with no navbar `sidebar.pinned`: smalldocs keeps the header on the screen unless one is `false`."
        bar = self.nav.navbar if self.nav.navbar is not None else self.sidebar
        return not (bar and bar.get("pinned") is False)

    def main_attrs(self) -> dict:  # Data attributes for `smalldocs.js` on `<main>`, or none
        "Pass `link-external-icon` and `link-external-filter` to `smalldocs.js`, which marks the links to other sites."
        m, out = self.meta, {}
        if m.get("link-external-icon"):
            out["data-external-icon"] = "true"
        if m.get("link-external-filter"):
            out["data-external-filter"] = str(m["link-external-filter"])
        return out

    def notebook_controls(self) -> list:  # Run and download links for an eligible notebook, else nothing
        "Put the notebook's run and download controls in the active theme."
        entry = self.page.env.get("notebook_bundle")
        if not entry:
            return []
        offset = self.offset()
        params = urlencode({"zip": quote(entry["zip"]), "path": entry["path"], "notebook": entry["notebook"]})
        return [Div(
            A(I(cls="bi bi-play-fill", aria_hidden="true"), "Run in browser", href=f"{offset}lab/loader.html?{params}",
              target="_blank", rel="noopener", cls="sd-notebook-button sd-notebook-run"),
            A(I(cls="bi bi-download", aria_hidden="true"), "Download and run", href=offset + quote(entry["zip"]),
              download="", cls="sd-notebook-button", title=f"Download the bundle; run with uvx juv run {entry['notebook']}"),
            cls="sd-notebook-controls", role="group", aria_label="Notebook controls",
        )]

    def render(self) -> str:  # The whole HTML document
        "Put the page together."
        page, m = self.page, self.meta
        side, in_body = self.toc_location()
        links = self.extra_links()
        toc = self.toc(extra=links) if side else []
        loose = [] if toc else links
        right_toc = toc if side == "right" else []
        margin = right_toc + ([Safe(page.env["margin"])] if page.env.get("margin") else []) + loose + self.repo_actions()
        layout_name = m.get("page-layout", "article")
        before = [Safe(t) for t in self.includes("include-before-body")]
        after = [Safe(t) for t in self.includes("include-after-body")]
        header = self.navbar() + self.secondary_nav()
        content_cls = f"quarto-container page-columns page-rows-contents page-layout-{layout_name}"
        content_cls += " has-sidebar" if self.sidebar or (side == "left" and toc) else ""
        content_cls += " has-margin" if margin or page.env.get("margin_notes") else ""
        main = Main(
            *self.title_block(),
            *self.notebook_controls(),
            *(self.toc(body=True, ids=not toc) if in_body else []),
            Safe(page.html),
            *self.back_to_top(),
            *self.appendix(),
            *self.page_navigation(),
            cls="content",
            id="quarto-document-content",
            **self.main_attrs(),
        )
        body = Body(
            *before,
            Header(*header, id="quarto-header", cls="headroom sticky-top" + ("" if self.pinned() else " sd-headroom")) if header else "",
            Div(
                *self.sidebar_html(toc if side == "left" else None),
                Div(*margin, id="quarto-margin-sidebar", cls="sidebar margin-sidebar") if margin else "",
                main,
                *self.comment_threads(),
                id="quarto-content",
                cls=content_cls,
            ),
            *self.footer(),
            *after,
            Script(Safe(self.preview_script())) if self.site.preview else "",
            cls=self.body_classes(bool(right_toc or loose)),
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
