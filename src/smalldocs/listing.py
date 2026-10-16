"Listings, as in Quarto: a page that lists other pages as a list, a grid of cards or a table, with categories and a feed."

import datetime as dt
import fnmatch
import html
import json
import math
import posixpath
import re
from email.utils import format_datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from .config import glob_match
from .layout import as_list, format_date

if TYPE_CHECKING:
    from .site import Page, Site

DEFAULT_FIELDS = {
    "default": ["image", "date", "title", "subtitle", "categories", "author", "description", "reading-time"],
    "grid": ["image", "title", "subtitle", "categories", "description", "author", "date", "reading-time"],
    "table": ["date", "title", "author"],
}
FIELD_NAMES = {
    "date": "Date", "title": "Title", "author": "Author", "subtitle": "Subtitle", "description": "Description",
    "reading-time": "Reading Time", "file-modified": "Modified", "filename": "File Name", "categories": "Categories",
    "word-count": "Word Count", "image": "Image",
}  # fmt: skip


def options(
    page: "Page",  # A page with `listing:` in its front matter
) -> list[dict]:  # One dict of options for each listing on the page, each with an `id`
    "Read `listing:`: `true`, a glob, a dict, or a list of dicts."
    raw = page.meta.get("listing")
    items = raw if isinstance(raw, list) else [raw]
    out = []
    for n, o in enumerate(items):
        if o is True or o is None:
            o = {}
        elif isinstance(o, str):
            o = {"contents": o}
        if not isinstance(o, dict):
            continue
        o = dict(o)
        o.setdefault("id", "listing" if n == 0 and len(items) == 1 else f"listing-{n + 1}")
        out.append(o)
    return out


def words(
    text: str,  # HTML
) -> int:  # How many words the HTML holds
    "Count the words of a page's HTML."
    return len(re.sub(r"<[^>]+>", " ", text).split())


def first_paragraph(
    page: "Page",  # A rendered page
    limit: int,  # The longest description, in characters
) -> str:  # Its first paragraph as plain text, cut at the limit
    "Find the description of a page with none: its first paragraph of text, as Quarto does."
    for m in re.finditer(r"<p>(.*?)</p>", page.html, re.S):
        text = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
        if text:
            return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"
    return ""


def item_image(
    site: "Site",  # The site
    item: "Page",  # The page being listed
    on: "Page",  # The listing page
) -> str:  # The link to the item's picture from the listing page, or empty
    "Find the picture of a listed page: `image:` in its front matter, else the first picture in it."
    from .site import rel

    img = item.front.get("image")
    if img:
        return site.resolve("/" + posixpath.normpath(posixpath.join(str(item.src.parent), str(img))), on)
    m = re.search(r'<img[^>]*\ssrc="([^"]+)"', item.html)
    if not m:
        return ""
    src = html.unescape(m.group(1))
    if re.match(r"^[a-z]+:|^//", src):
        return src
    return rel(PurePosixPath(posixpath.normpath(posixpath.join(str(item.out.parent), src))), on)


def sort_items(
    items: list[dict],  # The items, each with its fields
    spec: object,  # `sort:`: such as `date desc`, a list of those, or false
) -> list[dict]:  # The items in order
    "Sort the items as `sort:` says; the default is newest first, then by title."
    if spec is False:
        return items
    specs = as_list(spec) or ["date desc", "title"]
    for s in reversed(specs):
        field, _, way = str(s).partition(" ")
        rev = way.strip().lower() == "desc"

        def key(it: dict, field: str = field) -> tuple:
            v = it["sort"].get(field)
            return (0, v, "") if isinstance(v, int | float) and not isinstance(v, bool) else (1, 0, str(v).lower())

        present = [it for it in items if it["sort"].get(field) is not None]
        missing = [it for it in items if it["sort"].get(field) is None]
        items = sorted(present, key=key, reverse=rev) + missing
    return items


def gather(
    site: "Site",  # The site
    page: "Page",  # The listing page
    opts: dict,  # The listing's options
) -> list["Page"]:  # The pages it lists
    "Find the pages a listing lists: `contents` globs relative to the listing page, else every page in its folder and below."
    base = str(page.src.parent)
    base = "" if base == "." else base + "/"
    pats = []
    for c in [str(c) for c in as_list(opts.get("contents"))] or ["**"]:
        c = str(c)
        target = posixpath.normpath(base + c) if not c.startswith("/") else c.lstrip("/")
        if (site.root / target).is_dir():
            target = target.rstrip("/") + "/**"
        pats.append(target)
    found = []
    for src, p in site.pages.items():
        if p is page or site.hidden(p):
            continue
        if any(glob_match(str(src), pat) for pat in pats):
            found.append(p)
    return found


def item_fields(
    site: "Site",  # The site
    item: "Page",  # A listed page
    on: "Page",  # The listing page
    opts: dict,  # The listing's options
) -> dict:  # Everything a listing shows of the page, and the values it sorts by
    "Read what a listing shows of a page."
    from .site import rel

    authors = [a.get("name", "") if isinstance(a, dict) else str(a) for a in as_list(item.meta.get("author"))]
    n = words(item.html)
    date = item.date
    limit = int(opts.get("max-description-length", 175))
    desc = item.front.get("description")
    d = {
        "href": rel(item.out, on),
        "title": item.title,
        "subtitle": str(item.front.get("subtitle") or ""),
        "description": str(desc) if desc else first_paragraph(item, limit),
        "author": ", ".join(authors),
        "date": format_date(date, opts.get("date-format") or ("M/D/YY" if opts.get("type") == "table" else "MMM D, YYYY")),
        "categories": [str(c) for c in as_list(item.front.get("categories"))],
        "image": item_image(site, item, on),
        "image-alt": str(item.front.get("image-alt") or ""),
        "reading-time": f"{max(1, math.ceil(n / 200))} min",
        "word-count": str(n),
        "filename": item.src.name,
        "file-modified": format_date(dt.date.fromtimestamp(item.mtime), opts.get("date-format") or "MMM D, YYYY") if item.mtime else "",
        "_page": item,
    }
    d["sort"] = {
        "date": date.isoformat() if date else None,
        "title": item.title.lower(),
        "author": d["author"].lower() or None,
        "subtitle": d["subtitle"].lower() or None,
        "filename": item.src.name.lower(),
        "file-modified": item.mtime,
        "reading-time": n,
        "word-count": n,
    }
    for k, v in item.front.items():
        if k not in d and not isinstance(v, bool) and isinstance(v, str | int | float):
            d[k] = str(v)
            d["sort"].setdefault(k, v)
    return d


def data_attrs(
    it: dict,  # A listed item, with its fields
    index: int,  # Its place in the listing
) -> str:  # The `data-` attributes that the listing script filters and sorts by
    "Write the data the listing script reads: categories, sort keys and search text."
    sort = {k: v for k, v in it["sort"].items() if v is not None}
    text = " ".join([it["title"], it["subtitle"], it["description"], it["author"], *it["categories"]]).lower()
    return (
        f' data-index="{index}" data-categories="{html.escape(json.dumps(it["categories"]))}"'
        f' data-sort="{html.escape(json.dumps(sort, default=str))}" data-text="{html.escape(text)}"'
    )


def cats_html(
    it: dict,  # A listed item, with its fields
) -> str:  # The item's categories, each one a filter
    "Write an item's categories; a click filters the listing to one."
    if not it["categories"]:
        return ""
    cats = "".join(f'<div class="listing-category" data-category="{html.escape(c)}">{html.escape(c)}</div>' for c in it["categories"])
    return f'<div class="listing-categories">{cats}</div>'


def img_html(
    it: dict,  # A listed item, with its fields
    opts: dict,  # The listing's options
    cls: str,  # The class of the picture
) -> str:  # The item's picture, or a placeholder
    "Write an item's picture, at `image-height` when given."
    style = f' style="height: {html.escape(str(opts["image-height"]))};"' if opts.get("image-height") else ""
    if it["image"]:
        return f'<img src="{html.escape(it["image"])}" class="{cls}" alt="{html.escape(it["image-alt"])}" loading="lazy"{style}>'
    return f'<div class="listing-item-img-placeholder {cls}"{style}>&nbsp;</div>'


def render_default(
    items: list[dict],  # The items, each with its fields
    fields: list[str],  # The fields to show, in order
    opts: dict,  # The listing's options
) -> str:  # The HTML of a default listing
    "Write a default listing: date on the left, text in the middle, picture on the right."
    out = []
    for n, it in enumerate(items):
        meta = "".join(f'<div class="listing-{f}">{html.escape(it[f])}</div>' for f in ("date", "author", "reading-time") if f in fields and it.get(f))
        body = f'<h3 class="no-anchor listing-title">{html.escape(it["title"])}</h3>' if "title" in fields else ""
        if "subtitle" in fields and it["subtitle"]:
            body += f'<div class="listing-subtitle">{html.escape(it["subtitle"])}</div>'
        body = f'<a href="{html.escape(it["href"])}" class="no-external">{body}</a>'
        if "categories" in fields:
            body += cats_html(it)
        if "description" in fields and it["description"]:
            body += f'<div class="listing-description"><a href="{html.escape(it["href"])}" class="no-external">{html.escape(it["description"])}</a></div>'
        thumb = f'<div class="thumbnail"><a href="{html.escape(it["href"])}" class="no-external">{img_html(it, opts, "thumbnail-image")}</a></div>' if "image" in fields and it["image"] else ""
        out.append(f'<div class="quarto-post image-right"{data_attrs(it, n)}><div class="metadata"><a href="{html.escape(it["href"])}" class="no-external">{meta}</a></div><div class="body">{body}</div>{thumb}</div>')
    return f'<div class="list quarto-listing-default">{"".join(out)}</div>'


def render_grid(
    items: list[dict],  # The items, each with its fields
    fields: list[str],  # The fields to show, in order
    opts: dict,  # The listing's options
) -> str:  # The HTML of a grid of cards
    "Write a grid listing: one card for each page."
    cols = int(opts.get("grid-columns", 3))
    align = opts.get("grid-item-align", "left")
    border = "" if opts.get("grid-item-border", True) is not False else " borderless"
    out = []
    for n, it in enumerate(items):
        card = ""
        if "image" in fields:
            card += f'<p class="card-img-top">{img_html(it, opts, "thumbnail-image card-img")}</p>'
        body = ""
        if "title" in fields:
            body += f'<h5 class="no-anchor card-title listing-title">{html.escape(it["title"])}</h5>'
        if "subtitle" in fields and it["subtitle"]:
            body += f'<div class="card-subtitle listing-subtitle">{html.escape(it["subtitle"])}</div>'
        if "categories" in fields:
            body += cats_html(it)
        if "description" in fields and it["description"]:
            body += f'<div class="card-text listing-description">{html.escape(it["description"])}</div>'
        attrib = "".join(f'<div class="listing-{f}">{html.escape(it[f])}</div>' for f in ("author", "date", "reading-time") if f in fields and it.get(f))
        if attrib:
            body += f'<div class="card-attribution card-text-small {"justify" if "author" in fields and it["author"] else "end"}">{attrib}</div>'
        card += f'<div class="card-body post-contents">{body}</div>'
        out.append(f'<div class="g-col-1"{data_attrs(it, n)}><a href="{html.escape(it["href"])}" class="quarto-grid-link"><div class="quarto-grid-item card h-100 card-{align}{border}">{card}</div></a></div>')
    return f'<div class="list grid quarto-listing-cols-{cols}">{"".join(out)}</div>'


def render_table(
    items: list[dict],  # The items, each with its fields
    fields: list[str],  # The fields to show, in order
    opts: dict,  # The listing's options
) -> str:  # The HTML of a table listing
    "Write a table listing: one row for each page."
    fields = [f for f in fields if f != "image"]
    names = {**FIELD_NAMES, **(opts.get("field-display-names") or {})}
    head = "".join(f'<th class="listing-{f}">{html.escape(names.get(f, f))}</th>' for f in fields)
    rows = []
    for n, it in enumerate(items):
        cells = []
        for f in fields:
            v = it.get(f, "")
            if f == "title":
                cells.append(f'<td><a href="{html.escape(it["href"])}" class="title listing-title">{html.escape(it["title"])}</a></td>')
            elif f == "categories":
                cells.append(f"<td>{cats_html(it)}</td>")
            else:
                cells.append(f'<td><span class="listing-{f}">{html.escape(v if isinstance(v, str) else ", ".join(v))}</span></td>')
        rows.append(f"<tr{data_attrs(it, n)}>{''.join(cells)}</tr>")
    striped = " table-striped" if opts.get("table-striped") else ""
    hover = " table-hover" if opts.get("table-hover") else ""
    return f'<table class="quarto-listing-table table{striped}{hover}"><thead><tr>{head}</tr></thead><tbody class="list">{"".join(rows)}</tbody></table>'


def categories_html(
    items: list[dict],  # Every item of the page's listings
    style: object,  # `categories:`: true, `numbered`, `unnumbered` or `cloud`
) -> str:  # The list of categories for the margin
    "Write the categories of a listing for the margin; a click filters the listing."
    counts: dict[str, int] = {}
    for it in items:
        for c in it["categories"]:
            counts[c] = counts.get(c, 0) + 1
    if not counts:
        return ""
    style = "numbered" if style is True else str(style)
    num = style == "numbered"
    rows = [f'<div class="category" data-category="">All{f" <span class=quarto-category-count>({len(items)})</span>" if num else ""}</div>']
    for c in sorted(counts, key=str.lower):
        size = f' style="font-size: {0.8 + 0.6 * counts[c] / max(counts.values()):.2f}rem"' if style == "cloud" else ""
        rows.append(f'<div class="category" data-category="{html.escape(c)}"{size}>{html.escape(c)}{f" <span class=quarto-category-count>({counts[c]})</span>" if num else ""}</div>')
    return f'<div class="quarto-listing-category-title">Categories</div><div class="quarto-listing-category category-{"cloud" if style == "cloud" else "default"}">{"".join(rows)}</div>'


def expand(
    site: "Site",  # The site, with every page rendered
    page: "Page",  # A page with `listing:`
) -> None:
    "Put the page's listings into its HTML: in an empty div with the listing's id, or at the end."
    all_items: list[dict] = []
    listed: list[Page] = []
    margin_cats = None
    for opts in options(page):
        kind = opts.get("type", "default")
        if kind not in DEFAULT_FIELDS:
            site.warn(f"{page.src}: listing type {kind!r} is not known; using default")
            kind = "default"
        opts["type"] = kind
        pages = gather(site, page, opts)
        listed += pages
        items = [item_fields(site, p, page, opts) for p in pages]
        for inc_key, keep in (("include", True), ("exclude", False)):
            rules = opts.get(inc_key)
            if isinstance(rules, dict):
                items = [it for it in items if all(fnmatch.fnmatch(str(it.get(k, "")), str(v)) or str(v) in it.get("categories", []) for k, v in rules.items()) == keep]
        items = sort_items(items, opts.get("sort"))
        max_items = int(opts.get("max-items") or 0)
        if max_items > 0:
            items = items[:max_items]
        fields = as_list(opts.get("fields")) or DEFAULT_FIELDS[kind]
        body = {"default": render_default, "grid": render_grid, "table": render_table}[kind](items, fields, opts)
        size = int(opts.get("page-size") or 0)
        if size <= 0:
            size = 50 if kind != "grid" else 6 * int(opts.get("grid-columns", 3))
        ui = ""
        sort_ui, filter_ui = opts.get("sort-ui", kind != "grid"), opts.get("filter-ui", kind != "grid")
        if sort_ui or filter_ui:
            sorts = [f for f in ("date", "title", "author") if f in fields]
            sel = ""
            if sort_ui and sorts:
                opts_html = '<option value="">Default</option>' + "".join(
                    f'<option value="{f}:{d}">{FIELD_NAMES[f]} - {label}</option>' for f in sorts for d, label in (("asc", "Oldest" if f == "date" else "Ascending"), ("desc", "Newest" if f == "date" else "Descending"))
                )
                sel = f'<div class="quarto-listing-sort"><select class="form-select form-select-sm listing-sort" aria-label="Order by">{opts_html}</select></div>'
            box = '<div class="quarto-listing-filter"><input type="search" class="form-control form-control-sm listing-filter" placeholder="Filter" aria-label="Filter listings"></div>' if filter_ui else ""
            ui = f'<div class="listing-actions-group">{sel}{box}</div>'
        block = (
            f'<div class="quarto-listing quarto-listing-container-{kind}" id="listing-{html.escape(opts["id"])}" data-page-size="{size}">'
            f'{ui}{body}<div class="listing-no-matching d-none">No matching items</div><nav class="listing-pagination" aria-label="Pages"></nav></div>'
        )
        empty = re.compile(rf'<div id="{re.escape(opts["id"])}"[^>]*>\s*</div>')
        page.html = empty.sub(lambda m, block=block: block, page.html, count=1) if empty.search(page.html) else page.html + block
        all_items += items
        if opts.get("categories"):
            margin_cats = opts["categories"]
        if opts.get("feed"):
            page.env.setdefault("feeds", []).append((opts, items, pages))
    page.env["listing_pages"] = listed
    page.env["listing_categories"] = bool(margin_cats)
    page.env["listing"] = True
    if margin_cats:
        page.env["margin"] = categories_html(all_items, margin_cats)


def write_feeds(
    site: "Site",  # The site, with every page rendered
) -> None:
    "Write an RSS feed for each listing with `feed:`, beside its page, when `website.site-url` is set."
    base = site.project.website.get("site-url")
    for page in site.pages.values():
        for opts, items, _pages in page.env.get("feeds", []):
            if not base:
                site.warn(f"{page.src}: a listing feed needs website.site-url")
                continue
            base_url = base.rstrip("/") + "/"
            feed = opts["feed"] if isinstance(opts["feed"], dict) else {}
            rows = []
            for it in items[: int(feed.get("items", 20))]:
                p = it["_page"]
                link = base_url + str(p.out)
                date = p.date
                pub = f"<pubDate>{format_datetime(dt.datetime(date.year, date.month, date.day, tzinfo=dt.UTC))}</pubDate>" if date else ""
                cats = "".join(f"<category>{html.escape(c)}</category>" for c in it["categories"])
                rows.append(f"<item><title>{html.escape(it['title'])}</title><link>{html.escape(link)}</link><guid>{html.escape(link)}</guid><description>{html.escape(it['description'])}</description>{cats}{pub}</item>")
            title = feed.get("title") or f"{site.project.website.get('title', '')} - {page.title}".strip(" -")
            desc = feed.get("description") or site.project.website.get("description") or title
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>'
                f"<title>{html.escape(title)}</title><link>{html.escape(base_url + str(page.out))}</link><description>{html.escape(str(desc))}</description>"
                f'<atom:link href="{html.escape(base_url + str(page.out.with_suffix(".xml")))}" rel="self" type="application/rss+xml"/>'
                f"<generator>smalldocs</generator>{''.join(rows)}</channel></rss>\n"
            )
            (site.out / page.out.with_suffix(".xml")).write_text(xml, encoding="utf-8")
