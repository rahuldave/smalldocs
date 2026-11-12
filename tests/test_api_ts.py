"The API reference of a TypeScript package, from TypeDoc's JSON: one test per rule of SPEC-rust-typescript.md."

import json
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from smalldocs import api, api_ts
from smalldocs.api_ts import read_signature, split_comments, type_text
from smalldocs.cli import main
from smalldocs.markdown import render

FIX = Path(__file__).parent / "fixtures" / "ts"
TOP = f"---\n{api.MARK}\n"  # The start of each page that a build writes


def fixture(
    name: str,  # `lib` or `app`
) -> tuple[dict, Path]:  # TypeDoc's JSON for it, and the folder its file names start from
    "Read a fixture's TypeDoc JSON, as `api_ts.typedoc_json` gives it."
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8")), FIX / name


def site(
    tmp: Path,  # A folder for the site
    name: str,  # The fixture: `lib` or `app`
    monkeypatch: pytest.MonkeyPatch,  # To give the fixture's JSON in place of TypeDoc's
    extra: str = "",  # More lines for the api section
) -> Path:  # The site's folder
    "Make a site whose api section documents a fixture, with TypeDoc replaced by the fixture's JSON."
    entry = "src/index.ts" if name == "lib" else "src"
    conf = f"project:\n  type: website\napi:\n  language: typescript\n  entry: {FIX / name / entry}\n  root: {FIX / name}\n{extra}"
    (tmp / "_smalldocs.yml").write_text(conf, encoding="utf-8")
    (tmp / "index.qmd").write_text("# Home\n\nSee `Rect` and `Badge`.\n", encoding="utf-8")
    monkeypatch.setattr(api_ts, "typedoc_json", lambda s: fixture(name))
    return tmp


def pages(
    tmp: Path,  # The site's folder
) -> dict[str, str]:  # Each page the API build wrote, by its file name
    "Read the pages of the API build."
    return {p.relative_to(tmp / "api").as_posix(): p.read_text(encoding="utf-8") for p in sorted((tmp / "api").rglob("*.qmd"))}


def entry_of(
    text: str,  # A page
    name: str,  # An entry's id
) -> str:  # The entry, from its heading to the next heading
    "Cut one entry out of a page."
    start = next(i for i, ln in enumerate(text.split("\n")) if ln.endswith(f"{{#{name}}}"))
    lines = text.split("\n")[start:]
    end = next((i for i, ln in enumerate(lines[1:], 1) if ln.startswith("#")), len(lines))
    return "\n".join(lines[:end])


@pytest.fixture
def lib(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:  # The page of the library fixture
    "Build the library fixture and give its one page."
    site(tmp_path, "lib", monkeypatch)
    assert main(["api", "build", "--dir", str(tmp_path)]) == 0
    return pages(tmp_path)["lib.qmd"]


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:  # The pages of the app fixture
    "Build the app fixture, whose entry is a folder, and give its pages."
    site(tmp_path, "app", monkeypatch)
    assert main(["api", "build", "--dir", str(tmp_path)]) == 0
    return pages(tmp_path)


# ---------------------------------------------------------------- comments on parameters


def test_comment_after_each_parameter_and_the_return(lib: str) -> None:
    "A `//` comment on a parameter's line is that parameter's; one on the line of the return type is the return's."
    e = entry_of(lib, "add")
    assert "```ts\nfunction add(a: number, b: number = 1): number\n```" in e
    assert "| `a` | number | required | the first number |" in e
    assert "| `b` | number | `1` | the second number |" in e
    assert "| returns | number |  | the sum |" in e


def test_param_and_returns_tags_when_there_is_no_comment(lib: str) -> None:
    "Without a comment after it, a parameter takes its `@param`, and the return its `@returns`."
    e = entry_of(lib, "scale")
    assert "| `x` | number | required | the number to scale |" in e
    assert "| `by` | number | `2` | how much to scale it |" in e
    assert "| returns | number |  | the scaled number |" in e
    assert "@param" not in e


def test_arrow_function_constant_reads_its_comments(lib: str) -> None:
    "An arrow function in a constant is a function, with its comments read the same way; an optional parameter says so."
    e = entry_of(lib, "twice")
    assert "function twice(n: number, label?: string): string" in e
    assert "| `label` | string | optional | what goes before it |" in e
    assert "| returns | string |  | the text |" in e


def test_comment_on_the_line_of_the_brace_is_the_returns() -> None:
    "On a one-line signature, the comment is the return's, even when a parameter is on that line too."
    lines = split_comments("export function log(message: string): void {  // said\n}\n")
    said = read_signature(lines, 1, 16)
    assert said.params == [""] and said.returns == "said"


def test_two_parameters_on_one_line_share_no_comment() -> None:
    "A comment on a line with two parameters documents neither, because it cannot say which."
    src = "function f(a: number, b: number,  // which?\n           c = 1,  // the third\n): void {\n}\n"
    said = read_signature(split_comments(src), 1, 9)
    assert said.params == ["", "", "the third"] and said.returns == ""


def test_signature_reading_skips_strings_comments_and_generics() -> None:
    "Brackets and `//` in strings, `/* */` comments and type parameters do not confuse the reading of a signature."
    src = textwrap.dedent("""\
        export function g<T extends Array<number>>(a = "(,//)",  // the text
                                                   /* b */ b: T = [1, 2] as T,  // the list
        ): Map<string, T> {  // a map
        }
    """)
    said = read_signature(split_comments(src), 1, 16)
    assert said.params == ["the text", "the list"] and said.returns == "a map"


def test_a_constant_that_is_no_function_has_no_signature() -> None:
    "A line with no parameter list gives no comments."
    said = read_signature(split_comments("export const x = { a: 1 };  // x\n"), 1, 13)
    assert said.params == [] and said.returns == ""


def test_parameter_with_no_comment_and_no_tag_is_empty(lib: str) -> None:
    "A function with no comments at all still has its table, with the description empty."
    e = entry_of(lib, "bare")
    assert "| `x` | number | required |  |" in e and "| returns | number |  |  |" in e


# ---------------------------------------------------------------- the pages


def test_one_page_per_entry_point_holds_what_it_exports_again(lib: str, tmp_path: Path) -> None:
    "One entry point is one page, named after the project, with every item that `export *` brings in."
    assert list(pages(tmp_path)) == ["index.qmd", "lib.qmd"]
    assert pages(tmp_path)["index.qmd"] == TOP + 'title: "Reference"\n---\n\n| Name | Summary |\n| --- | --- |\n| [`lib`](/api/lib.qmd) | A small library of shapes and sums. |\n'
    assert lib.startswith(TOP + 'title: "lib"\ndescription: "A small library of shapes and sums."\n---\n')
    for name in ["add", "Rect", "Point", "Button", "ButtonProps", "Style", "Size", "Colour"]:
        assert f"{{#{name}}}" in lib


def test_one_page_per_file_when_entry_is_a_folder(app: dict[str, str]) -> None:
    "A folder as entry makes a page per file, in the folders of the source, titled by the file's own name."
    pages_ = {"components/Badge.qmd", "components/Chip.qmd", "components/format.qmd", "components/index.qmd", "hooks/useCounter.qmd", "utils/format.qmd"}
    assert set(app) == pages_ | {"index.qmd", "hooks/index.qmd", "utils/index.qmd"}
    assert app["components/Badge.qmd"].startswith(TOP + 'title: "Badge"\n')
    assert app["utils/format.qmd"].startswith(TOP + 'title: "format"\n')


def test_each_folder_has_an_index_that_lists_its_pages(app: dict[str, str]) -> None:
    "A folder with no module of its own gets an `index.qmd`, titled by the folder, with a table of its pages; a module that is a folder's index has the table too."
    assert app["hooks/index.qmd"] == TOP + 'title: "hooks"\n---\n\n| Name | Summary |\n| --- | --- |\n| [`useCounter`](/api/hooks/useCounter.qmd) |  |\n'
    rows = "| [`Badge`](/api/components/Badge.qmd) | Badge: a small label with a tone. |\n| [`Chip`](/api/components/Chip.qmd) | Chips: small labels in a row. |\n"
    assert "\n\n| Name | Summary |\n| --- | --- |\n" + rows + "| [`format`](/api/components/format.qmd) |  |\n\nIt exports again" in app["components/index.qmd"]


def test_nested_folders_list_their_subfolders() -> None:
    "A folder's index links to each subfolder's index, so nested folders become nested sections."
    said = {"components/A.qmd": "a", "components/charts/Bar.qmd": "", "components/charts/index.qmd": "Charts.", "components/charts/deep/Line.qmd": "", "hooks/useX.qmd": ""}
    assert api.folder_listing("api", "components", said) == "| Name | Summary |\n| --- | --- |\n| [`A`](/api/components/A.qmd) | a |\n| [`charts`](/api/components/charts/index.qmd) | Charts. |"
    assert api.folder_listing("api", "components/charts", said) == "| Name | Summary |\n| --- | --- |\n| [`Bar`](/api/components/charts/Bar.qmd) |  |\n| [`deep`](/api/components/charts/deep/index.qmd) |  |"


def test_an_index_file_is_named_by_its_folder_and_never_index(app: dict[str, str]) -> None:
    "`components/index.ts` is the folder's `index.qmd`; `api/index.qmd` is the reference's front page, which lists the top level."
    rows = "| [`components`](/api/components/index.qmd) | The components, in one place. |\n| [`hooks`](/api/hooks/index.qmd) |  |\n| [`utils`](/api/utils/index.qmd) |  |\n"
    assert app["index.qmd"] == TOP + 'title: "Reference"\n---\n\n| Name | Summary |\n| --- | --- |\n' + rows
    assert app["components/index.qmd"].startswith(TOP + 'title: "components"\ndescription: "The components, in one place."\n')


def test_reexports_have_one_entry_where_they_are_declared(app: dict[str, str]) -> None:
    "An item that an index exports again has its entry on its own file's page; the index names it."
    assert "{#Badge}" in app["components/Badge.qmd"] and "{#Badge}" not in app["components/index.qmd"]
    assert "It exports again `Badge`, `badgeText`, from the modules that declare them." in app["components/index.qmd"]


def test_interface_fields_with_the_comment_after_each(lib: str) -> None:
    "An interface shows its fields as a table, each with the comment after it; an optional field is marked."
    e = entry_of(lib, "Point")
    assert e.startswith("## interface Point {#Point}")
    assert "| `x` | number | the distance across |" in e and "| `label`? | string | a name to show beside it |" in e


def test_type_aliases_with_and_without_fields(lib: str) -> None:
    "An object type shows its fields; any other type shows what it stands for."
    assert "| `width` | number | across |" in entry_of(lib, "Size")
    assert '```ts\ntype Colour = "red" | "green" | "blue"\n```' in entry_of(lib, "Colour")


def test_enum_members_with_values_and_comments(lib: str) -> None:
    "An enum shows its members in source order, with their values, and the comment after each or its JSDoc."
    e = entry_of(lib, "Style")
    assert '| `Outline` | \\"outline\\" | Only the outline. |\n| `Filled` | \\"filled\\" | the inside too |' in e


def test_class_constructor_fields_and_methods(lib: str) -> None:
    "A class shows its constructor's parameters and its fields; each method is an entry of its own under it."
    e = entry_of(lib, "Rect")
    assert e.startswith("## class Rect {#Rect}") and "new Rect(corner: Point, size: Size)" in e
    assert "| `corner` | Point | required | the corner |" in e
    assert "| `corner` | Point | Where its corner is. |" in e and "| `size` | Size | how big it is |" in e
    m = entry_of(lib, "Rect.moved")
    assert m.startswith("### Rect.moved {#Rect.moved}")
    assert "| `dy` | number | `0` | up |" in m and "| returns | Rect |  | a new rectangle |" in m
    assert "| returns | number |  | width times height |" in entry_of(lib, "Rect.area")


def test_react_component_shows_its_props(lib: str) -> None:
    "A function with a capital name that takes one props object shows the props' fields as its parameters, with their defaults."
    e = entry_of(lib, "Button")
    assert "function Button(props: ButtonProps): JSX.Element" in e
    assert "| `label` | string | required | the text on it |" in e
    assert "| `disabled` | boolean | `false` | whether it is grey |" in e
    assert "| `onClick` | () =&gt; void | optional | what a click does |" in e


def test_component_props_that_are_not_exported_come_from_the_source(app: dict[str, str]) -> None:
    "TypeDoc leaves out a `Props` the file does not export, so its fields are read from the file, with their strings and JSDoc."
    e = entry_of(app["components/Badge.qmd"], "Badge")
    assert "| `text` | string | required | the words on the badge |" in e
    assert '| `tone` | \\"info\\" \\| \\"warn\\" | `"info"` | How it looks. |' in e
    assert "| `loud` | boolean | `false` |  |" in e
    assert "| `onPick` | (text: string, at: number) =&gt; void | optional |  |" in e  # the comment is on its last line, not its first
    assert "| returns | JSX.Element |  | the HTML of the badge |" in e


def test_default_export_takes_its_name_from_the_source(app: dict[str, str]) -> None:
    "`export default function Badge` is the entry `Badge`, not `default`."
    assert "## Badge {#Badge}" in app["components/Badge.qmd"] and "default" not in app["components/Badge.qmd"].split("---")[2].split("\n## ")[0]


def test_opening_comment_of_a_file_describes_its_module(app: dict[str, str]) -> None:
    "A file's opening comment, before its imports, is its module's description and text, though it has no `@module` tag."
    assert app["components/Badge.qmd"].startswith(TOP + 'title: "Badge"\ndescription: "Badge: a small label with a tone."\n---\n\nPages use it beside a name.\n')


def test_rest_of_the_module_comment_is_dedented_prose(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "The description is the first paragraph; the rest loses its common indentation, so prose is no code block."
    data, project = fixture("lib")
    data["comment"] = {"summary": [{"kind": "text", "text": "First line\nof the first paragraph.\n\n    Indented prose.\n      More of it."}]}
    site(tmp_path, "lib", monkeypatch)
    monkeypatch.setattr(api_ts, "typedoc_json", lambda s: (data, project))
    assert main(["api", "build", "--dir", str(tmp_path)]) == 0
    text = pages(tmp_path)["lib.qmd"]
    assert text.startswith(TOP + 'title: "lib"\ndescription: "First line of the first paragraph."\n---\n\nIndented prose.\nMore of it.\n\n## ')


def test_comment_keeps_lists_and_shows_angle_brackets() -> None:
    "An indented `- item` after prose stays a list; `<Opp>` is escaped outside code, and `<br>` and code spans stay."
    assert api_ts.structure("Phrases:\n    - one\n    - two\n\nMore.") == "Phrases:\n\n- one\n- two\n\nMore."
    assert api_ts.structure("```ts\n  x = 1\n```") == "```ts\n  x = 1\n```"
    assert api.escape_angles("vs <Opp> -> `a<b>` <br> a > b") == "vs &lt;Opp> -> `a<b>` <br> a > b"


def test_generic_interface_hook_and_constant(app: dict[str, str]) -> None:
    "Type parameters show in the signature; a constant shows its type."
    u = app["hooks/useCounter.qmd"]
    assert "interface Counter<T>" in u and "| `last` | T \\| null | the last thing counted |" in u
    assert "function useCounter<T>(start: number = 0, step: number = 1): Counter<T>" in u
    assert "| returns | Counter&lt;T&gt; |  |  |" in u
    assert "```ts\nconst MAX_ITEMS: 50\n```" in app["utils/format.qmd"]


def test_source_links_from_the_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "With `source`, each entry links to its file and line, from the root; without it, there is no link."
    site(tmp_path, "lib", monkeypatch, "  source: https://example.com/lib/blob/main\n")
    assert main(["api", "build", "--dir", str(tmp_path)]) == 0
    e = entry_of(pages(tmp_path)["lib.qmd"], "add")
    assert "[source](https://example.com/lib/blob/main/src/math.ts#L2){.source-link}" in e


def test_source_links_from_a_repository_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "With root the repository and entry `frontend/src`, every entry's link is `source`, the path from the root, and the line."
    repo = tmp_path / "repo"
    shutil.copytree(FIX / "app", repo / "frontend")
    docs = repo / "docs"
    docs.mkdir()
    conf = "project:\n  type: website\napi:\n  language: typescript\n  entry: ../frontend/src\n  root: ..\n  source: https://example.com/r/blob/main\n"
    (docs / "_smalldocs.yml").write_text(conf)
    data = json.loads((FIX / "app.json").read_text())
    monkeypatch.setattr(api_ts, "typedoc_json", lambda s: (data, repo / "frontend"))
    assert main(["api", "build", "--dir", str(docs)]) == 0
    built = pages(docs)
    assert "## Badge {#Badge}\n\n[source](https://example.com/r/blob/main/frontend/src/components/Badge.ts#L18){.source-link}\n" in built["components/Badge.qmd"]
    for text in built.values():
        heads = [ln for ln in text.split("\n---\n", 1)[1].split("\n") if ln.startswith("#")]
        assert text.count("{.source-link}") == len(heads)  # every entry has its link


def test_no_source_link_without_source(lib: str) -> None:
    "Without `source`, no entry has a source link."
    assert "source-link" not in lib


@pytest.mark.parametrize(
    ("t", "text"),
    [
        ({"type": "array", "elementType": {"type": "union", "types": [{"type": "intrinsic", "name": "string"}, {"type": "literal", "value": None}]}}, "(string | null)[]"),
        ({"type": "reference", "name": "Element", "qualifiedName": "JSX.Element", "target": {"packageName": "@types/react"}}, "JSX.Element"),
        ({"type": "reference", "name": "Map", "typeArguments": [{"type": "intrinsic", "name": "string"}, {"type": "literal", "value": 1}]}, "Map<string, 1>"),
        ({"type": "tuple", "elements": [{"type": "namedTupleMember", "name": "x", "isOptional": True, "element": {"type": "intrinsic", "name": "number"}}]}, "[x?: number]"),
        ({"type": "typeOperator", "operator": "keyof", "target": {"type": "reference", "name": "Point"}}, "keyof Point"),
        ({"type": "indexedAccess", "objectType": {"type": "reference", "name": "P"}, "indexType": {"type": "literal", "value": "x"}}, 'P["x"]'),
        ({"type": "templateLiteral", "head": "id-", "tail": [[{"type": "intrinsic", "name": "number"}, ""]]}, "`id-${number}`"),
        ({"type": "reflection", "declaration": {"children": [{"name": "a", "flags": {"isOptional": True}, "type": {"type": "intrinsic", "name": "string"}}]}}, "{ a?: string }"),
    ],
)
def test_types_as_typescript_writes_them(t: dict, text: str) -> None:
    "Each kind of type in TypeDoc's JSON is written as TypeScript writes it."
    assert type_text(t) == text


def test_types_in_tables_are_plain_text_escaped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "A type in a table is plain text, as on the Python pages, with `<`, `>` and `|` escaped, so `Counter<T>` shows as written."
    site(tmp_path, "app", monkeypatch)
    assert main(["render", str(tmp_path), "-q"]) == 0
    html = (tmp_path / "_site/api/hooks/useCounter.html").read_text()
    assert "<td>Counter&lt;T&gt;</td>" in html and "<td>T | null</td>" in html
    assert api.type_cell("A<`*`>") == "A&lt;\\`\\*\\`&gt;"


# ---------------------------------------------------------------- links, the manifest and `out`


def test_symbols_index_links_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "The build writes `_symbols.json`, so a name in backticks on any page links to its entry."
    site(tmp_path, "lib", monkeypatch)
    assert main(["render", str(tmp_path), "-q"]) == 0
    index = json.loads((tmp_path / "_symbols.json").read_text())
    assert index["Rect"] == "/api/lib.qmd#Rect" and index["Rect.moved"] == "/api/lib.qmd#Rect.moved" and index["lib.add"] == "/api/lib.qmd#add"
    assert '<a href="api/lib.html#Rect"><code>Rect</code></a>' in (tmp_path / "_site/index.html").read_text()


def test_build_deletes_only_pages_in_its_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "The API build deletes only pages an earlier build listed in `api/.smalldocs-api`, never a hand-written page."
    site(tmp_path, "app", monkeypatch)
    (tmp_path / "api").mkdir()
    (tmp_path / "api/index.qmd").write_text("# Reference\n")
    (tmp_path / "api/gone.qmd").write_text(TOP + "---\n# Gone\n")
    (tmp_path / "api/old").mkdir()
    (tmp_path / "api/old/gone.qmd").write_text(TOP + "---\n# Gone\n")
    (tmp_path / "api/old/mine.qmd").write_text("# Mine\n")
    (tmp_path / "keep.qmd").write_text("# Keep\n")
    (tmp_path / "api/.smalldocs-api").write_text("gone.qmd\nold/gone.qmd\n../keep.qmd\n/etc/x.qmd\nindex-x.qmd")
    assert main(["api", "build", "--dir", str(tmp_path)]) == 0
    assert (tmp_path / "api/index.qmd").read_text() == "# Reference\n" and not (tmp_path / "api/gone.qmd").exists()
    assert not (tmp_path / "api/old/gone.qmd").exists() and (tmp_path / "api/old/mine.qmd").exists() and (tmp_path / "keep.qmd").exists()
    assert "components/Badge.qmd" in (tmp_path / "api/.smalldocs-api").read_text().split("\n")


def test_stale_page_leaves_no_empty_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "A folder that an earlier build filled, and this one empties, is removed; a folder with a hand-written file stays."
    site(tmp_path, "app", monkeypatch)
    for rel in ["api/gone/a.qmd", "api/held/b.qmd", "api/held/notes.md"]:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(TOP + "---\nx\n")
    (tmp_path / "api/.smalldocs-api").write_text("gone/a.qmd\nheld/b.qmd")
    assert main(["api", "build", "--dir", str(tmp_path)]) == 0
    assert not (tmp_path / "api/gone").exists() and (tmp_path / "api/held/notes.md").exists()


def test_build_never_overwrites_a_hand_written_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    "A folder's hand-written `index.qmd` stays as it is; a hand-written page where a module's page goes stops the build."
    site(tmp_path, "app", monkeypatch)
    (tmp_path / "api/hooks").mkdir(parents=True)
    (tmp_path / "api/hooks/index.qmd").write_text("# My hooks\n")
    assert main(["api", "build", "--dir", str(tmp_path)]) == 0
    assert (tmp_path / "api/hooks/index.qmd").read_text() == "# My hooks\n"
    assert "hooks/index.qmd" not in (tmp_path / "api/.smalldocs-api").read_text().split("\n")
    (tmp_path / "api/hooks/useCounter.qmd").write_text("# Mine\n")
    (tmp_path / "api/.smalldocs-api").write_text("")
    assert main(["api", "build", "--dir", str(tmp_path)]) == 2
    assert "no earlier API build wrote it" in capsys.readouterr().err and (tmp_path / "api/hooks/useCounter.qmd").read_text() == "# Mine\n"


def test_page_paths_stay_inside_out() -> None:
    "A module whose name is no path inside `out` stops the build; `inside` refuses any path that leaves it."
    mods = [api_ts.Module("../x", {}, {}, api_ts.Sources(FIX))]
    with pytest.raises(ValueError, match=r"no path inside api\.out"):
        api_ts.page_paths(mods)
    out = FIX / "app"
    assert api.inside(out, "a/b.qmd") == out / "a/b.qmd"
    assert [api.inside(out, r) for r in ["../b.qmd", "/b.qmd", "a/../b.qmd", "a//b.qmd", "b.md", "a\\b.qmd"]] == [None] * 6


def test_sidebar_shows_names_in_folder_sections(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "With `auto: api/**`, the sidebar has a page per file by its name and a section per folder; as in Quarto, no section for `api` and no `api/index.qmd`."
    site(tmp_path, "app", monkeypatch)
    side_conf = 'website:\n  sidebar:\n    contents:\n      - auto: "api/**"\n'
    conf = (tmp_path / "_smalldocs.yml").read_text().replace("project:\n  type: website\n", "project:\n  type: website\n" + side_conf)
    (tmp_path / "_smalldocs.yml").write_text(conf)
    assert main(["render", str(tmp_path), "-q"]) == 0
    html = (tmp_path / "_site/index.html").read_text()
    side = html[html.index('id="quarto-sidebar"') :]
    side = side[: side.index("</nav>")]
    texts = re.findall(r'<span class="menu-text">([^<]*)</span>', side)
    for name in ["components", "hooks", "utils", "Badge", "Chip", "useCounter", "format"]:
        assert name in texts
    assert texts[0] == "components" and "Reference" not in texts and "Api" not in texts and not [x for x in texts if "/" in x]


@pytest.mark.parametrize("out", [".", "..", "../x"])
def test_out_must_be_inside_the_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, out: str) -> None:
    "`out` that is the site, or outside it, is refused before TypeDoc runs."
    site(tmp_path, "lib", monkeypatch, f'  out: "{out}"\n')
    monkeypatch.setattr(api_ts, "typedoc_json", lambda s: pytest.fail("TypeDoc ran"))
    assert main(["api", "build", "--dir", str(tmp_path)]) == 2


# ---------------------------------------------------------------- check


def test_check_lists_every_gap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    "`check` needs a doc comment on each item, a comment on each parameter, field and prop, and on each return but `void`."
    site(tmp_path, "app", monkeypatch)
    assert main(["api", "check", "--dir", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    for gap in [
        "components/Badge:Badge(loud): no comment",
        "hooks/useCounter:useCounter(step): no comment",
        "hooks/useCounter:useCounter: no return comment",
        "hooks/useCounter: no module comment",
    ]:
        assert gap in out
    assert "components/format:badgeText" not in out and "utils/format:shout" not in out
    assert "6 of 10 functions, classes, interfaces, types and constants are documented" in out


def test_check_void_needs_no_return_comment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    "A `void` function needs no return comment; a parameter with no comment and no `@param` is a gap."
    site(tmp_path, "lib", monkeypatch)
    assert main(["api", "check", "--dir", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "lib:log(message): no comment" in out and "lib:log: no return comment" not in out
    assert "lib:bare: no doc comment" in out and "lib:Rect" not in out and "lib:scale" not in out


def test_check_shown_is_the_same(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    "`--shown` holds what the pages show, which for TypeScript is all that `check` holds: TypeDoc gives only what is exported."
    site(tmp_path, "lib", monkeypatch)
    main(["api", "check", "--dir", str(tmp_path)])
    full = capsys.readouterr().out
    assert main(["api", "check", "--shown", "--dir", str(tmp_path)]) == 1
    assert capsys.readouterr().out == full


# ---------------------------------------------------------------- settings and running TypeDoc


def test_unknown_language_is_an_error(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    "A language that is not python, typescript, rust or openapi stops with a message that names it."
    (tmp_path / "_smalldocs.yml").write_text("project:\n  type: website\napi:\n  language: go\n")
    assert main(["api", "build", "--dir", str(tmp_path)]) == 2
    assert "language must be python, rust, typescript or openapi, not 'go'" in capsys.readouterr().err


def test_typescript_needs_entry_not_packages(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    "TypeScript needs no `packages`, but it needs `entry`."
    (tmp_path / "_smalldocs.yml").write_text("project:\n  type: website\napi:\n  language: typescript\n")
    assert main(["api", "build", "--dir", str(tmp_path)]) == 2
    assert "the api settings need entry" in capsys.readouterr().err


def test_list_and_module_are_for_python(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    "`smalldocs api list` and `module` say they are for Python only."
    site(tmp_path, "lib", monkeypatch)
    assert main(["api", "list", "--dir", str(tmp_path)]) == 2
    assert "for Python only" in capsys.readouterr().err


def test_python_pages_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "A Python site builds as before: `language: python` changes nothing, and the TypeScript code is not imported."
    pkg = tmp_path / "src/tspkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('"A package."\n\n\ndef f(\n    a: int,  # the a\n) -> int:  # the b\n    "Do f."\n    return a\n')
    monkeypatch.delitem(sys.modules, "smalldocs.api_ts")
    out = []
    for extra in ["", "  language: python\n"]:
        d = tmp_path / f"docs{len(out)}"
        d.mkdir()
        (d / "_smalldocs.yml").write_text(f"project:\n  type: website\napi:\n  packages: [tspkg]\n  root: ..\n{extra}")
        assert main(["api", "build", "--dir", str(d)]) == 0
        out.append(((d / "api/tspkg.qmd").read_text(), (d / "_symbols.json").read_text()))
    assert out[0] == out[1] and "| `a` | int | required | the a |" in out[0][0]
    assert "smalldocs.api_ts" not in sys.modules
    monkeypatch.delitem(sys.modules, "tspkg")


def test_settings_read_typescript_keys(tmp_path: Path) -> None:
    "`entry` takes one path or a list; `tsconfig` is a path; both are from the site's folder."
    s = api.Settings.read(tmp_path, {"language": "typescript", "entry": "../src/index.ts", "tsconfig": "../tsconfig.json"})
    assert (s.language, s.entry, s.tsconfig, s.packages) == ("typescript", ("../src/index.ts",), "../tsconfig.json", [])
    assert api.Settings.read(tmp_path, {"language": "typescript", "entry": ["a.ts", "b.ts"]}).entry == ("a.ts", "b.ts")


def test_missing_node_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "Without Node and npx, the build stops with a message that says to install Node."
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ValueError, match="need Node and npx"):
        api_ts.command(tmp_path)


def test_project_typedoc_first_then_npx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "The project's own TypeDoc runs when `node_modules/.bin/typedoc` exists; otherwise TypeDoc 0.28 from npx."
    monkeypatch.setattr(shutil, "which", lambda name: f"/bin/{name}")
    assert api_ts.command(tmp_path) == ["npx", "--yes", "--package", "typedoc@0.28", "typedoc"]
    (tmp_path / "node_modules/.bin").mkdir(parents=True)
    (tmp_path / "node_modules/.bin/typedoc").write_text("")
    assert api_ts.command(tmp_path) == [str(tmp_path / "node_modules/.bin/typedoc")]


def test_typedoc_runs_outside_the_project_with_expand_for_a_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "TypeDoc writes its JSON to a temporary folder, never into the project, and a folder entry runs with `--entryPointStrategy expand`."
    seen = {}

    def fake(args: list[str], **kw: object) -> subprocess.CompletedProcess:
        "Stand in for TypeDoc: note the command, and write empty JSON where it says."
        seen["args"], seen["cwd"] = args, kw["cwd"]
        Path(args[args.index("--json") + 1]).write_text("{}")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(subprocess, "run", fake)
    (tmp_path / "src").mkdir()
    before = sorted(tmp_path.rglob("*"))
    assert api_ts.run_typedoc(tmp_path, [tmp_path / "src"], tmp_path / "tsconfig.json") == {}
    a = seen["args"]
    assert seen["cwd"] == tmp_path and not Path(a[a.index("--json") + 1]).is_relative_to(tmp_path)
    assert a[a.index("--entryPointStrategy") + 1] == "expand" and a[a.index("--tsconfig") + 1] == str(tmp_path / "tsconfig.json")
    assert sorted(tmp_path.rglob("*")) == before


def test_typedoc_failure_shows_its_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "When TypeDoc fails, the build stops and shows the end of what TypeDoc said."
    monkeypatch.setattr(shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(subprocess, "run", lambda args, **kw: subprocess.CompletedProcess(args, 1, "\x1b[91m[error]\x1b[0m src/a.ts:1 bad type\n", ""))
    with pytest.raises(ValueError, match=r"TypeDoc failed in .*\n\[error\] src/a.ts:1 bad type"):
        api_ts.run_typedoc(tmp_path, [tmp_path / "a.ts"])


def test_project_folder_is_the_nearest_with_a_tsconfig(tmp_path: Path) -> None:
    "TypeDoc runs in the tsconfig's folder, or the nearest folder above the entry with a package.json or a tsconfig.json."
    (tmp_path / "web/src").mkdir(parents=True)
    (tmp_path / "web/package.json").write_text("{}")
    s = api.Settings.read(tmp_path / "web", {"language": "typescript", "entry": "src"})
    assert api_ts.project_of(s, [tmp_path / "web/src"]) == tmp_path / "web"
    s.tsconfig = "../tsconfig.json"
    assert api_ts.project_of(s, [tmp_path / "web/src"]) == tmp_path


@pytest.mark.skipif(shutil.which("npx") is None, reason="needs Node and npx")
@pytest.mark.parametrize(("name", "entry"), [("lib", "src/index.ts"), ("app", "src"), ("react", "src")])
def test_real_typedoc_makes_the_same_pages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, entry: str) -> None:
    "Real TypeDoc, run on the fixtures' sources, gives the pages that the stored JSON gives."
    stored = tmp_path / "stored"
    stored.mkdir()
    site(stored, name, monkeypatch)
    assert main(["api", "build", "--dir", str(stored)]) == 0
    monkeypatch.undo()
    live = tmp_path / "live"
    live.mkdir()
    (live / "_smalldocs.yml").write_text(f"project:\n  type: website\napi:\n  language: typescript\n  entry: {FIX / name / entry}\n  root: {FIX / name}\n")
    assert main(["api", "build", "--dir", str(live)]) == 0
    assert pages(live) == pages(stored)


# ---------------------------------------------------------------- findings of the adversarial review


def test_comma_inside_a_generic_ends_no_parameter() -> None:
    "`Record<string, number>` is one parameter's type, so the comments after it stay with their parameters."
    src = "export function f(opts: Record<string, number>,  // A\n  b: Map<string, () => void> = new Map<string, () => void>(),  // B\n): number {  // R\n}\n"
    said = read_signature(split_comments(src), 1, 16)
    assert said.params == ["A", "B"] and said.returns == "R"


def test_strings_in_destructured_defaults() -> None:
    "A comma, a quote or a brace inside a string default does not split the destructured props."
    src = "export function Tag({ text = \"a, b\", end = 'p}q', n = 2 }: P): string {\n}\n"
    assert read_signature(split_comments(src), 1, 16).defaults == {"text": '"a, b"', "end": "'p}q'", "n": "2"}


def test_regular_expression_with_a_quote_hides_no_comment() -> None:
    "A quote or a backtick inside a regular expression starts no string, so the comments after it are read."
    src = 'function f(a = /"/g,  // A\n  b = /`[/]`/,  // B\n  c = x / 2,  // C\n): void {\n}\n'
    assert read_signature(split_comments(src), 1, 9).params == ["A", "B", "C"]


def test_comment_belongs_to_the_last_item_on_its_line_alone() -> None:
    "A comment after two fields on one line, or after the `}` that ends them, is no field's."
    lines = split_comments("interface P { x: number; y: number }  // a point\ninterface Q {\n  z: string;  // the z\n}\n")
    assert api_ts.declared_fields(lines, "P") == [api_ts.Field("x", "number", False, "", shared=True), api_ts.Field("y", "number", False, "", shared=True)]
    assert api_ts.declared_fields(lines, "Q") == [api_ts.Field("z", "string", False, "the z")]


def test_declared_fields_past_generics_with_braces_and_quoted_keys() -> None:
    "A body is found past `extends Base<{ x: 1 }>`; a quoted key is a field; a type that is not an object gives none."
    src = "interface P extends Base<{ x: 1 }> {\n  'd-e': Record<string, number>;  // dashed\n  f?: (a: string, b: number) => void\n}\ntype Q = A & { q: 1 }\n"
    lines = split_comments(src)
    assert api_ts.declared_fields(lines, "P") == [
        api_ts.Field("d-e", "Record<string, number>", False, "dashed"),
        api_ts.Field("f", "(a: string, b: number) => void", True, ""),
    ]
    assert api_ts.declared_fields(lines, "Q") is None


def test_pages_and_ids_never_share_a_name() -> None:
    "Two modules or two entries of one name, such as `b.ts` and `b/index.ts`, or `B` beside `b` on macOS, get `-2`."
    assert api_ts.unique(["b", "B", "b", "c"]) == ["b", "B-2", "b-3", "c"]
    mods = [api_ts.Module(n, {}, {}, api_ts.Sources(FIX)) for n in ["b", "b", "x/y"]]  # `b.ts`, and `b/index.ts` as `modules` names it
    assert api_ts.page_paths(mods) == ["b", "b-2", "x/y"]


def test_static_method_has_its_own_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "A static method and an instance method of one name are two entries with two ids, and `static` in the heading."
    data, project = fixture("lib")
    rect = next(c for c in data["children"] if c["name"] == "Rect")
    area = next(c for c in rect["children"] if c["name"] == "area")
    rect["children"].append({**area, "id": 9999, "flags": {"isStatic": True}})
    site(tmp_path, "lib", monkeypatch)
    monkeypatch.setattr(api_ts, "typedoc_json", lambda s: (data, project))
    assert main(["api", "build", "--dir", str(tmp_path)]) == 0
    text = pages(tmp_path)["lib.qmd"]
    assert "### Rect.area {#Rect.area}" in text and "### static Rect.area {#Rect.area-2}" in text
    assert json.loads((tmp_path / "_symbols.json").read_text())["Rect.area-2"] == "/api/lib.qmd#Rect.area-2"


# ---------------------------------------------------------------- Rahul's decisions on the open points


def test_component_needs_no_return_comment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    "A React component needs no comment on its return; a function that returns no JSX, or has a small name, still does."
    site(tmp_path, "app", monkeypatch)
    assert main(["api", "check", "--dir", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "components/Chip:Chip" not in out
    assert "components/Chip:Divider: no return comment" in out and "components/Chip:chips: no return comment" in out
    assert main(["api", "build", "--dir", str(tmp_path)]) == 0
    assert "| returns | JSX.Element |  |  |" in entry_of(pages(tmp_path)["components/Chip.qmd"], "Chip")  # the page still shows the return


def test_typescript_links_any_name_in_the_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "On a TypeScript site, a name in backticks that is a key of `_symbols.json` links, though it looks like no code, as `useCounter`."
    site(tmp_path, "app", monkeypatch)
    (tmp_path / "index.qmd").write_text("# Home\n\nSee `useCounter`, `shout` and `nothing`.\n")
    assert main(["render", str(tmp_path), "-q"]) == 0
    html = (tmp_path / "_site/index.html").read_text()
    assert '<a href="api/hooks/useCounter.html#useCounter"><code>useCounter</code></a>' in html
    assert '<a href="api/utils/format.html#shout"><code>shout</code></a>' in html and "<code>nothing</code>" in html


def test_python_sites_link_names_as_before(tmp_path: Path) -> None:
    "On a Python site, a plain word such as `f` still does not link, and `language: python` changes no byte of the page."
    pkg = tmp_path / "src/lnkpkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('"A package."\n\n\ndef f(\n    a: int,  # the a\n) -> int:  # the b\n    "Do f."\n    return a\n')
    html = []
    for extra in ["", "  language: python\n"]:
        d = tmp_path / f"docs{len(html)}"
        d.mkdir()
        (d / "_smalldocs.yml").write_text(f"project:\n  type: website\napi:\n  packages: [lnkpkg]\n  root: ..\n{extra}")
        (d / "index.qmd").write_text("# Home\n\nSee `f` and `f()`.\n")
        assert main(["render", str(d), "-q"]) == 0
        html.append((d / "_site/index.html").read_text())
        sys.modules.pop("lnkpkg", None)
    assert html[0] == html[1]
    assert '<code>f</code> and <a href="api/lnkpkg.html#f"><code>f()</code></a>' in html[0]


# ---------------------------------------------------------------- findings of the second adversarial review


def test_stale_entry_in_another_case_keeps_the_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "A manifest entry that differs from a written page only by case is that page on macOS, so it is not deleted."
    site(tmp_path, "app", monkeypatch)
    assert main(["api", "build", "--dir", str(tmp_path)]) == 0
    m = tmp_path / "api/.smalldocs-api"
    m.write_text(m.read_text().replace("components/Badge.qmd", "Components/Badge.qmd"))
    assert main(["api", "build", "--dir", str(tmp_path)]) == 0
    assert (tmp_path / "api/components/Badge.qmd").exists()


def test_index_in_any_case_and_folders_in_one_spelling() -> None:
    "A module `Index` never takes a folder's `index.qmd`; `A/x` and `a/y` share the folder spelt first."
    mods = [api_ts.Module(n, {}, {}, api_ts.Sources(FIX)) for n in ["Index", "c/INDEX", "A/x", "a/y"]]
    assert api_ts.page_paths(mods) == ["Index-module", "c/INDEX-module", "A/x", "A/y"]


def test_prose_keeps_quotes_autolinks_comments_and_links() -> None:
    "`escape_angles` keeps a `>` quote, `<https://x>`, `<!-- c -->` and `<a href>`; a bare `<a>` in a sentence is text."
    assert api.escape_angles("> Note\nsee <https://x.org> <!-- c --> <a href='u'>u</a>") == "> Note\nsee <https://x.org> <!-- c --> <a href='u'>u</a>"
    assert api.escape_angles("the <a> element") == "the &lt;a> element"


def test_structure_keeps_nesting_tight_lists_and_fences() -> None:
    "Nested items keep their nesting, a wrapped item stays tight, `2024. was` stays prose, and an indented fence moves as one."
    src = "Steps:\n  - one\n    goes on\n  - two\n    - two a\n\nIn\n2024. was a year.\n  ```ts\n    x = 1\n  ```"
    assert api_ts.structure(src) == "Steps:\n\n- one\n  goes on\n- two\n  - two a\n\nIn\n2024. was a year.\n```ts\n  x = 1\n```"


def test_type_cell_escapes_maths_and_links() -> None:
    "A template-literal type is no maths, and `_`, `[`, `]` and `&` are escaped too."
    assert api.type_cell("`${A}-${B}`") == "\\`\\${A}-\\${B}\\`"
    assert api.type_cell("[a_b] & c") == "\\[a\\_b\\] &amp; c"


def test_stopped_build_keeps_its_pages_in_the_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "A build that stops part way, here at a page it cannot write, lists the pages it wrote, so the next build may write them again."
    site(tmp_path, "app", monkeypatch)
    write = Path.write_text

    def fail(self: Path, text: str, **kw: object) -> int:
        "Write as usual, except `utils/format.qmd`, which fails as a full disk would."
        if self.as_posix().endswith("api/utils/format.qmd"):
            raise OSError("no space left")
        return write(self, text, **kw)

    monkeypatch.setattr(Path, "write_text", fail)
    assert main(["api", "build", "--dir", str(tmp_path)]) != 0
    listed = set((tmp_path / "api/.smalldocs-api").read_text().split("\n"))
    assert "components/Badge.qmd" in listed and "utils/format.qmd" not in listed
    monkeypatch.setattr(Path, "write_text", write)
    assert main(["api", "build", "--dir", str(tmp_path)]) == 0


def test_hand_written_page_stops_the_build_before_it_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    "A hand-written page where a module's page goes stops the build before it writes any page, and the page stays."
    site(tmp_path, "app", monkeypatch)
    (tmp_path / "api/utils").mkdir(parents=True)
    (tmp_path / "api/utils/format.qmd").write_text("# Mine\n")
    assert main(["api", "build", "--dir", str(tmp_path)]) == 2
    assert "no earlier API build wrote it" in capsys.readouterr().err
    assert [p.relative_to(tmp_path / "api").as_posix() for p in (tmp_path / "api").rglob("*")] == ["utils", "utils/format.qmd"]


def test_hand_written_index_of_a_module_folder_is_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "A hand-written `components/index.qmd` stays; the page of `components/index.ts` then sits beside it as `components/components.qmd`, as on a Rust site."
    site(tmp_path, "app", monkeypatch)
    (tmp_path / "api/components").mkdir(parents=True)
    (tmp_path / "api/components/index.qmd").write_text("# Mine\n")
    assert main(["api", "build", "--dir", str(tmp_path)]) == 0
    p = pages(tmp_path)
    assert p["components/index.qmd"] == "# Mine\n" and "It exports again `Badge`" in p["components/components.qmd"]
    assert "| [`components`](/api/components/index.qmd) |" in p["index.qmd"]


# ---------------------------------------------------------------- findings of the review of the merged Rust and TypeScript pages


def test_emoji_in_a_summary_renders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "An emoji in a module's comment is one character in the front matter, so the site renders; JSON's surrogate pair broke PyYAML."
    data, project = fixture("lib")
    data["comment"] = {"summary": [{"kind": "text", "text": "Shapes 🦀 and sums, with Vec<T>. "}]}
    site(tmp_path, "lib", monkeypatch)
    monkeypatch.setattr(api_ts, "typedoc_json", lambda s: (data, project))
    assert main(["render", str(tmp_path), "-q"]) == 0
    assert 'description: "Shapes 🦀 and sums, with Vec<T>."' in pages(tmp_path)["lib.qmd"] and api.yaml_text("a\u2028b") == '"a\\u2028b"'
    assert '<meta name="description" content="Shapes 🦀 and sums, with Vec&lt;T&gt;.' in (tmp_path / "_site/api/lib.html").read_text()


def test_page_renamed_only_in_case_takes_its_new_spelling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "A module renamed only in case, `Chip` to `chip`, or a folder `hooks` to `Hooks`, is written in its new spelling, and the old page is gone, on any disk."
    site(tmp_path, "app", monkeypatch)
    assert main(["api", "build", "--dir", str(tmp_path)]) == 0
    data, project = fixture("app")
    text = json.dumps(data).replace('"src/components/Chip"', '"src/components/chip"').replace('"src/hooks/useCounter"', '"src/Hooks/useCounter"')
    monkeypatch.setattr(api_ts, "typedoc_json", lambda s: (json.loads(text), project))
    assert main(["api", "build", "--dir", str(tmp_path)]) == 0
    names = {p.relative_to(tmp_path / "api").as_posix() for p in (tmp_path / "api").rglob("*.qmd")}
    assert {"components/chip.qmd", "Hooks/useCounter.qmd", "Hooks/index.qmd"} <= names
    assert not {"components/Chip.qmd", "hooks/useCounter.qmd", "hooks/index.qmd"} & names


@pytest.mark.parametrize("rel", ["utils/format.md", "utils/format.ipynb", "index.md"])
def test_hand_written_md_or_notebook_counts_as_a_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rel: str) -> None:
    "A hand-written `.md` or `.ipynb` is a page as a `.qmd` is: a module's page there stops the build, and a folder's index there is not written."
    site(tmp_path, "app", monkeypatch)
    (tmp_path / "api" / rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "api" / rel).write_text("# Mine\n")
    code = main(["api", "build", "--dir", str(tmp_path)])
    if rel == "index.md":
        assert code == 0 and not (tmp_path / "api/index.qmd").exists()
    else:
        assert code == 2 and not (tmp_path / "api/utils/format.qmd").exists()
    assert (tmp_path / "api" / rel).read_text() == "# Mine\n"


def test_escape_angles_leaves_fenced_code_with_a_blank_line() -> None:
    "A fenced code block that holds a blank line is code, so its `<` stays; the prose around it is escaped."
    text = "Use Map<K>.\n\n```ts\nconst m = new Map<string, number>()\n\nm.set('a', 1)\n```\n\nThen Set<T>.\n~~~\na<b\n~~~"
    want = "Use Map&lt;K>.\n\n```ts\nconst m = new Map<string, number>()\n\nm.set('a', 1)\n```\n\nThen Set&lt;T>.\n~~~\na<b\n~~~"
    assert api.escape_angles(text) == want


def test_edited_page_is_never_written_over(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    "A page that a build wrote and someone then edited, so it has lost the mark, stops the next build, though the manifest lists it."
    site(tmp_path, "app", monkeypatch)
    assert main(["api", "build", "--dir", str(tmp_path)]) == 0
    (tmp_path / "api/utils/format.qmd").write_text("---\ntitle: My notes\n---\n")
    assert main(["api", "build", "--dir", str(tmp_path)]) == 2
    assert "has no mark" in capsys.readouterr().err and (tmp_path / "api/utils/format.qmd").read_text() == "---\ntitle: My notes\n---\n"


def test_type_cells_keep_quotes_tildes_and_carets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "A string-literal type keeps straight quotes, and `~` and `^` are no subscript or superscript."
    assert api.type_cell("\"a\" | 'b' ~T~ x^2^") == "\\\"a\\\" | \\'b\\' \\~T\\~ x\\^2\\^"
    site(tmp_path, "app", monkeypatch)
    assert main(["render", str(tmp_path), "-q"]) == 0
    assert "<td>&quot;info&quot; | &quot;warn&quot;</td>" in (tmp_path / "_site/api/components/Badge.html").read_text()


# ---------------------------------------------------------------- headings and file names that Markdown or a link would misread


def test_heading_text_is_escaped_and_its_id_is_not(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "A name such as `__x__`, or `$b` in the namespace `$a`, shows as it is: no bold, no maths; the heading's id is the name."
    data, project = fixture("lib")
    add = next(c for c in data["children"] if c["name"] == "add")
    data["children"] += [{**add, "id": 9001, "name": "__x__"}, {"id": 9002, "kind": api_ts.NAMESPACE, "name": "$a", "children": [{**add, "id": 9003, "name": "$b"}]}]
    site(tmp_path, "lib", monkeypatch)
    monkeypatch.setattr(api_ts, "typedoc_json", lambda s: (data, project))
    assert main(["render", str(tmp_path), "-q", "--strict"]) == 0
    text = pages(tmp_path)["lib.qmd"]
    assert "## \\_\\_x\\_\\_ {#__x__}" in text and "## namespace \\$a {#$a}" in text and "### \\$a.\\$b {#$a.$b}" in text
    html = (tmp_path / "_site/api/lib.html").read_text()
    assert '<h2 class="anchored" data-anchor-id="__x__">__x__</h2>' in html
    assert '<h3 class="anchored" data-anchor-id="$a.$b">$a.$b</h3>' in html and "math inline" not in html


def test_heading_text_escapes_every_sign() -> None:
    "Each sign that Markdown, maths or HTML reads is escaped; a `_` inside a word, as in `in_a`, needs nothing."
    assert api.heading_text("in_a") == "in_a" and api.heading_text("a-b.c") == "a-b.c"
    assert api.heading_text("a--b...c") == "a\\-\\-b\\.\\.\\.c"
    env: dict = {}
    assert ">a--b...c $x$ __y__</h2>" in render(f"## {api.heading_text('a--b...c $x$ __y__')} {{#q}}", env) and env["headings"][0]["text"] == "a--b...c $x$ __y__"
    assert api.heading_text("_a __b__ $c$ *d* `e` <f> &g [h] {i} #j ~k~ ^l^ 'm' \"n\" @o") == (
        "\\_a \\_\\_b\\_\\_ \\$c\\$ \\*d\\* \\`e\\` \\<f\\> \\&g \\[h\\] \\{i\\} \\#j \\~k\\~ \\^l\\^ \\'m\\' \\\"n\\\" \\@o"
    )


def test_title_of_a_file_is_escaped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "A page's title is Markdown, so a file `$x$.ts` gives the title `$x$`, not the maths `x`."
    data, project = fixture("app")
    next(m for m in data["children"] if m["name"] == "src/utils/format")["name"] = "src/utils/$x$"
    site(tmp_path, "app", monkeypatch)
    monkeypatch.setattr(api_ts, "typedoc_json", lambda s: (data, project))
    assert main(["render", str(tmp_path), "-q", "--strict"]) == 0
    assert pages(tmp_path)["utils/$x$.qmd"].startswith(TOP + 'title: "\\\\$x\\\\$"\n')
    html = (tmp_path / "_site/api/utils/$x$.html").read_text()
    assert '<h1 class="title">$x$</h1>' in html and "<title>$x$" in html and "math inline" not in html


@pytest.mark.parametrize("name, quoted", [("a#b", "a%23b"), ("a?b", "a%3Fb"), ("a%41b", "a%2541b"), ("a b", "a%20b")])
def test_file_names_with_hash_query_or_percent_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, quoted: str) -> None:
    "A file `a#b.ts` gives the page `a#b.qmd`; each link to it, from its folder's index, `_symbols.json`, a name in backticks and `source`, finds it."
    data, project = fixture("app")
    mod = next(m for m in data["children"] if m["name"] == "src/utils/format")
    mod["name"] = f"src/utils/{name}"
    for c in mod["children"]:
        c["sources"][0]["fileName"] = f"src/utils/{name}.ts"
    site(tmp_path, "app", monkeypatch, "  source: https://example.com/app/blob/main\n")
    monkeypatch.setattr(api_ts, "typedoc_json", lambda s: (data, project))
    (tmp_path / "index.qmd").write_text("# Home\n\nSee `shout`.\n")
    assert main(["render", str(tmp_path), "-q", "--strict"]) == 0
    p = pages(tmp_path)
    assert p[f"utils/{name}.qmd"].startswith(TOP + f"title: {api.yaml_text(api.heading_text(name))}\n")
    assert f"| [`{name}`](/api/utils/{quoted}.qmd) |" in p["utils/index.qmd"]
    assert f"[source](https://example.com/app/blob/main/src/utils/{quoted}.ts#L" in p[f"utils/{name}.qmd"]
    assert json.loads((tmp_path / "_symbols.json").read_text())["shout"] == f"/api/utils/{quoted}.qmd#shout"
    assert f'<a href="api/utils/{quoted}.html#shout"><code>shout</code></a>' in (tmp_path / "_site/index.html").read_text()
    assert f'href="{quoted}.html"' in (tmp_path / "_site/api/utils/index.html").read_text()
    assert (tmp_path / f"_site/api/utils/{name}.html").exists()


def test_link_path_keeps_what_quarto_reads() -> None:
    "`+page`, `@scope` and `$lib` stay as they are, because Quarto does not decode them; `&` is encoded, so `a&amp;b` is no entity."
    assert api.link_path("/api/@s/+page/$lib.qmd") == "/api/@s/+page/$lib.qmd"
    assert api.link_path("/api/a&amp;b #?%.qmd") == "/api/a%26amp;b%20%23%3F%25.qmd"


# ---------------------------------------------------------------- what cricsdb showed


@pytest.fixture
def react(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:  # The pages of the React fixture
    "Build the React fixture, whose entry is a folder, and give its pages."
    site(tmp_path, "react", monkeypatch)
    assert main(["api", "build", "--dir", str(tmp_path)]) == 0
    return pages(tmp_path)


def react_check(
    tmp: Path,  # A folder for the site
    monkeypatch: pytest.MonkeyPatch,  # To give the fixture's JSON
    capsys: pytest.CaptureFixture,  # To read what `check` prints
) -> str:  # What `api check` prints for the React fixture
    "Run `api check` on the React fixture."
    site(tmp, "react", monkeypatch)
    assert main(["api", "check", "--dir", str(tmp)]) == 1
    return capsys.readouterr().out


def test_opening_comment_is_the_module_s_when_no_declaration_takes_it(react: dict[str, str]) -> None:
    "A file's opening comment is the module's when another doc comment follows it, even with no import; one right before a declaration is that declaration's, as in TypeDoc."
    assert 'description: "Panels: boxes that hold other parts. No import follows this comment."' in react["Panel.qmd"]
    assert 'description: ""' in react["hooks.qmd"] and "Keep a value, and give a setter." in entry_of(react["hooks.qmd"], "useValue")
    assert api_ts.header_comment("/** The file. */\n\n// a note\n/** The first. */\nexport const a = 1;\n").strip() == "The file."
    assert api_ts.header_comment("/** The first. */\nexport const a = 1;\n") == ""


def test_component_with_no_props_needs_no_return_comment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    "A capital-named function that returns JSX and takes no parameter is a component, so it needs no return comment; one that takes a string is no component."
    out = react_check(tmp_path, monkeypatch, capsys)
    assert "Panel:Frame" not in out
    assert "Panel:Title: no return comment" in out


def test_is_jsx_knows_what_react_draws() -> None:
    "`JSX.Element`, `React.ReactNode`, `ReactElement` and the like are JSX, alone or with `null`, `undefined` or `false`; a string is not."
    ref = lambda q: {"type": "reference", "name": q.rpartition(".")[2], "qualifiedName": q}  # noqa: E731
    assert api_ts.is_jsx(ref("JSX.Element")) and api_ts.is_jsx(ref("React.JSX.Element")) and api_ts.is_jsx(ref("React.ReactNode"))
    assert api_ts.is_jsx({"type": "union", "types": [ref("ReactElement"), {"type": "literal", "value": None}, {"type": "intrinsic", "name": "undefined"}]})
    assert not api_ts.is_jsx({"type": "intrinsic", "name": "string"}) and not api_ts.is_jsx(ref("Element"))
    assert not api_ts.is_jsx({"type": "union", "types": [{"type": "literal", "value": None}]})
    assert not api_ts.is_jsx({"type": "union", "types": [ref("JSX.Element"), {"type": "intrinsic", "name": "string"}]})


def test_return_comment_after_a_return_type_on_several_lines(react: dict[str, str]) -> None:
    "The comment on the `{` after a return type on several lines documents the return; a comment inside the type does not."
    p = react["hooks.qmd"]
    assert "| returns | (v: string) =&gt; void |  | the setter |" in entry_of(p, "useValue")
    assert "| returns | { x: number } |  | the point |" in entry_of(p, "point")
    assert "| returns | \\[number, number\\] |  | the pair |" in entry_of(p, "pair")
    src = "function f(a: string, // the a\n): (\n  v: string, // the v\n) => void { // the setter\n}\n"
    assert read_signature(split_comments(src), 1, 9).returns == "the setter"
    src = "function f(a: string, // the a\n): { x: number } | null\n{ // the box\n}\n"
    assert read_signature(split_comments(src), 1, 9).returns == "the box"


def test_intersection_props_are_a_component_s_props(react: dict[str, str]) -> None:
    "Props written `PanelProps & { footer?: string }` are the fields of each part, with their comments and defaults."
    e = entry_of(react["Panel.qmd"], "FooterPanel")
    assert "| `title` | string | required | the words at the top |" in e
    assert "| `wide` | boolean | `false` | whether it fills the row |" in e
    assert "| `footer` | string | optional | the words at the bottom |" in e


def test_param_tags_document_inline_props(react: dict[str, str]) -> None:
    "Props on one line take their words from JSDoc's `@param text` or `@param props.color`; the parameter stays `props`, though TypeDoc names it after the first `@param`."
    e = entry_of(react["Panel.qmd"], "Tag")
    assert "function Tag(props: { text: string; color: string }): JSX.Element" in e
    assert "| `text` | string | required | the words on the tag |" in e and "| `color` | string | required | its colour |" in e
    lines = split_comments("/**\n * Do it.\n * @param {string} a - the a,\n *   on two lines\n * @param [p.b=1] the b\n * @returns x\n */\nexport function f() {}\n")
    assert api_ts.param_tags(lines, 8) == {"a": "the a, on two lines", "p.b": "the b", ".b": "the b"}
    assert api_ts.param_tags(lines, 1) == {}


def test_comment_shared_by_several_fields_is_reported_clearly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    "A comment after two fields on one line is neither's, and `check` says why, and what to do."
    out = react_check(tmp_path, monkeypatch, capsys)
    said = "no comment: the comment on its line follows more than this field, so it is no field's; put each field on its own line, or give each a JSDoc"
    assert f"Panel:Box.width: {said}" in out and f"Panel:Box.height: {said}" in out


def test_undocumented_props_field_is_reported_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    "A field of an exported props type is reported at the type's entry, `Box.width`, and not again at each component, `BoxView(width)`."
    out = react_check(tmp_path, monkeypatch, capsys)
    assert "Panel:Box.width" in out and "BoxView" not in out


# ---------------------------------------------------------------- findings of the adversarial review of these fixes


def test_opening_comment_never_takes_code() -> None:
    "The module comment ends at its own `*/`; a later doc comment never pulls code into it."
    assert api_ts.header_comment('/** f doc */\nexport function f() {}\n/** g doc */\n/** h doc */\nexport function h() {}\n') == ""
    assert api_ts.header_comment("/** f doc */\nexport function f() {}\n/** trailing */\n") == ""
    assert api_ts.header_comment('/** Mod doc. */\n/* eslint-disable */\nimport x from "y";\n').strip() == "Mod doc."


def test_opening_comment_past_directives_licences_and_marks() -> None:
    "A licence, a `#!` line or a byte-order mark before the comment, and a directive or a type re-export after it, leave it the module's."
    for text in [
        '/** Mod doc. */\n"use client";\nimport x from "y";\n',
        '/* MIT license */\n/** Mod doc. */\nimport x from "y";\n',
        '// Copyright\n/** Mod doc. */\nimport x from "y";\n',
        '/** Mod doc. */\nexport type { A } from "./a";\n',
        '﻿/** Mod doc. */\nimport x from "y";\n',
        '#!/usr/bin/env node\n/** Mod doc. */\nimport x from "y";\n',
    ]:
        assert api_ts.header_comment(text).strip() == "Mod doc.", text


def test_param_tags_past_blank_and_comment_lines_and_odd_names() -> None:
    "TypeDoc reads a doc comment past a blank line or a `//` line, so the `@param` tags are read there too; a default with a space and a type with braces are read."
    src = "/**\n * A card.\n * @param props.title the title\n * @param {string} [props.g=\"x y\"] - the g\n * @param {{x: number}} f the f\n */\n\n// eslint-disable-next-line\nexport function Card() {}\n"
    tags = api_ts.param_tags(split_comments(src), 9)
    assert tags[".title"] == "the title" and tags["props.g"] == "the g" and tags["f"] == "the f"


def test_destructured_parameter_of_a_plain_function_keeps_its_param_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "A function that is no component keeps TypeDoc's reading of its destructured parameter, with the text of its `@param`."
    data, root = fixture("react")
    tag = next(c for m in data["children"] for c in m.get("children", []) if c["name"] == "Tag")
    sig = tag["signatures"][0]
    plain = sig | {"name": "tag", "type": {"type": "intrinsic", "name": "string"}}
    mod = api_ts.Module("Panel", {}, {}, api_ts.Sources(root))
    rows, gaps = mod.param_rows("tag", plain)
    assert rows[0][0] == "`text`" and rows[0][3] == "the words on the tag" and gaps == [": no return comment"]


def test_component_props_that_smalldocs_cannot_read_need_no_return_comment() -> None:
    "A capital-named function that returns JSX and takes one object it cannot read, such as a node_modules type, is still a component; one that takes a string is not."
    jsx = {"type": "reference", "name": "Element", "qualifiedName": "JSX.Element"}
    other = {"parameters": [{"name": "p", "type": {"type": "reference", "name": "HTMLAttributes", "target": {"packagePath": "node_modules/x.d.ts"}}}], "type": jsx}
    assert api_ts.component("Ext", other)
    assert not api_ts.component("Title", {"parameters": [{"name": "t", "type": {"type": "intrinsic", "name": "string"}}], "type": jsx})
    assert not api_ts.component("ext", other) and api_ts.component("Frame", {"type": jsx})
    assert not api_ts.is_jsx({"type": "union", "types": [jsx, {"type": "literal", "value": 0}]})  # `0` is drawn, so it is no `null`


def test_comment_after_the_closing_brace_says_so() -> None:
    "A comment after one field and the `}` that closes it is no field's, and the reason does not speak of other fields."
    lines = split_comments("interface One { a: string }  // the a\n")
    (f,) = api_ts.declared_fields(lines, "One")
    assert f.shared and api_ts.gap(f).startswith("no comment: the comment on its line follows more than this field")


def test_opening_comment_reads_banners_of_slashes_at_once() -> None:
    "A banner of slashes, or lines of `// a // b`, before a declaration takes no time; the pattern never backtracks."
    import time

    start = time.monotonic()
    assert api_ts.header_comment("/" * 60 + "\nexport const x = 1;\n") == ""
    assert api_ts.header_comment("// a // b // c\n" * 2000 + "export const x=1;\n") == ""
    assert api_ts.header_comment("// " * 18 + "\nexport const x=1;\n") == ""
    assert time.monotonic() - start < 2


def test_empty_block_comment_is_no_doc_comment() -> None:
    "`/**/` is an empty comment, so the doc comment after it is the module's."
    assert api_ts.header_comment('/**/\n/** Mod */\nimport x from "y";\n').strip() == "Mod"


def test_param_tags_past_a_plain_block_comment() -> None:
    "A `/* */` comment between the doc comment and the declaration is skipped, as TypeDoc skips it."
    src = "/**\n * Doc.\n * @param a the a\n */\n/* not doc */\nexport function F({ a }: P) {}\n"
    assert api_ts.param_tags(split_comments(src), 6) == {"a": "the a"}
    assert api_ts.param_tags(split_comments("/* plain */\nexport function F() {}\n"), 2) == {}


def test_a_union_of_primitives_is_no_props_object() -> None:
    "`text: string | number` is no props object, so the function is no component."
    jsx = {"type": "reference", "name": "Element", "qualifiedName": "JSX.Element"}
    union = {"type": "union", "types": [{"type": "intrinsic", "name": "string"}, {"type": "intrinsic", "name": "number"}]}
    assert not api_ts.component("Label", {"parameters": [{"name": "text", "type": union}], "type": jsx})
