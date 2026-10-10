"Read a `_quarto.yml` project: the options smalldocs knows, merged as Quarto merges them, and the ones it ignores."

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PAGE_EXTS = (".qmd", ".md", ".ipynb")
# The keys smalldocs reads. A value of None means any value is taken as it is.
KNOWN: dict = {
    "project": {
        "type": None, "output-dir": None, "render": None, "resources": None, "pre-render": None, "post-render": None,
        "title": None, "execute-dir": None, "preview": None,
    },
    "website": {
        "title": None, "description": None, "site-url": None, "site-path": None, "repo-url": None, "repo-branch": None,
        "repo-subdir": None, "repo-actions": None, "favicon": None, "image": None, "navbar": None, "sidebar": None,
        "page-navigation": None, "page-footer": None, "search": None, "open-graph": None, "twitter-card": None,
        "back-to-top-navigation": None, "bread-crumbs": None, "reader-mode": None, "draft-mode": None, "drafts": None,
        "google-analytics": None, "cookie-consent": None, "other-links": None, "code-links": None,
    },
    "execute": None,
    "format": None,
    "smalldocs": None,
    "filters": None,
    "metadata-files": None,
}  # fmt: skip
HTML_OPTIONS = {
    "theme", "css", "toc", "toc-depth", "toc-title", "toc-location", "toc-expand", "number-sections", "number-depth",
    "code-copy", "code-overflow", "highlight-style", "from", "page-layout", "anchor-sections", "smooth-scroll",
    "link-external-newwindow", "link-external-icon", "include-in-header", "include-before-body", "include-after-body",
    "title-block-banner", "grid", "lang", "fig-align", "code-fold", "code-tools", "html-math-method", "mainfont",
    "monofont", "fontsize", "linestretch", "linkcolor", "backgroundcolor", "fontcolor", "max-width", "callout-appearance",
    "callout-icon", "date-format", "author", "date", "title-prefix", "pagetitle", "description", "keywords",
    "citations-hover", "footnotes-hover", "reference-location", "search", "comments", "license", "copyright",
    "execute", "jupyter", "echo", "warning", "freeze", "minimal", "embed-resources", "self-contained", "df-print",
}  # fmt: skip


class ConfigError(Exception):
    "A project that smalldocs cannot build, with a message that says why."


class BuildError(Exception):
    "A build that cannot go on, with a message that says why."


@dataclass
class Project:
    "A website project: its folder, its merged config, and what smalldocs did not understand in it."

    root: Path  # The folder that holds `_quarto.yml`
    config: dict  # The whole config, as read
    warnings: list[str] = field(default_factory=list)  # One line for each key or feature that smalldocs ignores

    @property
    def project(self) -> dict:  # The `project:` section
        "The `project:` section."
        return section(self.config, "project")

    @property
    def website(self) -> dict:  # The `website:` section
        "The `website:` section, with `book:` read as a website."
        return section(self.config, "website") or section(self.config, "book")

    @property
    def smalldocs(self) -> dict:  # The `smalldocs:` section, which Quarto ignores
        "The `smalldocs:` section."
        return section(self.config, "smalldocs")

    @property
    def output(self) -> Path:  # The folder the site is written to
        "The output folder: `project.output-dir`, default `_site`."
        return (self.root / str(self.project.get("output-dir") or "_site")).resolve()

    def html_options(self) -> dict:  # The options that apply to every page, before a page's own
        "The project-wide page options: top-level keys, then `format.html`."
        base = {k: v for k, v in self.config.items() if (k not in KNOWN or k == "execute") and k != "book"}
        fmt = self.config.get("format") or {}
        html = fmt.get("html") if isinstance(fmt, dict) else None
        return merge(base, html if isinstance(html, dict) else {})


def section(
    cfg: dict,  # The whole config
    key: str,  # A top-level key, such as `website`
) -> dict:  # Its value, or an empty dict when it is missing
    "Read a section of the config; one that is not a mapping is an error."
    v = cfg.get(key)
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise ConfigError(f"_quarto.yml: {key} must be a mapping of keys, not {type(v).__name__}")
    return v


def as_list(
    v: object,  # A config value that may be one item or a list
) -> list:  # The value as a list: None is empty, a single value is one item
    "Make a config value that may be one item or a list into a list."
    return [] if v is None else v if isinstance(v, list) else [v]


def glob_regex(
    pattern: str,  # A glob, such as `posts/*.qmd` or `images/**`
) -> re.Pattern:  # A regular expression for whole paths
    "Turn a glob into a regex as Quarto reads globs: `*` and `?` stop at `/`, `**` crosses folders."
    out, i = "", 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif c == "*":
            out += "[^/]*"
            i += 1
        elif c == "?":
            out += "[^/]"
            i += 1
        elif c == "[":
            j = pattern.find("]", i + 1)
            if j < 0:
                out += re.escape(c)
                i += 1
            else:
                body = pattern[i + 1 : j]
                out += "[" + ("^" + body[1:] if body.startswith("!") else body) + "]"
                i = j + 1
        else:
            out += re.escape(c)
            i += 1
    try:
        return re.compile(out + r"\Z")
    except re.error as e:
        raise ConfigError(f"glob {pattern!r}: {e}") from e


def glob_match(
    path: str,  # A path relative to the root, with `/`
    pattern: str,  # A glob relative to the root; a leading `/` is the root
) -> bool:  # Whether the path matches
    "Match a path against a glob as Quarto does: `*` inside one folder, `**` across; a glob with no `/` matches at any depth."
    pattern = pattern.lstrip("/")
    if "/" not in pattern and pattern != "**":
        pattern = "**/" + pattern
    return bool(glob_regex(pattern).match(path))


def read_yaml(
    path: Path,  # A YAML file
) -> object:  # What it holds
    "Read a YAML file; a syntax error becomes a `ConfigError` that names the file."
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: {e}") from e
    except ValueError as e:  # a date such as 2024-13-45
        raise ConfigError(f"{path}: {e}") from e


def merge(
    a: dict,  # The options from further out
    b: dict,  # The options from nearer the page, which win
) -> dict:  # A new dict; nested dicts are merged, lists and values replaced
    "Merge two option dicts as Quarto does: the nearer one wins, key by key."
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def check_keys(
    cfg: dict,  # A part of the config
    known: dict,  # What smalldocs knows of that part
    path: str,  # Where the part is, for the message
) -> list[str]:  # A line for each key that smalldocs ignores
    "List the keys of the config that smalldocs does not read."
    out = []
    for k, v in cfg.items():
        if k not in known:
            out.append(f"{path}{k}")
        elif isinstance(known[k], dict) and isinstance(v, dict):
            out += check_keys(v, known[k], f"{path}{k}.")
    return out


def load(
    root: Path | str,  # A folder that holds `_quarto.yml`, or the file itself
) -> Project:  # The project
    "Read a project's `_quarto.yml` (and `_quarto.yaml`), and note what smalldocs will ignore."
    root = Path(root).resolve()
    if root.is_file():
        root = root.parent
    files = [root / n for n in ("_quarto.yml", "_quarto.yaml") if (root / n).exists()]
    if not files:
        raise ConfigError(f"{root} has no _quarto.yml")
    cfg = read_yaml(files[0]) or {}
    if not isinstance(cfg, dict):
        raise ConfigError(f"{files[0]}: the top level must be a mapping of keys")
    for extra in as_list(cfg.get("metadata-files")):
        p = root / str(extra)
        if p.exists():
            more = read_yaml(p) or {}
            if not isinstance(more, dict):
                raise ConfigError(f"{p}: the top level must be a mapping of keys")
            cfg = merge(more, cfg)
    proj = Project(root, cfg)
    for key in ("project", "website", "book", "smalldocs"):
        section(cfg, key)
    kind = proj.project.get("type", "default")
    if kind == "book":
        proj.warnings.append("project.type: book is built as a website; chapters become the sidebar")
    elif kind not in ("website", "default"):
        raise ConfigError(f"project.type {kind!r}: smalldocs builds only websites")
    proj.warnings += [f"unknown key {k}" for k in check_keys(cfg, KNOWN, "") if not k.startswith("book")]
    fmt = cfg.get("format") or {}
    if isinstance(fmt, dict):
        proj.warnings += [f"format {k} is not built: smalldocs makes only html" for k in fmt if k != "html"]
        html = fmt.get("html") or {}
        if isinstance(html, dict):
            proj.warnings += [f"format.html.{k} is ignored" for k in html if k not in HTML_OPTIONS]
    for f in as_list(cfg.get("filters")):
        name = f if isinstance(f, str) else str(f)
        if Path(name).name != "linkify.lua":
            proj.warnings.append(f"filter {name} is not run: smalldocs runs no Lua")
    return proj


def dir_metadata(
    project: Project,  # The project
    rel: Path,  # A page's path, relative to the root
) -> dict:  # The options from every `_metadata.yml` between the root and the page, nearest last
    "Merge the `_metadata.yml` files of the page's folders, as Quarto does."
    out: dict = {}
    folder = project.root
    for part in [None, *rel.parent.parts]:
        if part:
            folder = folder / part
        f = folder / "_metadata.yml"
        if f.exists() and folder != project.root:
            meta = read_yaml(f) or {}
            if not isinstance(meta, dict):
                raise ConfigError(f"{f}: the top level must be a mapping of keys")
            out = merge(out, meta)
    return out
