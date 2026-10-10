# smalldocs: a plan

A small, pure-Python tool that builds a Quarto-like website from a `_quarto.yml` project: regular pages,
API reference pages, and listing (blog/collection) pages, into `_site`. No PDF, Word, slides, books,
code execution, Lua, Sass or Pandoc.

## 1. What we use Quarto for today (surveyed 2026-10-10)

18 `_quarto.yml` sites under `~/Projects` (babykev and its copies, smallwikiapp, nbinlineai and its
copies, ProblemSolving, smallwikiapp-walk, babykev-class prototype). timewalk-test has none: its tags
hold no `docs/`. All are `type: website` except `playing_with_quarto` (a book, with pdf and docx).

Config keys in use, and nothing else:

| Area | Keys |
|---|---|
| project | `type: website`, `output-dir`, `pre-render`, `render` (globs), `resources` (globs) |
| website | `title`, `description`, `site-url`, `repo-url`, `navbar.left` (text/href), `sidebar` (`style: docked`, `search`, `contents` with files, globs like `api/*`, `section:`, `text`/`href`), `page-navigation`, `search` |
| format.html | `theme: cosmo` (every site), `css`, `toc`, `toc-depth`, `code-copy`, `from: markdown-tex_math_dollars-smart` |
| filters | `linkify.lua` only: a backticked name becomes a link to its API entry, from `_symbols.json` |

Markdown in the 71 pages: pipe tables (43 pages), images, `{#id}` on headings, `{.source-link}` on
links, inline `$` (dollars, not maths). No callouts, tabsets, listings, shortcodes, cross-refs, footnotes
or executed code. One notebook (`babykev/docs/guide/01_mask.ipynb`), rendered from stored outputs.

The API pages come from a per-project `docs/apidocs.py` (86 lines) over a per-project `docs.py`
(babykev: 451 lines; fastcore `docments`, dataclasses, pydantic). The copies have drifted
(smallwikiapp's has `check` and `module`; babykev's does not).

Quarto 1.8.26 is 638 MB: Deno, Pandoc, dart-sass, esbuild and Typst.

## 2. Feasibility: yes

- **Themes without Sass.** Quarto compiles Bootswatch Sass with its own layer. We do not need to:
  Bootswatch 5.3.8 ships each of its 25 themes as a plain `bootstrap.min.css` (about 30 KB gzipped), and
  Bootstrap 5.3 exposes the theme as CSS variables (`--bs-primary`, `--bs-body-bg`, `--bs-border-color`,
  `--bs-secondary-bg`, `--bs-link-color`, `--bs-font-sans-serif`, ...). One hand-written `smalldocs.css`
  that uses only these variables, plus Bootstrap's own classes (`navbar`, `card`, `nav-tabs`, `table`,
  `alert`), looks right under every theme. All 25 vendored add about 750 KB to the wheel; a build copies
  only the chosen one into `_site/site_libs/`.
- **Markdown.** markdown-it-py (the parser behind MyST) with mdit-py-plugins covers front matter,
  tables, footnotes, definition lists, `$` maths, task lists and inline `{.class}` attributes. We add
  small rules for what Pandoc has and it lacks: `{#id .class}` after a heading, fenced divs
  `::: {.class}`, raw `{=html}` blocks, and Pandoc's heading-id algorithm, so anchors stay the same.
- **HTML.** We copy the shape of Quarto's markup (its class and id names: `#quarto-header`,
  `#quarto-sidebar`, `#TOC`, `.quarto-title-block`, `.quarto-grid-item`, `callout-*`, `panel-tabset`),
  not its files, and write it with `fastcore.xml` (FT components), so templating adds no dependency.
- **Notebooks.** `.ipynb` is JSON: markdown cells, code cells, and stored outputs (stream, text/plain,
  text/html, image/png, image/svg+xml, error with ANSI stripped), with `#| echo: false` and
  `#| output: false`. No kernel, as Quarto by default.
- **API docs.** Generalise babykev's `docs.py` and `apidocs.py` into `smalldocs.api`, and build
  `linkify.lua` in. This removes the drifting copies.

Dependencies: `fastcore`, `markdown-it-py`, `mdit-py-plugins`, `PyYAML`, `Pygments`. All pure Python.
Vendored: Bootswatch and Bootstrap (MIT), Fuse.js (Apache-2.0) for search.

Estimate: 3,000 to 4,000 lines of Python, about 600 of CSS and JS.

## 3. Risks, and what we do about them

| Risk | Answer |
|---|---|
| markdown-it is not Pandoc: grid tables, citations `[@key]`, raw LaTeX, `{.class}` on spans | Out of scope; `smalldocs check` names each one with file and line. None of our sites uses them |
| Anchors change and links break | Pandoc's id algorithm, tested against Quarto's output; a link checker in `render` |
| `.qmd` links | Rewrite `.qmd`/`.md`/`.ipynb` to `.html` and root `/` links to relative ones, as Quarto does (`_symbols.json` targets are `/api/api.qmd#Noul`) |
| Looks almost like Quarto, not exactly | Screenshot comparisons against Quarto under cosmo, flatly, darkly and sketchy |
| `theme: [cosmo, custom.scss]` | Refused with a message: use `css:` and `--bs-*` variables. No site of ours uses `.scss` |
| Lua filters | Ignored with a warning; the only one we use (linkify) is built in. Later: Python filters |
| `{python}` cells in `.qmd` | Shown as code, not run, with a warning |

## 4. What smalldocs does

**Commands**

```
smalldocs render [DIR]            build DIR (default .) into its output-dir, default _site
smalldocs preview [DIR] [--port]  render, serve, rebuild on change, reload the browser
smalldocs check [DIR]             config keys we ignore, Pandoc-only syntax, broken links
smalldocs api build|check|module NAME   the reference pages; the gaps in the docments; one module as Markdown
smalldocs publish gh-pages [DIR]  push the output-dir to the gh-pages branch (as quarto publish gh-pages)
```

**Config.** Read `_quarto.yml` unchanged, so one site builds with either tool. Our own settings go
under a `smalldocs:` key, which Quarto ignores:

```yaml
smalldocs:
  api:
    packages: [babykev]          # importable packages to document
    out: api                     # pages go to docs/api/
    source: https://github.com/rahuldave/babykev/blob/main
    linkify: true                # `render` in prose links to its entry
```

Unknown keys get a warning that names them; `--strict` makes it an error.

**Supported, by area**

- project: `type: website`, `output-dir`, `render`, `resources`, `pre-render`, `post-render` (run with
  Quarto's `QUARTO_PROJECT_*` environment variables).
- website: `title`, `description`, `site-url` (sitemap.xml), `repo-url` (link and repo actions),
  `favicon`, `navbar` (left/right, menus, `search`), `sidebar` (docked/floating, files, globs, sections,
  `auto`), `page-navigation`, `page-footer`, `search` (search.json and a Fuse.js box), `open-graph` (basic).
- format.html: `theme` (any Bootswatch name, or `light:`/`dark:` with a toggle), `css`, `toc`,
  `toc-depth`, `toc-title`, `number-sections`, `code-copy`, `highlight-style` (Pygments),
  `from: ...-tex_math_dollars-smart`, `page-layout` (article, full), `anchor-sections`.
- page front matter: `title`, `subtitle`, `description`, `author`, `date`, `categories`, `image`,
  `draft`, `toc`, `listing`, `page-layout`, `search: false`.
- Markdown: CommonMark, pipe tables, footnotes, definition lists, task lists, `{#id .class key=val}`,
  fenced divs, callouts (note, tip, warning, important, caution; collapse; title), `panel-tabset`,
  raw HTML, `$`/`$$` maths with KaTeX, mermaid blocks (mermaid.js from a CDN).
- Listings (`listing:` in front matter): `contents` (globs), `type: default|grid|table`, `sort`,
  `fields`, `categories` (with filter), `sort-ui`, `filter-ui`, `page-size`, `max-items`,
  `grid-columns`, `image-height`, `feed: true` (RSS). Item data from each page's front matter; when it
  is missing, the first paragraph for the description and the first image for the picture. Several
  listings per page, by `id`.
- API: the generic `smalldocs.api` from babykev's `docs.py`. Modules, classes, methods, functions;
  signatures with types; docment tables; dataclass fields; pydantic fields (detected, not imported);
  TypedDict keys with comments; a source link per entry; the `check` of docments; and the name index
  that the built-in linkify uses.

## 5. Layout of the repository

```
smalldocs/
  pyproject.toml   justfile   ruff.toml   CLAUDE.md   README.md
  src/smalldocs/
    config.py      # _quarto.yml: load, defaults, unknown keys, globs
    markdown.py    # markdown-it setup and the Pandoc-like rules (ids, divs, callouts, tabsets, raw)
    notebook.py    # .ipynb to the same tokens
    pages.py       # discovery, front matter, link rewriting, the page model
    layout.py      # fastcore.xml: navbar, sidebar, title block, TOC, page nav, footer
    listing.py     # listings and RSS
    search.py      # search.json, sitemap.xml
    api.py         # the API reference (from babykev docs.py and apidocs.py)
    serve.py       # preview: http.server, watch, reload
    publish.py     # gh-pages
    cli.py         # the commands, with fastcore.script
    assets/        # smalldocs.css, smalldocs.js, vendor/{bootswatch/*, bootstrap, fuse, katex?}
  tests/           # one test per feature, and a kitchen-sink site
  docs/            # smalldocs' own site, built by smalldocs: it uses every feature
```

## 6. Phases

Each phase ends with its tests green and an Opus adversarial review, as in timewalk.

1. **Skeleton.** pyproject (hatchling, uv), justfile, ruff, CLAUDE.md, vendored assets with licences.
2. **Core render.** Config, discovery, the Markdown pipeline, link rewriting, navbar, sidebar, TOC,
   title block, themes, `css`, `resources`, `pre-render`. Test: babykev/docs, smallwikiapp-walk/site,
   nbinlineai/docs and ProblemSolving/site build with no Quarto, and every link resolves.
3. **Pages in full.** Notebooks, Pygments highlighting, code-copy, callouts, tabsets, maths, mermaid,
   page navigation, footer, light/dark.
4. **API.** `smalldocs.api` and the built-in linkify. Test: babykev's reference pages and
   `_symbols.json` match what `apidocs.py` makes today.
5. **Listings and search.** Default, grid and table; categories; sorting; pages; RSS; search.json and
   the search box; sitemap.
6. **Preview and publish.** `smalldocs preview` with reload; `publish gh-pages`.
7. **Compare with Quarto.** Render each surveyed site with both into the scratchpad. Compare pages,
   anchors and links mechanically, and screenshots by eye under four themes. Write smalldocs' own docs.
8. **Release.** GitHub repo `rahuldave/smalldocs`, PyPI via trusted publishing from a GitHub Action,
   `v0.1.0`.

Only after that, and when you say so: move babykev, timewalk-test and the kits from Quarto to
smalldocs.

## 7. Decisions for you

1. **Name.** `smalldoc` is taken on PyPI (a 2012 SmallTalk-style API documenter by sebastien).
   `smalldocs` is free. I recommend it.
2. **Templates in `fastcore.xml`, not Jinja2.** One dependency fewer, and in Python. The cost: a user
   cannot override a template file; they override with CSS, or with a Python hook later.
3. **Vendor all 25 Bootswatch themes** in the wheel (about 750 KB), so that a build works offline. The
   other choice is links to a CDN.
4. **PyPI.** Publishing needs a trusted publisher set up on your PyPI account for the GitHub repository.
