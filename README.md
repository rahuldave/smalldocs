# smalldocs

smalldocs builds a website from a folder of Markdown pages and notebooks, in Python. A file
`_smalldocs.yml` in the folder holds the options of the site. smalldocs looks like
[Quarto](https://quarto.org), and also builds a Quarto project from its `_quarto.yml`, with no change.
It writes the site into the folder `_site`. The site has these parts:

- pages with a navbar, a sidebar and a table of contents
- notebooks, with the outputs that were saved in them
- reference pages, made from the code of a package
- listings of posts, with categories and a feed

The site can use any [Bootswatch](https://bootswatch.com) theme, in a light version and a dark version.

smalldocs makes websites only. It does not make PDF files, Word files, slides or books, and it runs no
code. It is one package from PyPI, and it needs no Pandoc, Deno, Sass or TeX.

```bash
pip install smalldocs

smalldocs render docs              # build docs/_site
smalldocs preview docs             # serve it at http://127.0.0.1:4200, and build it again on each change
smalldocs check docs               # what smalldocs ignores, broken links, Markdown that only Pandoc reads
smalldocs api build --dir docs     # the API reference, from docstrings, types and docments
smalldocs publish gh-pages docs    # push the site to the branch gh-pages
```

The documentation is at [rahuldave.com/smalldocs](https://rahuldave.com/smalldocs/). smalldocs builds it from [`docs/`](docs/).

## What smalldocs reads

- **The options.** smalldocs reads `_smalldocs.yml`, `_metadata.yml` and front matter, and merges them
  as Quarto does. In a `_quarto.yml`, it reads the sections `project`, `website`, `format.html` and
  `smalldocs`.
- **The Markdown.** smalldocs reads CommonMark, tables, footnotes, attributes, divs, callouts, tabsets,
  maths, diagrams, raw HTML and shortcodes. It makes the ids of headings by the rules of Pandoc. So links
  that were written for Quarto keep working.
- **Notebooks.** smalldocs shows the outputs that were saved in a notebook. It obeys the `#|` options of
  Quarto in each cell.
- **Listings.** smalldocs makes listings as rows, cards or a table, with sorting, a filter, categories,
  pages and an RSS feed.

## Licence

smalldocs has the MIT licence. It includes Bootstrap, Bootswatch and Bootstrap Icons, with the MIT
licence, and Fuse.js, with the Apache-2.0 licence. The licence of each is in `src/smalldocs/assets/vendor/`.

The documentation follows the nossaifd writing guide, https://github.com/rahuldave/nossaifd. See
`style/README.md`.
