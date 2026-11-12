# Spec: API pages for Rust and TypeScript

Status: built and merged. Rahul approved the spec on 2026-11-12, and approved what was built, with the
sidebar change, on the same day. This spec says what was built and what was decided.

## What it is for

`smalldocs api` makes reference pages for a Python package. This spec adds the same pages for a Rust
crate and for a TypeScript package. The pages keep the docments convention. A comment after each
parameter says what the parameter is.

```rust
/// Add two numbers.
///
/// # Returns
///
/// The sum.
pub fn add(a: i32,   // the first number
           b: i32,   // the second number
) -> i32 {
```

```ts
/** Add two numbers. */
export function add(a: number,      // the first number
                    b: number = 1,  // the second number
): number {                         // the sum
```

## The tools that read the code

Each language has a compiler tool that writes what it knows as JSON. smalldocs runs that tool, reads
the JSON and writes the pages.

- **Rust: rustdoc.** smalldocs runs `cargo +TOOLCHAIN rustdoc -- -Z unstable-options --output-format json`.
  The JSON gives each public item with its doc comment, its types, its generics, its `impl` blocks and
  its re-exports (`pub use`). It also gives the file and the lines of each item.
- **TypeScript: TypeDoc.** smalldocs runs `typedoc --json`. The JSON gives each exported item with its
  JSDoc comment, its types, inferred types too, and its defaults. It follows `export * from`. It also
  gives the file and the line of each item.

Neither tool keeps the comment after a parameter. smalldocs reads those from the source file, at the
lines that the JSON gives (see [Comments on parameters](#comments-on-parameters)).

We tested both tools on 2026-11-12:

- TypeDoc 0.28.20 with TypeScript 6.0.3, on a package of two files. It followed `export * from`. It
  inferred `number` for a function with no return type. It read `@param` and `@returns`. It did not
  read the comments after the parameters.
- rustdoc from stable Rust 1.95.0 on a small crate. Its JSON had format version 57, with the docs,
  the typed inputs and output, the `pub use` and the `impl` blocks of each struct. It ran only with
  `RUSTC_BOOTSTRAP=1`, because `-Z` needs a nightly toolchain.
- rustdoc from nightly Rust 1.102.0 (2026-11-11). Its JSON had format version 61. It gave the first
  and last line of each function, and resolved the intra-doc links ``[`add`]`` and
  ``[`std::fmt::Display`]`` to items.

## How a project runs it

The project needs no Python environment. Its author runs smalldocs with uvx, which makes a temporary
environment:

```bash
uvx smalldocs api build --dir docs
uvx smalldocs render docs
```

The section `api` in `_smalldocs.yml` names the language. In a `_quarto.yml`, the section is
`smalldocs.api`.

```yaml
api:
  language: rust             # python by default; rust or typescript
  manifest: ../Cargo.toml    # rust: the crate, from the folder of the site
  toolchain: nightly         # rust: the toolchain that runs rustdoc
  out: api
  source: https://github.com/me/mycrate/blob/main
```

```yaml
api:
  language: typescript
  entry: ../src/index.ts     # typescript: the entry points, one path or a list, or a folder
  tsconfig: ../tsconfig.json
  out: api
```

Without `language`, the section works as before. `api list` and `api module` are for Python only.
For Rust and TypeScript, `api` has `build` and `check`.

### Crates with only a binary, and apps with no index

Some projects have no public API.

- **A Rust crate with only `main.rs`,** such as gest. smalldocs then runs rustdoc on the binary with
  `--document-private-items`, and documents every item. The option `private: true` does the same for
  a library.
- **A TypeScript app with no index file,** such as the React front end of cricsdb. `entry` is then a
  folder, and smalldocs runs TypeDoc with `--entryPointStrategy expand`. Each file gets its own page.

### What must be installed

- **Rust:** a nightly toolchain, installed with `rustup toolchain install nightly`. It does not
  replace the default toolchain. If cargo or the toolchain is missing, smalldocs stops with a message
  that says how to install it. smalldocs never installs a toolchain itself.
- **TypeScript:** Node and the project's own packages, from `npm install`. smalldocs runs the
  project's TypeDoc when `node_modules/.bin/typedoc` exists. If not, it runs
  `npx --yes --package typedoc@0.28 typedoc`, which fetches TypeDoc into npm's cache, as uvx does for
  Python. If Node is missing, smalldocs stops and says so.

### The toolchain and the format of rustdoc's JSON

The rustdoc JSON format changes between nightly releases. smalldocs reads the formats 57 and 61.

- The default toolchain is `nightly`, so a new project works at once.
- When rustdoc writes another format, smalldocs stops. Its message names the format that it found and
  the formats that it reads. It asks the author to pin a dated nightly that writes one of them, such as
  `toolchain: nightly-2026-11-11`.
- `toolchain` must be text. A number, such as `1.95`, is an error that asks for quotes.

### What the tools leave in the project

Nothing. TypeDoc writes its JSON into a temporary folder. rustdoc writes into the user's own cache
folder, in the temporary folder. If cargo changes the project's `Cargo.lock`, smalldocs puts it back.

### No new dependency

The new code uses only the standard library. So smalldocs needs no optional extra for it.
`smalldocs api` still imports only fastcore and PyYAML, and it loads the module of a language only
when a site names that language.

## Comments on parameters

smalldocs reads a parameter's comment by its line, as fastcore does for Python.

1. The JSON gives the lines of the function. smalldocs reads its signature, from the first line to the
   line with the `{` that opens the body.
2. A `//` comment on the same line as a parameter documents that parameter. Rust finds a parameter
   as `name:`, `mut name:` or `r#name:`. TypeScript finds one as `name`, `name?` or `name =`.
3. A `//` comment on the line of the `)`, or on the line of the `{` that opens the body, documents
   the return value. A return type can span lines, such as `): (v: string) => void {` after a
   parameter list. The comments on the lines between belong to the parts of that type.
4. A comment on a line with two parameters documents neither, because it cannot say which.
5. A signature on one line keeps one rule. A comment on a line with the return type documents the
   return value, even when a parameter is on that line too. In Rust, a line with one parameter and no
   `->` gives its comment to the parameter.
6. Without that comment, smalldocs uses the doc comment's `@param` and `@returns` in TypeScript. In
   Rust it uses a `# Arguments` list in the doc comment, with lines such as ``* `a` - the first number``.
7. **In Rust, a `# Returns` section documents the return value.** A `# Returns` section is the Rust
   convention, as `# Arguments` is. rustfmt moves a comment after the `{` into the body, so a comment
   there does not last. A comment on the line of `->` still counts when rustfmt leaves it there.
   Rahul decided this on 2026-11-12.
   - A section of one paragraph of prose moves into the table, out of the doc comment. The targets of
     its links, such as `[x]: https://x`, stay in the doc comment.
   - A longer section stays in the doc comment, such as one with a list or an example. The table then
     holds its first paragraph, or "See Returns, below." when that paragraph is no prose.
   - A section runs to the next heading of its level or above. A `#` line inside a code block is no
     heading. The same holds for `# Arguments`.
   - A function that returns `()` keeps its `# Returns` section in the doc comment, as it has no row.
8. **A destructured parameter takes JSDoc's `@param` tags,** both `@param a` and `@param props.a`.
   TypeDoc drops a `@param props.a` when no `@param props` comes with it. It also names the parameter
   after the first `@param`, such as `a`. So smalldocs reads these tags from the source, and keeps
   the name `props`. It reads the doc comment past blank lines and comments that are no doc comments, as TypeDoc does. A
   function that is no component keeps TypeDoc's reading.

## The pages

The pages have the same kind of headings, ids, tables and source links as the Python pages.

### Where each page goes

The pages follow the source's folders, or the crate's modules. The Python pages are one page per
module in one folder. These pages are in folders.

- **TypeScript: one page per file.** A file `src/components/Badge.ts` gives
  `api/components/Badge.qmd`. A folder that every file is in, such as `src/`, is left out. An
  `index.ts` gives the page of its folder, `api/components/index.qmd`.
- **Rust: one page per module.** The crate's root is `api/<crate>.qmd`. A module with modules in it
  is its folder's `index.qmd`, such as `api/geo/index.qmd`. A module with none is a file, such as
  `api/geo/plane.qmd`.
- **No two pages share a file,** even on a disk that does not tell `A.qmd` from `a.qmd`. A second page
  of one name gets `-2`. A module named `index` gets `index-module.qmd`, because `index.qmd` is its
  folder's page.
- **A file name can hold `#`, `?`, `%` or a space.** The page keeps that name, and each link to it is
  percent-encoded, such as `a%23b.qmd`. The site decodes the link when it builds.

### Titles and the folder index

- **The title of a page is the file's name, or the module's own name,** such as `Badge` or `plane`.
- **A folder with no page of its own gets an `index.qmd`.** Its title is the folder's name. It lists
  the folder's pages and subfolders in a table, each by name, with a link and a summary.
- **The index of `out` itself, `api/index.qmd`, is titled "Reference".** For Rust, its description is
  the crate's summary. A sidebar `auto: api/**` leaves it out (see [The sidebar](#the-sidebar)).

### The comment of a module

A TypeScript file's description is its module comment. smalldocs follows TypeDoc's rule:

- **A comment with `@module` or `@packageDocumentation`** is the module's. TypeDoc reads it.
- **A declaration takes the comment right before it.** When a file opens with a `/** */` comment and
  a declaration follows it at once, the comment is the declaration's, as in TypeDoc.
- **Otherwise the opening comment is the module's.** This holds when an import, a re-export,
  a directive such as `"use client"`, another `/** */` comment or the end of the file follows it.
  TypeDoc drops such a comment, so smalldocs reads it from the file. A file with no imports keeps its
  comment this way, when the first declaration has its own comment.
- **Other comments do not count.** A licence in `/* */` or `//` comments, a `#!` line or a byte-order
  mark may come before the opening comment, and `//` or `/* */` comments may come after it.

### What each page holds

- **Each item:** a heading with its id, a source link, the signature in a `rust` or `ts` code block,
  the doc comment, and the table of parameters with type, default and description.
- **Headings name the kind of item,** such as `## struct Command`, `## fn add`, `## class Rect` or
  `## interface Point`. A method is one level down, as `### Command::call` or `### Rect.area`. A
  TypeScript function has no word before its name.
- **Heading text is escaped.** A name such as `__x__` or `$a.$b` shows as it is, not as bold text or
  maths. A title is escaped in the same way. The id of a heading is the name, unescaped.
- **Types in tables are plain text,** as on the Python pages, with the signs of Markdown, maths and
  HTML escaped.
- **A Rust path shows as the source writes it,** such as `io::Error` or `std::result::Result`. So
  `pub type Result<T> = std::result::Result<T, E>` does not read as a type of itself. rustdoc's JSON
  gives `std::path::Path` for a `Path` that a `use` brings in. So smalldocs shows the longest end of
  the path that the entry's source writes. That source is a function's signature, or the whole of
  any other item. A path with no source, such as a trait in "Implements", shows by its last name.
- **A Rust constant shows its value.** rustdoc's JSON gives `_` for a value that is not a literal,
  such as an array. smalldocs then shows the value as the source writes it, without its comments.
- **A stray `<` in a comment is escaped,** so that `Vec<u8>` shows as text. Code spans, code blocks and
  real HTML tags stay as they are.
- **Rust has no defaults,** so its tables have no Default column.
- **Structs and classes:** a table of the fields. Then the methods, each as its own entry.
- **Enums:** a table of the variants.
- **Traits and interfaces:** their methods. The fields of an interface or a type, as a table, with
  the comment after each field.
- **React components:** a component is a function with a capital name that returns JSX and takes
  no parameter or one props object. JSX here is `JSX.Element`, `ReactElement`, `ReactNode` or
  `ReactPortal`, with or without `React.`, alone or with `null`, `undefined` or `false`. A props object
  is any parameter that is not a string, a number, a boolean, a bigint, a symbol, a literal, or a
  union of them. A function that takes one of those is no component. Its entry
  shows the fields of the props type as the table of parameters, with the comment after each field
  and the default from the destructured props. Props written `Props & { more?: string }` are the
  fields of each part. When smalldocs cannot read a part, such as a type from `node_modules`, the
  entry shows the one `props` parameter. The function is still a component.
- **A comment on a line with several fields belongs to none of them,** as for parameters. In
  `{ width: number; height: number }  // the size`, neither field has a comment. The same holds for a
  comment after a field and the `}` that closes its type. Give each field its own line, or a JSDoc.
- **Rust `impl` blocks:** the methods of an inherent `impl` are entries under the type. A trait impl
  is listed by the trait's name only, such as "Implements `Display`". The auto traits, such as `Send`,
  and the blanket impls, such as `From`, are left out.
- **Re-exports:** an item has one entry, on the page of the module that declares it. The page that
  exports it again names it.

## Pages that a build writes, and pages that a person writes

A build must never lose a person's work, and must never leave its own old pages behind.

- **The mark.** The first line of the front matter of each page that a build writes is
  `# written by smalldocs api build; a build writes over it`. A build writes over a page, or deletes
  it, only when the page has this mark.
- **The manifest.** The build lists its pages in `api/.smalldocs-api`. The next build deletes a page
  that the manifest lists and the build no longer writes, when the page has the mark. A folder that
  this leaves empty goes too.
- **A build that stops** keeps in the manifest what it wrote, and what the manifest listed before.
- **A hand-written page stops the build.** A `.md`, an `.ipynb` or a `.qmd` without the mark, where a
  page of the build goes, stops the build before it writes anything. The message names the page.
  A page that a build wrote and a person then edited has lost its mark, so it stops the build too.
- **A hand-written folder index stays.** When a person wrote `api/components/index.qmd`, the
  module's page moves beside it, to `api/components/components.qmd`.
- **`out` must be a folder inside the site,** as for Python. smalldocs checks this before it runs a
  tool.

## Links

- **Source links need `root`.** A source link is the item's path from `root`, added to `source`.
  Without `root`, it is the git repository that holds the crate's manifest, or the manifest's folder.
  For TypeScript it is the git repository of the first entry, or else the default of the Python pages.
  So a site outside the repository still gets source links. When `source` is set but an item's file is
  outside `root`, the build warns once, and names the files. A file outside the project, such as one
  of another crate in cargo's cache or one in `node_modules`, can have no link, so it gets no warning.
- smalldocs writes `_symbols.json` as it does for Python. A name in backticks in any page then links
  to its entry.
- **On a Rust or TypeScript site, a name links when it is in `_symbols.json`.** On a Python site a name
  must also look like code, such as `add()` or `a.b`. On these sites `useCounter` links too. The site
  passes this to the renderer as `symbols_exact`.
- Rust's intra-doc links, such as ``[`Parser`]``, become links too. rustdoc's JSON resolves each to an
  item.
- A name from another crate links to that crate's docs. rustdoc's JSON gives `html_root_url` for each
  external crate, for example `https://doc.rust-lang.org/nightly/` for `std`. When a crate has none,
  the link goes to docs.rs. We have tested this for `std` only.
- TypeScript names from other packages are not linked, in this first version.

## `smalldocs api check`

`check` does for Rust and TypeScript what it does for Python.

- Every public item needs a doc comment.
- Every parameter needs a comment, or a `@param` or `# Arguments` line.
- The return needs a comment unless it is `()` or `void`. In Rust, a `# Returns` section is the way
  to document it, and `check` says so.
- A React component needs no comment on its return, because it returns what it draws. Its page still
  shows the return type.
- **A field is reported once.** When a component's props type has an entry of its own, `check`
  reports a field with no comment at that entry, such as `Box.width`, and not at each component.
- **A field whose line has other fields** is reported with the reason, and with what to do.
- `--shown` and `check-shown` work the same. TypeDoc gives only what a package exports, so a
  TypeScript check always holds only what the pages show.

## The sidebar

A sidebar entry `auto: api/**` now makes no section for `api` itself, and leaves out
`api/index.qmd`, as Quarto does. The subfolders of `api` are still sections.

This changes existing output. Before, any site with `auto: dir/**` got one section for `dir` around
its pages. A site that wants the folder's index in the sidebar lists it by name, before the `auto`
entry.

## Rules this keeps

- **The Python pages do not change.** A site without `language` builds byte for byte as before.
- **The API build deletes only pages in its manifest,** `api/.smalldocs-api`, that have the mark, and
  `out` must be inside the site.
- **`smalldocs api` imports only fastcore and PyYAML,** and the standard library.

## Tests

- **Fixtures.** The tests keep small JSON outputs of rustdoc, in the formats 57 and 61, and of TypeDoc,
  and the source files they came from. They need no Rust and no Node.
- **One test per rule.** Each rule above has a test, in `tests/test_api_rust.py` and
  `tests/test_api_ts.py`.
- **Real tools.** One test runs the real rustdoc, and one the real TypeDoc, on the fixtures' sources.
  Each is skipped when its tool is missing.
- **Two scripts make the fixtures again,** `scripts/rust_fixtures.py` and `scripts/ts_fixtures.py`.

## The projects we test it on

| Project | Language | What it is | Its docs now |
|---|---|---|---|
| jagt | Rust | a library and a binary, about 2,000 lines | no doc comments |
| cx | Rust | a library and a binary, about 800 lines | no doc comments |
| gest (Rahul's fork) | Rust | a binary only, about 46,000 lines | 2,808 doc comment lines, no comments after parameters |
| cricsdb, `frontend/` | TypeScript | a React app, 158 files | few doc comments |

## What is left

The code is merged into `main` with no release. These steps are still to do:

1. **Try it** on gest, which has doc comments, and on cricsdb.
2. **Document the targets.** Where a project has no docs, an agent adds the doc comments and the
   comments after the parameters, by the project's own rules, in its own branch.
3. **Learn from them.** Fix what the targets show, and write it down.
4. **Write our docs:** a page `guide/api-rust-typescript.qmd`, and a news post. Every page, here and in
   the targets, goes through the nossaifd checker and declaude.
5. An adversarial review, then a release, one patch number up.

## Decisions

Rahul approved these on 2026-11-12.

- **The minimum TypeDoc version** is 0.28, the one we tested.
- **Rust without nightly** has no fallback. `RUSTC_BOOTSTRAP=1` works on stable, but it is
  unsupported.
- **The name of the language key** is `language`.
- **The pages follow the folders and the module tree,** with an index for each folder.
- **A hand-written page stops the build,** and is never written over.
- **A React component needs no comment on its return.**
- **Names link exactly** on Rust and TypeScript sites.
- **The rule for a signature on one line stays** as it is.
- **A Rust return is documented in a `# Returns` section,** because rustfmt moves a comment after the
  `{` into the body. A comment on the line of `->` still counts.
- **The default toolchain is `nightly`,** with a message to pin a dated nightly.
- **The sidebar change stays,** though it changes existing output.
