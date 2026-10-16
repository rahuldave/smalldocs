"Build a website: find the pages, read their metadata, render them, lay them out, and write `_site`."

import datetime as dt
import html
import json
import os
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote

import yaml

from . import extensions, layout, listing, shortcodes
from .config import PAGE_EXTS, BuildError, Project, as_list, dir_metadata, filter_paths, glob_match, html_format, load, merge
from .markdown import render, split_front_matter
from .notebook import to_markdown

ASSETS = Path(__file__).parent / "assets"
SKIP_DIRS = {"node_modules", "venv", "env", "renv", "site-packages", "__pycache__"}
SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:|^//")


@dataclass
class Page:
    "One page of the site: where it comes from and goes to, its options, and once rendered, its HTML."

    src: PurePosixPath  # The source, relative to the project root, such as `guide/intro.qmd`
    out: PurePosixPath  # The output, relative to the output folder, such as `guide/intro.html`
    front: dict  # The page's own front matter
    meta: dict  # Every option that applies to it: project, folder, then front matter
    body: str  # Its Markdown, without the front matter (a notebook already turned into Markdown)
    html: str = ""  # The rendered body
    env: dict = field(default_factory=dict)  # What rendering found: headings, search text, maths, ...

    @property
    def title(self) -> str:  # The title: front matter, else a leading heading, else the file name
        "The page's title."
        t = self.env.get("title_text") or self.front.get("title") or self.env.get("title") or self.meta.get("pagetitle")
        return str(t) if t else self.src.stem.replace("-", " ").replace("_", " ")

    @property
    def date(self) -> dt.date | None:  # The page's date, if it has one
        "The page's date, from `date:` (an ISO date, `today`, `now` or `last-modified`)."
        return parse_date(self.meta.get("date"), self.mtime)

    mtime: float = 0.0  # When the source last changed


def parse_date(
    value: object,  # The value of `date:`
    mtime: float = 0.0,  # The source's modification time, for `last-modified`
) -> dt.date | None:  # The date, or None
    "Read a date as Quarto does: ISO text, a YAML date, `today`, `now` or `last-modified`."
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if v in ("today", "now"):
        return dt.date.today()
    if v == "last-modified":
        return dt.date.fromtimestamp(mtime) if mtime else None
    for f in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d", "%m/%d/%Y", "%d %B %Y", "%B %d, %Y", "%b %d, %Y", "%Y-%m"):
        try:
            return dt.datetime.strptime(value.strip(), f).date()
        except ValueError:
            pass
    return None


def is_glob(
    s: str,  # A path, as written in the config
) -> bool:  # Whether the string has glob characters
    "Say whether a path has glob characters."
    return any(c in s for c in "*?[")


def rel(
    target: PurePosixPath | str,  # A path relative to the output root
    page: "Page | None",  # The page the link is written on; None for the root
) -> str:  # The path from the page to the target
    "Write a link from a page to another output file, relative, as Quarto does."
    base = posixpath.dirname(str(page.out)) if page else ""
    r = posixpath.relpath(str(target), base or ".")
    return quote(r, safe="/:@!$,;~+&=")


@dataclass
class ThemeFile:
    "One theme stylesheet of the site: where its CSS comes from, and where the site keeps it."

    name: str  # The theme, as `theme` names it: a Bootswatch theme, a CSS file, or an extension
    mode: str  # `light` or `dark`
    src: Path  # The CSS file to copy
    href: str  # Its path in `site_libs`, such as `themes/cosmo.min.css` or `themes/ac215/ac215.css`
    ext: "extensions.Extension | None" = None  # The extension it comes from, if any


class Site:
    "A project being built."

    def __init__(
        self,
        project: Project,  # The project to build
        quiet: bool = False,  # Print nothing but errors
        preview: bool = False,  # Add the reload script for `smalldocs preview`
    ):
        self.project = project
        self.root = project.root
        self.out = project.output
        self.quiet = quiet
        self.preview = preview
        self.pages: dict[PurePosixPath, Page] = {}
        self.warnings: list[str] = list(project.warnings)
        self.resources: set[PurePosixPath] = set()
        self.broken: list[tuple[str, str]] = []
        self.symbols: dict[str, str] = {}
        self._themes: list[ThemeFile] | None = None

    # ------------------------------------------------------------ messages

    def say(
        self,
        msg: str,  # The line to print
    ) -> None:
        "Print a line, unless quiet."
        if not self.quiet:
            print(msg, file=sys.stderr)

    def warn(
        self,
        msg: str,  # The warning
    ) -> None:
        "Keep a warning, once."
        if msg not in self.warnings:
            self.warnings.append(msg)

    # ------------------------------------------------------------ discovery

    def ignored(
        self,
        path: Path,  # A file under the root
    ) -> bool:  # Whether a file is left out of the site
        "Leave out files under `_` or `.` folders, the output folder, and virtual environments."
        r = path.relative_to(self.root)
        if any(p.startswith((".", "_")) or p in SKIP_DIRS for p in r.parts):
            return True
        return self.out == path or self.out in path.parents

    def walk(self) -> list[Path]:  # Every file under the root that is not left out
        "List the project's files, in order, without the ones Quarto leaves out."
        out = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            d = Path(dirpath)
            dirnames[:] = sorted(n for n in dirnames if not self.ignored(d / n))
            out += [d / f for f in sorted(filenames) if not self.ignored(d / f)]
        return out

    def discover(self) -> list[PurePosixPath]:  # The sources of the pages to render
        "Find the pages: `project.render` when it is given, else every `.qmd`, `.md` and `.ipynb` that is not left out."
        render_list = [str(r) for r in as_list(self.project.project.get("render"))]
        files = [PurePosixPath(p.relative_to(self.root).as_posix()) for p in self.walk()]
        if render_list:
            keep, drop = [], []
            for pat in render_list:
                bare = pat.lstrip("!")
                if bare.endswith("/") or (not is_glob(bare) and (self.root / bare.lstrip("/")).is_dir()):
                    bare = bare.rstrip("/") + "/**"  # a folder means the pages in it
                (drop if pat.startswith("!") else keep).append(bare)
            found = [f for f in files if any(glob_match(str(f), p) for p in keep) and not any(glob_match(str(f), p) for p in drop)]
            for pat in keep:
                if not is_glob(pat) and (self.root / pat).is_file() and PurePosixPath(pat.lstrip("/")) not in found:
                    found.append(PurePosixPath(pat.lstrip("/")))
            return [f for f in found if f.suffix in PAGE_EXTS]
        return [f for f in files if f.suffix in PAGE_EXTS and f.stem.lower() != "readme"]

    def read(
        self,
        src: PurePosixPath,  # The page's source, relative to the root
    ) -> Page:  # The page with its options, not yet rendered
        "Read a page's source and options."
        path = self.root / src
        try:
            text = path.read_text(encoding="utf-8-sig")
            if src.suffix == ".ipynb":
                front, body = to_markdown(text)
            else:
                front, body = split_front_matter(text)
        except (yaml.YAMLError, ValueError, UnicodeDecodeError) as e:
            raise BuildError(f"{src}: {e}") from e
        opts = merge(merge(self.project.html_options(), dir_metadata(self.project, Path(src))), front)
        html = html_format(front.get("format"))[1]
        if isinstance(html, dict):
            opts = merge(opts, html)
        cells = cell_defaults(opts)
        if src.suffix == ".ipynb" and cells:
            front, body = to_markdown(text, cells)
        if "{{<" in body:
            notes: list[str] = []
            body = shortcodes.expand(body, path, self.root, opts, notes)
            for n in notes:
                self.warn(f"{src.parent / n}" if src.parent != PurePosixPath(".") else n)
        out = src.with_suffix(".html")
        return Page(src=src, out=out, front=front, meta=opts, body=body, mtime=path.stat().st_mtime)

    # ------------------------------------------------------------ links

    def find_page(
        self,
        target: PurePosixPath,  # A path relative to the root: a source, an output, or a folder
    ) -> Page | None:  # The page for a source path, or a folder's index
        "Find the page a path points at: the source itself, or a folder's `index` page."
        if target in self.pages:
            return self.pages[target]
        for ext in PAGE_EXTS:
            for cand in (target.with_suffix(ext) if target.suffix in (".html", *PAGE_EXTS) else None, target / f"index{ext}"):
                if cand is not None and cand in self.pages:
                    return self.pages[cand]
        return None

    def resolve(
        self,
        href: str,  # A link as written in a page, or in the config
        page: Page | None,  # The page it is written on; None for the config, which is relative to the root
        record: bool = True,  # Note a broken link
    ) -> str:  # The link to write in the HTML
        "Rewrite a link: pages to their `.html`, `/x` from the root, and local files copied as resources."
        if not href or href.startswith(("#", "?")) or SCHEME.match(href):
            return href
        m = re.match(r"([^#?]*)(.*)", href, re.S)
        path, tail = unquote(m.group(1)), m.group(2)
        if path.startswith("/"):
            joined = posixpath.normpath(path.lstrip("/") or ".")
        else:
            joined = posixpath.normpath(posixpath.join(str(page.src.parent) if page else "", path))
        if joined == ".." or joined.startswith("../"):
            if record:
                self.broken.append((str(page.src) if page else self.project.file, f"{href} (outside the project)"))
            return href
        target = PurePosixPath(joined)
        found = self.find_page(target)
        if found is not None:
            dir_link = found.out.name == "index.html" and path.endswith("/")
            return (rel(found.out.parent, page) + "/" if dir_link else rel(found.out, page)) + tail
        file = self.root / joined
        if target.suffix in PAGE_EXTS and file.is_file():
            # a page that is not built: a draft, or left out by `render`. Never publish its source
            if record:
                self.broken.append((str(page.src) if page else self.project.file, f"{href} (a page that is not built)"))
            return rel(target.with_suffix(".html"), page) + tail
        if file.is_file():
            self.resources.add(target)
            return rel(target, page) + tail
        if file.is_dir():
            return rel(target, page) + ("/" if path.endswith("/") else "") + tail
        if target.suffix in PAGE_EXTS:
            target = target.with_suffix(".html")
        if record and not (self.out / joined).exists():
            self.broken.append((str(page.src) if page else self.project.file, href))
        return rel(target, page) + tail

    # ------------------------------------------------------------ the steps

    def run_scripts(
        self,
        key: str,  # `pre-render` or `post-render`
        inputs: list[PurePosixPath],  # The pages being rendered
    ) -> None:
        "Run `project.pre-render` or `project.post-render`, with Quarto's environment variables."
        scripts = [str(s) for s in as_list(self.project.project.get(key))]
        env = {
            **os.environ,
            "QUARTO_PROJECT_RENDER_ALL": "1",
            "QUARTO_PROJECT_DIR": str(self.root),
            "QUARTO_PROJECT_OUTPUT_DIR": os.path.relpath(self.out, self.root),
            "QUARTO_PROJECT_INPUT_FILES": "\n".join(str(i) for i in inputs),
            "QUARTO_PROJECT_OUTPUT_FILES": "\n".join(str(i.with_suffix(".html")) for i in inputs),
            "SMALLDOCS": "1",
        }
        for s in scripts:
            words = shlex.split(s)
            if len(words) == 1 and words[0].endswith(".py"):
                words = [sys.executable, *words]
            self.say(f"{key}: {s}")
            try:
                r = subprocess.run(words, cwd=self.root, env=env)
            except OSError as e:
                raise BuildError(f"{key} script could not start: {s}: {e}") from e
            if r.returncode:
                raise BuildError(f"{key} script failed with code {r.returncode}: {s}")

    def load_symbols(self) -> None:
        "Read the name index that turns a name in backticks into a link: `_symbols.json`, when linkify is on."
        sd = self.project.smalldocs
        api = sd.get("api") or {}
        filters = [] if self.project.native else filter_paths(self.project.config)
        on = sd.get("linkify", api.get("linkify", bool(api) or any(Path(f).name == "linkify.lua" for f in filters)))
        index = self.root / str(sd.get("symbols") or "_symbols.json")
        if on and index.exists():
            try:
                symbols = json.loads(index.read_text(encoding="utf-8"))
            except ValueError as e:
                raise BuildError(f"{index}: {e}") from e
            self.symbols = {str(k): str(v) for k, v in symbols.items()} if isinstance(symbols, dict) else {}

    def render_page(
        self,
        page: Page,  # The page to render
    ) -> None:
        "Render one page's Markdown into HTML."
        m = page.meta
        env = {
            "title": page.front.get("title"),
            "link": lambda href, kind, page=page: self.resolve(href, page),
            "symbols": self.symbols,
            "code_copy": m.get("code-copy", True) is not False,
            "number_sections": bool(m.get("number-sections")),
            "external_new_window": bool(m.get("link-external-newwindow")),
            "cell_defaults": cell_defaults(m),
        }
        title = page.front.get("title")
        if isinstance(title, str) and re.search(r"[*_`\[<$\\&]", title):
            env["title_html"] = layout.inline_md(title, self, page)
            env["title_text"] = html.unescape(re.sub(r"<[^>]+>", "", env["title_html"]))
        page.html = render(page.body, env, str(m.get("from") or ""))
        page.env = env
        if env.get("unrun"):
            self.warn(f"{page.src}: {len(env['unrun'])} executable cell(s) shown but not run; smalldocs runs no code")

    def check_output(self) -> None:
        "Refuse an output folder that a build must not empty: the project, a folder above it, or a folder that is not a built site."
        out = self.out
        if out == self.root or out in self.root.parents or out == Path.home():
            raise BuildError(f"output-dir {out} holds the project; it is emptied at each build, so give a folder inside or beside it")
        if not out.exists():
            return
        if not out.is_dir():
            raise BuildError(f"output-dir {out} is a file, not a folder")
        if (out / ".git").exists():
            raise BuildError(f"output-dir {out} holds a git repository; it is emptied at each build, so give another folder")
        if any(out.iterdir()) and not (out / "site_libs").is_dir():
            raise BuildError(f"output-dir {out} is not empty and is not a built site (it has no site_libs); it is emptied at each build, so give another folder, or empty it yourself")

    def build(self) -> int:  # The number of pages written
        "Build the whole site into the output folder."
        self.check_output()
        sources = self.discover()
        api = self.project.smalldocs.get("api")
        if api:
            from .api import build_from_config

            build_from_config(self.project)
        self.run_scripts("pre-render", sources)
        sources = self.discover()  # pre-render may write pages, as apidocs.py does
        for src in sources:
            page = self.read(src)
            if page.meta.get("draft") is True:
                continue
            self.pages[src] = page
        if not self.pages:
            raise BuildError(f"no pages to render in {self.root}")
        self.load_symbols()
        for page in self.pages.values():
            self.render_page(page)
        nav = layout.SiteNav(self)
        for page in self.pages.values():
            if page.meta.get("listing"):
                listing.expand(self, page)
        if self.out.exists():
            for child in self.out.iterdir():
                shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
        self.out.mkdir(parents=True, exist_ok=True)
        for page in self.pages.values():
            dest = self.out / page.out
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(layout.page(self, nav, page), encoding="utf-8")
        self.copy_assets(nav)
        self.copy_resources()
        self.write_search()
        self.write_sitemap()
        listing.write_feeds(self)
        self.run_scripts("post-render", sources)
        for src, href in self.broken:
            self.warn(f"{src}: broken link {href}")
        return len(self.pages)

    # ------------------------------------------------------------ files beside the pages

    def theme_files(self) -> list["ThemeFile"]:  # One for each theme stylesheet the site uses: light first, then dark
        "Find the themes in `theme`: one name, a list, or `light:` and `dark:`. A name is a Bootswatch theme, a CSS file, or an extension."
        if self._themes is not None:
            return self._themes
        own = self.project.smalldocs.get("theme") if not self.project.native else None
        fmt = self.project.format_extension
        # `format: tufte-html` uses the theme of the extension `tufte`, when it has a smalldocs.yml
        fmt_theme = fmt if fmt and fmt in extensions.find(self.root) else None
        theme = own or self.project.html_options().get("theme") or fmt_theme or "cosmo"

        def first(v: object) -> str:  # The first name that is not Sass; smalldocs reads only one theme of a list
            ns = [str(x) for x in (v if isinstance(v, list) else [v]) if x]
            for n in ns:
                if n.endswith(".scss"):
                    self.warn(f"theme {n}: smalldocs compiles no Sass; use css: and the --bs-* variables")
            return next((n for n in ns if not n.endswith(".scss")), "cosmo")

        if isinstance(theme, dict):
            wanted = [(first(theme[mode]), mode) for mode in ("light", "dark") if theme.get(mode)]
        else:
            name = first(theme)
            ext = extensions.lookup(self.root, name) if not (self.root / name).is_file() else None
            wanted = [(name, mode) for mode in ext.modes()] if ext else [(name, "light")]
        self._themes = [self.theme_file(name, mode) for name, mode in wanted]
        return self._themes

    def theme_file(
        self,
        name: str,  # A name in `theme`: a CSS file, an extension, or a Bootswatch theme
        mode: str,  # `light` or `dark`
    ) -> "ThemeFile":  # Where its CSS comes from and goes to
        "Find one theme's CSS: a file in the project, then an extension in `_extensions/`, then a Bootswatch theme."
        vendor = ASSETS / "vendor"
        if (self.root / name).is_file():
            return ThemeFile(name, mode, self.root / name, f"themes/{extensions.css_name(name)}")
        ext = extensions.lookup(self.root, name)
        if ext is not None:
            for k in ext.spec:
                if k not in extensions.SPEC_KEYS:
                    self.warn(f"{ext.where}/{extensions.SPEC}: unknown key {k}")
            css = ext.css(mode)
            if not extensions.is_bootstrap((ext.path / css).read_text(encoding="utf-8-sig", errors="replace")):
                self.warn(f"{ext.where}/{css} is not a whole Bootstrap 5.3 stylesheet: the page loads no Bootstrap but the theme's")
            return ThemeFile(name, mode, ext.path / css, f"themes/{name}/{css}", ext)
        if name in extensions.PLAIN:
            return ThemeFile(name, mode, vendor / "bootstrap" / "bootstrap.min.css", f"themes/{extensions.css_name(name)}")
        if name in extensions.bundled():
            return ThemeFile(name, mode, vendor / "bootswatch" / f"{name}.min.css", f"themes/{extensions.css_name(name)}")
        names = sorted({*extensions.bundled(), *extensions.PLAIN, *extensions.find(self.root)})
        raise BuildError(f"theme {name!r} is not a Bootswatch theme, a CSS file or an extension in _extensions/: use one of {', '.join(names)}")

    def theme_extra(
        self,
        key: str,  # `logo` or `favicon`
    ) -> tuple[Path, PurePosixPath] | None:  # The file, and its path in the output folder, such as `site_libs/themes/ac215/logo.png`; None when the site sets its own
        "Find the theme's logo or favicon, which the site uses only when it sets none."
        web = self.project.website
        if key == "logo":
            bars = [b for b in as_list(web.get("sidebar")) if isinstance(b, dict)]
            nb = web.get("navbar")
            if web.get("logo") or (isinstance(nb, dict) and nb.get("logo")) or any(b.get("logo") for b in bars):
                return None
        elif web.get(key):
            return None
        for t in self.theme_files():
            if t.ext is not None and t.ext.spec.get(key):
                rel = t.ext.file(key, t.ext.spec[key])
                return t.ext.path / rel, PurePosixPath("site_libs/themes", t.name, rel)
        return None

    def copy_assets(
        self,
        nav: "layout.SiteNav",  # The site's navigation
    ) -> None:
        "Copy the theme, Bootstrap, the icons, search and smalldocs' own CSS and JavaScript into `site_libs`."
        libs = self.out / "site_libs"
        vendor = ASSETS / "vendor"
        shutil.copytree(vendor / "bootstrap", libs / "bootstrap", dirs_exist_ok=True, ignore=shutil.ignore_patterns("bootstrap.min.css", "LICENSE"))
        shutil.copytree(vendor / "bootstrap-icons", libs / "bootstrap-icons", dirs_exist_ok=True)
        shutil.copytree(vendor / "fuse", libs / "fuse", dirs_exist_ok=True, ignore=shutil.ignore_patterns("LICENSE"))
        for t in self.theme_files():
            dest = libs / t.href
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(t.src, dest)
            if t.ext is not None:
                top = t.ext.path.resolve()
                for f in extensions.css_files(t.src, t.ext, self.warn):
                    to = libs / "themes" / t.name / f.relative_to(top)
                    to.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(f, to)
        for key in ("logo", "favicon"):
            extra = self.theme_extra(key)
            if extra is not None:
                (self.out / extra[1]).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(extra[0], self.out / extra[1])
        for f in ("smalldocs.css", "smalldocs.js"):
            shutil.copy(ASSETS / f, libs / f)
        for css in layout.as_list(self.project.html_options().get("css")):
            if (self.root / css).is_file():
                self.resources.add(PurePosixPath(css))
        fav = self.project.website.get("favicon")
        if fav and (self.root / fav).is_file():
            self.resources.add(PurePosixPath(fav))

    def copy_resources(self) -> None:
        "Copy the files that pages link to, and `project.resources`, keeping their paths."
        pats = [str(p) for p in as_list(self.project.project.get("resources"))]
        if pats:
            for f in self.walk_all():
                r = f.relative_to(self.root).as_posix()
                if any(glob_match(r, pat) or glob_match(r, pat.rstrip("/") + "/**") for pat in pats):
                    self.resources.add(PurePosixPath(r))
        outs = {p.out for p in self.pages.values()}
        out_root = self.out.resolve()
        for r in sorted(self.resources):
            src = self.root / r
            dest = (self.out / r).resolve()
            if r.is_absolute() or str(r) == ".." or str(r).startswith("../") or (dest != out_root and out_root not in dest.parents):
                self.warn(f"{r} is outside the project; it is not copied")
                continue
            if r in outs:
                self.warn(f"{r} is not copied: a page is built to the same path")
                continue
            if src.is_file() and r not in self.pages and r.suffix not in PAGE_EXTS:
                dest = self.out / r
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)

    def walk_all(self) -> list[Path]:  # Every file under the root but the output folder, hidden ones too
        "List every file, for `resources`, which may name a hidden file such as `.nojekyll`."
        out = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            d = Path(dirpath)
            dirnames[:] = [n for n in dirnames if (d / n) != self.out and n not in (".git", ".venv", "node_modules", "__pycache__")]
            out += [d / f for f in filenames]
        return out

    def write_search(self) -> None:
        "Write `search.json`: one entry for each section of each page, as Quarto's search reads."
        entries = []
        for page in self.pages.values():
            if page.meta.get("search") is False:
                continue
            for sec in page.env.get("search", []):
                text = re.sub(r"<[^>]+>", " ", sec["text"])
                href = str(page.out) + (f"#{sec['id']}" if sec["id"] else "")
                entries.append({"objectID": href, "href": href, "title": page.title, "section": sec["title"] if sec["id"] else "", "text": html.unescape(text)})
        (self.out / "search.json").write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")

    def write_sitemap(self) -> None:
        "Write `sitemap.xml` when `website.site-url` is set."
        base = self.project.website.get("site-url")
        if not base:
            return
        base = base.rstrip("/") + "/"
        rows = []
        for page in self.pages.values():
            mod = dt.datetime.fromtimestamp(page.mtime, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            rows.append(f"  <url>\n    <loc>{html.escape(base + quote(str(page.out)))}</loc>\n    <lastmod>{mod}</lastmod>\n  </url>")
        xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "\n".join(rows) + "\n</urlset>\n"
        (self.out / "sitemap.xml").write_text(xml, encoding="utf-8")


def cell_defaults(
    opts: dict,  # A page's merged options
) -> dict:  # `echo`, `output` and `include` as the page and `execute:` set them
    "Read the options that hide code or output in every cell of a page: `echo: false`, or `execute: {echo: false}`."
    ex = opts.get("execute") if isinstance(opts.get("execute"), dict) else {}
    out = {}
    for k in ("echo", "output", "include"):
        v = opts.get(k, ex.get(k))
        if v is not None:
            out[k] = v
    return out


def build(
    root: Path | str = ".",  # The project folder
    quiet: bool = False,  # Print nothing but errors and warnings
    preview: bool = False,  # Add the reload script, for `smalldocs preview`
) -> Site:  # The built site, with its warnings
    "Load a project and build it."
    site = Site(load(root), quiet=quiet, preview=preview)
    n = site.build()
    where = os.path.relpath(site.out)
    site.say(f"wrote {n} page(s) to {site.out if where.startswith('..') else where}")
    return site
