# How the site is written

Every page of the site in `docs/` follows `GUIDE.md`, the nossaifd writing guide. `GUIDE.md` and `check.py`
are copies from the nossaifd repository, https://github.com/rahuldave/nossaifd. If the guide changes there,
copy both files again.

Check the pages with the recipe, and fix each hard problem:

```
just style                                     # every page, and the Markdown cells of the notebook
python3 style/check.py -v docs/guide/api.qmd   # one page, with the soft notes
```

Then read the page, and build the site with `just render docs`.

## Glossary

Use each term in this meaning, and define it on the first page where a reader meets it.

| Term | Meaning |
|---|---|
| project | A folder with a `_smalldocs.yml` or `_quarto.yml` file. smalldocs builds one project into one site |
| site | The HTML files that smalldocs writes into the output folder |
| output folder | The folder that holds the site: `_site`, or the folder that `output-dir` names |
| page | A `.qmd`, `.md` or `.ipynb` file that smalldocs turns into one HTML file |
| front matter | The YAML block between two `---` lines at the top of a page |
| option | A key in `_smalldocs.yml`, in a `_metadata.yml` file or in front matter |
| glob | A path pattern with `*`, `?` or `**`, such as `guide/*.qmd` |
| theme | A Bootswatch stylesheet, which sets the colours and the fonts of the site |
| navbar | The bar across the top of each page, with links to pages |
| sidebar | The list of pages at the left of each page |
| table of contents | The list of the headings of a page, at the right of the page |
| callout | A box that sets off a note, a tip or a warning |
| tabset | A group of tabs, each with its own content |
| listing | A page that lists other pages, as rows, cards or a table |
| docment | A comment beside a parameter that describes the parameter. fastcore reads it |
| reference page | A page that smalldocs makes from the code of a module |
| shortcode | A tag such as `{{</* meta title */>}}` that smalldocs replaces before it reads the Markdown |
| build | One run of smalldocs that writes the site |
| preview | A build that smalldocs serves, and builds again when a file changes |

## Headings that other pages link to

No page links to a heading of another page yet. If you add such a link, add the heading here, so that
nobody changes its text.
