# smalldocs

Codex instructions, derived from `CLAUDE.md`. Keep the shared project rules in both files consistent.
The Codex review, browser, and attribution instructions below adapt the Claude-specific workflow.

smalldocs builds a Quarto-like website from a `_smalldocs.yml` or `_quarto.yml` project, in pure Python, and is published on
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
  become `.html`; links from `/` start at the root. Check a change with the tests and the example sites (below).
- **New features never change existing output.** A page, site or notebook that uses none of a new feature builds byte for byte as before. Check it with the example sites before a release (see Checking a change).
- **`_smalldocs.yml` is the config; read `_quarto.yml` unchanged.** `config.load` looks for `_smalldocs.yml`
  first (`Project.native`). There the page options and smalldocs' own options (`linkify`, `symbols`, `api`,
  `config.OWN_KEYS`) are top-level keys, and `format`, `smalldocs` and `filters` are warnings. In a
  `_quarto.yml`, page options are under `format.html` and smalldocs' own settings under `smalldocs:`, which
  Quarto ignores. A key smalldocs does not read is a warning, never silent.
- **Any Bootswatch theme, with no Sass.** `assets/smalldocs.css` uses only Bootstrap's `--bs-*` variables
  and its own `--sd-*` ones. Never hard-code a colour that a theme should set (the Quarto highlight colours
  and the inline-code purple are the exceptions, with dark variants under `html.quarto-dark`).
- **The output folder is emptied at each build**, so `Site.check_output` refuses an output folder that is
  the project or above it, holds `.git`, or is not empty and has no `site_libs`. The API build deletes only
  pages listed in its manifest, `api/.smalldocs-api`, and `api.out` must be inside the site. Keep these
  guards; each has a test.
- **Never publish a source.** A link to a page that is not built is reported, and its `.qmd` is never
  copied. `resources` and `render` take one glob or a list (`config.as_list`); globs use `config.glob_match` (but `api.check` uses `glob_regex` from the root, so `*.py` is the root's files only)
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
| `src/smalldocs/config.py` | `_smalldocs.yml` or `_quarto.yml`: load, merge (`merge`, `dir_metadata`), the known keys, `ConfigError`, `BuildError` |
| `src/smalldocs/markdown.py` | markdown-it-py with mdit-py-plugins, and Pandoc's rules: heading attributes and ids, fenced divs, callouts, tabsets, figures, sections, typography, code, maths |
| `src/smalldocs/highlight.py` | Pygments tokens to Pandoc's classes (`kw`, `st`, `co`, ...) |
| `src/smalldocs/notebook.py` | `.ipynb` to Markdown with raw HTML outputs; nothing runs |
| `src/smalldocs/shortcodes.py` | `include`, `meta`, `var`, `env`, `pagebreak`, `kbd`, `video`, `lipsum`, `placeholder` |
| `src/smalldocs/site.py` | `Site`: discovery, pages, link rewriting (`resolve`), scripts, assets, resources, search.json, sitemap |
| `src/smalldocs/layout.py` | `SiteNav` (sidebars, navbar, order, breadcrumbs) and `Layout` (the page, in Quarto's markup, with `fastcore.xml`) |
| `src/smalldocs/listing.py` | Listings (default, grid, table), categories, RSS |
| `src/smalldocs/api.py` | The API reference: inventory, Markdown, pages, `_symbols.json`, `check` |
| `src/smalldocs/serve.py`, `publish.py`, `check.py`, `cli.py` | The commands |
| `src/smalldocs/extensions.py` | Theme extensions: `smalldocs add`, `smalldocs themes`, and finding `_extensions/<name>/smalldocs.yml` |
| `src/smalldocs/quarto_keys.py` | The names of Quarto's page options for HTML, written by `scripts/quarto_keys.py` from Quarto's schema. A front-matter key in it that smalldocs does not read is a warning |
| `QUARTO-GAPS.md` | What Quarto does that smalldocs does not, ticked as each gap closes |
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
3. For anything in `layout.py`, `markdown.py` or `assets/`: build `docs/` and drive it with the configured browser tools (CUA). Check tabs, callouts,
   search, the dark toggle, listings, and a phone width. Do not start separate browser automation outside CUA.
4. The example sites. Build them in the scratchpad, never in place. Use two copies of each, because each
   build empties `_site`.
   - The Tufte example. Copy `~/Projects/smalldocs-tufte/example` twice with `cp -Rp`, which keeps the
     files' times that a listing records. In each copy, run
     `smalldocs add ~/Projects/smalldocs-tufte --dir COPY --force`, which takes that repository's last
     commit. Build one copy with `uvx --refresh --from smalldocs==X.Y.Z smalldocs render COPY --strict`,
     where X.Y.Z is the last release. Without `--refresh`, uv may not know of the newest release.
     Build the other with `uv run --project ~/Projects/smalldocs smalldocs render COPY --strict`. Compare every file. Only the version and the files in `site_libs` may differ.
   - `docs/`. Build it with `uv run smalldocs render docs --strict`. It uses every feature, so its pages
     change with a new feature, and `api/` and `search.json` change with the docstrings. Read what
     changes and why.
   - A new feature. Add a case to a copy of one of them, and look at it in Chrome.
   - Quarto. For a change to ids, links or the page's markup, build a small `_quarto.yml` site with
     Quarto (`/usr/local/bin/quarto`) and with smalldocs. Compare the ids and the links.
   - The API pages. Only the tests check them against babykev's. Change what `api.py` writes only on
     purpose.
   - Rahul's other sites. Do not build ProblemSolving, babykev, nbinlineai, smallwikiapp or the class
     repos. They are in production, and each has its own agent that builds and checks it. In the final
     report, write two or three lines for each of them. Say what changed, and what to do or check.
5. Get an independent adversarial review from a separate Codex subagent before each commit.
   Use an available reviewer model; the Opus requirement in `CLAUDE.md` applies to Claude sessions.
   The reviewer must inspect the proposed diff and check results without changing files.

## Conventions

- Python 3.11+, ruff with line length 150. Dependencies: fastcore, markdown-it-py, mdit-py-plugins,
  PyYAML, Pygments. Nothing else at run time.
- Type and document every function in the docments style: one comment per parameter, one on the return,
  a one-line docstring.
- Plain, short sentences in docs, docstrings and messages.
- Ask Rahul before every commit. Complete the changes, checks, and review before asking, so he can approve a concrete result.
  End each Codex commit message with the line `Coded using Codex`. Keep Claude attribution for Claude-authored commits.

## Releasing

Raise `version` in `pyproject.toml` and `__version__` in `src/smalldocs/__init__.py`, run the checks,
`just build`, then `uv publish` (the token is in `~/.pypirc`; pass it with `--token`). Tag `vX.Y.Z`.
