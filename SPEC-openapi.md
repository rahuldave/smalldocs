# Spec: an HTTP API reference from an OpenAPI document

Status: written on 2026-11-12, and approved by Rahul on the same day. His decisions are in
[Decisions](#decisions). Step 1 of [The order of work](#the-order-of-work) is built, in the branch
`openapi-reference`. [What the build changed](#what-the-build-changed), at the end, lists each place where
the code differs from the first draft, and why. The text above it is kept true to the code.

## What it is for

A web backend has an HTTP API, and its readers need a reference for each endpoint. The reference gives
each endpoint's parameters, its request body, its responses and the shapes of its data. Most web
frameworks describe their API in an OpenAPI document, a JSON or YAML file in a standard format.
It has an entry for each operation, and a schema for each kind of data. An operation is
one method on one path, such as `GET /api/v1/teams`.

This spec adds a section to `api` that reads an OpenAPI document and writes reference pages. The pages
look like the Python pages of smalldocs, for example [the page of `smalldocs.api`](https://docs.smallish.dev/api/api.html).
Each entry has a heading with an id, a source link, a code block, a description and a table.

The first target is the FastAPI backend of cricsdb. Its file `api/app.py` sets
`openapi_url="/api/openapi.json"`. Its hand-written `docs/api.md` stays as the narrative page, next to the
generated reference. That page names 74 operations in backticks, such as `` `GET /api/v1/tournaments` ``.
Most of those names then link to their entries, as names of Python functions do now (see
[Links between pages](#links-between-pages)).

## Where the document comes from

### What other frameworks do

Other frameworks write the document too. We checked how each one gives it without a running
server. "Checked" means that we read the page on 2026-11-12. "Not checked" means that the line comes from
memory, and must be read before the docs cite it.

| Producer | How to get the document with no server | Version | Evidence |
|---|---|---|---|
| FastAPI (Python) | `app.openapi()` after an import of the app. We ran it (below) | 3.1.0 | [checked](https://fastapi.tiangolo.com/how-to/extending-openapi/) |
| utoipa (Rust) | `ApiDoc::openapi().to_pretty_json()`, or `to_yaml()` with the `yaml` feature, in a small binary or a test | not stated on the page | [checked](https://docs.rs/utoipa/latest/utoipa/openapi/struct.OpenApi.html) |
| poem-openapi (Rust) | `OpenApiService::spec()` gives JSON and `spec_yaml()` gives YAML, as a `String` | not checked | [checked](https://docs.rs/poem-openapi/latest/poem_openapi/struct.OpenApiService.html) |
| dropshot (Rust) | `dropshot-api-manager` with `cargo openapi generate` and `cargo openapi check`. It keeps the documents in a folder `openapi/` of the repository | not checked | [checked](https://github.com/oxidecomputer/dropshot-api-manager) |
| aide (Rust) | `finish_api` fills an `OpenApi` struct, which serde writes as JSON | not checked | [checked](https://docs.rs/aide/latest/aide/axum/index.html), but the serde step is not checked |
| NestJS, `@nestjs/swagger` | `SwaggerModule.createDocument(app, config)` on an app from `NestFactory.create`. The page says that the document can be saved as JSON or YAML, but gives no code | not stated | [checked](https://docs.nestjs.com/openapi/introduction) |
| tsoa | `tsoa spec` reads the controllers and writes the file. `tsoa.json` sets the folder | not stated | [checked](https://tsoa-community.github.io/docs/generating.html) |
| Hono, `@hono/zod-openapi` | `app.getOpenAPI31Document({...})` on the app object | 3.1.0 | [checked](https://github.com/honojs/middleware/tree/main/packages/zod-openapi) |
| Fastify, `@fastify/swagger` | `await fastify.ready()`, then `fastify.swagger()`, or `fastify.swagger({ yaml: true })` for YAML. No `listen()` | 3.0.3 by default, 3.1.0 or 3.2.0 if set | [checked](https://github.com/fastify/fastify-swagger) |
| zod-to-openapi | `new OpenApiGeneratorV31(registry.definitions).generateDocument({...})`, a library with no framework | 3.0 or 3.1 | not checked |
| drf-spectacular (Django) | `python manage.py spectacular --file schema.yml` | 3.0.3 | not checked |
| swag (Go) | `swag init` writes `docs/swagger.json` | Swagger 2.0 | not checked |

The table shows two things.

- **No producer needs a server, as far as we read.** Each one gives the document from a call in a small
  program, or from a command that writes a file. Four pages do not say that no server is needed (see
  [Notes for later](#notes-for-later)). So smalldocs needs a command and a file, and not a URL.
- **No producer gives the source location** of an operation in the pages that we read. Only FastAPI lets
  smalldocs find it, because a FastAPI route keeps its Python function (see [Source links](#source-links)).

### The three inputs

smalldocs is Python, and it runs through uv or uvx. It can document a project in any language, because it
reads the document and not the code. A section takes exactly one of these inputs.

- **`file:`** names a JSON or YAML file in the repository, from the folder of the site. It suits
  dropshot-api-manager, tsoa, drf-spectacular and swag, which write a file.
- **`command:`** is a command that prints the document on its standard output. smalldocs runs it in
  `root`, the project's folder, in the project's own environment. It takes one string, which smalldocs
  splits as a shell does but runs with no shell, or a list. It suits utoipa, poem-openapi, Hono, Fastify
  and NestJS, through a small program that the project keeps.
- **`fastapi:`** names a FastAPI app as `module:attribute`, as uvicorn does. smalldocs runs its own short
  Python program in the project's environment. The program imports the app, calls `app.openapi()` and adds
  the file and line of each route. It prints the result, and writes nothing.

The input does not set the language. Each section says `language: openapi`, as the decisions say.

The FastAPI case is one line of config.

```yaml
api:
  - language: openapi
    fastapi: api.app:app
    out: reference
    source: https://github.com/rahuldave/cricsdb/blob/main
```

An app that adds its routes at startup adds one more line, `setup:` (see
[Routes added at startup](#routes-added-at-startup-the-key-setup)). cricsdb is such an app.

```yaml
api:
  - language: openapi
    fastapi: api.app:app
    setup: api.routers:register_routers
    out: reference
    source: https://github.com/rahuldave/cricsdb/blob/main
```

The other inputs look like this.

```yaml
api:
  - language: openapi
    command: cargo run --quiet --bin openapi   # a binary that prints ApiDoc::openapi().to_pretty_json()
  - language: openapi
    command: npx tsx scripts/openapi.ts        # a script that prints app.getOpenAPI31Document(...)
  - language: openapi
    file: ../openapi/my-api.json               # written by `cargo openapi generate`
```

There is no `url:` input, for three reasons.

- **A build must repeat.** A document from a running server depends on what is running at that moment.
- **Every producer above gives the document without a server,** by its page or by its signature.
- **A command covers the rare case.** `command: curl -s http://localhost:8000/api/openapi.json` fetches the
  document from a running server.

### How the FastAPI program runs

- **The runner** is `uv run --frozen python -c PROGRAM`, in `root`. The option `python:` sets
  another runner, such as `python: .venv/bin/python`. `--frozen` never changes `uv.lock`, but uv can still
  install packages into the project's `.venv` (see [Decisions](#decisions)).
- **The app and the setup are in environment variables,** `SMALLDOCS_FASTAPI_APP` and
  `SMALLDOCS_FASTAPI_SETUP`, and not in `sys.argv`. An app that reads its arguments at import, with
  argparse or a settings class, then sees no smalldocs argument.
- **Only the document goes to standard output.** The program sends `sys.stdout` to standard error during
  the import and the setup, so an app that prints at import does not break the JSON. It writes the
  document to `sys.__stdout__` at the end.
- **The program runs with `-c`,** because Python then puts the current folder first on `sys.path`. A
  program run from a file sees only its own folder, and the import of `api.app` fails. We saw this failure
  in a test. The current folder then also comes before the standard library. So the program first
  imports its own modules (`json`, `inspect`, `asyncio`, `os` and `sys`) with that folder taken off
  `sys.path`, and puts it back before it imports the app. A project file `json.py` then does not shadow
  the program's `json`.
- **smalldocs sets `PYTHONDONTWRITEBYTECODE=1`,** so the import writes no `__pycache__` folders.
- **smalldocs never imports FastAPI itself.** The program is a string in smalldocs, and it runs in the
  project's environment. So `smalldocs api` still imports only fastcore and PyYAML, and the standard
  library.
- **A document with no operations is an error.** The message names the app. It says that the routers may
  be added only at startup, and that `setup:` can add them (see
  [Routes added at startup](#routes-added-at-startup-the-key-setup)).
- **Each build runs the program,** because `Site.build` runs the API build first. So `smalldocs serve`
  runs `uv run` and imports the app on every save. The guide page says so.

### What a command may do

smalldocs writes nothing into the project, except the pages in the site's `out` folder and
`_symbols.json`, as for Python. It does not save the OpenAPI document. But a command is the project's own
tool, and it can write. For example, `cargo run` writes into `target/`. smalldocs cannot stop that, and the
docs say so.

A command that fails stops the build. The message gives its exit code and the end of its standard error.
Output that is not JSON or YAML stops the build too. So a command's standard output must hold only the
document. Notices from `npx` or `cargo` must go to standard error, for example with `cargo run --quiet`.
The option `timeout:` gives the seconds to wait, 300 by default.

## The pages

### One page for each tag

An OpenAPI tag is a name that groups operations, such as `Batting`. FastAPI takes it from `tags=` on a
router.

- **Each tag has a page** `out/<tag>.qmd`. Its title is the tag's name, and its description is the tag's
  description from the document's top-level `tags`. The file name follows the rule for operation ids
  below, so `Head to Head` becomes `head-to-head.qmd` and `2024 Season` becomes `2024-season.qmd`. A tag
  whose name has no letter or digit gets the name `tag`.
- **File names never collide.** The names `schemas` and `index` are taken first. A tag whose file name is
  taken, such as `schemas`, `index`, or `Scope Averages` after `Scope-Averages`, gets `-2`, then `-3`,
  from the reserving mode of the shared `unique` (see
  [What the shared layer must gain](#what-the-shared-layer-must-gain)). So a tag `schemas` gets
  `schemas-2.qmd`. Case does not tell file names apart, so `Teams` and `teams` give `teams.qmd` and
  `teams-2.qmd`.
- **A tag in the top-level `tags` that no operation uses** has no page.
- **The pages keep the document's order.** The order of the top-level `tags` comes first, then the order
  in which tags first appear. Each page has `order:` in its front matter, so the sidebar keeps that order.
  The index of the folder lists the pages by name, as for Rust and TypeScript.
- **Operations with no tag** go on a page `default.qmd`, with the title "default", as Swagger UI names it.
  A tag named `default`, in any case, shares that page, as Swagger UI merges them.
- **An operation with several tags** has one entry, on the page of its first tag, as a Python re-export
  has one entry.
- **The schemas** have their own page, `schemas.qmd`.

cricsdb has 11 tags, so its reference has 12 pages.

### One entry for each operation

Here is the entry for `GET /api/players/{player_id}` from the test app (see [Tests](#tests)).

````markdown
## GET /api/players/\{player_id\} {#get-api-players-player_id}

[source](https://github.com/me/tiny/blob/main/app.py#L21){.source-link}

```http
GET /api/players/{player_id}?season={season}&limit=10
x-trace: {x-trace}
```

Get Player

Get one player.

| Parameter | In | Type | Default | Required | Description |
|---|---|---|---|---|---|
| `player_id` | path | string | | yes | The player's id |
| `season` | query | string or null | | | Only this season |
| `limit` | query | integer | `10` | | At most this many rows |
| `x-trace` | header | string or null | | | A trace id |

| Status | Media type | Type | Description |
|---|---|---|---|
| 200 | `application/json` | [Player](schemas.qmd#Player) | Successful Response |
| 422 | `application/json` | [HTTPValidationError](schemas.qmd#HTTPValidationError) | Validation Error |
````

- **The heading** is the method and the path, as plain text. A test checks that smalldocs keeps the
  braces of `{player_id}` as text, and reads only the last braces as the id. Quarto gives the same text
  and id (see [What the build changed](#what-the-build-changed)).
- **The heading escapes Markdown in the path.** Both smalldocs and Pandoc read `## GET /a/__x__/b` with
  `x` in bold. We checked both on 2026-11-12. So the heading escapes the path with the shared
  `heading_text`, which the Rust and TypeScript pages use. It puts a backslash before each sign of
  Markdown, maths and HTML, braces too. The page then shows the path as it is.
- **The id** comes from the method and the path. smalldocs removes the braces and puts a `-` for each run
  of other characters than letters, digits, `_` and `.`. It then makes the id lower case, and trims `-`
  from both ends. So `GET /api/v1/batters/{person_id}/by-innings` has the id
  `get-api-v1-batters-person_id-by-innings`, and `GET /` has the id `get`. The id does not change when the
  code changes, unless the path changes.
- **The id is explicit, so it is not Pandoc's id of the heading text.** Pandoc would make
  `get-apiplayersplayer_id` from that text. The explicit id wins in both tools.
- **smalldocs makes the ids unique itself.** Pandoc keeps two explicit ids that are the same, with only a
  warning, and so does smalldocs now. So the section first makes every operation's id, its natural id.
  The reserving mode of the shared `unique` keeps each natural id for its first operation. It gives each
  repeat `-2`, then `-3`, in the document's order, and skips every natural id. For example, `/a/{b}`,
  `/a/b` and `/a-b` all give `get-a-b`, so the second gets `get-a-b-2` and the third `get-a-b-3`. When
  `/a/b-2` is also a path, `get-a-b-2` is its natural id, so the second gets `get-a-b-3` and the third
  `get-a-b-4`. Case does not tell ids apart, as in `unique` now. The ids are unique in the whole section,
  across its pages, so an operation keeps its id when it moves to another tag.
- **Text in a table cell** has each `|` escaped as `\|` by the shared `table`, and each line break folded
  to a space by `one_line`. `one_line` is used only for cells, and never for the body of a page. In
  cricsdb, 236 parameter descriptions hold a `|`, such as `'won' | 'lost' | 'tied'`. Unescaped, each one
  would split its row.
- **The code block** is the request in HTTP form. It shows each path parameter as `{name}`, each query
  parameter with its default or `{name}`, each header on its own line, by the name that the document
  gives it, and the cookies on one line `Cookie: a={a}; b={b}`. It is the signature of the
  operation, as a Python entry has the signature of a function.
- **The summary and the description** follow, in that order. smalldocs leaves out the summary when the
  description starts with it.
- **The parameters** come from the operation and from its path. An operation's parameter replaces the
  path's parameter with the same name and place. A cookie parameter shows `cookie` in the column In.
- **The request body,** when there is one, is a line that gives its media type and its type, and says
  whether it is required. A body with a schema of its own, and no name, has a table of its fields.
- **The responses** are a table, with one row for each status and media type. `default` is a status too.
- **`deprecated: true`** adds the line "Deprecated." under the heading, and the word in the description of
  a parameter.

### One entry for each schema

A schema is the shape of one kind of data, under `components.schemas` in the document. A Pydantic model
in FastAPI becomes one schema.

````markdown
## Player {#Player}

A player.

| Field | Type | Default | Required | Description |
|---|---|---|---|---|
| `id` | string | | yes | The cricsheet id |
| `name` | string | | yes | The full name |
| `team` | string or null | | | The current team, if any |
````

- **The id** is the schema's name, as a Python class has its name as its id. The id keeps the name's
  case, but case does not tell two ids apart, the same rule as for file names and operation ids. So
  `Player` has the id `Player`, and a later `player` has the id `player-2`. A character outside Pandoc's
  id rules becomes `-`. Two names that then give the same id, such as `Page[Player]` and `Page-Player-`,
  get `-2` on the second, as operation ids do.
- **An id of the page's own markup is never used.** A schema named `TOC` or `quarto-content` would clash
  with an id that `layout.py` writes. These ids are reserved, so such a schema gets `-2`, as in `TOC-2`.
  The reserved ids are a new constant in `api.py` (see
  [What the shared layer must gain](#what-the-shared-layer-must-gain)).
- **An object** has a table of its fields. A field that is an object with no name, written inline, has
  rows with dotted names, such as `stats.runs`, to a depth of three. A field that is a `$ref` to a named
  schema is a link, and is never expanded.
- **An enum** has a line "One of" with its values. A schema that is not an object, such as a string with a
  format, has a line with its type.
- Python model entries have no code block, so schema entries have none.

### Types in the tables

smalldocs writes each type from its JSON Schema, in a short form. A type is plain text, as `type_cell`
writes it for Rust and TypeScript, and a schema's name is a link (see [What it reuses](#what-it-reuses)).

| Schema | Written as |
|---|---|
| `$ref` to `#/components/schemas/Player` | [Player](schemas.qmd#Player) |
| `type: string`, `format: date-time` | string (date-time) |
| `type: array`, `items` of `Player` | array of [Player](schemas.qmd#Player) |
| `additionalProperties` of `integer` | map of integer |
| `anyOf` or `oneOf` | each type, joined with "or" |
| `allOf` of one type | that type |
| `allOf` of several types | each type, joined with "and" |
| `type: [string, integer]` (3.1) | string or integer |
| `type: "null"` | null |
| `enum` | one of `"male"`, `"female"` |
| `const` (3.1) | `"male"` |
| `{}` | any |
| `false` (3.1) | never |
| `array` of `string or null` | array of (string or null) |

A default is the JSON value in backticks, such as `10`, `"male"` or `null`. A value is a code span from
the shared `code_span`, whose backticks are longer than any run in the value. A type that joins types
with "or" or "and" is in parentheses after "array of" and "map of".

### OpenAPI 3.0 and 3.1

smalldocs reads OpenAPI 3.0 and 3.1. A field that the two versions write in two ways has one output.

- **A type that can be null** is `nullable: true` in 3.0. It is `type: [string, "null"]` or an `anyOf`
  with `{type: "null"}` in 3.1. Each is written as "string or null".
- **`nullable` comes last.** 3.0 ignores what sits beside a `$ref`, so producers write
  `allOf: [{$ref: Player}]` with `nullable: true`. smalldocs first writes the type, here `Player`, and then
  adds "or `null`". So the 3.0 form and the 3.1 form `anyOf: [{$ref: Player}, {type: "null"}]` give the
  same text.
- **A `$ref` with a description beside it** is allowed in 3.1. smalldocs then uses that description.
- **A `$ref` to a named schema,** `#/components/schemas/X`, is always a link to `X`, and is never
  inlined. So a schema that refers to itself, such as a `Tree` whose `kids` are an array of `Tree`, ends in
  a link and not in a loop.
- **Every other `$ref` inside the document** is inlined. It may be a parameter, a request body, a response, a path
  item, or a schema pointer below a named schema, such as `#/components/schemas/X/properties/y`. smalldocs
  keeps the chain of refs that it is following. A ref that is already on the chain stops the build, with
  a message that names the chain. A `$ref` to another file stops the build, with a message that names it.
- **OpenAPI 3.2** is read as 3.1, with one warning. Its new fields are left out.
- **Swagger 2.0,** with `swagger: "2.0"`, stops the build. The message says that smalldocs reads OpenAPI
  3.0 and 3.1.

### What is left out

These parts of a document are not on the pages in the first version.

- **Callbacks, webhooks and links.**
- **Security schemes and security requirements.** See [Decisions](#decisions).
- **Examples** of requests and responses. See [Decisions](#decisions).
- **`servers`, response headers, `externalDocs`, XML and `discriminator`.**
- **Limits on a value,** such as `minimum`, `maxLength` and `pattern`.
- **Extensions** whose names start with `x-`, except `x-smalldocs-source`.

## Source links

An entry gets a source link when its operation or schema has an extension `x-smalldocs-source` with a
`file` and a `line`. A relative `file` is relative to `root`. An absolute `file`, as the FastAPI program
writes, is made relative to `root`. A file outside `root` gets no link. smalldocs puts the path under the
URL of `source:`, as for Python.

- **FastAPI:** the program adds the extension to each operation. It takes the route's function, with
  `inspect.unwrap(route.endpoint)`, and reads its file and line with `inspect`. The line is the line of
  the first decorator. On cricsdb, all 127 operations got a file and a line.
- **When `inspect` fails,** the entry has no source link, and the build goes on. This happens for a
  `functools.partial`, a built-in, or code with no source file. A decorator without `functools.wraps` makes
  the link point at the decorator's code. The guide page says so.
- **FastAPI schemas** get no source link in the first version. See [Decisions](#decisions).
- **Other producers:** none of them writes a source location. A project may add `x-smalldocs-source` in
  its own program, and the link then appears.

## Links between pages

- **`_symbols.json`** gets these keys for each section.
  - The method and the path of each operation, such as `GET /api/players/{player_id}`.
  - The `operationId` of each operation, such as `getPlayer`, or FastAPI's
    `get_player_api_players__player_id__get`.
  - The name of each schema, such as `Player`, and the name after the folder, such as `reference.Player`.
- **A short name belongs to the first section** that has it, as names in the Python index belong to the
  first module now. So a Python model `Player` and a schema `Player` can share one site.
- **Types in the tables** are links written into the page, and not names for linkify. So they link to the
  right schema in every site.
- **The narrative page** of cricsdb names 74 operations in backticks. Linkify links a name that is the
  same text as a key. We counted on 2026-11-12, with `register_routers`.
  - **45 names match a key exactly.**
  - **16 more differ only in a parameter's name,** such as `GET /api/v1/batters/{id}/by-innings` for the
    path's `{person_id}`.
  - **13 are shorthand,** such as `GET /by-over`, and match nothing.

  smalldocs links only exact names. cricsdb's agent edits the 16 names in `docs/api.md` to use the
  parameter names of the code, such as `{person_id}`. A reader who calls the API needs those names. The
  13 shorthand names need an edit too, if they are to link.

## `smalldocs api check`

`check` holds the document to the same standard as Python code. It reports each gap on one line, as the
Python check does, and returns 1 when it finds one.

- **Each operation** needs a summary or a description. FastAPI makes every summary from the function's
  name, such as "Get Player". So for `fastapi:` input, `check` needs the description, which is the
  docstring.
- **Each parameter** needs a description.
- **Each schema** needs a description, and so does each of its fields.
- **Each `2xx` response** needs a schema, but only when the section sets `check-responses: true`. It is off
  by default, because many projects, cricsdb among them, return plain dictionaries for now. A `2xx`
  response is one whose status is from 200 to 299, or `2XX`. A `204` response has no body, so it is not
  checked. A missing schema counts as no schema. So do the empty schema `{}` and an `object` with no
  `properties`. FastAPI writes `{}` for a route with no return type, and
  `{"type": "object", "additionalProperties": true}` for a route typed `-> dict`. The line says
  "no response schema" and names the operation. In FastAPI the fix is a Pydantic `response_model`.
- **FastAPI's own schemas,** `HTTPValidationError` and `ValidationError`, are not checked.
- **`--shown` and `check-shown`** change nothing, because the pages show every operation and schema.

On cricsdb, `check` would report 49 operations with no docstring and 1,164 parameters with no description. Those 1,164 gaps have only 32 names. For example, `gender` has no description in 125
operations. So the report also gives the count for each parameter name. With `check-responses: true`, it
would also report all 127 operations, for no response schema.

## Many sections in one site

A project can want both its Python reference and its HTTP reference. cricsdb could want three, for its
Python code, its TypeScript front end and its HTTP API. So `api` takes a list of sections, and each section
names its `language`.

```yaml
api:
  - packages: [cricsdb]        # python, the default language
    root: ..
    out: python
  - language: openapi
    fastapi: api.app:app
    root: ..
    out: reference
```

- **A single mapping** works as now, and builds byte for byte as before. A list of one Python section
  builds the same bytes as that mapping, and a test checks it.
- **Each section has its own `out`.** Two sections with the same `out`, or one `out` inside another,
  stop the build. Each `out` has its own manifest, `.smalldocs-api`, and the build deletes only the pages
  that the manifest lists.
- **A single mapping writes exactly what it writes now.** It writes `_symbols.json` as today, and no
  names file.
- **Each build writes its index beside its manifest.** Today Python's `build` and `write_reference`
  each write `_symbols.json`. Both keep doing so for a single mapping, through the shared `write_names`.
  For a list, each section's build writes its names file, and no `_symbols.json`. Python's `build` gets this through a refactor inside `api.py`,
  which changes no byte of the Python pages. A test checks it with babykev-style pages.
- **The merge is in one place, the loop over the list.** Only the loop, `merge_names`, writes
  `_symbols.json` for a list. It reads the names file of each section, in the order of the list.
- **Each section of a list keeps its names beside its manifest,** in `out/.smalldocs-symbols.json`. The
  file has two keys, `{"names": {...}, "full": [...]}`. `names` is the index in the order the build made
  it, so a list of one section writes the same `_symbols.json` as the mapping. `full` lists the full names
  in it, such as `reference.Player` or `mycrate::Point::distance`. Names files are written only
  when `api` is a list.
- **`--out NAME`** runs one section, and writes its names file. The loop then merges that section's new
  index with the names files of the other sections, so their names stay.
- **A short name that two sections give** belongs to the first section, with no warning, as a short name
  of two Python modules does now.
- **A full name that two sections give,** such as `reference.Player` from a Python module `reference` and
  from the OpenAPI folder `reference`, belongs to the first section, with a warning that names both. Today
  a later Python key replaces an earlier one, so this is new only for a list.
- **A section removed from the list** leaves its pages, because no section names its manifest. The loop
  finds each `.smalldocs-api` in the site that no section names, and warns with its folder. It deletes
  nothing there, because the API build deletes only the pages of a section in the list.
- **Two outs that differ only in case,** such as `API` and `api`, are one folder, as on macOS.
- **The warnings go through the build's warnings.** `build_from_config` returns them with its pages, and
  `Site.build` keeps each one with `Site.warn`, so `render --strict` fails on them. `smalldocs api build`
  prints each one on standard error, as `warning: ...`.
- **`smalldocs api build` and `check`** run every section.
- **`smalldocs api list` and `module`** are for Python. With a list, they act on the Python section. When
  the list has no Python section, they stop with a message. When it has several, they stop with a message
  that asks for `--out NAME`.

These places in the code read `api`, and each must take a list.

| Place | What it does now | What it does with a list |
|---|---|---|
| `config.section` (config.py:174) | Refuses an `api` that is not a mapping | Accepts a list of mappings for `api` |
| `config.check_native` (config.py:364) | Calls `section` for `api` | Checks each item of the list |
| `api.build_from_config` | Reads one `Settings` and builds | Reads each item, builds it, and merges the indexes |
| `api.main` (api.py:1091) | Reads one `Settings` | Runs each item, or the item of `--out NAME` |
| `site.load_symbols` (site.py:319, 328) | Calls `api.get` on a mapping | Reads `linkify` from the top level, and exact matching from every item |
| `cli.py` (the parser of `smalldocs api`) | Has `--dir` and `--shown` | Gains `--out NAME` |
| `Site.build` (site.py:411) | Builds when `api` is not empty | Builds the same way |
- **`linkify`** moves to the top level for a list. `site.load_symbols` now calls `api.get("linkify", ...)`
  (site.py:319), which fails on a list. With a list, it reads `linkify` from the top level, and linkify is
  on by default.
- **Exact matching** is the line `self.exact_symbols = isinstance(api, dict) and api.get("language") in
  ("rust", "typescript")` (site.py:328). With it, a name in backticks links when it is a key, though it
  does not look like code. `openapi` joins that tuple, because `GET /api/v1/teams` does not look like code.
  With a list, exact matching is on when any section's language is `rust`, `typescript` or `openapi`.

We also looked at a separate top-level key, `openapi:`. We prefer the list, for two reasons.

- **One set of rules.** `out`, the manifest, `source`, `check` and `_symbols.json` work the same in every
  section. A second key would repeat each of them.
- **The list serves Rust and TypeScript too.** A repository with a crate and a front end needs two
  sections of the sibling spec, `SPEC-rust-typescript.md`, as well.

## What it reuses

Rahul's rule: the OpenAPI reference must not write API pages a second way. smalldocs already has two
writers.

- **Python,** in `api.py`. It is kept byte for byte, because babykev's pages must not change. The OpenAPI
  reader does not touch it.
- **The shared layer of Rust and TypeScript,** in `api.py`, in the part "the pages of Rust and
  TypeScript". `api_rust.py` and `api_ts.py` both use it. We read it on 2026-11-12, in the merged branch
  `rust-typescript-api`.

`api_openapi.py` is a third reader of that shared layer. It adds no code of its own to write pages, keep
a manifest, escape text or write an index.

### The contract of a reader

There is no shared class of entries today. `api_rust.py` has its own `Entry` and `Page`, and `api_ts.py`
has its own `Module`. What the readers share is the hand-off. A reader makes three things and gives them
to `write_reference`.

- **The text of each page,** by its path in `out`.
- **The index of names,** for `_symbols.json`.
- **The pages that someone wrote by hand,** from `hand_written`.

`api_openapi.py` keeps that contract. Its `build(s)` has the same shape as `api_rust.build`, in a few
lines.

```python
taken = hand_written(out_folder(s))
pages = {...}            # one page per tag, and schemas.qmd
pages |= folder_indexes(s.out, summaries, taken, description)
return write_reference(s, pages, index, taken)
```

A shared class of entries for all three readers would be a change to Rust and TypeScript. It is a note
for later, and is not part of this spec.

### What it calls from `api.py`

| Function | What the OpenAPI reader uses it for |
|---|---|
| `Settings.read` and `Settings.read_other` | Read a section with `language: openapi` |
| `language_module` | Send the section to `smalldocs.api_openapi`, for `build` and for `check` |
| `out_folder` | Refuse an `out` that is the site or outside it, before the program or the command runs |
| `hand_written` | Find the pages that someone wrote in `out`, which a build never writes over |
| `page_key` | Compare a tag's file name with the hand-written pages and the other pages, by case as macOS does |
| `front_matter` | Begin each page with the mark of a build, the title and the description |
| `yaml_text` | Quote a tag's name in the front matter, through `front_matter` |
| `escape_angles` | Escape a stray `<` in the descriptions, which are Markdown |
| `type_cell` | Write each type as plain text in a cell, with Markdown's signs escaped |
| `table` | Write each table, with `\|` for each `|` in a cell |
| `folder_indexes` | Write `out/index.qmd`, with the document's `info.description` |
| `write_reference` | Write the pages, delete only the marked pages of the last manifest, refuse to write over a hand-written page, and write `_symbols.json` for a single mapping |

`listing` and `folder_listing` run inside `folder_indexes`. `MARK` and `marked` run inside
`front_matter`, `hand_written` and `write_reference`.

### What the shared layer must gain

Each addition is generic, so that any reader can use it. Each one keeps the output of Python, Rust and
TypeScript the same, byte for byte.

- **Nothing for the tables.** `table(rows, head)` already takes any column titles. The OpenAPI tables
  with the columns In and Required are calls of `table`, with no new code.
- **`front_matter` gains `order`,** an optional number. With no `order`, it writes the same bytes as now.
- **`one_line` moves** from `api_ts.py` to `api.py`. `api_ts.py` imports it from there. It folds the lines
  of a description for a table cell only, never for the body of a page.
- **`unique` moves** from `api_ts.py` to `api.py`, and gains a second mode. Its default mode stays as it
  is, because the TypeScript pages depend on it.
  - **The default mode** gives a repeat `-2`, then `-3`, and ignores case, as now.
  - **The reserving mode** takes a set of reserved names too. It keeps each name for its first
    occurrence. It gives each repeat `-2`, then `-3`, and skips every name in the list and every reserved
    name. It ignores case too. The OpenAPI reader uses this mode for ids and for file names.

  `api_rust.unique`, which writes `-module`, stays in `api_rust.py`.
- **A constant of reserved ids** is new code in `api.py`. It holds the 16 fixed ids that `layout.py` writes. They are
  `TOC`, `toc-title`, `title-block-header`, `quarto-header`, `quarto-content`, `quarto-document-content`,
  `quarto-sidebar`, `quarto-sidebar-glass`, `quarto-margin-sidebar`, `quarto-search`, `quarto-appendix`,
  `quarto-back-to-top`, `navbarCollapse`, `smalldocs-page-style`, `giscus-base-theme` and
  `giscus-alt-theme`. It also holds three patterns of ids that a page writes:
  - `toc-` before a heading's id, from `layout.py`;
  - `fn1`, `fn2` and on, for footnotes, from `markdown.py`;
  - `fnref1`, `fnref2` and on, for the links to footnotes, from `markdown.py`.

  The constant is in `api.py`, because `api.py` must not import `layout.py`. A test builds a page with a
  table of contents, a footnote and giscus, and checks that the constant holds every id that the page
  has.
- **`source_line(s, path, line)`** joins `source`, the path and `#L<line>` into a source link. `path` is
  relative to `root`. `api_rust.source_link` and `api_ts.source_link` end with nearly the same lines. The
  OpenAPI reader calls `source_line` with the path that [Source links](#source-links) gives. Rust and
  TypeScript may move to it later, with the same output.
- **`write_reference` writes `_symbols.json` only for a single mapping,** as now. For a section of a list,
  it writes the names file `out/.smalldocs-symbols.json` instead, and returns the index. The loop then
  writes `_symbols.json` (see [Many sections in one site](#many-sections-in-one-site)).
- **Python's `build` returns its index** through a refactor inside `api.py`, as `write_reference` does.
  The Python pages, and `_symbols.json` for a single mapping, keep every byte.
- **`Settings` gains six fields for OpenAPI,** `file`, `command`, `fastapi`, `setup`, `python` and
  `timeout`. `Settings.read` accepts `openapi` as a language, and `language_module` maps it to
  `smalldocs.api_openapi`.

### The list of sections goes through the same dispatch

`build_from_config` and `main` read each item of a list-shaped `api` with `Settings.read`, as they read
the single mapping now. Each item then goes to `build(s)`, which sends Python to its own code and any
other language to `language_module(s).build(s)`. `run` sends `check` the same way. So a list adds one loop
over the items, and no second path for any language. The loop is also the one place that merges the
indexes and writes `_symbols.json`.

## The code

- **A new module, `api_openapi.py`,** reads the document and makes the text of the pages, as
  `api_rust.py` and `api_ts.py` do. It uses `json`, `subprocess`, `shlex` and `re`, and PyYAML for YAML.
  smalldocs needs no new dependency.
- **`api.py`** reads a list of sections, and sends each one to its language, through `language_module`.
  The section [What it reuses](#what-it-reuses) lists what `api_openapi.py` takes from `api.py`.
- **`config.py` and `site.py`** accept `api` as a list, at the places in the table of
  [Many sections in one site](#many-sections-in-one-site).
- **`cli.py`** gives `smalldocs api` the option `--out NAME`.
- **The pages are plain `.qmd` files,** which smalldocs renders as any other page. The same document
  gives the same pages, byte for byte, because smalldocs keeps the document's order.

## Rules this keeps

- **The Python pages do not change.** A site whose `api` is one mapping builds byte for byte as before.
- **The API build deletes only pages in its manifest,** and `out` must be inside the site.
- **`smalldocs api` imports only fastcore and PyYAML,** and the standard library.
- **No source is published.** The OpenAPI document is not copied into the site. A project that wants to
  publish it lists it in `resources`.

## Tests

### What we ran

We ran these commands on 2026-11-12, in the scratchpad and in cricsdb. None of them changed a tracked file
of cricsdb.

1. A test app of 30 lines, with a path, a query and a header parameter, a body, a response model and a
   tag. We wrote its document with
   `uv run --no-project --with fastapi python -c "import json, app; json.dump(app.app.openapi(), open('tiny-openapi.json', 'w'), indent=1)"`.
   It ran with FastAPI 0.162.5 and Pydantic 2.14.3, and needed no server. The document had
   `openapi: 3.1.0`, two paths and four schemas, `HTTPValidationError`, `NewPlayer`, `Player` and
   `ValidationError`.
2. In that document, FastAPI made the summary "Get Player" from the function's name, and the description
   from the docstring. A value that can be null was an `anyOf` with `{"type": "null"}`. In the response
   schema `Player`, FastAPI left out the default of `team`.
3. In cricsdb, `PYTHONDONTWRITEBYTECODE=1 uv run --no-sync python -c` imported `api.app` and called
   `app.openapi()`. With FastAPI 0.135.3, the document had `openapi: 3.1.0` and no paths.
4. We then called `register_routers(app)` first. The document had 127 `GET` operations in 11 tags, and two
   schemas. 127 operations had a summary and 78 had a description. 985 of 2,149 parameters had a
   description. No `200` response had a schema, because the routes return plain dictionaries.
5. The source program found the file and line of all 127 operations. Run from a file, it failed with
   `ModuleNotFoundError: No module named 'app'`. Run with `-c`, it worked.

### Fixtures

The fixtures live in `tests/openapi/`. The tests need no FastAPI, no Rust and no Node.

- **`tiny_app.py` and `tiny.json`,** the test app of step 1 and its document with source locations. A
  script, `scripts/openapi_cases.py`, writes `tiny.json` again, as `scripts/fence_cases.py` does for the
  fenced divs.
- **Real documents from the OpenAPI Initiative,** from
  [learn.openapis.org](https://github.com/OAI/learn.openapis.org/tree/main/examples).
  They are `v3.0/petstore.yaml`, `v3.0/petstore-expanded.yaml` and `v3.0/callback-example.yaml`, and
  `v3.1/webhook-example.yaml`. Their license is CC BY 4.0, so the fixtures keep a line of credit.
- **A hand-made 3.0 document** with `nullable`, an `allOf` of one type, parameters on a path, a parameter
  by `$ref`, two paths with the same id, an operation with two tags and one with none.
- **A Swagger 2.0 document,** which must stop the build.

cricsdb's document is not a fixture, because it is large and it changes with cricsdb.

### One test for each rule

- **Ids:** the id of each operation and schema, and braces and Markdown characters in the heading.
  Collisions are `/a/{b}`, `/a/b` and `/a-b`, a real path `/a/b-2`, `GET /`, and `Player` then `player`,
  which gives `player-2`. A schema named `TOC` gives `TOC-2`. One test checks the constant of reserved
  ids against a built page.
- **`unique`:** the default mode gives the same names as now, on the TypeScript cases. The reserving mode
  skips a natural name and a reserved name.
- **Cells:** a description with `|` and one with a line break.
- **Types:** each row of the table of types, and the same output for a 3.0 and a 3.1 type that can be
  null, also with `allOf` of a `$ref`. Cycles are a schema that refers to itself, and a chain of response
  refs that loops.
- **Links:** a `$ref` link, the keys in `_symbols.json`, and a short name in two sections.
- **Pages:** one page per tag, the `default` page, an operation with two tags, and the order of pages.
  File names are tags `schemas`, `index`, `Default`, `2024 Season`, `Scope Averages` with `Scope-Averages`,
  and a declared tag that no operation uses.
- **Check:** each kind of gap, FastAPI's own schemas skipped, and the counts by parameter name.
- **Inputs:** a JSON file, a YAML file, a command, a failed command, output that is not JSON, a document
  with no operations, a `$ref` to another file, Swagger 2.0, and the timeout.
- **The program:** an app that prints at import, an app that reads `sys.argv`, an app that calls
  `sys.exit(2)`, a project file `json.py`, and a route on a `functools.partial`.
- **Setup:** a `setup:` that adds a router, and an `async def` setup. The errors are a value with no
  `:`, a module that is not found, a name that is not in the module, and a name that is not callable. They
  also include a setup that raises, and `setup:` with `file:` or `command:`.
- **Sections:** a single mapping unchanged, with no names file, and a list of one section with the same
  `_symbols.json`. Also a list with Python and OpenAPI, and two sections with one `out`. Also the manifest
  and names file of each, `--out NAME` keeping the other names, a short and a full name in two sections,
  and a removed section, with the warnings in `Site.warnings`.
- **Python bytes:** babykev-style pages, built before and after the refactor of `build`, are the same.
- **Linkify:** `exact_symbols` with a mapping of `language: openapi`, and with a list that has one.
- **The command:** `api list` and `module` with one Python section, none, and two.
- **The real program:** one test runs the FastAPI program on `tiny_app.py` with
  `uv run --no-project --with fastapi`. It is skipped when uv cannot fetch FastAPI. A second test runs it
  on `tiny_app.py` with a setup function in the fixtures, `tiny_setup.py`, which adds a router.

The example sites of `CLAUDE.md` must build as before, and `docs/` must not change.

## Routes added at startup: the key `setup:`

Some FastAPI apps add their routes in their lifespan function, which runs when the server starts. An
import of such an app gives a document with no paths. The key `setup:` fixes that, with no change to the
app.

### What it is

`setup:` is optional, and it is allowed only with `fastapi:`. It names a function as `module:function`,
as `fastapi:` names the app. The program then does these steps, in this order.

1. It imports the app, as before.
2. It imports the setup module and gets the function. A dotted name after the `:`, such as
   `routers:Setup.run`, is read one attribute at a time, as uvicorn reads the app.
3. It calls the function with one argument, the app, and ignores what the function returns.
4. It calls `app.openapi()`, and adds the source locations, as before.

The program never runs the lifespan, and it never starts a server.

### An `async def` setup

A setup function may be `async def`. The program checks the function with
`inspect.iscoroutinefunction`, and checks the value that the call returns with `inspect.isawaitable`. In
either case it runs the coroutine with `asyncio.run`, once, and then calls `app.openapi()`. The program
starts no event loop of its own before that, so `asyncio.run` does not meet a running loop.

### How setup errors are reported

Each error stops the build. The message names the section by its `out`, and names the value of `setup:`.

- **A value with no `:`, or with an empty side,** is an error of the settings, as every other error of
  `Settings.read`. smalldocs finds it before it runs the program.
- **`setup:` with `file:` or `command:`** is an error of the settings too. A command runs the project's own
  program, which can make its own setup call.
- **The program names the step that failed.** It runs four steps. They are the import of the app, the import of
  the setup, the call of the setup, and `app.openapi()`. It wraps each step in `except BaseException`, so
  it also catches `SystemExit` and `KeyboardInterrupt`. On a failure it prints one marker line on standard
  error, then the traceback, and exits with 1. The marker line is
  `smalldocs-openapi-error: STEP: TYPE: MESSAGE`, where STEP is `app-import`, `setup-import`, `setup-call`
  or `openapi`.
- **smalldocs reads the marker, and not the exit code.** An app that calls `sys.exit(2)` at import, and
  uv's own errors, both exit with 2, so an exit code alone cannot say which step failed. smalldocs prints
  the marker line, such as
  `setup api.routers:register_routers: setup-import: AttributeError: module 'api.routers' has no attribute 'register_routers'`,
  and then the end of the traceback.
- **A failure with no marker line** came from uv or Python before the program ran. smalldocs then prints
  the exit code and the end of standard error, as for a failed command.
- **A name that is not callable** is a failure of the step `setup-import`.
- **A setup that adds no operations** gives the same error as an app with no operations. The message says
  that the setup ran.

### cricsdb

These facts come from cricsdb's code at commit `d72a589`.

- **The lifespan adds the routes.** The function `lifespan` (`api/app.py`, line 70) calls `init_db()`, and
  then `register_routers(app)` at line 77. It then adds the admin router.
- **`register_routers` needs no database.** It is at `api/routers/__init__.py`, line 18. It only calls
  `app.include_router` for each of 11 routers. A comment at line 76 of `app.py` says that it must come after
  `init_db`, but the function itself does not use the database.
- **The admin router is left out.** It needs a live database, because the lifespan calls `db.reflect()`
  (line 84) before it adds the router. A setup of `register_routers` does not add it. Leaving it out is right for a
  public reference, because the admin pages are behind a password.
- **The fallback of the single-page app is not in the document.** It is `@app.get("/{path:path}",
  include_in_schema=False)`, at line 97.

So cricsdb's section is the second example in [The three inputs](#the-three-inputs).

We checked it on 2026-11-12, with this command, which does what the program does.

```sh
cd ~/Projects/cricsdb && PYTHONDONTWRITEBYTECODE=1 uv run --no-sync python -c \
  "from api.app import app; from api.routers import register_routers; register_routers(app); \
   import json; d=app.openapi(); print(len(d['paths']))"
```

It printed 127. The document had 127 paths and 127 operations, all `GET`, `openapi: 3.1.0`, and two
schemas. `git status` in cricsdb was the same before and after the run. cricsdb's code does not change.

## Routes added at startup, in Rust and TypeScript

Rust and TypeScript apps also build their routes at run time, often in `main`, after the program
connects to a database. This section asks whether `command:` covers them, or whether they need a key like
`setup:`.

### How each producer gets the document

We read each page on 2026-11-12. "Not stated" means that the page does not say it, and that the line is
our reading of the code or of the signature.

| Producer | Where the routes are listed | How a program gets the document without `listen` | Evidence |
|---|---|---|---|
| utoipa | `#[derive(OpenApi)]` with `paths(...)`, a list of functions with `#[utoipa::path]`, fixed at compile time | `ApiDoc::openapi()`, which needs no router and no server | [checked](https://docs.rs/utoipa/latest/utoipa/derive.OpenApi.html) |
| utoipa-axum | `OpenApiRouter::routes(routes!(...))`, at run time, as the router is built | `into_openapi()`, or `split_for_parts()`, which gives the axum `Router` and the `OpenApi` | [checked](https://docs.rs/utoipa-axum/latest/utoipa_axum/router/struct.OpenApiRouter.html) |
| aide | `ApiRouter::api_route`, at run time. Routes added with plain `route` are not in the document | `finish_api(&mut api)` fills an `OpenApi` value. So a function that builds the `ApiRouter` serves both `main` and the program, which never calls `axum::serve`. That it needs no server is not stated | [checked](https://docs.rs/aide/latest/aide/axum/index.html) |
| poem-openapi | The API type given to `OpenApiService::new(api, title, version)` | `spec()` gives JSON and `spec_yaml()` gives YAML, as a `String`, from `&self`. That it needs no server is not stated | [checked](https://docs.rs/poem-openapi/latest/poem_openapi/struct.OpenApiService.html) |
| dropshot | `ApiDescription::register(endpoint)`, at run time | `api.openapi(title, version)` gives an `OpenApiDefinition`, whose `json()` gives a value and `write(out)` writes it. dropshot-api-manager does this for each API with `cargo openapi generate` | [checked](https://docs.rs/dropshot/latest/dropshot/struct.ApiDescription.html) |
| NestJS, `@nestjs/swagger` | The controllers of the modules of `NestFactory.create(AppModule)` | `SwaggerModule.createDocument(app, config)`. The page says that the document can be saved as JSON or YAML, and gives no code. That it works without `app.listen` is not stated | [checked](https://docs.nestjs.com/openapi/introduction) |
| tsoa | The controllers that `controllerPathGlobs` finds | `tsoa spec` writes the file into `spec.outputDirectory`, in a build step before `tsc`. That it never runs the app is not stated | [checked](https://tsoa-community.github.io/docs/getting-started.html) |
| Hono, `@hono/zod-openapi` | `app.openapi(route, handler)` on the `OpenAPIHono` app, at run time | `app.getOpenAPIDocument(config)` gives 3.0, and `app.getOpenAPI31Document(config)` gives 3.1, as an object | [checked in the source](https://github.com/honojs/middleware/blob/main/packages/zod-openapi/src/index.ts) |
| Fastify, `@fastify/swagger` | Each route registered after the plugin. The README says that a route registered before the plugin is not in the document | `await app.ready()`, then `app.swagger()` for an object, or `app.swagger({ yaml: true })` for a string. The README's example never calls `listen` | [checked](https://github.com/fastify/fastify-swagger) |

### What the table shows

- **Every producer gives the document from a value in memory, as far as we read.** That value is a
  type, a router, a service or an app. No producer needs `listen` or `serve`, though four pages do not say
  so.
- **Building the app may still run startup code.** Fastify's `ready()` runs every plugin, and NestJS's
  `NestFactory.create` builds every provider. A plugin or a provider that connects to a database then
  connects. `setup:` solves the same problem for FastAPI, and the project's program must solve it
  for itself, for example with a module that leaves the database out.
- **The program that prints the document is the project's own.** In Rust it is a small binary, such as
  `src/bin/openapi.rs`. In TypeScript it is a small script, such as `scripts/openapi.ts`. It builds the
  router or the app in the same function that `main` uses, and it prints the document. The project's own
  code then makes the call that `setup:` makes for FastAPI.
- **A `setup:` key would not help outside Python.** smalldocs cannot import a Rust or TypeScript module,
  so it cannot call a function in it. The project must write a program in any case, and that program can
  do the setup.

### Recommendation

`command:` covers every producer in the table, with one small program for each project. The program must
also keep startup code that needs a database out of the app it builds. smalldocs needs
no `setup:`-like key outside Python. The guide page `guide/api-http.qmd` gives one short program for each
producer, marked as untested until a test runs it.

## The order of work

1. **Build and test** the shared pieces that `api.py` gains, then `api_openapi.py` and the list of
   sections, with the fixtures. Rust and TypeScript pages must not change. Each change then gets these
   checks, from `CLAUDE.md`.
   - **The Python pages:** the tests that hold `api.py` to babykev's pages pass, byte for byte.
   - **The Tufte example:** two copies, one built with the last release and one with this branch. Only
     the version and `site_libs` may differ.
   - **`docs/`:** rebuilt with `--strict`, and each change read.
   - **Quarto:** a small `_quarto.yml` site that holds the generated OpenAPI pages, rendered with
     Quarto and with smalldocs. The ids and the links must match.
   - **A review:** an adversarial review before each commit.
2. **Try it** on cricsdb, in a copy, with its narrative page `docs/api.md`. cricsdb's agent then builds
   and checks cricsdb's site, in cricsdb's own branch.
3. **Learn from it.** Fix what cricsdb shows, and write it down.
4. **Write our docs:** a page `guide/api-http.qmd`, and a news post. Every page goes through the nossaifd
   checker and declaude.
5. An adversarial review, then a release, one patch number up.

## Decisions

Rahul approved these on 2026-11-12. He agreed with each recommendation of the draft.

- **`api` takes a list of sections.** There is no separate key `openapi:`. The
  reasons are in [Many sections in one site](#many-sections-in-one-site).
- **The language is `openapi`,** because it names what smalldocs reads, as `rust`
  names the rustdoc JSON.
- **The input does not set the language.** `fastapi:`, `command:` or `file:` alone does not mean
  `language: openapi`. Each section names its language.
- **No `url:` input.** A build must repeat, and a command covers the rare case.
- **The runner for FastAPI** is `uv run --frozen`. It never changes `uv.lock`, but it can install
  packages into the project's `.venv`, as the project's own `uv run` does. `uv run --no-sync` changes
  nothing, but it fails when there is no `.venv`, for example on a new checkout.
- **cricsdb's routers use the key `setup:`,** with `setup: api.routers:register_routers`. cricsdb's code does
  not change. See [Routes added at startup](#routes-added-at-startup-the-key-setup).
- **`check-responses: true` makes `check` report each `2xx` response with no schema.** It is off by
  default. A public route should return a Pydantic model, but all 127 of cricsdb's routes return plain
  dictionaries for now. A bare `dict` counts as no schema.
- **Links from a narrative page match names exactly.** cricsdb's agent edits the 16 names in
  `docs/api.md` that use other parameter names. smalldocs gets no second key.
- **Examples, security, and source links for FastAPI schemas** wait for a later version. cricsdb's
  narrative page gives its examples by hand. cricsdb's document has no security scheme, because its admin
  router is not in the document. The name of a schema is not always the name of its Pydantic model.
- **One page for each tag,** even for cricsdb's tag `Teams`, which has 36 operations. The pages follow the
  groups that the project chose.

## Notes for later

- **Programs for Rust and TypeScript.** Test one small program for each producer in the table of
  [Routes added at startup, in Rust and TypeScript](#routes-added-at-startup-in-rust-and-typescript). Four
  facts are not stated on their pages. They are aide with no server, poem-openapi with no server, NestJS with no
  `app.listen`, and `tsoa spec` with no run of the app.
- **NestJS and the database.** `NestFactory.create` builds every provider of the module. A provider that
  connects to a database may then connect. We have not checked this. A project may need a module for the
  program that leaves the database out.
- **Examples, security, and source links for FastAPI schemas,** as the decisions say.
- **A shared class of entries.** One model of entries for the three readers could replace the
  readers' own `Entry`, `Page` and `Module`. It would change Rust and TypeScript, so it waits.
- **The sibling spec.** `SPEC-rust-typescript.md` uses `manifest:` for the path of `Cargo.toml`, which
  clashes in name with the API manifest `.smalldocs-api`. It also gives `api` only as a mapping, so it
  needs the list form of this spec.

## What the build changed

Step 1 is built. This list gives each place where the code differs from the first draft of this spec, and
why. Each one has a test in `tests/test_api_openapi.py`.

- **The base.** The branch starts from `origin/main` after the merge of the Rust and TypeScript work, at
  `c2db1eb`. That merge added `heading_text` and `link_path` to `api.py`. The OpenAPI reader uses them for
  its headings and for the links of `_symbols.json`, and `source_line` uses `link_path` too. So the
  reader adds no escaping and no encoding of its own.
- **The names file keeps the order.** The draft gave `{"full": {...}, "short": {...}}`. Two dicts lose
  the order of the index, so a list of one Python section would write `_symbols.json` with its keys in
  another order. The file is `{"names": {...}, "full": [...]}` instead.
- **The builds do not return their index.** Each build writes its names file, through `write_names`,
  and the loop reads every names file. So `--out NAME` and a full build merge in the same way, and no
  `build` changes what it returns. `written_pages` of TypeScript returns its full names as a third value,
  and `api_rust.build` gives its full names to `write_reference`.
- **The reserved ids.** The draft listed 16 fixed ids and three patterns. A built page has more ids. They are
  `TOC-body`, `quarto-bootstrap-light` and `quarto-bootstrap-dark`, `quarto-sidebar-section-1` and on,
  `nav-menu-1` and on, `cb1` for a code block and `cb1-1` for its lines, `callout-1`, `tabset-1-1` and
  `fnref1:2`. `RESERVED_IDS` holds them. The pattern `toc-` with any id after it cannot be in the
  constant, because `TOC-2` and every other id with `-2` would then be reserved. So `entry_ids(names)`
  makes the ids of a page's entries with `unique`, and then looks for an id that is `toc-` before another
  final id. It reserves each such id, and runs `unique` again, until none is left. The reserved names are
  in a set, so ten thousand ids take well under a second.
- **`unique` ends.** When the pattern holds `name-2` too, as it holds `cb1-2` for `cb1`, the suffixes go
  on from `name-id`, so `cb1` becomes `cb1-id-2`.
- **Shared code of the build.** `code_span`, `code_block`, `entry_ids` with its class `PageIds`, and `write_names` are new in
  `api.py`, beside `one_line`, `unique` and `source_line`. Each is generic.
- **`Settings`** gains `check_responses`, `listed` and `warnings`, beside the six fields of the draft.
  `warnings` carries the warning of OpenAPI 3.2 to the loop.
- **`build_from_config`** returns the pages and the warnings, and `Site.build` keeps each warning.
- **`smalldocs api check` with a list** prints `api section OUT (LANGUAGE)` before each section, and
  returns 1 when any section has a gap.
- **The marks of a project.** With `language: openapi`, a site folder with a `pyproject.toml` is its own
  root, as one with a `Cargo.toml` is for Rust.
- **The pages.** An operation's heading, source link, the line "Deprecated.", the request, the summary,
  the description, the parameters, the request body and the responses come in that order. The page of
  schemas has the description "The shape of each kind of data that the API takes or gives." A schema
  that is an `allOf` of named schemas says "It has the fields of" and links them.
- **Quarto.** We rendered the pages of `tiny.json`, of `handmade-3.0.yaml` and of a document with signs
  in its paths and names with Quarto 1.8.26 and with smalldocs. The heading ids,
  the heading texts and the links are the same. One cell differs: Pandoc shows a `\|` inside a code span
  in a table as `\|`, and smalldocs shows it as `|`. This comes from the shared `table`, and it touches
  the TypeScript pages too. It is an open issue of `markdown.py`, outside this spec.
- **What the review of step 1 changed.** An adversarial review found these, and each has a test.
  - **A value of the wrong kind,** such as a list for `responses` or a number for `parameters`, stops the
    build with a message that names the section. It is no bare Python error. So does a lone surrogate in
    a text. The check wraps the whole build of the pages, so a bug of smalldocs there would get the same
    message; the cause stays in the traceback.
  - **A JSON pointer reaches a key that YAML reads as a number,** such as an unquoted `200:`. A digit
    that is not ASCII, such as `²`, is no index of a list.
  - **The FastAPI program keeps file descriptor 1 for the document.** It copies descriptor 1, and points
    descriptor 1 at standard error. So `os.write(1, ...)` and `print(file=sys.__stdout__)` at import go
    to standard error too. The program flushes both streams, and then ends with `os._exit`, so a thread
    that the app started does not hold the build. It writes the marker line and the traceback to
    descriptor 2, so an app that replaces `sys.stderr` does not hide them.
  - **A timeout or Ctrl-C kills the runner's whole process group.** The runner starts in a new session.
    So the Python that `uv run` starts stops too. A worker that the app starts in a session of its own is
    out of reach, and smalldocs waits for it 5 seconds at most.
  - **Standard error goes to a temporary file, not a pipe.** So a worker process that the app starts,
    and that keeps standard error open, does not hold the build.
  - **A YAML document cannot repeat itself without end.** The parser counts each value, with an alias
    counted each time it is used. A document of more than 2,000,000 values stops the build, and so does
    one that holds itself. JSON nested too deep is no document.
  - **A line break in a name is a space.** This holds for a path, a tag, an `operationId`, a schema's
    name, a parameter's name and place, a status, a media type and a format. So no heading, table row or code line is split.
  - **`null` takes no format,** so `type: [string, "null"]` with `format: date-time` is
    `string (date-time) or null`.
  - **A `$ref` that is no JSON pointer,** such as `#foo`, points at nothing, and stops the build.
  - **A schema whose YAML name is a number,** such as `1:`, is read as the name `1`.
  - **`--out ./api` and `--out api/`** name the section with out `api`.
- **Open points from the review.** These stay open, and the report of step 1 lists them.
  - A description with an unclosed code fence swallows the entries after it, as a Python docstring does.
  - A heading inside a description may take the id of an entry.
  - `escape_angles` lets raw HTML from a description through, as it does for the other languages.
  - The walk for folders of removed sections reads the whole site folder, `node_modules` too.
  - `check` skips `HTTPValidationError` and `ValidationError` for every input, as this spec says.
  - A key of a section that smalldocs does not read is silent, as for the other languages.
  - An inline request body with an `allOf` of a named schema does not say "It has the fields of".

## What cricsdb showed

Steps 2 and 3 ran on 2026-11-12, on cricsdb at commit `d72a589`, in a copy of its site at
`/private/tmp/claude-501/cricsdb-http-site`. The site has two sections in a list, TypeScript in `api` and
OpenAPI in `reference`, with the navbar item "HTTP reference".

- **The build.** It made 13 pages in `reference`. They are the 11 tags, the schemas and the index. They hold 127
  operations and 2 schemas. The whole site built 194 pages in 38 seconds, with the TypeScript section.
  `git status` in cricsdb was the same before and after.
- **The source links.** All 127 operations have a link to their file and line.
- **The narrative page.** In `docs/api.md`, which the copy holds as `guide/http-api.md`, 45 names of operations link to their entries, as the counts
  in [Links between pages](#links-between-pages) said.
- **`check`.** It reports 49 operations with no docstring and 1,164 parameters with no description,
  under 32 names, as this spec said. With `check-responses: true`, it reports all 127 operations.
- **The look.** A tag page and the page of schemas look like the Python page of `smalldocs.api`. Each has a
  heading, a source link, a code block, the prose and the tables.
- **Nothing in the code had to change.** Two points are for the project and for later.
  - An operation with 16 query parameters has a request line that is wider than the page. The code
    block scrolls, as a long Python signature does.
  - The sidebar section "HTTP reference" comes after the long list of the TypeScript pages. The site's
    `sidebar` sets that order.
