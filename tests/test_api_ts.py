"The API reference of a TypeScript package, from TypeDoc's JSON: one test per rule of SPEC-rust-typescript.md."

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from smalldocs import api, api_ts
from smalldocs.api_ts import read_signature, split_comments, type_text
from smalldocs.cli import main

FIX = Path(__file__).parent / "fixtures" / "ts"


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
    return {p.name: p.read_text(encoding="utf-8") for p in sorted((tmp / "api").glob("*.qmd"))}


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
    assert "| `a` | `number` | required | the first number |" in e
    assert "| `b` | `number` | `1` | the second number |" in e
    assert "| returns | `number` |  | the sum |" in e


def test_param_and_returns_tags_when_there_is_no_comment(lib: str) -> None:
    "Without a comment after it, a parameter takes its `@param`, and the return its `@returns`."
    e = entry_of(lib, "scale")
    assert "| `x` | `number` | required | the number to scale |" in e
    assert "| `by` | `number` | `2` | how much to scale it |" in e
    assert "| returns | `number` |  | the scaled number |" in e
    assert "@param" not in e


def test_arrow_function_constant_reads_its_comments(lib: str) -> None:
    "An arrow function in a constant is a function, with its comments read the same way; an optional parameter says so."
    e = entry_of(lib, "twice")
    assert "function twice(n: number, label?: string): string" in e
    assert "| `label` | `string` | optional | what goes before it |" in e
    assert "| returns | `string` |  | the text |" in e


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
    assert "| `x` | `number` | required |  |" in e and "| returns | `number` |  |  |" in e


# ---------------------------------------------------------------- the pages


def test_one_page_per_entry_point_holds_what_it_exports_again(lib: str, tmp_path: Path) -> None:
    "One entry point is one page, named after the project, with every item that `export *` brings in."
    assert list(pages(tmp_path)) == ["lib.qmd"]
    assert lib.startswith('---\ntitle: "lib"\ndescription: "A small library of shapes and sums."\n---\n')
    for name in ["add", "Rect", "Point", "Button", "ButtonProps", "Style", "Size", "Colour"]:
        assert f"{{#{name}}}" in lib


def test_one_page_per_file_when_entry_is_a_folder(app: dict[str, str]) -> None:
    "A folder as entry makes a page per file, named from the folder they share; two files of one name keep their paths."
    assert set(app) == {"Badge.qmd", "Chip.qmd", "components-format.qmd", "components.qmd", "useCounter.qmd", "utils-format.qmd"}
    assert app["Badge.qmd"].startswith('---\ntitle: "components/Badge"\n')
    assert app["utils-format.qmd"].startswith('---\ntitle: "utils/format"\n')


def test_an_index_file_is_named_by_its_folder_and_never_index(app: dict[str, str]) -> None:
    "`components/index.ts` is the page `components`; no page is `index.qmd`, which is the reference's front page."
    assert "index.qmd" not in app
    assert app["components.qmd"].startswith('---\ntitle: "components"\ndescription: "The components, in one place."\n')


def test_reexports_have_one_entry_where_they_are_declared(app: dict[str, str]) -> None:
    "An item that an index exports again has its entry on its own file's page; the index names it."
    assert "{#Badge}" in app["Badge.qmd"] and "{#Badge}" not in app["components.qmd"]
    assert "It exports again `Badge`, `badgeText`, from the modules that declare them." in app["components.qmd"]


def test_interface_fields_with_the_comment_after_each(lib: str) -> None:
    "An interface shows its fields as a table, each with the comment after it; an optional field is marked."
    e = entry_of(lib, "Point")
    assert e.startswith("## interface Point {#Point}")
    assert "| `x` | `number` | the distance across |" in e and "| `label`? | `string` | a name to show beside it |" in e


def test_type_aliases_with_and_without_fields(lib: str) -> None:
    "An object type shows its fields; any other type shows what it stands for."
    assert "| `width` | `number` | across |" in entry_of(lib, "Size")
    assert '```ts\ntype Colour = "red" | "green" | "blue"\n```' in entry_of(lib, "Colour")


def test_enum_members_with_values_and_comments(lib: str) -> None:
    "An enum shows its members in source order, with their values, and the comment after each or its JSDoc."
    e = entry_of(lib, "Style")
    assert '| `Outline` | `"outline"` | Only the outline. |\n| `Filled` | `"filled"` | the inside too |' in e


def test_class_constructor_fields_and_methods(lib: str) -> None:
    "A class shows its constructor's parameters and its fields; each method is an entry of its own under it."
    e = entry_of(lib, "Rect")
    assert e.startswith("## class Rect {#Rect}") and "new Rect(corner: Point, size: Size)" in e
    assert "| `corner` | `Point` | required | the corner |" in e
    assert "| `corner` | `Point` | Where its corner is. |" in e and "| `size` | `Size` | how big it is |" in e
    m = entry_of(lib, "Rect.moved")
    assert m.startswith("### Rect.moved {#Rect.moved}")
    assert "| `dy` | `number` | `0` | up |" in m and "| returns | `Rect` |  | a new rectangle |" in m
    assert "| returns | `number` |  | width times height |" in entry_of(lib, "Rect.area")


def test_react_component_shows_its_props(lib: str) -> None:
    "A function with a capital name that takes one props object shows the props' fields as its parameters, with their defaults."
    e = entry_of(lib, "Button")
    assert "function Button(props: ButtonProps): string" in e
    assert "| `label` | `string` | required | the text on it |" in e
    assert "| `disabled` | `boolean` | `false` | whether it is grey |" in e
    assert "| `onClick` | `() => void` | optional | what a click does |" in e


def test_component_props_that_are_not_exported_come_from_the_source(app: dict[str, str]) -> None:
    "TypeDoc leaves out a `Props` the file does not export, so its fields are read from the file, with their strings and JSDoc."
    e = entry_of(app["Badge.qmd"], "Badge")
    assert "| `text` | `string` | required | the words on the badge |" in e
    assert '| `tone` | `"info" \\| "warn"` | `"info"` | How it looks. |' in e
    assert "| `loud` | `boolean` | `false` |  |" in e
    assert "| `onPick` | `(text: string, at: number) => void` | optional |  |" in e  # the comment is on its last line, not its first
    assert "| returns | `string` |  | the HTML of the badge |" in e


def test_default_export_takes_its_name_from_the_source(app: dict[str, str]) -> None:
    "`export default function Badge` is the entry `Badge`, not `default`."
    assert "## Badge {#Badge}" in app["Badge.qmd"] and "default" not in app["Badge.qmd"].split("---")[2].split("\n## ")[0]


def test_opening_comment_of_a_file_describes_its_module(app: dict[str, str]) -> None:
    "A file's opening comment, before its imports, is its module's description and text, though it has no `@module` tag."
    assert app["Badge.qmd"].startswith('---\ntitle: "components/Badge"\ndescription: "Badge: a small label with a tone."\n---\n\nPages use it beside a name.\n')


def test_generic_interface_hook_and_constant(app: dict[str, str]) -> None:
    "Type parameters show in the signature; a constant shows its type."
    u = app["useCounter.qmd"]
    assert "interface Counter<T>" in u and "| `last` | `T \\| null` | the last thing counted |" in u
    assert "function useCounter<T>(start: number = 0, step: number = 1): Counter<T>" in u
    assert "| returns | `Counter<T>` |  |  |" in u
    assert "```ts\nconst MAX_ITEMS: 50\n```" in app["utils-format.qmd"]


def test_source_links_from_the_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "With `source`, each entry links to its file and line, from the root; without it, there is no link."
    site(tmp_path, "lib", monkeypatch, "  source: https://example.com/lib/blob/main\n")
    assert main(["api", "build", "--dir", str(tmp_path)]) == 0
    e = entry_of(pages(tmp_path)["lib.qmd"], "add")
    assert "[source](https://example.com/lib/blob/main/src/math.ts#L2){.source-link}" in e


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


def test_types_in_tables_are_code(app: dict[str, str]) -> None:
    "A type in a table is inline code, so that `<T>` is no HTML tag, and a comment over several lines is one line."
    assert "`Counter<T>`" in app["useCounter.qmd"]


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
    (tmp_path / "api/gone.qmd").write_text("# Gone\n")
    (tmp_path / "api/.smalldocs-api").write_text("gone.qmd\nindex-x.qmd")
    assert main(["api", "build", "--dir", str(tmp_path)]) == 0
    assert (tmp_path / "api/index.qmd").read_text() == "# Reference\n" and not (tmp_path / "api/gone.qmd").exists()
    assert "Badge.qmd" in (tmp_path / "api/.smalldocs-api").read_text().split("\n")


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
    "A language that is not python, typescript or rust stops with a message that names it."
    (tmp_path / "_smalldocs.yml").write_text("project:\n  type: website\napi:\n  language: go\n")
    assert main(["api", "build", "--dir", str(tmp_path)]) == 2
    assert "api.language must be python, typescript or rust, not 'go'" in capsys.readouterr().err


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
@pytest.mark.parametrize(("name", "entry"), [("lib", "src/index.ts"), ("app", "src")])
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
    assert api_ts.declared_fields(lines, "P") == [api_ts.Field("x", "number", False, ""), api_ts.Field("y", "number", False, "")]
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
    assert api_ts.stems(mods) == ["b", "b-2", "y"]


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
    "A React component needs no comment on its return; a function with no props, or a small name, still does."
    site(tmp_path, "app", monkeypatch)
    assert main(["api", "check", "--dir", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "components/Chip:Chip" not in out
    assert "components/Chip:Divider: no return comment" in out and "components/Chip:chips: no return comment" in out
    assert main(["api", "build", "--dir", str(tmp_path)]) == 0
    assert "| returns | `string` |  |  |" in entry_of(pages(tmp_path)["Chip.qmd"], "Chip")  # the page still shows the return


def test_typescript_links_any_name_in_the_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "On a TypeScript site, a name in backticks that is a key of `_symbols.json` links, though it looks like no code, as `useCounter`."
    site(tmp_path, "app", monkeypatch)
    (tmp_path / "index.qmd").write_text("# Home\n\nSee `useCounter`, `shout` and `nothing`.\n")
    assert main(["render", str(tmp_path), "-q"]) == 0
    html = (tmp_path / "_site/index.html").read_text()
    assert '<a href="api/useCounter.html#useCounter"><code>useCounter</code></a>' in html
    assert '<a href="api/utils-format.html#shout"><code>shout</code></a>' in html and "<code>nothing</code>" in html


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
