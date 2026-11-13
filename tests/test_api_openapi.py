"The HTTP API reference from an OpenAPI document, and the list of api sections: one test per rule of SPEC-openapi.md."

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from smalldocs import api, api_openapi
from smalldocs.cli import main
from smalldocs.config import load
from smalldocs.site import Site
from smalldocs.site import build as build_site

FIX = Path(__file__).parent / "openapi"


def write(
    folder: Path,  # A folder
    files: dict[str, str],  # The text of each file, by its path in the folder
) -> Path:  # The folder
    "Write some files."
    for rel, text in files.items():
        f = folder / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(textwrap.dedent(text), encoding="utf-8")
    return folder


def doc_file(
    folder: Path,  # A folder
    data: dict,  # An OpenAPI document
    name: str = "openapi.json",  # The file's name
) -> str:  # The file's path
    "Write a document as JSON."
    f = folder / name
    f.write_text(json.dumps(data), encoding="utf-8")
    return str(f)


def site(
    tmp: Path,  # The site's folder
    api_yaml: str,  # The `api` setting, as YAML
    home: str = "# Home\n",  # The text of `index.qmd`
) -> Path:  # The site's folder
    "Make a site with an api setting."
    write(tmp, {"_smalldocs.yml": "project:\n  type: website\n" + api_yaml, "index.qmd": home})
    return tmp


def pages(
    folder: Path,  # A folder of pages
) -> dict[str, str]:  # Each page by its path in the folder
    "Read the pages of a folder."
    return {p.relative_to(folder).as_posix(): p.read_text(encoding="utf-8") for p in sorted(folder.rglob("*.qmd"))}


def ops(
    paths: dict,  # Each path, with its methods and their operations
    **extra: object,  # More top-level keys, such as `tags` or `components`
) -> dict:  # A 3.1 document
    "Make a small document."
    return {"openapi": "3.1.0", "info": {"title": "T", "version": "1"}, "paths": paths, **extra}


def op(
    **keys: object,  # The keys of the operation
) -> dict:  # An operation with one response
    "Make an operation."
    return {"responses": {"200": {"description": "OK"}}, **keys}


def document(
    tmp: Path,  # A folder
    data: dict,  # A document
) -> api_openapi.Document:  # It, read
    "Read a document as a build does."
    s = api.Settings.read(tmp, {"language": "openapi", "file": doc_file(tmp, data), "out": "http"})
    return api_openapi.Document(s, data)


def built(
    tmp: Path,  # The site's folder
    data: dict,  # A document
    extra: str = "",  # More lines of the section
) -> dict[str, str]:  # The pages written
    "Build the reference of a document."
    site(tmp, f"api:\n  language: openapi\n  file: {doc_file(tmp, data)}\n  out: http\n{extra}")
    api.build_sections(tmp, load(tmp).smalldocs["api"])
    return pages(tmp / "http")


# ---------------------------------------------------------------- the shared layer


def test_unique_default_mode_is_unchanged() -> None:
    "The default mode gives a repeat `-2`, then `-3`, and ignores case, as the TypeScript pages need."
    assert api.unique(["b", "B", "b", "c"]) == ["b", "B-2", "b-3", "c"]
    assert api.unique(["a", "a", "a-2"]) == ["a", "a-2", "a-2-2"]


def test_unique_reserving_mode_skips_natural_and_reserved_names() -> None:
    "The reserving mode keeps each name for its first place, and a repeat skips the names of the list and the reserved ones."
    assert api.unique(["a", "a", "a-2"], re.compile("x")) == ["a", "a-3", "a-2"]
    assert api.unique(["TOC", "toc", "x"], api.RESERVED_IDS) == ["TOC-2", "toc-3", "x"]
    assert api.entry_ids(["cb1", "fn1", "Player", "toc-Player"]) == ["cb1-id-2", "fn1-2", "Player", "toc-Player-2"]
    assert api.entry_ids(["X", "x", "toc-x-2"]) == ["X", "x-2", "toc-x-2-2"]  # `toc-` before an id that `unique` gave is taken too
    assert api.unique(["Player", "player"], re.compile("$^")) == ["Player", "player-2"]


def test_front_matter_order_and_one_line() -> None:
    "`front_matter` writes the same bytes with no `order`; `one_line` folds a description for a cell."
    assert api.front_matter("T", "D") == f'---\n{api.MARK}\ntitle: "T"\ndescription: "D"\n---\n\n'
    assert api.front_matter("T", None, 3) == f'---\n{api.MARK}\ntitle: "T"\norder: 3\n---\n\n'
    assert api.one_line("a\n  b\n") == "a b"


def test_code_span_and_block_hold_backticks() -> None:
    "A value with a backtick stays code; a block with a fence in it is not closed by it."
    assert api.code_span('"a`b"') == '``"a`b"``'
    assert api.code_span("`") == "`` ` ``"
    assert api.code_block("a\n```\nb", "http") == "````http\na\n```\nb\n````"


def test_source_line(tmp_path: Path) -> None:
    "`source_line` joins `source`, the path and the line, and gives nothing with no `source`."
    s = api.Settings.read(tmp_path, {"language": "openapi", "file": "x.json", "source": "https://example.com/blob/main/"})
    assert api.source_line(s, "api/a b.py", 7) == "[source](https://example.com/blob/main/api/a%20b.py#L7){.source-link}"
    s.source = ""
    assert api.source_line(s, "a.py", 1) == ""


def test_reserved_ids_hold_every_id_of_a_page(tmp_path: Path) -> None:
    "Every id that a page's own markup writes, with a table of contents, a footnote, giscus and code, is in `RESERVED_IDS`, or is `toc-` before a heading's id."
    giscus = "comments:\n  giscus:\n    repo: me/r\n    repo-id: R\n    category: C\n    category-id: K\n"
    home = "---\ntitle: Home\n---\n\n## First {#first}\n\nA note.[^1]\n\n```python\nx = 1\ny = 2\n```\n\n[^1]: The note.\n"
    write(tmp_path, {"_smalldocs.yml": f"project:\n  type: website\nwebsite:\n  title: T\n  navbar:\n    left:\n      - text: Menu\n        menu: [index.qmd]\n  sidebar:\n    contents:\n      - section: S\n        contents: [index.qmd]\ntoc: true\n{giscus}", "index.qmd": home})
    build_site(tmp_path, quiet=True)
    found = set(re.findall(r'id="([^"]+)"', (tmp_path / "_site/index.html").read_text()))
    assert {"first", "fn1", "fnref1", "TOC", "toc-first", "cb1"} <= found
    assert sorted(i for i in found - {"first"} if not (api.RESERVED_IDS.fullmatch(i) or (i.startswith("toc-") and i[4:] in found))) == []


# ---------------------------------------------------------------- ids and headings


def test_operation_ids_and_their_collisions(tmp_path: Path) -> None:
    "An id is the method and the path; a repeat gets `-2`, then `-3`, and skips a natural id such as that of `/a/b-2`."
    d = document(tmp_path, ops({"/a/{b}": {"get": op()}, "/a/b": {"get": op()}, "/a-b": {"get": op()}, "/a/b-2": {"get": op()}, "/": {"get": op()}}))
    assert [o.id for o in d.ops] == ["get-a-b", "get-a-b-3", "get-a-b-4", "get-a-b-2", "get"]
    assert api_openapi.natural_id("get", "/api/v1/batters/{person_id}/by-innings") == "get-api-v1-batters-person_id-by-innings"


def test_schema_ids_keep_case_and_avoid_reserved_ids(tmp_path: Path) -> None:
    "A schema's id is its name; `player` after `Player` is `player-2`, `TOC` is `TOC-2`, and signs outside an id become `-`."
    schemas = {k: {"type": "object"} for k in ["Player", "player", "TOC", "Page[Player]", "Page-Player-"]}
    d = document(tmp_path, ops({"/": {"get": op()}}, components={"schemas": schemas}))
    assert list(d.schema_ids.values()) == ["Player", "player-2", "TOC-2", "Page-Player-", "Page-Player--2"]


def test_heading_keeps_braces_and_markdown_signs_as_text(tmp_path: Path) -> None:
    "The heading shows the path as it is: braces stay text, `__x__` is no bold, and only the last braces are the id."
    out = built(tmp_path, ops({"/a/__x__/{player_id}": {"get": op()}}))
    assert "## GET /a/\\_\\_x\\_\\_/\\{player_id\\} {#get-a-__x__-player_id}" in out["default.qmd"]
    build_site(tmp_path, quiet=True)
    html = (tmp_path / "_site/http/default.html").read_text()
    assert 'data-anchor-id="get-a-__x__-player_id">GET /a/__x__/{player_id}</h2>' in html


def test_table_cells_escape_bars_and_fold_lines(tmp_path: Path) -> None:
    "A `|` in a description is `\\|`, and a line break in a cell is a space."
    p = {"name": "r", "in": "query", "description": "'won' | 'lost'\nor 'tied'", "schema": {"type": "string"}}
    out = built(tmp_path, ops({"/a": {"get": op(parameters=[p])}}))
    assert "| `r` | query | string |  |  | 'won' \\| 'lost' or 'tied' |" in out["default.qmd"]


# ---------------------------------------------------------------- types


@pytest.mark.parametrize(
    "schema,text",
    [
        ({"$ref": "#/components/schemas/Player"}, "[Player](schemas.qmd#Player)"),
        ({"type": "string", "format": "date-time"}, "string (date-time)"),
        ({"type": "array", "items": {"$ref": "#/components/schemas/Player"}}, "array of [Player](schemas.qmd#Player)"),
        ({"type": "object", "additionalProperties": {"type": "integer"}}, "map of integer"),
        ({"anyOf": [{"type": "string"}, {"type": "integer"}]}, "string or integer"),
        ({"oneOf": [{"type": "string"}, {"type": "null"}]}, "string or null"),
        ({"allOf": [{"$ref": "#/components/schemas/Player"}]}, "[Player](schemas.qmd#Player)"),
        ({"allOf": [{"$ref": "#/components/schemas/Player"}, {"type": "object"}]}, "[Player](schemas.qmd#Player) and object"),
        ({"type": ["string", "integer"]}, "string or integer"),
        ({"type": "null"}, "null"),
        ({"enum": ["male", "female"]}, 'one of `"male"`, `"female"`'),
        ({"const": "male"}, '`"male"`'),
        ({}, "any"),
        ({"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "null"}]}}, "array of (string or null)"),
        ({"type": "string", "format": "a*b"}, "string (a\\*b)"),
    ],
)
def test_types(tmp_path: Path, schema: dict, text: str) -> None:
    "Each row of the table of types."
    d = document(tmp_path, ops({"/": {"get": op()}}, components={"schemas": {"Player": {"type": "object"}}}))
    assert d.type_of(schema) == text


def test_null_in_3_0_and_3_1_is_written_alike(tmp_path: Path) -> None:
    "`nullable` of 3.0, also beside an `allOf` of a `$ref`, gives the text of the 3.1 forms."
    comp = {"schemas": {"Player": {"type": "object"}}}
    d30 = api_openapi.Document(api.Settings.read(tmp_path, {"language": "openapi", "file": "x"}), {"openapi": "3.0.3", "paths": {}, "components": comp})
    d31 = document(tmp_path, ops({}, components=comp))
    assert d30.type_of({"type": "string", "nullable": True}) == d31.type_of({"type": ["string", "null"]}) == d31.type_of({"anyOf": [{"type": "string"}, {"type": "null"}]})
    ref = {"$ref": "#/components/schemas/Player"}
    assert d30.type_of({"allOf": [ref], "nullable": True}) == d31.type_of({"anyOf": [ref, {"type": "null"}]}) == "[Player](schemas.qmd#Player) or null"


def test_a_schema_that_refers_to_itself_ends_in_a_link(tmp_path: Path) -> None:
    "A `Tree` whose `kids` are an array of `Tree` is a link, not a loop."
    tree = {"type": "object", "description": "A tree.", "properties": {"kids": {"type": "array", "items": {"$ref": "#/components/schemas/Tree"}}}}
    out = built(tmp_path, ops({"/": {"get": op()}}, components={"schemas": {"Tree": tree}}))
    assert "| `kids` | array of [Tree](schemas.qmd#Tree) |" in out["schemas.qmd"]


def test_a_loop_of_refs_stops_the_build(tmp_path: Path) -> None:
    "A chain of response refs that loops stops the build, with a message that names the chain."
    comp = {"responses": {"A": {"$ref": "#/components/responses/B"}, "B": {"$ref": "#/components/responses/A"}}}
    with pytest.raises(ValueError, match="a loop of \\$ref: #/components/responses/A -> #/components/responses/B -> #/components/responses/A"):
        built(tmp_path, ops({"/": {"get": {"responses": {"200": {"$ref": "#/components/responses/A"}}}}}, components=comp))


def test_a_ref_to_another_file_stops_the_build(tmp_path: Path) -> None:
    "A `$ref` to another file names it."
    with pytest.raises(ValueError, match=re.escape("a $ref to another file, other.yaml#/X")):
        built(tmp_path, ops({"/": {"get": {"responses": {"200": {"$ref": "other.yaml#/X"}}}}}))


def test_a_3_1_ref_with_a_description_uses_it(tmp_path: Path) -> None:
    "A field that is a `$ref` with a description beside it shows that description, and links the schema."
    comp = {"schemas": {"T": {"type": "object", "properties": {"p": {"$ref": "#/components/schemas/P", "description": "The p"}}}, "P": {"type": "object"}}}
    assert "| `p` | [P](schemas.qmd#P) |  |  | The p |" in built(tmp_path, ops({"/": {"get": op()}}, components=comp))["schemas.qmd"]


# ---------------------------------------------------------------- the pages


def test_the_tiny_app_page(tmp_path: Path) -> None:
    "The entry of `GET /api/players/{player_id}` is the one of the spec: source, request, summary, tables."
    site(tmp_path, f"api:\n  language: openapi\n  file: {FIX / 'tiny.json'}\n  root: {FIX}\n  out: http\n  source: https://example.com/me/tiny/blob/main\n")
    api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])
    page = (tmp_path / "http/players.qmd").read_text()
    entry = page.split("## POST")[0]
    assert entry.endswith(
        textwrap.dedent("""\
        ## GET /api/players/\\{player_id\\} {#get-api-players-player_id}

        [source](https://example.com/me/tiny/blob/main/tiny_app.py#L25){.source-link}

        ```http
        GET /api/players/{player_id}?season={season}&limit=10
        x-trace: {x-trace}
        ```

        Get Player

        Get one player.

        | Parameter | In | Type | Default | Required | Description |
        | --- | --- | --- | --- | --- | --- |
        | `player_id` | path | string |  | yes | The player's id |
        | `season` | query | string or null |  |  | Only this season |
        | `limit` | query | integer | `10` |  | At most this many rows |
        | `x-trace` | header | string or null |  |  | A trace id |

        | Status | Media type | Type | Description |
        | --- | --- | --- | --- |
        | 200 | `application/json` | [Player](schemas.qmd#Player) | Successful Response |
        | 422 | `application/json` | [HTTPValidationError](schemas.qmd#HTTPValidationError) | Validation Error |

        """)
    )
    assert "Request body, required: `application/json`, [NewPlayer](schemas.qmd#NewPlayer)." in page
    assert "| `team` | string or null |  |  | The current team, if any |" in (tmp_path / "http/schemas.qmd").read_text()


def test_the_handmade_document(tmp_path: Path) -> None:
    "Tags, `default`, two tags, path parameters, a `$ref` parameter, a body's fields, `deprecated` and the order of pages."
    site(tmp_path, f"api:\n  language: openapi\n  file: {FIX / 'handmade-3.0.yaml'}\n  out: http\n")
    api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])
    out = pages(tmp_path / "http")
    assert list(out) == ["default.qmd", "index.qmd", "players.qmd", "schemas.qmd", "teams.qmd"]  # `Unused` has no page
    assert 'title: "Teams"\ndescription: "The teams, and their players."\norder: 1\n---\n\nA second paragraph of the tag.' in out["teams.qmd"]
    assert "order: 2" in out["players.qmd"] and "order: 3" in out["default.qmd"] and "order: 4" in out["schemas.qmd"]
    teams = out["teams.qmd"]
    assert "GET /a/{b}?limit=10&verbose=false" in teams  # the path's own `verbose` is replaced by the operation's
    assert "| `b` | path | string |  | yes | The b of the path |" in teams and "The operation's verbose" in teams and "The path's own" not in teams
    assert "Get an a by its b." in teams and "\nGet an a\n" not in teams  # the description starts with the summary
    assert "| default | `application/json` | [Problem](schemas.qmd#Problem) | A problem |" in teams
    assert "| `stats.runs` | integer |  |  | The runs |" in teams
    assert "## GET /a/b {#get-a-b-2}\n\nDeprecated." in out["players.qmd"] and "/a/{b}" not in out["players.qmd"]
    assert "Cookie: who={who}" in out["default.qmd"] and "| `X-Key` | header | string |  | yes | Deprecated. The key \\| or none |" in out["default.qmd"]
    assert "| 200 | `application/json` | array of (string or null) | A line, and another. |" in out["default.qmd"]
    assert "| `captain` | [Player](schemas.qmd#Player) or null |" in out["schemas.qmd"]
    assert 'One of `"male"`, `"female"`.' in out["schemas.qmd"]
    assert 'description: "The hand-made API."' in out["index.qmd"]


def test_tag_file_names(tmp_path: Path) -> None:
    "Tags `schemas`, `index`, `Default`, `2024 Season`, `Scope Averages` with `Scope-Averages`, `Teams` with `teams`, and `!!`."
    tags = ["schemas", "index", "Default", "2024 Season", "Scope Averages", "Scope-Averages", "Teams", "teams", "!!"]
    paths = {f"/p{i}": {"get": op(tags=[t])} for i, t in enumerate(tags)} | {"/none": {"get": op()}}
    out = built(tmp_path, ops(paths))
    titles = {rel: re.search(r'title: "(.*)"', text).group(1) for rel, text in out.items()}
    assert titles == {
        "schemas-2.qmd": "schemas", "index-2.qmd": "index", "default.qmd": "default", "2024-season.qmd": "2024 Season", "scope-averages.qmd": "Scope Averages",
        "scope-averages-2.qmd": "Scope-Averages", "teams.qmd": "Teams", "teams-2.qmd": "teams", "tag.qmd": "\\\\!\\\\!", "index.qmd": "Reference",
    }  # fmt: skip
    assert "GET /none" in out["default.qmd"]  # an operation with no tag shares the page of `Default`


def test_a_hand_written_page_keeps_its_name(tmp_path: Path) -> None:
    "A tag whose file name is a hand-written page's takes `-2`; the hand-written page stays."
    write(tmp_path, {"http/teams.md": "# Mine\n"})
    out = built(tmp_path, ops({"/a": {"get": op(tags=["Teams"])}}))
    assert "teams-2.qmd" in out and (tmp_path / "http/teams.md").read_text() == "# Mine\n"


def test_symbols_keys(tmp_path: Path) -> None:
    "`_symbols.json` has the method and path, the operationId, and each schema by its name and after the folder."
    built(tmp_path, ops({"/a/{id}": {"get": op(operationId="getA", tags=["A"])}}, components={"schemas": {"Player": {"type": "object"}}}))
    assert json.loads((tmp_path / "_symbols.json").read_text()) == {
        "GET /a/{id}": "/http/a.qmd#get-a-id", "getA": "/http/a.qmd#get-a-id", "Player": "/http/schemas.qmd#Player", "http.Player": "/http/schemas.qmd#Player",
    }  # fmt: skip


def test_a_narrative_page_links_an_operation(tmp_path: Path) -> None:
    "A name in backticks that is a key links to its entry, though it does not look like code."
    site(tmp_path, f"api:\n  language: openapi\n  file: {doc_file(tmp_path, ops({'/a': {'get': op()}}))}\n  out: http\n", "# Home\n\nSee `GET /a` and `GET /b`.\n")
    build_site(tmp_path, quiet=True)
    html = (tmp_path / "_site/index.html").read_text()
    assert '<a href="http/default.html#get-a"><code>GET /a</code></a>' in html and "<code>GET /b</code>" in html


def test_the_oai_examples_build(tmp_path: Path) -> None:
    "The examples of the OpenAPI Initiative build; a document of webhooks alone has no operations."
    for name in ["petstore.yaml", "petstore-expanded.yaml", "callback-example.yaml"]:
        d = tmp_path / name
        site(d, f"api:\n  language: openapi\n  file: {FIX / name}\n  out: http\n")
        api.build_sections(d, load(d).smalldocs["api"])
        assert (d / "http/index.qmd").exists()
    assert "| `limit` | query | integer (int32) |  |  | How many items to return at one time (max 100) |" in (tmp_path / "petstore.yaml/http/pets.qmd").read_text()
    d = tmp_path / "webhook"
    site(d, f"api:\n  language: openapi\n  file: {FIX / 'webhook-example.yaml'}\n  out: http\n")
    with pytest.raises(ValueError, match="no operations"):
        api.build_sections(d, load(d).smalldocs["api"])


def test_the_pages_render_with_no_warning(tmp_path: Path) -> None:
    "The pages of the handmade document render with `--strict`: every link is to a page and an id that exist."
    site(tmp_path, f"api:\n  language: openapi\n  file: {FIX / 'handmade-3.0.yaml'}\n  out: http\n")
    assert main(["render", str(tmp_path), "--strict"]) == 0


# ---------------------------------------------------------------- source links


def test_source_links(tmp_path: Path) -> None:
    "A relative file is from the root; an absolute one is made relative; one outside the root, or with no line, has no link."
    root = tmp_path / "repo"
    (root / "api").mkdir(parents=True)
    where = [{"file": "api/a.py", "line": 3}, {"file": str(root / "api/b.py"), "line": 5}, {"file": "/elsewhere/c.py", "line": 1}, {"file": "api/d.py"}]
    paths = {f"/p{i}": {"get": op(**{"x-smalldocs-source": w})} for i, w in enumerate(where)}
    out = built(tmp_path, ops(paths), f"  root: {root}\n  source: https://example.com/blob/main\n")["default.qmd"]
    assert "(https://example.com/blob/main/api/a.py#L3)" in out and "(https://example.com/blob/main/api/b.py#L5)" in out
    assert out.count("[source]") == 2


# ---------------------------------------------------------------- check


def test_check_gaps(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    "Each gap: an operation with no summary or description, a parameter, a schema and a field; FastAPI's own schemas are not held."
    p = [{"name": "gender", "in": "query", "schema": {"type": "string"}}]
    paths = {"/a": {"get": op(parameters=p)}, "/b": {"get": op(summary="B", parameters=p)}}
    comp = {"schemas": {"S": {"type": "object", "properties": {"x": {"type": "string"}}}, "HTTPValidationError": {"type": "object"}}}
    site(tmp_path, f"api:\n  language: openapi\n  file: {doc_file(tmp_path, ops(paths, components=comp))}\n  out: http\n")
    assert main(["api", "check", "--dir", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "default   0 of   2\nschemas   0 of   1\n" in out
    for line in ["GET /a: no summary or description", "GET /a (query gender): no description", "GET /b (query gender): no description", "schemas:S: no description", "schemas:S.x: no description"]:
        assert line in out
    assert "HTTPValidationError" not in out and "GET /b: no" not in out
    assert "Parameters with no description, by name:\n  gender     2\n" in out
    assert out.endswith("0 of 3 operations and schemas are documented\n")


def test_check_responses_is_opt_in(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    "`check-responses: true` needs a schema for each `2xx` response: no schema, `{}` and a bare object count as none; 204 is not held."
    bare = {"application/json": {"schema": {"type": "object", "additionalProperties": True}}}
    good = {"application/json": {"schema": {"type": "object", "properties": {"a": {"type": "string"}}}}}
    responses = {"200": {"description": "a", "content": bare}, "201": {"description": "b", "content": {"application/json": {"schema": {}}}}, "2XX": {"description": "c"}, "204": {"description": "d"}, "202": {"description": "e", "content": good}}
    data = ops({"/a": {"get": {"summary": "A", "responses": responses}}})
    site(tmp_path, f"api:\n  language: openapi\n  file: {doc_file(tmp_path, data)}\n  out: http\n")
    assert main(["api", "check", "--dir", str(tmp_path)]) == 0
    capsys.readouterr()
    site(tmp_path, f"api:\n  language: openapi\n  file: {tmp_path / 'openapi.json'}\n  out: http\n  check-responses: true\n")
    assert main(["api", "check", "--dir", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert [ln for ln in out.splitlines() if "response schema" in ln] == ["GET /a 200: no response schema", "GET /a 201: no response schema", "GET /a 2XX: no response schema"]


def test_check_with_fastapi_needs_the_description(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    "FastAPI makes every summary from the function's name, so for `fastapi:` input `check` needs the description."
    write(tmp_path, {"app.py": APP.format(doc=json.dumps(ops({"/a": {"get": op(summary="Get A")}})))})
    site(tmp_path, f"api:\n  language: openapi\n  fastapi: app:app\n  python: {sys.executable}\n  root: .\n  out: http\n")
    assert main(["api", "check", "--dir", str(tmp_path)]) == 1
    assert "GET /a: no description" in capsys.readouterr().out


# ---------------------------------------------------------------- the inputs


def test_inputs_json_yaml_and_a_command(tmp_path: Path) -> None:
    "A JSON file, a YAML file and a command that prints the document give the same pages."
    data = ops({"/a": {"get": op(summary="A")}})
    results = []
    for i, extra in enumerate(["  file: d.json\n", "  file: d.yaml\n", f"  command: [{sys.executable}, -c, 'print(open(\"d.json\").read())']\n  root: .\n"]):
        d = tmp_path / str(i)
        write(d, {"d.json": json.dumps(data), "d.yaml": yaml.safe_dump(data)})
        site(d, f"api:\n  language: openapi\n  out: http\n{extra}")
        api.build_sections(d, load(d).smalldocs["api"])
        results.append(pages(d / "http"))
    assert results[0] == results[1] == results[2]


@pytest.mark.parametrize(
    "extra,message",
    [
        (f"  command: {sys.executable} -c 'import sys; sys.stderr.write(\"bad\\\\n\"); sys.exit(3)'\n", "failed with code 3:\nbad"),
        (f"  command: {sys.executable} -c 'print(\"Compiling...\")'\n", "gave no OpenAPI document in JSON or YAML"),
        (f"  command: {sys.executable} -c 'import time; time.sleep(5)'\n  timeout: 0.5\n", "did not finish in 0.5 seconds"),
        ("  command: no-such-tool-here\n", "could not start"),
        ("  file: missing.json\n", "is not found"),
        (f"  file: {FIX / 'swagger-2.0.json'}\n", "is Swagger 2.0; smalldocs reads OpenAPI 3.0 and 3.1"),
        (f"  file: {FIX / 'webhook-example.yaml'}\n", "gave a document with no operations"),
    ],
)
def test_input_errors(tmp_path: Path, extra: str, message: str) -> None:
    "A failed command, output that is not a document, the timeout, a missing file, Swagger 2.0 and no operations stop the build."
    site(tmp_path, f"api:\n  language: openapi\n  out: http\n  root: .\n{extra}")
    with pytest.raises(ValueError, match=re.escape(message)):
        api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])


def test_openapi_3_2_is_read_as_3_1_with_a_warning(tmp_path: Path) -> None:
    "OpenAPI 3.2 builds, with one warning."
    data = ops({"/a": {"get": op()}}) | {"openapi": "3.2.0"}
    site(tmp_path, f"api:\n  language: openapi\n  file: {doc_file(tmp_path, data)}\n  out: http\n")
    _, warnings = api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])
    assert warnings == ["the api section with out 'http': OpenAPI 3.2.0 is read as 3.1, and its new fields are left out"]


@pytest.mark.parametrize(
    "conf,message",
    [
        ({"fastapi": "app:app", "file": "x.json"}, "give exactly one of file, command and fastapi, not file, fastapi"),
        ({}, "give exactly one of file, command and fastapi, not none"),
        ({"fastapi": "app"}, "fastapi 'app' must be module:name"),
        ({"fastapi": "app:app", "setup": "routers"}, "setup 'routers' must be module:name"),
        ({"fastapi": "app:app", "setup": ":f"}, "setup ':f' must be module:name"),
        ({"file": "x.json", "setup": "a:b"}, "setup is for fastapi only"),
        ({"command": "x", "setup": "a:b"}, "setup is for fastapi only"),
        ({"file": "x.json", "timeout": "soon"}, "timeout must be a number"),
        ({"file": "x.json", "check-responses": "yes"}, "check-responses must be true or false"),
    ],
)
def test_settings_errors(tmp_path: Path, conf: dict, message: str) -> None:
    "Each wrong setting is found before anything runs, and the message names the section by its `out`."
    with pytest.raises(ValueError, match=re.escape(message)):
        api.Settings.read(tmp_path, {"language": "openapi", "out": "http", **conf})


# ---------------------------------------------------------------- the FastAPI program, on duck-typed apps


APP = '''
"An app that FastAPI's program can read, with no FastAPI."
DOC = {doc}


class App:
    "Gives a document, as FastAPI does."

    routes = []

    def openapi(self):
        "The document."
        return DOC


app = App()
'''


def program_site(
    tmp: Path,  # The site's folder, which is the project's root too
    app_py: str,  # The text of `app.py`
    extra: str = "",  # More lines of the section
) -> Path:  # The site's folder
    "Make a site whose section reads `app.py` with the FastAPI program, run by this Python."
    write(tmp, {"app.py": app_py})
    return site(tmp, f"api:\n  language: openapi\n  fastapi: app:app\n  python: {sys.executable}\n  root: .\n  out: http\n{extra}")


def test_program_survives_print_argv_and_a_json_module(tmp_path: Path) -> None:
    "An app that prints at import and reads `sys.argv` builds, and a project file `json.py` does not shadow the program's."
    data = json.dumps(ops({"/a": {"get": op()}}))
    head = 'import sys\nprint("hello from the app")\nassert sys.argv[1:] == [], sys.argv\n'
    write(tmp_path, {"json.py": "raise ImportError('the project json.py was imported')\n"})
    program_site(tmp_path, head + APP.format(doc=data))
    api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])
    assert "GET /a" in (tmp_path / "http/default.qmd").read_text()
    assert not (tmp_path / "__pycache__").exists()


def test_program_sys_exit_at_import_names_the_step(tmp_path: Path) -> None:
    "An app that calls `sys.exit(2)` at import fails at the step `app-import`, and the message names the app."
    program_site(tmp_path, "import sys\nsys.exit(2)\n")
    with pytest.raises(ValueError, match=re.escape("the api section with out 'http': fastapi app:app: app-import: SystemExit: 2")):
        api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])


def test_program_no_operations_names_setup(tmp_path: Path) -> None:
    "An app with no operations says that `setup:` can add them; with a setup, it says the setup ran."
    program_site(tmp_path, APP.format(doc=json.dumps(ops({}))) + "\ndef nothing(app):\n    pass\n")
    with pytest.raises(ValueError, match="can name the function that adds them in setup"):
        api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])
    program_site(tmp_path, APP.format(doc=json.dumps(ops({}))) + "\ndef nothing(app):\n    pass\n", "  setup: app:nothing\n")
    with pytest.raises(ValueError, match="the setup app:nothing ran, and added none"):
        api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])


def test_program_source_of_routes(tmp_path: Path) -> None:
    "Each route's function gives its file and line, through a decorator with `wraps`; a `functools.partial` gives no link."
    app_py = '''
    import functools


    def deco(f):
        @functools.wraps(f)
        def inner(*a):
            return f(*a)
        return inner


    @deco
    def get_a():
        pass


    class Route:
        def __init__(self, path, endpoint):
            self.path_format, self.endpoint, self.methods, self.include_in_schema = path, endpoint, {"GET"}, True


    class App:
        routes = [Route("/a", get_a), Route("/b", functools.partial(print))]

        def openapi(self):
            return {"openapi": "3.1.0", "paths": {"/a": {"get": {"responses": {}}}, "/b": {"get": {"responses": {}}}}}


    app = App()
    '''
    program_site(tmp_path, app_py, "  source: https://example.com/blob/main\n")
    api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])
    out = (tmp_path / "http/default.qmd").read_text()
    assert "[source](https://example.com/blob/main/app.py#L12){.source-link}" in out and out.count("[source]") == 1


@pytest.mark.parametrize(
    "setup,message",
    [
        ("nomodule:f", "setup nomodule:f: setup-import: ModuleNotFoundError: No module named 'nomodule'"),
        ("app:missing", "setup app:missing: setup-import: AttributeError:"),
        ("app:NOT_CALLABLE", "setup app:NOT_CALLABLE: setup-import: TypeError: app:NOT_CALLABLE is not callable"),
        ("app:broken", "setup app:broken: setup-call: RuntimeError: no database"),
        ("app:leave", "setup app:leave: setup-call: SystemExit: 4"),
    ],
)
def test_setup_errors(tmp_path: Path, setup: str, message: str) -> None:
    "A setup that is not found, not callable, or that raises, names its step; the end of the traceback follows."
    funcs = "\nNOT_CALLABLE = 3\n\n\ndef broken(app):\n    raise RuntimeError('no database')\n\n\ndef leave(app):\n    raise SystemExit(4)\n"
    program_site(tmp_path, APP.format(doc=json.dumps(ops({"/a": {"get": op()}}))) + funcs, f"  setup: {setup}\n")
    with pytest.raises(ValueError, match=re.escape(message)) as e:
        api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])
    assert "Traceback" in str(e.value) or "setup-import" in str(e.value)


def test_async_setup_runs_once(tmp_path: Path) -> None:
    "An `async def` setup runs with `asyncio.run`, once, before `app.openapi()`."
    app_py = APP.format(doc=json.dumps(ops({}))) + '''

async def add(app):
    "Add an operation."
    DOC["paths"]["/n" + str(len(DOC["paths"]))] = {"get": {"responses": {}}}
'''
    program_site(tmp_path, app_py, "  setup: app:add\n")
    api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])
    assert re.findall(r"^## (.*) \{", (tmp_path / "http/default.qmd").read_text(), re.M) == ["GET /n0"]


def test_a_failure_with_no_marker_gives_the_code(tmp_path: Path) -> None:
    "A runner that fails before the program runs, as uv does, gives its exit code and its standard error."
    write(tmp_path, {"app.py": ""})
    site(tmp_path, f"api:\n  language: openapi\n  fastapi: app:app\n  python: [{sys.executable}, -c, 'import sys; sys.stderr.write(\"no venv\"); sys.exit(2)', --]\n  root: .\n  out: http\n")
    with pytest.raises(ValueError, match="failed with code 2:\nno venv"):
        api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])


# ---------------------------------------------------------------- the real program, with FastAPI from uv's cache

UV_FASTAPI = ["uv", "run", "--no-project", "--with", "fastapi", "python"]


@pytest.fixture(scope="module")
def fastapi_runner() -> list[str]:  # The runner, or a skip when uv cannot give FastAPI
    "Give a Python that has FastAPI, from uv's cache."
    if not shutil.which("uv"):
        pytest.skip("no uv")
    r = subprocess.run([*UV_FASTAPI, "-c", "import fastapi"], capture_output=True, timeout=300)
    if r.returncode:
        pytest.skip("uv cannot fetch FastAPI")
    return UV_FASTAPI


def test_real_program_on_the_tiny_app(tmp_path: Path, fastapi_runner: list[str]) -> None:
    "The program gives the document of `tiny.json`, with the file and line of each route."
    folder = shutil.copytree(FIX, tmp_path / "proj", ignore=shutil.ignore_patterns("__pycache__"))
    s = api.Settings.read(tmp_path, {"language": "openapi", "fastapi": "tiny_app:app", "python": fastapi_runner, "root": "proj"})
    text, *_ = api_openapi.document_text(s)
    got = json.loads(text)
    for item in got["paths"].values():
        for o in item.values():
            o["x-smalldocs-source"]["file"] = Path(o["x-smalldocs-source"]["file"]).relative_to(folder.resolve()).as_posix()
    assert got == json.loads((FIX / "tiny.json").read_text())
    assert not (folder / "__pycache__").exists()


@pytest.mark.parametrize("setup", ["tiny_setup:add_teams", "tiny_setup:add_teams_later"])
def test_real_program_with_a_setup(tmp_path: Path, fastapi_runner: list[str], setup: str) -> None:
    "A setup, plain or `async def`, adds a router, whose tag gets a page."
    shutil.copytree(FIX, tmp_path / "proj", ignore=shutil.ignore_patterns("__pycache__"))
    site(tmp_path, f"api:\n  language: openapi\n  fastapi: tiny_app:app\n  setup: {setup}\n  python: {json.dumps(fastapi_runner)}\n  root: proj\n  out: http\n")
    api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])
    assert "## GET /api/teams {#get-api-teams}" in (tmp_path / "http/teams.qmd").read_text()


# ---------------------------------------------------------------- many sections in one site


def python_package(
    tmp: Path,  # A folder
    name: str,  # The package's name, unique to the test
) -> None:
    "Write a small package with one documented function and one model-like class."
    write(tmp, {f"src/{name}/__init__.py": '"A package."\n\n\ndef f(\n    a: int,  # the a\n) -> int:  # the b\n    "Do f."\n    return a\n\n\nclass Player:\n    "A player."\n'})


def test_a_list_of_one_python_section_builds_the_same_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "A list of one Python section writes the same pages and `_symbols.json` as the mapping; the mapping writes no names file."
    python_package(tmp_path, "onepkg")
    monkeypatch.syspath_prepend(str(tmp_path / "src"))
    out = []
    for i, conf in enumerate(["api:\n  packages: [onepkg]\n  root: ..\n", "api:\n  - packages: [onepkg]\n    root: ..\n"]):
        d = site(tmp_path / f"docs{i}", conf)
        assert main(["api", "build", "--dir", str(d)]) == 0
        out.append((pages(d / "api"), (d / "_symbols.json").read_text(), (d / "api/.smalldocs-api").read_text()))
    assert out[0] == out[1]
    assert not (tmp_path / "docs0/api" / api.NAMES).exists() and (tmp_path / "docs1/api" / api.NAMES).exists()
    monkeypatch.delitem(sys.modules, "onepkg")


def test_python_and_openapi_in_one_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "A Python section and an OpenAPI section: each has its manifest and names file; a short name is the first section's; a full name in both warns."
    python_package(tmp_path, "reference")
    monkeypatch.syspath_prepend(str(tmp_path / "src"))
    data = ops({"/a": {"get": op()}}, components={"schemas": {"Player": {"type": "object"}, "f": {"type": "object"}}})
    d = site(tmp_path / "docs", f"api:\n  - packages: [reference]\n    root: ..\n    out: python\n  - language: openapi\n    file: {doc_file(tmp_path, data)}\n    out: reference\n")
    _, warnings = api.build_sections(d, load(d).smalldocs["api"])
    index = json.loads((d / "_symbols.json").read_text())
    assert index["Player"] == "/python/reference.qmd#Player" and index["reference.Player"] == "/python/reference.qmd#Player"
    assert index["f"] == "/python/reference.qmd#f" and index["GET /a"] == "/reference/default.qmd#get-a"
    assert warnings == [f"api: the name reference.{n} is in the sections with out 'python' and 'reference'; it links to 'python'" for n in ("Player", "f")]
    for out in ("python", "reference"):
        assert (d / out / ".smalldocs-api").exists() and (d / out / api.NAMES).exists()
    monkeypatch.delitem(sys.modules, "reference")


def test_out_name_builds_one_section_and_keeps_the_other_names(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    "`--out NAME` builds one section, and `_symbols.json` keeps the names of the others."
    a, b = doc_file(tmp_path, ops({"/a": {"get": op()}}), "a.json"), doc_file(tmp_path, ops({"/b": {"get": op()}}), "b.json")
    d = site(tmp_path / "docs", f"api:\n  - language: openapi\n    file: {a}\n    out: one\n  - language: openapi\n    file: {b}\n    out: two\n")
    assert main(["api", "build", "--dir", str(d)]) == 0
    before = (d / "_symbols.json").read_text()
    Path(b).write_text(json.dumps(ops({"/c": {"get": op()}})))
    assert main(["api", "build", "--dir", str(d), "--out", "two"]) == 0
    index = json.loads((d / "_symbols.json").read_text())
    assert "GET /a" in index and "GET /c" in index and "GET /b" not in index and "GET /b" in before
    assert main(["api", "build", "--dir", str(d), "--out", "three"]) == 2
    assert "no api section has out 'three'" in capsys.readouterr().err


@pytest.mark.parametrize("outs", [("http", "http"), ("http", "http/v2"), ("API", "api")])
def test_two_sections_share_no_folder(tmp_path: Path, outs: tuple[str, str]) -> None:
    "Two sections with one `out`, or one inside the other, stop the build."
    f = doc_file(tmp_path, ops({"/a": {"get": op()}}))
    site(tmp_path, "api:\n" + "".join(f"  - language: openapi\n    file: {f}\n    out: {o}\n" for o in outs))
    with pytest.raises(ValueError, match="share a folder"):
        api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])


def test_a_removed_section_warns_and_strict_fails(tmp_path: Path) -> None:
    "A section removed from the list leaves its pages, and the build warns with its folder, so `--strict` fails."
    f = doc_file(tmp_path, ops({"/a": {"get": op()}}))
    two = f"api:\n  - language: openapi\n    file: {f}\n    out: one\n  - language: openapi\n    file: {f}\n    out: two\n"
    site(tmp_path, two)
    build_site(tmp_path, quiet=True)
    site(tmp_path, two.split("  - language: openapi\n    file: " + f + "\n    out: two\n")[0])
    s = Site(load(tmp_path), quiet=True)
    s.build()
    assert any("api: two holds the pages of an api section that the config no longer has" in w for w in s.warnings)
    assert (tmp_path / "two/default.qmd").exists()
    assert main(["render", str(tmp_path), "--strict"]) == 1


def test_exact_symbols_for_openapi(tmp_path: Path) -> None:
    "Names match exactly with a mapping of `language: openapi`, and with a list that has one; `linkify` is at the top level for a list."
    f = doc_file(tmp_path, ops({"/a": {"get": op()}}))
    for conf, exact in [(f"api:\n  language: openapi\n  file: {f}\n", True), (f"api:\n  - packages: [x]\n  - language: openapi\n    file: {f}\n    out: http\n", True), ("api:\n  packages: [x]\n", False)]:
        write(tmp_path, {"_symbols.json": "{}"})
        s = Site(load(site(tmp_path, conf)), quiet=True)
        s.load_symbols()
        assert s.exact_symbols is exact
    s = Site(load(site(tmp_path, f"linkify: false\napi:\n  - language: openapi\n    file: {f}\n")), quiet=True)
    s.load_symbols()
    assert s.symbols == {}


def test_list_and_module_pick_the_python_section(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    "`api list` and `module` act on the one Python section; none, or two without `--out`, stop with a message."
    python_package(tmp_path, "listpkg")
    monkeypatch.syspath_prepend(str(tmp_path / "src"))
    f = doc_file(tmp_path, ops({"/a": {"get": op()}}))
    oa = f"  - language: openapi\n    file: {f}\n    out: http\n"
    py = "  - packages: [listpkg]\n    root: ..\n    out: {}\n"
    d = site(tmp_path / "docs", "api:\n" + oa + py.format("python"))
    assert main(["api", "list", "--dir", str(d)]) == 0 and "listpkg.f" in capsys.readouterr().out
    site(d, "api:\n" + oa)
    assert main(["api", "list", "--dir", str(d)]) == 2 and "no api section is python" in capsys.readouterr().err
    site(d, "api:\n" + oa + py.format("p1") + py.format("p2"))
    assert main(["api", "module", "listpkg", "--dir", str(d)]) == 2 and "name one with --out NAME" in capsys.readouterr().err
    assert main(["api", "module", "listpkg", "--dir", str(d), "--out", "p2"]) == 0 and "# listpkg" in capsys.readouterr().out
    monkeypatch.delitem(sys.modules, "listpkg")


def test_a_list_must_hold_mappings(tmp_path: Path) -> None:
    "An `api` list of something else than mappings is an error of the config."
    site(tmp_path, "api:\n  - just text\n")
    with pytest.raises(Exception, match="a list of mappings"):
        load(tmp_path)


def test_smalldocs_api_imports_no_fastapi(tmp_path: Path) -> None:
    "`smalldocs api` with an OpenAPI section imports no FastAPI and no Pydantic: only fastcore, PyYAML and the standard library."
    f = doc_file(tmp_path, ops({"/a": {"get": op()}}))
    site(tmp_path, f"api:\n  language: openapi\n  file: {f}\n")
    code = f"import sys; from smalldocs.cli import main; main(['api', 'build', '--dir', {str(tmp_path)!r}]); print(sorted(m for m in sys.modules if m.split('.')[0] in ('fastapi', 'pydantic', 'markdown_it', 'pygments')))"
    assert subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip().endswith("[]")


# ---------------------------------------------------------------- what the review of step 1 found


@pytest.mark.parametrize(
    "where,value",
    [
        ("responses", [1, 2]),
        ("responses", "x"),
        ("parameters", 5),
        ("requestBody", {"content": {"application/json": {"schema": {"type": "object", "properties": [1]}}}}),
        ("requestBody", {"content": {"application/json": {"schema": {"type": "object", "required": [{"a": 1}], "properties": {"a": {}}}}}}),
        ("requestBody", {"content": {"application/json": {"schema": {"allOf": 5}}}}),
    ],
)
def test_a_value_of_the_wrong_kind_names_the_section(tmp_path: Path, where: str, value: object) -> None:
    "A list or a number where OpenAPI has a mapping stops the build with a message that names the section, not a bare Python error."
    with pytest.raises(ValueError, match="the api section with out 'http': the document has a value of the wrong kind"):
        built(tmp_path, ops({"/a": {"get": {"responses": {"200": {"description": "OK"}}, where: value}}}))


def test_wrong_kinds_at_the_top_and_deep_json(tmp_path: Path) -> None:
    "Top-level `tags` or `components` of the wrong kind, and JSON nested too deep, stop with a message."
    with pytest.raises(ValueError, match="value of the wrong kind"):
        (tmp_path / "a").mkdir()
        built(tmp_path / "a", ops({"/a": {"get": op()}}, tags=5))
    with pytest.raises(ValueError, match=re.escape("components and components.schemas must be mappings")):
        (tmp_path / "b").mkdir()
        built(tmp_path / "b", ops({"/a": {"get": op()}}, components=[1]))
    (tmp_path / "c").mkdir()
    (tmp_path / "c/deep.json").write_text("[" * 100000 + "]" * 100000)
    site(tmp_path / "c", "api:\n  language: openapi\n  file: deep.json\n  out: http\n")
    with pytest.raises(ValueError, match="gave no OpenAPI document"):
        api.build_sections(tmp_path / "c", load(tmp_path / "c").smalldocs["api"])


def test_null_takes_no_format(tmp_path: Path) -> None:
    "A 3.1 `type: [string, null]` with a format gives `string (date-time) or null`."
    assert document(tmp_path, ops({})).type_of({"type": ["string", "null"], "format": "date-time"}) == "string (date-time) or null"


def test_a_timeout_kills_what_the_runner_started(tmp_path: Path) -> None:
    "On a timeout, the program under the runner stops too, and is not left running."
    marker = tmp_path / "alive"
    app_py = f"import time\nfor _ in range(40):\n    time.sleep(0.25)\nopen({str(marker)!r}, 'w').write('still running')\n"
    write(tmp_path, {"app.py": app_py})
    runner = [sys.executable, "-c", "import subprocess, sys; sys.exit(subprocess.call([sys.executable] + sys.argv[1:]))"]
    site(tmp_path, f"api:\n  language: openapi\n  fastapi: app:app\n  python: {json.dumps(runner)}\n  root: .\n  out: http\n  timeout: 1\n")
    with pytest.raises(ValueError, match="did not finish in 1 seconds"):
        api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])
    import time

    time.sleep(10.5)
    assert not marker.exists()


def test_program_ends_with_a_thread_running_and_keeps_fd_1(tmp_path: Path) -> None:
    "An app that starts a thread, and writes to file descriptor 1 at import, still gives its document at once."
    head = "import os, sys, threading, time\nthreading.Thread(target=time.sleep, args=(60,)).start()\nos.write(1, b'hello\\n')\nprint('hi', file=sys.__stdout__)\n"
    program_site(tmp_path, head + APP.format(doc=json.dumps(ops({"/a": {"get": op()}}))), "  timeout: 20\n")
    api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])
    assert "GET /a" in (tmp_path / "http/default.qmd").read_text()


def test_line_breaks_in_names_split_nothing(tmp_path: Path) -> None:
    "A line break in a path, a schema's name, a parameter's name or a status is a space, so no heading or row is split."
    p = {"name": "p\n| injected | row |", "in": "query", "schema": {"type": "string"}}
    data = ops({"/a\n# Injected": {"get": {"parameters": [p], "responses": {"200\nx": {"description": "OK"}}}}}, components={"schemas": {"A\nB": {"type": "object"}}})
    out = built(tmp_path, data)
    assert "## GET /a \\# Injected {#get-a-injected}" in out["default.qmd"]
    assert "| `p \\| injected \\| row \\|` | query |" in out["default.qmd"] and "| 200 x |" in out["default.qmd"]
    assert "## A B {#A-B}" in out["schemas.qmd"]
    assert "\n# Injected" not in out["default.qmd"]


def test_many_operations_build_in_linear_time(tmp_path: Path) -> None:
    "Ten thousand operations and schemas get their ids quickly."
    import time

    paths = {f"/p{i}": {"get": op()} for i in range(10000)}
    t = time.perf_counter()
    document(tmp_path, ops(paths, components={"schemas": {f"S{i}": {"type": "object"} for i in range(10000)}}))
    assert time.perf_counter() - t < 5


def test_yaml_aliases_cannot_blow_up(tmp_path: Path) -> None:
    "A small YAML document whose aliases repeat a value millions of times, or hold itself, stops the build."
    lines = ["openapi: 3.1.0", "paths: {/a: {get: {responses: {'200': {description: OK}}}}}", "components:", "  schemas:", "    X:", "      default: &a0 [1, 2]"]
    lines += [f"      d{k}: &a{k} [*a{k - 1}, *a{k - 1}, *a{k - 1}, *a{k - 1}]" for k in range(1, 12)]
    write(tmp_path, {"bomb.yaml": "\n".join(lines) + "\n", "loop.yaml": "openapi: 3.1.0\npaths: &p {/a: {get: {responses: {'200': {description: OK, x: *p}}}}}\n"})
    for name, message in (("bomb.yaml", "holds more than"), ("loop.yaml", "holds itself")):
        site(tmp_path, f"api:\n  language: openapi\n  file: {name}\n  out: http\n")
        with pytest.raises(ValueError, match=message):
            api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])


def test_a_ref_that_is_no_pointer_points_at_nothing(tmp_path: Path) -> None:
    "`$ref: '#foo'` is no JSON pointer, so it stops the build."
    with pytest.raises(ValueError, match=re.escape("the $ref #foo points at nothing")):
        built(tmp_path, ops({"/a": {"get": {"parameters": [{"$ref": "#foo"}], "responses": {}}}}))


def test_a_schema_named_by_a_number(tmp_path: Path) -> None:
    "A schema whose YAML name is a number is reached by its `$ref`."
    write(tmp_path, {"d.yaml": "openapi: 3.1.0\npaths: {/a: {get: {responses: {'200': {description: OK, content: {application/json: {schema: {$ref: '#/components/schemas/1'}}}}}}}}\ncomponents: {schemas: {1: {type: object}}}\n"})
    site(tmp_path, "api:\n  language: openapi\n  file: d.yaml\n  out: http\n")
    api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])
    assert "[1](schemas.qmd#1)" in (tmp_path / "http/default.qmd").read_text()


def test_out_name_is_a_path(tmp_path: Path) -> None:
    "`--out ./http` and `--out http/` name the section with out `http`."
    f = doc_file(tmp_path, ops({"/a": {"get": op()}}))
    d = site(tmp_path / "docs", f"api:\n  - language: openapi\n    file: {f}\n    out: http\n")
    for out in ("./http", "http/", "HTTP"):
        assert main(["api", "build", "--dir", str(d), "--out", out]) == 0


# ---------------------------------------------------------------- what the review of the fixes found


def test_ctrl_c_stops_the_program_too(tmp_path: Path) -> None:
    "Ctrl-C during a build kills the program, which runs in a session of its own."
    import signal
    import time

    marker = tmp_path / "alive"
    write(tmp_path, {"app.py": f"import time\ntime.sleep(6)\nopen({str(marker)!r}, 'w').write('x')\n"})
    site(tmp_path, f"api:\n  language: openapi\n  fastapi: app:app\n  python: {sys.executable}\n  root: .\n  out: http\n")
    proc = subprocess.Popen([sys.executable, "-m", "smalldocs.cli", "api", "build", "--dir", str(tmp_path)], start_new_session=True, stderr=subprocess.DEVNULL)
    time.sleep(2)
    os.killpg(proc.pid, signal.SIGINT)
    proc.wait(timeout=20)
    time.sleep(6)
    assert not marker.exists()


def test_a_worker_that_keeps_stderr_open_holds_nothing(tmp_path: Path) -> None:
    "An app that starts a worker process at import gives its document at once; the worker keeps standard error open."
    import time

    head = "import subprocess, sys\nsubprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
    program_site(tmp_path, head + APP.format(doc=json.dumps(ops({"/a": {"get": op()}}))), "  timeout: 15\n")
    t = time.perf_counter()
    api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])
    assert time.perf_counter() - t < 10


def test_unflushed_output_and_a_replaced_stderr_reach_the_message(tmp_path: Path) -> None:
    "What the app printed to `sys.__stdout__` before it failed is in the message, and so is the marker when it replaced `sys.stderr`."
    program_site(tmp_path, "import sys\nprint('CAUSE here', file=sys.__stdout__)\nraise SystemExit(3)\n")
    with pytest.raises(ValueError, match="CAUSE here"):
        api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])
    program_site(tmp_path, "import io, sys\nsys.stderr = io.StringIO()\nraise RuntimeError('hidden')\n")
    with pytest.raises(ValueError, match="app-import: RuntimeError: hidden"):
        api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])


def test_a_lone_surrogate_and_a_unicode_digit_name_the_section(tmp_path: Path) -> None:
    "A description with a lone surrogate, and a pointer with `²`, stop the build with the section's name."
    (tmp_path / "a").mkdir()
    with pytest.raises(ValueError, match="the api section with out 'http'"):
        built(tmp_path / "a", ops({"/a": {"get": op(description="bad \ud800 char")}}))
    (tmp_path / "b").mkdir()
    with pytest.raises(ValueError, match=re.escape("the $ref #/tags/² points at nothing")):
        built(tmp_path / "b", ops({"/a": {"get": {"parameters": [{"$ref": "#/tags/²"}], "responses": {}}}}, tags=[{"name": "x"}]))


def test_a_pointer_reaches_a_key_that_yaml_reads_as_a_number(tmp_path: Path) -> None:
    "`#/paths/~1a/get/responses/200` reaches an unquoted `200:` of YAML."
    doc = "openapi: 3.1.0\npaths:\n  /a:\n    get:\n      responses:\n        200: {description: Fine}\n  /b:\n    get:\n      responses:\n        200: {$ref: '#/paths/~1a/get/responses/200'}\n"
    write(tmp_path, {"d.yaml": doc})
    site(tmp_path, "api:\n  language: openapi\n  file: d.yaml\n  out: http\n")
    api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])
    assert (tmp_path / "http/default.qmd").read_text().count("| 200 |  |  | Fine |") == 2


def test_line_breaks_in_tags_operation_ids_and_schema_names(tmp_path: Path) -> None:
    "A line break in a tag, an operationId or a schema's name is a space in the title and in `_symbols.json`."
    out = built(tmp_path, ops({"/a": {"get": op(tags=["Tag\nTwo"], operationId="op\nid")}}, components={"schemas": {"S\nT": {"type": "object"}}}))
    assert 'title: "Tag Two"' in out["tag-two.qmd"]
    assert {"op id", "S T", "http.S T"} <= set(json.loads((tmp_path / "_symbols.json").read_text()))


# ---------------------------------------------------------------- what the third review found


def alive(
    pid: int,  # A process id
) -> bool:  # Whether the process still runs
    "Tell whether a process runs."
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_a_worker_left_by_a_good_build_is_killed(tmp_path: Path) -> None:
    "A process that the app starts does not outlive a build that succeeds."
    import time

    pid = tmp_path / "pid"
    head = f"import subprocess\nopen({str(pid)!r}, 'w').write(str(subprocess.Popen(['sleep', '301']).pid))\n"
    program_site(tmp_path, head + APP.format(doc=json.dumps(ops({"/a": {"get": op()}}))), "  timeout: 20\n")
    api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])
    time.sleep(0.5)
    assert not alive(int(pid.read_text()))


def test_a_command_that_leaves_a_child_gives_its_document_at_once(tmp_path: Path) -> None:
    "A command that ends, and leaves a child that holds its output, gives its document without waiting for the timeout."
    import time

    doc = json.dumps(ops({"/a": {"get": op()}}))
    write(tmp_path, {"print.sh": f"sleep 300 &\necho '{doc}'\n"})
    site(tmp_path, "api:\n  language: openapi\n  command: [sh, print.sh]\n  root: .\n  out: http\n  timeout: 20\n")
    t = time.perf_counter()
    api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])
    assert time.perf_counter() - t < 10
    assert "GET /a" in (tmp_path / "http/default.qmd").read_text()


@pytest.mark.parametrize("sig", ["SIGTERM", "SIGHUP"])
def test_sigterm_and_sighup_stop_the_program_too(tmp_path: Path, sig: str) -> None:
    "SIGTERM or SIGHUP to the build kills the program, and the build stops as the signal asks."
    import signal
    import time

    marker = tmp_path / "alive"
    write(tmp_path, {"app.py": f"import time\ntime.sleep(6)\nopen({str(marker)!r}, 'w').write('x')\n"})
    site(tmp_path, f"api:\n  language: openapi\n  fastapi: app:app\n  python: {sys.executable}\n  root: .\n  out: http\n")
    proc = subprocess.Popen([sys.executable, "-m", "smalldocs.cli", "api", "build", "--dir", str(tmp_path)], stderr=subprocess.DEVNULL)
    time.sleep(2)
    proc.send_signal(getattr(signal, sig))
    assert proc.wait(timeout=20) == -getattr(signal, sig)
    time.sleep(6)
    assert not marker.exists()


def test_the_marker_after_a_progress_bar_and_the_app_output_before_the_traceback(tmp_path: Path) -> None:
    "The marker is found after output with no line break, and the message ends with the traceback, after the app's own output."
    program_site(tmp_path, "import sys\nsys.stderr.write('loading models...')\nsys.stderr.flush()\nraise RuntimeError('the real cause')\n")
    with pytest.raises(ValueError, match="fastapi app:app: app-import: RuntimeError: the real cause"):
        api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])
    noise = "import sys\nfor i in range(30):\n    print('noise', i, file=sys.__stdout__)\nraise RuntimeError('the real cause')\n"
    program_site(tmp_path, noise)
    with pytest.raises(ValueError) as e:
        api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])
    assert "noise 29" in str(e.value) and str(e.value).endswith("RuntimeError: the real cause")


def test_a_long_line_of_stderr_is_cut(tmp_path: Path) -> None:
    "One long line of standard error is cut to 500 characters in the message."
    program_site(tmp_path, "import os\nos.write(2, b'x' * 100000)\nos._exit(4)\n")
    with pytest.raises(ValueError) as e:
        api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])
    assert len(str(e.value)) < 1000 and "failed with code 4" in str(e.value)


def test_no_document_shows_the_end_of_stderr(tmp_path: Path) -> None:
    "A command that ends well and prints no document shows the end of its standard error, which may say why."
    write(tmp_path, {"say.sh": "echo 'the real reason: DATABASE_URL is not set' >&2\n"})
    site(tmp_path, "api:\n  language: openapi\n  command: [sh, say.sh]\n  root: .\n  out: http\n")
    with pytest.raises(ValueError, match=r"(?s)gave no OpenAPI document.*DATABASE_URL is not set"):
        api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])


def test_output_that_is_not_utf_8_stops_the_build(tmp_path: Path) -> None:
    "A command that prints a byte that is not UTF-8 stops the build, as a file does."
    write(tmp_path, {"latin.py": "import sys\nsys.stdout.buffer.write(b'{\"openapi\": \"3.1.0\", \"info\": {\"title\": \"caf\\xe9\"}, \"paths\": {}}')\n"})
    site(tmp_path, f"api:\n  language: openapi\n  command: [{sys.executable}, latin.py]\n  root: .\n  out: http\n")
    with pytest.raises(ValueError, match="printed text that is not UTF-8"):
        api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])


def test_a_closed_fd_2_still_gives_the_marker(tmp_path: Path) -> None:
    "An app that closes file descriptor 2 still names the step that failed."
    program_site(tmp_path, "import os\nos.close(2)\nraise RuntimeError('no stderr')\n")
    with pytest.raises(ValueError, match="app-import: RuntimeError: no stderr"):
        api.build_sections(tmp_path, load(tmp_path).smalldocs["api"])


def test_many_refs_resolve_in_linear_time(tmp_path: Path) -> None:
    "Eight thousand operations, each with a `$ref` to a parameter of its own, build quickly."
    import time

    n = 8000
    params = {f"p{i}": {"name": f"p{i}", "in": "query", "schema": {"type": "string"}} for i in range(n)}
    paths = {f"/p{i}": {"get": {"parameters": [{"$ref": f"#/components/parameters/p{i}"}], "responses": {}}} for i in range(n)}
    t = time.perf_counter()
    built(tmp_path, ops(paths, components={"parameters": params}))
    assert time.perf_counter() - t < 3


def test_two_schemas_on_one_line_stop_the_build(tmp_path: Path) -> None:
    "Two schemas whose names are the same once a line break is a space stop the build, and neither is lost."
    with pytest.raises(ValueError, match="two schemas have the name 'A B' on one line"):
        built(tmp_path, ops({"/a": {"get": op()}}, components={"schemas": {"A\nB": {"type": "string"}, "A B": {"type": "integer"}}}))


def test_a_key_of_another_language_is_not_checked(tmp_path: Path) -> None:
    "A key of another language warns, and its value does not stop the build."
    assert section_warnings(tmp_path, {"language": "typescript", "toolchain": 1}) == ["the api section with out 'api': toolchain is not read for typescript; it is for rust"]
    assert section_warnings(tmp_path, {"language": "openapi", "file": "a.json", "entry": 5}) == ["the api section with out 'api': entry is not read for openapi; it is for typescript"]


def test_package_with_packages_warns(tmp_path: Path) -> None:
    "`package` beside `packages` is not read, and warns."
    assert section_warnings(tmp_path, {"packages": ["x"], "package": "y"}) == ["the api section with out 'api': package is not read, because packages is given; give one of them"]


def test_python_and_timeout_warn_where_they_are_not_read(tmp_path: Path) -> None:
    "`python` is read only with `fastapi`, and `timeout` only with `command` or `fastapi`."
    got = section_warnings(tmp_path, {"language": "openapi", "file": "a.json", "python": "py", "timeout": 5})
    assert got == ["the api section with out 'api': python is not read without fastapi", "the api section with out 'api': timeout is not read without command or fastapi"]
    assert section_warnings(tmp_path, {"language": "openapi", "command": "x", "timeout": 5}) == []


def test_an_ignored_sighup_leaves_the_command_running(tmp_path: Path) -> None:
    "A build that ignores SIGHUP, as under `nohup`, keeps its command when SIGHUP comes, and builds."
    import time

    head = "import time\ntime.sleep(4)\n"
    program_site(tmp_path, head + APP.format(doc=json.dumps(ops({"/a": {"get": op()}}))), "  timeout: 30\n")
    code = f"import signal, sys; signal.signal(signal.SIGHUP, signal.SIG_IGN); from smalldocs.cli import main; sys.exit(main(['api', 'build', '--dir', {str(tmp_path)!r}]))"
    proc = subprocess.Popen([sys.executable, "-c", code], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    time.sleep(2)
    proc.send_signal(subprocess.signal.SIGHUP)
    assert proc.wait(timeout=30) == 0
    assert "GET /a" in (tmp_path / "http/default.qmd").read_text()


def section_warnings(
    site: Path,  # The site's folder
    conf: dict,  # An api section
) -> list[str]:  # Its warnings
    "Read one api section, and give its warnings."
    return api.Settings.read(site, conf).warnings


@pytest.mark.parametrize(
    "conf,warning",
    [
        ({"packages": ["x"], "linkfy": False}, "the api section with out 'api': linkfy is not read for python; smalldocs does not know it"),
        ({"packages": ["x"], "toolchain": "nightly"}, "the api section with out 'api': toolchain is not read for python; it is for rust"),
        ({"language": "rust", "entry": "src"}, "the api section with out 'api': entry is not read for rust; it is for typescript"),
        ({"language": "typescript", "private": True}, "the api section with out 'api': private is not read for typescript; it is for rust"),
        ({"language": "openapi", "file": "a.json", "out": "http", "packages": ["x"]}, "the api section with out 'http': packages is not read for openapi; it is for python"),
        ({"language": "openapi", "file": "a.json", "check-response": True}, "the api section with out 'api': check-response is not read for openapi; smalldocs does not know it"),
    ],
)
def test_a_key_that_the_section_does_not_read_warns(tmp_path: Path, conf: dict, warning: str) -> None:
    "Each key of an api section that its language does not read is a warning, for every language."
    assert section_warnings(tmp_path, conf) == [warning]


@pytest.mark.parametrize(
    "conf",
    [
        {"packages": ["x"], "root": ".", "out": "api", "source": "https://x", "linkify": False, "check": "*.py", "check-shown": True, "language": "python"},
        {"language": "rust", "manifest": "Cargo.toml", "toolchain": "nightly", "private": True, "root": ".", "out": "api", "source": "s", "linkify": True, "check-shown": True},
        {"language": "typescript", "entry": "src", "tsconfig": "tsconfig.json", "root": ".", "out": "api", "source": "s", "linkify": True, "check-shown": True},
        {"language": "openapi", "fastapi": "a:app", "setup": "a:f", "python": "python", "timeout": 5, "check-responses": True, "root": ".", "out": "api", "check-shown": True},
    ],
)
def test_the_keys_that_a_section_reads_do_not_warn(tmp_path: Path, conf: dict) -> None:
    "A section with only the keys of its language has no warning."
    assert section_warnings(tmp_path, conf) == []


def test_an_unread_key_warns_in_the_build_and_with_api_check(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    "The warning of an unread key reaches the site's warnings, so `--strict` fails, and `smalldocs api check` prints it."
    f = doc_file(tmp_path, ops({"/a": {"get": op()}}))
    site(tmp_path, f"api:\n  - language: openapi\n    file: {f}\n    out: http\n    tags: [a]\n")
    s = Site(load(tmp_path), quiet=True)
    s.build()
    assert "the api section with out 'http': tags is not read for openapi; smalldocs does not know it" in s.warnings
    assert main(["render", str(tmp_path), "--strict"]) == 1
    capsys.readouterr()
    main(["api", "check", "--dir", str(tmp_path)])
    assert "warning: the api section with out 'http': tags is not read for openapi" in capsys.readouterr().err
