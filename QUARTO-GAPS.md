# What smalldocs does not do that Quarto does, for HTML websites

This is the list of Quarto features that smalldocs does not support, and the work to close the gaps. Each
item is ticked when it is done, tested and documented.

The list comes from an audit of smalldocs 0.2.0 against Quarto 1.8.26. The audit took every option in
Quarto's schema (`share/schema/*.yml`) that applies to the `html` format: 1,028 paths, with the nested keys
of `website`, `project` and `listing`, and the options of notebook cells. It checked each against the keys
that smalldocs' code reads. It rendered each Markdown feature to see what smalldocs makes of it.

"Silent" means that smalldocs accepted the key and did nothing, with no warning. That breaks the rule in
CLAUDE.md that a key smalldocs does not read is a warning.

## Step 1: no silent keys

- [x] Every key that smalldocs reads is listed, down to the nested keys of `navbar`, `sidebar`,
      `page-footer`, `search`, `listing` and each entry of a navbar or sidebar
- [x] Any other key in the config gives a warning
- [x] A Quarto page option in front matter that smalldocs does not read gives a warning
- [x] The options that need code to run (`jupyter`, `freeze`, `df-print`, `execute-dir`, `cache`, `engine`)
      say that smalldocs runs no code
- [x] `logo` as a mapping no longer stops the build

## Step 2: the features with the most use

### Markdown

- [x] Table captions, `: Caption {#tbl-a}`, and `tbl-cap-location`
- [x] `.content-visible` and `.content-hidden`, with `when-format`, `unless-format`, `when-meta`, `when-profile`
- [x] Shortcodes `kbd` and `video`
- [x] Tabset groups, `group="lang"`
- [x] `code-line-numbers`
- [x] `code-fold` and `code-summary`, for executable cells and notebook cells, as in Quarto
- [x] `code-overflow`
- [x] Subscript `H~2~O` and superscript `x^2^`
- [x] Lists numbered with letters or roman numerals: `a.`, `A.`, `i.`, `I.`, `a)`, `(a)`
- [x] `fig-align` and `fig-alt`
- [x] `layout-ncol`, `layout-nrow` and `layout` on a div (not yet: Quarto's negative widths for spacers)
- [x] `callout-appearance` and `callout-icon` as page defaults (smalldocs keeps its own callout markup)
- [x] `anchor-sections` and `number-depth`

### Page and site

- [x] `toc-location` (left, right, body, left-body, right-body) and `toc-expand`
- [x] `mainfont`, `monofont`, `fontsize`, `linestretch`, `linkcolor`, `backgroundcolor`, `fontcolor`, `max-width`
- [x] `target`, `rel`, `aria-label`, `id` and `url` on the entries of the navbar, sidebar and footer
- [x] `logo` as a mapping (`path`, `alt`, `light`, `dark`), `logo-alt` and `logo-href`
- [x] `navbar`: `collapse`, `collapse-below`, `toggle-position`, `tools-collapse`, `pinned`
- [x] `sidebar`: `background`, `foreground`, `border`, `alignment`, `header`, `footer`, `pinned`
- [x] `page-footer`: `background`, `foreground`, `border`
- [x] `search`: `location`, `type`, `limit`, `keyboard-shortcut`
- [x] `google-analytics`, `twitter-card`, `open-graph.locale`, `open-graph.site-name`, `keywords`, `title-prefix`
- [x] `back-to-top-navigation`, `other-links`, `code-links`
- [x] `license` and `copyright`
- [x] `link-external-icon`, `link-external-filter`, `smooth-scroll`
- [x] `draft-mode` and `drafts`
- [x] `comments`: giscus, utterances and hypothes.is

### Notebook cells

None of the notebooks in the projects that use smalldocs set these options, so they change no page that
exists. A notebook that does not set them renders as before.

- [x] `fig-cap`, `fig-alt`, `fig-align`, `tbl-cap`
- [x] `column`, `fig-column`, `tbl-column` (such as `#| column: margin`)
- [x] `layout-ncol`, `layout-nrow`
- [x] `code-fold`, `code-summary`, `code-line-numbers`, `code-overflow`

## Step 3: cross-references

- [ ] `@fig-`, `@tbl-`, `@sec-`, `@eq-` references, with numbering, and `crossref` options
- [ ] Figure divs `::: {#fig-a}` with a caption paragraph, and subfigures
- [x] `layout="[[1,1],[1]]"` grids, done in step 2 (not yet: negative widths for spacers)
- [ ] Equation labels, `$$...$$ {#eq-a}`

## Since the audit

- [x] `website.llms-txt` (Quarto 1.9): a Markdown copy of each page, `page.llms.md`, and `llms.txt`, with
      `when-format="llms-txt"`

## Step 4: later

- [ ] Code annotations, `# <1>`
- [ ] `lightbox`
- [ ] `footnotes-hover`
- [ ] `reader-mode`
- [ ] `website.announcement`, `body-header`, `body-footer`, `margin-header`, `margin-footer`
- [ ] `listing`: `image-placeholder`, `image-align`, `image-lazy-loading`, `field-types`, `field-links`, `field-required`
- [ ] `cookie-consent`
- [ ] `highlight-style`, `code-tools`
- [ ] `search`: `copy-button`, `collapse-after`, `show-item-context`, `merge-navbar-crumbs`
- [ ] Example lists `(@)` and line blocks
- [ ] `_brand.yml`
- [ ] Citations and a bibliography (decide whether to support them)

## Changes to existing behaviour, for a decision

These would change sites that exist, so they are not made:

- [ ] Quarto's search keys `f`, `/` and `s` by default. smalldocs keeps `/`; a site can set `keyboard-shortcut`
- [ ] In a sidebar with no navbar, search results as wide as the sidebar. Today a long result is cut off
- [ ] Figures centred, as Quarto centres them. Bootstrap's `.figure` is inline-block, so smalldocs shows them at the left

## Not planned

- Running code, and the options of execution: `jupyter`, `freeze`, `cache`, `engine`, `df-print`
- PDF, Word, slides and books; compiling Sass; `embed-resources` and `self-contained`
- Graphviz `{dot}` blocks: make an SVG with Graphviz, and use it as an image
- `listing.template` (EJS templates), `about` pages, Algolia search
- Grid tables and raw LaTeX, which `smalldocs check` reports

## What works

Ordinary lists, task lists, definition lists, tables with alignment, footnotes (at the end, or in the margin),
callouts with collapse and appearance, tabsets, figures with captions, margin content and wide columns,
Mermaid, KaTeX maths, attributes on headings, links, images and spans, fenced divs, raw HTML, the shortcodes
`include`, `meta`, `var`, `env` and `pagebreak`, listings (default, grid and table) with categories, sorting,
filtering, paging and RSS, the navbar, sidebar, breadcrumbs, page navigation, search, light and dark themes,
theme extensions, repo actions, Open Graph, `_metadata.yml`, `metadata-files`, `pre-render` and `post-render`,
`render` and `resources` globs, and drafts with `draft: true`.
