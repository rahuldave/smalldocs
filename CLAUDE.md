# smalldocs

smalldocs builds a Quarto-like website from a `_quarto.yml` project, in pure Python, and is published on
PyPI as `smalldocs`. It exists so that Rahul's projects (babykev, smallwikiapp, nbinlineai, ProblemSolving,
the timewalk class kits) can build their docs sites without Quarto, which is 600 MB of Pandoc, Deno, Sass
and Typst. It makes websites only: no PDF, Word, slides or books, and it runs no code.

The user documentation is the site in `docs/`, built by smalldocs itself. Keep it true when the behaviour
changes. The README is a short front page.

Write every page of the site, and the README, by the nossaifd writing guide, `style/GUIDE.md`. Use the
glossary in `style/README.md`, and define jargon where it first appears. Check with `just style`, which also
reads the Markdown cells of the notebooks; it must pass before a commit.

## Rules the tool must keep

- **A project that builds with Quarto builds with smalldocs, with the same pages, the same anchors and the
  same links.** Heading ids follow Pandoc's algorithm (`markdown.pandoc_id`); links to `.qmd`/`.md`/`.ipynb`
  become `.html`; links from `/` start at the root. Check a change against real sites (below).
- **Read `_quarto.yml` unchanged.** smalldocs' own settings live under `smalldocs:`, which Quarto ignores. A
  key smalldocs does not read is a warning, never silent.
- **Any Bootswatch theme, with no Sass.** `assets/smalldocs.css` uses only Bootstrap's `--bs-*` variables
  and its own `--sd-*` ones. Never hard-code a colour that a theme should set (the Quarto highlight colours
  and the inline-code purple are the exceptions, with dark variants under `html.quarto-dark`).
- **The output folder is emptied at each build**, so `Site.check_output` refuses an output folder that is
  the project or above it, holds `.git`, or is not empty and has no `site_libs`. The API build deletes only
  pages listed in its manifest, `api/.smalldocs-api`, and `api.out` must be inside the site. Keep these
  guards; each has a test.
- **Never publish a source.** A link to a page that is not built is reported, and its `.qmd` is never
  copied. `resources` and `render` take one glob or a list (`config.as_list`); globs use `config.glob_match`
  (as Quarto: with a `/`, `*` stays in one folder; with no `/`, the glob matches at any depth).
- **`publish` never touches the working tree or the current branch.** It works in a temporary worktree,
  removes it in `finally`, deletes only a branch it made (a uuid name), skips hooks, and refuses to
  publish onto the current branch, the remote's default branch, `main` or `master`.
- **`smalldocs api` must import only fastcore and PyYAML**, because it runs in the documented project's
  environment. Keep the imports in `cli.py` lazy.
- **The API pages are byte-for-byte what babykev's `apidocs.py` made.** `api.module_markdown` and `api.page`
  are ported from `babykev/src/babykev/docs.py` and `babykev/docs/apidocs.py`.

## Layout

| File | What it is |
|---|---|
| `src/smalldocs/config.py` | `_quarto.yml`: load, merge (`merge`, `dir_metadata`), the known keys, `ConfigError`, `BuildError` |
| `src/smalldocs/markdown.py` | markdown-it-py with mdit-py-plugins, and Pandoc's rules: heading attributes and ids, fenced divs, callouts, tabsets, figures, sections, typography, code, maths |
| `src/smalldocs/highlight.py` | Pygments tokens to Pandoc's classes (`kw`, `st`, `co`, ...) |
| `src/smalldocs/notebook.py` | `.ipynb` to Markdown with raw HTML outputs; nothing runs |
| `src/smalldocs/shortcodes.py` | `include`, `meta`, `var`, `env`, `pagebreak` |
| `src/smalldocs/site.py` | `Site`: discovery, pages, link rewriting (`resolve`), scripts, assets, resources, search.json, sitemap |
| `src/smalldocs/layout.py` | `SiteNav` (sidebars, navbar, order, breadcrumbs) and `Layout` (the page, in Quarto's markup, with `fastcore.xml`) |
| `src/smalldocs/listing.py` | Listings (default, grid, table), categories, RSS |
| `src/smalldocs/api.py` | The API reference: inventory, Markdown, pages, `_symbols.json`, `check` |
| `src/smalldocs/serve.py`, `publish.py`, `check.py`, `cli.py` | The commands |
| `src/smalldocs/assets/` | `smalldocs.css`, `smalldocs.js`, and `vendor/` (Bootswatch 5.3.8, Bootstrap 5.3.8, Bootstrap Icons 1.11.3, Fuse.js 7.0.0). Vendored: do not edit |
| `tests/test_smalldocs.py` | One test per feature |
| `docs/` | smalldocs' own site; it uses every feature, and its Reference is made by `smalldocs.api` from this package |

## Commands

```
just test            # pytest; extra arguments go to pytest
just lint            # ruff
just render DIR      # build a site
just docs            # preview smalldocs' own site with reload
just build           # the wheel and sdist into dist/
```

## Checking a change

1. `just test`, `just lint` and `just style`, as separate commands; read each result.
2. `uv run smalldocs api check --dir docs`: every function typed and documented.
3. For anything in `layout.py`, `markdown.py` or `assets/`: build `docs/` and drive it in headless Chrome
   (Playwright, `channel="chrome"`): tabs, callouts, search, the dark toggle, listings, a phone width.
4. Against real sites: copy a site into the scratchpad (never build in place: ProblemSolving's
   `output-dir` is `../docs`, a folder of its repository), render it with Quarto and with smalldocs, and
   compare the pages, the ids and the links. babykev needs its own Python for the API; run smalldocs
   with `PYTHONPATH` set to `src` and to this project's site-packages.
5. An adversarial review by an Opus subagent before each commit.

## Conventions

- Python 3.11+, ruff with line length 150. Dependencies: fastcore, markdown-it-py, mdit-py-plugins,
  PyYAML, Pygments. Nothing else at run time.
- Type and document every function in the docments style: one comment per parameter, one on the return,
  a one-line docstring.
- Plain, short sentences in docs, docstrings and messages.
- Ask Rahul before every commit. End each commit message with the line `Coded using Claude`.

## Releasing

Raise `version` in `pyproject.toml` and `__version__` in `src/smalldocs/__init__.py`, run the checks,
`just build`, then `uv publish` (the token is in `~/.pypirc`; pass it with `--token`). Tag `vX.Y.Z`.
