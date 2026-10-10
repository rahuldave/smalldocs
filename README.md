# smalldocs

smalldocs builds a website from a [Quarto](https://quarto.org) project, in pure Python. It reads the same
`_quarto.yml` and the same Markdown, and writes the same kind of site into `_site`: pages with a navbar, a
sidebar and a table of contents, notebooks with their saved outputs, reference pages made from your code,
and listings of posts with categories and a feed. The site takes any [Bootswatch](https://bootswatch.com)
theme, in light and dark.

It makes websites only: no PDF, Word, slides or books, and it runs no code. In return it is one package
from PyPI, with no Pandoc, Deno, Sass or TeX.

```bash
pip install smalldocs

smalldocs render docs              # build docs/_site
smalldocs preview docs             # serve it at http://127.0.0.1:4200, rebuild and reload on each change
smalldocs check docs               # what smalldocs ignores, broken links, Markdown only Pandoc reads
smalldocs api build --dir docs     # the API reference, from docstrings, types and docments
smalldocs publish gh-pages docs    # push the site to the gh-pages branch
```

The documentation is in [`docs/`](docs/), built with smalldocs.

## What it reads

- `_quarto.yml`, `_metadata.yml` and front matter, merged as Quarto merges them: `project`
  (`output-dir`, `render`, `resources`, `pre-render`, `post-render`), `website` (navbar, sidebar, page
  navigation, footer, search, site URL, repository links) and `format.html` (theme, CSS, table of contents,
  numbered sections, includes).
- Markdown: CommonMark, tables, footnotes, definition lists, task lists, `{#id .class}` attributes,
  fenced divs, callouts, tabsets, `$` maths (KaTeX), mermaid, raw HTML, and the shortcodes `include`,
  `meta`, `var` and `env`. Heading ids follow Pandoc's rules, so links written for Quarto keep working.
- Notebooks, with the outputs they were saved with, and Quarto's `#|` cell options.
- Listings: `default`, `grid` and `table`, with sorting, filtering, categories, pages and RSS.

## Licence

MIT. smalldocs ships Bootstrap, Bootswatch and Bootstrap Icons (MIT) and Fuse.js (Apache-2.0), each with
its licence in `src/smalldocs/assets/vendor/`.
