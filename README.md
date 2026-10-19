# smalldocs

smalldocs builds a website from a folder of Markdown pages and notebooks, in Python. A file
`_smalldocs.yml` in the folder holds the options of the site. smalldocs writes the site into the folder
`_site`. The site has these parts:

- pages with a navbar, a sidebar and a table of contents
- notebooks, with the outputs that were saved in them
- reference pages, made from the code of a package
- listings of posts, with categories and a feed

The site can use any [Bootswatch](https://bootswatch.com) theme, in a light version and a dark version, or a theme from a
git repository.

smalldocs makes websites only. It does not make PDF files, Word files, slides or books, and it runs no
code. It is one package from PyPI, and it needs no other programs.

smalldocs takes its conventions from [Quarto](https://quarto.org). They are the `.qmd` pages, the
Markdown of [Pandoc](https://pandoc.org) and the options of a site. So a Quarto website builds with smalldocs, from its `_quarto.yml`,
with no change.

```bash
pip install smalldocs

smalldocs render docs              # build docs/_site
smalldocs preview docs             # serve it at http://127.0.0.1:4200, and build it again on each change
smalldocs check docs               # options that smalldocs ignores, broken links, Markdown it does not read
smalldocs api build --dir docs     # the API reference, from docstrings, types and comments
smalldocs publish gh-pages docs    # push the site to the branch gh-pages
```

The documentation is at [docs.smallish.dev](https://docs.smallish.dev/). smalldocs builds it from [`docs/`](docs/).

## What smalldocs reads

- **The options.** smalldocs reads `_smalldocs.yml`, a `_metadata.yml` file in each folder, and the
  front matter of each page. The front matter wins over a `_metadata.yml`, and a `_metadata.yml` wins
  over `_smalldocs.yml`.
- **The Markdown.** smalldocs reads CommonMark. It also reads front matter, tables, footnotes,
  attributes, divs, callouts, tabs, maths, diagrams, raw HTML and shortcodes. A `.qmd` page is Markdown
  that uses them. [Writing pages](https://docs.smallish.dev/guide/markdown.html) describes each one.
- **Notebooks.** smalldocs shows the outputs that were saved in a notebook. The `#|` option lines at
  the top of a cell can hide its code or its output. Optional
  [browser notebooks](https://docs.smallish.dev/guide/browser-notebooks.html) add run and download buttons with JupyterLite and Pyodide.
- **Listings.** smalldocs makes listings as rows, cards or a table, with sorting, a filter, categories,
  pages and an RSS feed.

## Licence

smalldocs has the MIT licence. It includes Bootstrap, Bootswatch and Bootstrap Icons, with the MIT
licence, and Fuse.js, with the Apache-2.0 licence. The licence of each is in `src/smalldocs/assets/vendor/`.

The documentation follows the nossaifd writing guide, https://github.com/rahuldave/nossaifd. See
`style/README.md`.
