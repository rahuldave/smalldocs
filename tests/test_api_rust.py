"Tests of the API pages of a Rust crate, from the rustdoc JSON in tests/fixtures/rust; only the last test needs Rust."

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from smalldocs import api_rust
from smalldocs.api import Settings
from smalldocs.cli import main
from smalldocs.site import build

FIXTURES = Path(__file__).parent / "fixtures" / "rust"
CRATE = FIXTURES / "tinycrate"


@pytest.fixture(autouse=True)
def own_temp(
    tmp_path: Path,  # pytest's temporary folder
    monkeypatch: pytest.MonkeyPatch,  # pytest's patcher
) -> None:
    "Keep rustdoc's cache, which goes in the temporary folder, inside pytest's folder."
    (tmp_path / "tmp").mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmp"))


def fixture(
    name: str = "61",  # The fixture's suffix: `61`, `61-private` or `57`
) -> dict:  # rustdoc's JSON of the fixture crate
    "Read one of the rustdoc JSON fixtures."
    return json.loads((FIXTURES / f"tinycrate-{name}.json").read_text())


@pytest.fixture
def site(
    tmp_path: Path,  # pytest's temporary folder
    monkeypatch: pytest.MonkeyPatch,  # pytest's patcher
) -> Path:  # A site whose api settings name the fixture crate, with rustdoc replaced by the fixtures
    "Make a site for the fixture crate, and serve rustdoc's JSON from the fixtures: the public one, or the private one when asked."
    (tmp_path / "_smalldocs.yml").write_text(
        f"project:\n  type: website\napi:\n  language: rust\n  manifest: {CRATE / 'Cargo.toml'}\n  root: {CRATE}\n  source: https://example.com/tiny/blob/main\n"
    )
    (tmp_path / "index.qmd").write_text("---\ntitle: Tiny\n---\n\nSee `Point::distance`, `Point` and `add()`.\n")
    monkeypatch.setattr(api_rust, "rustdoc", lambda s, private=False: (fixture("61-private" if private else "61"), CRATE))
    return tmp_path


def pages(
    site: Path,  # The site's folder
) -> dict[str, str]:  # The text of each page that `api build` wrote, under its file name
    "Build the API pages of the site and read them."
    assert main(["api", "build", "--dir", str(site)]) == 0
    return {p.name: p.read_text() for p in sorted((site / "api").glob("*.qmd"))}


def entry(
    page: str,  # The text of a page
    anchor: str,  # The id of one entry's heading
) -> str:  # The text of that entry, up to the next heading of its level or above
    "Cut one entry out of a page."
    start = page.index(f"{{#{anchor}}}")
    start = page.rindex("\n", 0, start) + 1
    level = len(page[start:].split(" ", 1)[0])
    rest = page[start + 1 :]
    ends = [i for i in (rest.find("\n" + "#" * n + " ") for n in range(2, level + 1)) if i >= 0]
    return page[start : start + 1 + min(ends)] if ends else page[start:]


def test_python_pages_unchanged_without_language(tmp_path: Path) -> None:
    "Without `language`, the settings are the Python ones, and building them never loads the Rust module."
    s = Settings.read(tmp_path, {"packages": ["x"]})
    assert (s.language, s.manifest, s.toolchain, s.private) == ("python", None, "nightly", False)
    assert Settings.read(tmp_path, {"packages": ["x"], "language": "python"}) == s
    script = "import sys; from smalldocs import api, cli; print('smalldocs.api_rust' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True).stdout.strip() == "False"


def test_language_must_be_known_and_needs_no_packages(tmp_path: Path) -> None:
    "`language` is python, rust or typescript; a crate needs no packages; `private` must be true or false."
    with pytest.raises(ValueError, match="language must be python, rust or typescript"):
        Settings.read(tmp_path, {"language": "go"})
    s = Settings.read(tmp_path, {"language": "rust", "manifest": "../Cargo.toml", "toolchain": "nightly-2026-11-11", "private": True})
    assert s.packages == [] and s.manifest == (tmp_path.parent / "Cargo.toml").resolve() and s.toolchain == "nightly-2026-11-11" and s.private
    with pytest.raises(ValueError, match="private must be true or false"):
        Settings.read(tmp_path, {"language": "rust", "private": "yes"})


def test_rust_does_not_touch_sys_path(site: Path) -> None:
    "A crate is read by rustdoc, so `Settings.importable` puts nothing on `sys.path`."
    before = list(sys.path)
    pages(site)
    assert sys.path == before


def test_comments_after_parameters_by_line(site: Path) -> None:
    "The comment after a parameter describes it; the one on the line of `->` describes the return."
    add = entry(pages(site)["tinycrate.qmd"], "add")
    assert "```rust\npub fn add(a: i32, b: i32) -> i32\n```" in add
    assert "| `a` | `i32` | the first number |\n| `b` | `i32` | the second number |\n| returns | `i32` | the sum |" in add


def test_comment_on_a_one_line_signature_and_the_body_line(site: Path) -> None:
    "On a line with one parameter and no `->`, the comment is the parameter's; on a line of `->` with no parameter, or of the `{`, it is the return's."
    p = pages(site)["tinycrate.qmd"]
    assert "| `name` | `String` | the name, which is changed |" in entry(p, "greet")
    assert "| returns | `Self` | the point (0, 0) |" in entry(p, "Point.origin")
    assert "| `value` | `T` | the value |\n| returns | `Option<T>` | the value, wrapped |" in entry(p, "wrap")
    assert "| returns | `f64` | the area, in square units |" in entry(p, "Shape.area")


def test_arguments_list_when_there_is_no_comment(site: Path) -> None:
    "Without a comment, a parameter's description comes from the doc comment's `# Arguments` list, which leaves the text."
    scale = entry(pages(site)["tinycrate.qmd"], "scale")
    assert "| `x` | `f64` | the number |\n| `by` | `f64` | the factor |" in scale
    assert "Arguments" not in scale


def test_struct_fields_and_inherent_methods(site: Path) -> None:
    "A struct has a table of its public fields, with the doc comment or the comment after each; its own methods are entries under it."
    p = pages(site)["tinycrate.qmd"]
    point = entry(p, "Point")
    assert "| `x` | `f64` | Across. |\n| `y` | `f64` | Up |" in point and "hidden" not in point
    assert "### Point::distance {#Point.distance}" in p and "pub fn distance(&self, other: &Point) -> f64" in p
    assert "| `other` | `&Point` | the other point |" in entry(p, "Point.distance")
    assert "secret" not in p, "a private method is left out of a library's pages"


def test_enum_variants(site: Path) -> None:
    "An enum has a table of its variants, each as Rust writes it, or with `{ .. }` when its fields are long, and its doc comment, with links, or the comment after it."
    colour = entry(pages(site)["tinycrate.qmd"], "Colour")
    rows = [
        "| `Red` | Pure red, not [`Colour::Green`](/api/tinycrate.qmd#Colour). |",
        "| `Green` | Pure green |",
        "| `Rgb(u8, u8, u8)` | A colour by its parts. |",
        "| `Named { name: String }` | A named colour. |",
        "| `Mix { .. }` | A mix of three named colours. |",
    ]
    assert "\n".join(rows) in colour


def test_trait_methods_and_implementors(site: Path) -> None:
    "A trait's methods are entries under it, and the types that implement it are listed."
    p = pages(site)["tinycrate.qmd"]
    assert "```rust\nfn area(&self) -> f64;\n```" in entry(p, "Shape.area") and "### Shape::name {#Shape.name}" in p
    assert "Implemented for [`Circle`](/api/shapes.qmd#Circle)." in entry(p, "Shape")


def test_trait_impls_by_name_without_auto_and_blanket_impls(site: Path) -> None:
    "A trait impl is listed by the trait's name, linked; auto traits such as `Send`, blanket impls such as `From<T>`, and derive's markers are left out."
    point = entry(pages(site)["tinycrate.qmd"], "Point")
    line = next(x for x in point.splitlines() if x.startswith("Implements "))
    assert "[`Display`](https://doc.rust-lang.org/nightly/core/fmt/trait.Display.html)" in line and "[`Clone`]" in line
    for left_out in ("Send", "Sync", "Unpin", "From", "Into", "Any", "StructuralPartialEq"):
        assert f"[`{left_out}" not in line
    assert "Point::fmt" not in point and "Point::clone" not in point, "a trait impl's methods are not entries"


def test_reexports_have_one_entry(site: Path) -> None:
    "An item has one entry: where it is defined, when that module has a page, and otherwise on the page that re-exports it."
    p = pages(site)
    root = p["tinycrate.qmd"]
    assert "## struct Circle {#Circle}" in p["shapes.qmd"] and "{#Circle}" not in root
    assert "Re-exports [`Circle`](/api/shapes.qmd#Circle), [`Map`](https://doc.rust-lang.org/nightly/std/collections/hash/map/struct.HashMap.html)." in root
    assert "## struct Token {#Token}" in root and "pub struct Token(pub String);" in root, "from a private module"
    assert "## count {#count}" in root, "from a glob re-export of a private module"
    assert set(p) == {"tinycrate.qmd", "shapes.qmd", "deep.qmd"}, "a private module has no page; a public module inside it has one"


def test_intra_doc_links(site: Path) -> None:
    "Intra-doc links become links: to the entry on this site, or to the docs of the crate an item is from."
    add = entry(pages(site)["tinycrate.qmd"], "add")
    assert "See [`Point`](/api/tinycrate.qmd#Point) and [`std::fmt::Display`](https://doc.rust-lang.org/nightly/core/fmt/trait.Display.html)." in add


def test_external_crate_without_root_url_links_to_docs_rs() -> None:
    "A crate whose JSON has no `html_root_url` links to docs.rs; a method links into its type's page."
    data = fixture()
    data["external_crates"]["99"] = {"name": "serde_json", "html_root_url": None}
    data["paths"]["9001"] = {"crate_id": 99, "path": ["serde_json", "value", "Value"], "kind": "enum"}
    data["paths"]["9002"] = {"crate_id": 99, "path": ["serde_json", "value", "Value", "as_str"], "kind": "function"}
    crate = api_rust.Crate(data, CRATE)
    assert crate.url(9001) == "https://docs.rs/serde_json/latest/serde_json/value/enum.Value.html"
    assert crate.url(9002) == "https://docs.rs/serde_json/latest/serde_json/value/enum.Value.html#method.as_str"


def test_page_front_matter_module_docs_and_examples(site: Path) -> None:
    "A page has the module's title and summary, its other docs, a table of its modules; a doc example is Rust, without its hidden lines, under the entry's heading."
    p = pages(site)
    root = p["tinycrate.qmd"]
    assert root.startswith('---\ntitle: "tinycrate"\ndescription: "A tiny crate for the tests of smalldocs."\n---\n\nIt has a function')
    assert "| [`shapes`](shapes.qmd) | Shapes, read from `&[u8]`. |" in root, "a code span in a summary keeps its brackets"
    wrapper = entry(root, "Wrapper")
    assert "#### Examples\n\n```rust\nlet w = Wrapper { inner: &3 };" in wrapper and "# use" not in wrapper
    assert "[source](https://example.com/tiny/blob/main/src/lib.rs#L" in wrapper
    assert "## macro point {#macro.point}" in root and "macro_rules! point {" in root


def test_symbols_index(site: Path) -> None:
    "`_symbols.json` has each name by itself, as `Type::method`, as `Type.method` and by its full path; names in backticks link to the entries."
    pages(site)
    index = json.loads((site / "_symbols.json").read_text())
    assert index["Point"] == index["tinycrate::Point"] == "/api/tinycrate.qmd#Point"
    assert index["Point::distance"] == index["Point.distance"] == index["tinycrate::Point::distance"] == "/api/tinycrate.qmd#Point.distance"
    assert index["Circle"] == "/api/shapes.qmd#Circle"
    s = build(site, quiet=True)
    home = (s.out / "index.html").read_text()
    assert '<a href="api/tinycrate.html#Point.distance"><code>Point::distance</code></a>' in home
    assert '<a href="api/tinycrate.html#add"><code>add()</code></a>' in home


def test_formats_57_and_61_write_the_same_pages(site: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "rustdoc's JSON formats 57 and 61 give the same pages; only the docs of `std` that each toolchain links to differ."
    p61 = pages(site)
    monkeypatch.setattr(api_rust, "rustdoc", lambda s, private=False: (fixture("57"), CRATE))
    p57 = pages(site)
    assert "doc.rust-lang.org/1.95.0/core/fmt/trait.Display.html" in p57["tinycrate.qmd"]
    assert {k: v.replace("/1.95.0/", "/nightly/") for k, v in p57.items()} == p61


def test_build_deletes_only_its_own_pages(site: Path) -> None:
    "The build deletes only a page that its manifest lists and this build did not write, never a page someone wrote."
    (site / "api").mkdir()
    (site / "api/index.qmd").write_text("---\ntitle: API\n---\n")
    (site / "api/gone.qmd").write_text("---\ntitle: x\n---\n")
    (site / "api/.smalldocs-api").write_text("gone.qmd")
    pages(site)
    assert (site / "api/index.qmd").exists() and not (site / "api/gone.qmd").exists()
    assert (site / "api/.smalldocs-api").read_text() == "deep.qmd\nshapes.qmd\ntinycrate.qmd"


@pytest.mark.parametrize("out", [".", "..", "../x"])
def test_out_must_be_inside_the_site(site: Path, out: str, monkeypatch: pytest.MonkeyPatch) -> None:
    "`api.out` that is the site or outside it is refused before rustdoc runs."
    monkeypatch.setattr(api_rust, "rustdoc", lambda s, private=False: pytest.fail("rustdoc ran"))
    conf = (site / "_smalldocs.yml").read_text().replace("language: rust", f'language: rust\n  out: "{out}"')
    (site / "_smalldocs.yml").write_text(conf)
    assert main(["api", "build", "--dir", str(site)]) == 2


def test_binary_documents_private_items(site: Path) -> None:
    "`private: true`, as a crate with only a binary has, documents private items and modules."
    conf = (site / "_smalldocs.yml").read_text().replace("language: rust", "language: rust\n  private: true")
    (site / "_smalldocs.yml").write_text(conf)
    p = pages(site)
    assert "### Point::secret {#Point.secret}" in p["tinycrate.qmd"] and "| `hidden` | `bool` |  |" in p["tinycrate.qmd"]
    assert "```rust\nfn secret(&self) -> bool\n```" in p["tinycrate.qmd"], "a private item, which rustdoc restricts to its own module, has no `pub`"
    assert api_rust.visibility({"visibility": {"restricted": {"parent": 7, "path": "::a::b"}}}, "9") == "pub(in crate::a::b) "
    assert {"inner.qmd", "helpers.qmd"} <= set(p) and "## struct Token {#Token}" in p["inner.qmd"]


def test_check_lists_gaps(site: Path, capsys: pytest.CaptureFixture) -> None:
    "`check` holds every item, private ones too, to a doc comment and a docment for each parameter, return, field and variant; `--shown` only what the pages show."
    assert main(["api", "check", "--dir", str(site)]) == 1
    out = capsys.readouterr().out
    for gap in [
        "tinycrate:undocumented: no doc comment",
        "tinycrate:undocumented(x): no docment",
        "tinycrate:undocumented: no return docment",
        "tinycrate:scale: no return docment",
        "tinycrate:Point.hidden: no docment",
        "tinycrate:Point::secret: no doc comment",
        "tinycrate::inner::helpers: no module doc comment",
    ]:
        assert gap in out
    assert "tinycrate:add:" not in out and "tinycrate:add(" not in out and "of 36 items are documented" in out
    assert main(["api", "check", "--shown", "--dir", str(site)]) == 1
    shown = capsys.readouterr().out
    assert "secret" not in shown and "hidden" not in shown and "tinycrate:undocumented(x): no docment" in shown


def test_list_and_module_are_for_python(site: Path, capsys: pytest.CaptureFixture) -> None:
    "`api list` and `api module` stop with a message for a crate."
    assert main(["api", "list", "--dir", str(site)]) == 2
    assert "for Python only" in capsys.readouterr().err


def fake_cargo(
    tmp_path: Path,  # A folder for the script
    monkeypatch: pytest.MonkeyPatch,  # pytest's patcher, to put the script on the PATH
    script: str,  # The body of the shell script
) -> None:
    "Put a fake `cargo` first on the PATH."
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "cargo").write_text("#!/bin/sh\n" + script)
    (bin_dir / "cargo").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/bin:/usr/bin")


def rust_site(
    tmp_path: Path,  # A folder
) -> Path:  # A site whose api settings name the fixture crate, with the real `rustdoc`
    "Make a site for the fixture crate."
    s = tmp_path / "site"
    s.mkdir()
    (s / "_smalldocs.yml").write_text(f"project:\n  type: website\napi:\n  language: rust\n  manifest: {CRATE / 'Cargo.toml'}\n")
    (s / "index.qmd").write_text("# Tiny\n")
    return s


def test_missing_cargo_and_toolchain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    "Without cargo, or without the toolchain, the build stops with a message that says what to install."
    s = rust_site(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path / "nothing"))
    assert main(["api", "build", "--dir", str(s)]) == 2
    assert "cargo is not installed" in capsys.readouterr().err
    fake_cargo(tmp_path, monkeypatch, "echo \"error: toolchain 'nightly' is not installed\" >&2\nexit 1\n")
    assert main(["api", "build", "--dir", str(s)]) == 2
    assert "rustup toolchain install nightly" in capsys.readouterr().err
    assert main(["render", str(s), "-q"]) == 2, "a render stops too"


def test_unknown_format_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    "A rustdoc JSON format that smalldocs does not read stops the build with a message that names the version found."
    s = rust_site(tmp_path)
    meta = {
        "workspace_root": str(CRATE),
        "packages": [{"name": "tinycrate", "manifest_path": str(CRATE / "Cargo.toml"), "targets": [{"name": "tinycrate", "kind": ["lib"]}]}],
    }
    (tmp_path / "meta.json").write_text(json.dumps(meta))
    data = {**fixture(), "format_version": 99}
    (tmp_path / "doc.json").write_text(json.dumps(data))
    fake_cargo(
        tmp_path,
        monkeypatch,
        f'case "$2" in metadata) cat {tmp_path / "meta.json"};; rustdoc) mkdir -p "$CARGO_TARGET_DIR/doc"; cp {tmp_path / "doc.json"} "$CARGO_TARGET_DIR/doc/tinycrate.json";; esac\n',
    )
    assert main(["api", "build", "--dir", str(s)]) == 2
    assert "wrote JSON format 99, and smalldocs reads formats 57 and 61" in capsys.readouterr().err


def has_nightly() -> bool:  # Whether `cargo +nightly` runs
    "Tell whether cargo and the nightly toolchain are installed."
    if shutil.which("cargo") is None:
        return False
    return subprocess.run(["cargo", "+nightly", "--version"], capture_output=True, env={**os.environ, "RUSTUP_AUTO_INSTALL": "0"}).returncode == 0


@pytest.mark.skipif(not has_nightly(), reason="needs cargo and the nightly toolchain")
def test_real_rustdoc(tmp_path: Path) -> None:
    "The real rustdoc of the nightly toolchain gives the pages that the fixtures give, and writes nothing into the crate."
    crate = tmp_path / "tinycrate"
    shutil.copytree(CRATE, crate)
    s = Settings.read(tmp_path, {"language": "rust", "manifest": "tinycrate/Cargo.toml", "root": "tinycrate"})
    data, root = api_rust.rustdoc(s)
    assert data["format_version"] in api_rust.FORMATS and root == crate.resolve()
    assert sorted(p.name for p in crate.rglob("*")) == sorted(p.name for p in CRATE.rglob("*")), "no Cargo.lock and no target in the crate"
    real = api_rust.Crate(data, root)
    fixed = api_rust.Crate(fixture(), CRATE)
    assert [api_rust.page_markdown(s, real, p) for p in real.pages] == [api_rust.page_markdown(s, fixed, p) for p in fixed.pages]


# ---------------------------------------------------------------- findings of the adversarial review


def test_glob_cycle_ends(site: Path) -> None:
    "Two hidden modules that glob-import each other, `pub use a::*` and `pub use b::*`, give each item one entry, and the build ends."
    root = pages(site)["tinycrate.qmd"]
    assert root.count("## in_a {#in_a}") == 1 and root.count("## in_b {#in_b}") == 1


def test_public_module_inside_a_private_one(site: Path) -> None:
    "`pub use hidden::deep`, a public module inside a private one, gives the module its page, listed with the root's modules."
    p = pages(site)
    assert "## deepfn {#deepfn}" in p["deep.qmd"] and p["deep.qmd"].startswith('---\ntitle: "tinycrate::deep"')
    assert "| [`deep`](deep.qmd) | A public module inside a private one. |" in p["tinycrate.qmd"]


def test_renamed_reexport_keeps_its_comments(site: Path, capsys: pytest.CaptureFixture) -> None:
    "`pub use hidden::add_two as plus` reads the comments from `fn add_two` in the source, so `check` finds no gap."
    plus = entry(pages(site)["tinycrate.qmd"], "plus")
    assert "pub fn plus(a: i32, b: i32) -> i32" in plus and "| `a` | `i32` | the first |\n| `b` | `i32` | the second |\n| returns | `i32` | the sum |" in plus
    main(["api", "check", "--shown", "--dir", str(site)])
    assert "plus" not in capsys.readouterr().out


def test_methods_of_two_impls_with_one_name(site: Path) -> None:
    "`impl Holder<u8>` and `impl Holder<u16>` each with `new` give two headings with different ids."
    p = pages(site)["tinycrate.qmd"]
    assert "### Holder::new {#Holder.new}" in p and "### Holder::new {#Holder.new-2}" in p


def test_arrow_in_generics_and_where_is_not_the_return(site: Path) -> None:
    "A `->` inside `<F: Fn(u8) -> u8>` or a `where` clause is not the return's, so their comments go to the parameter or nowhere."
    apply = entry(pages(site)["tinycrate.qmd"], "apply")
    assert "| `f` | `F` | the function |\n| `x` | `u8` | the input |\n| returns | `u8` |  |" in apply and "a bound" not in apply


def test_pattern_parameter(site: Path, capsys: pytest.CaptureFixture) -> None:
    "A parameter written as a pattern, `(b, c): (u8, u8)`, gets the comment after it, and `check` finds no gap."
    assert "| `(b, c)` | `(u8, u8)` | the pair |" in entry(pages(site)["tinycrate.qmd"], "pair")
    main(["api", "check", "--shown", "--dir", str(site)])
    assert "pair" not in capsys.readouterr().out


def test_character_literal_and_block_comment(site: Path) -> None:
    "A `'\"'` in a `/* */` comment starts no string, so the comment after the parameter is still read."
    assert "| `c` | `char` | the character |" in entry(pages(site)["tinycrate.qmd"], "quote")
    assert api_rust.split_comment("let c = '\"'; // a quote") == ("let c = '\"'; ", "a quote")
    assert api_rust.split_comment("fn f<'a>(x: &'a str) // a") == ("fn f<'a>(x: &'a str) ", "a")


def test_four_backtick_fence(site: Path) -> None:
    "A ```` fence that holds a ``` example ends at its own ````, so the heading after it stays."
    fences = entry(pages(site)["tinycrate.qmd"], "fences")
    assert "````text\n```\nnot closed\n````\n\n#### Panics\n\nNever." in fences


def test_disambiguators_and_keyword_names(site: Path) -> None:
    "`[fn@add]` shows as `add`, as rustdoc shows it; a function named `r#type` keeps its `r#`."
    p = pages(site)["tinycrate.qmd"]
    assert "see [add](/api/tinycrate.qmd#add) and [Point](/api/tinycrate.qmd#Point)." in entry(p, "apply")
    assert "```rust\npub fn r#type()\n```" in p


def test_one_line_struct_comment_belongs_to_no_field(site: Path) -> None:
    "The comment after `pub struct Size { pub w: u32, pub h: u32 }` describes no single field."
    size = entry(pages(site)["tinycrate.qmd"], "Size")
    assert "| `w` | `u32` |  |\n| `h` | `u32` |  |" in size


def test_function_and_macro_of_one_name(site: Path) -> None:
    "A function `point` and a macro `point!` each have an entry, and the full path names the first."
    pages(site)
    index = json.loads((site / "_symbols.json").read_text())
    assert index["tinycrate::point"] == "/api/tinycrate.qmd#point" and "{#macro.point}" in (site / "api/tinycrate.qmd").read_text()


def test_toolchain_must_be_text(tmp_path: Path) -> None:
    "`toolchain: 1.80`, which YAML reads as the number 1.8, stops with a message to quote it."
    with pytest.raises(ValueError, match="put a number in quotes"):
        Settings.read(tmp_path, {"language": "rust", "toolchain": 1.8})


def test_cache_folder_is_the_users_own(tmp_path: Path) -> None:
    "The cache is one folder per user that only the user can write; a folder that others can write to is refused."
    folder = api_rust.cache_folder()
    assert folder.parent == tmp_path / "tmp" and folder.stat().st_mode & 0o077 == 0
    folder.chmod(0o777)
    with pytest.raises(ValueError, match="others can write to it"):
        api_rust.cache_folder()


def fake_rustdoc(
    tmp_path: Path,  # pytest's temporary folder
    monkeypatch: pytest.MonkeyPatch,  # pytest's patcher
    rustdoc: str,  # The shell commands of `cargo rustdoc`
) -> tuple[Path, Path]:  # A site for a copy of the fixture crate, and that copy
    "Put a fake cargo on the PATH, whose `metadata` describes a copy of the fixture crate and whose `rustdoc` runs the given commands."
    crate = tmp_path / "crate"
    shutil.copytree(CRATE, crate)
    meta = {"workspace_root": str(crate), "packages": [{"name": "tinycrate", "manifest_path": str(crate / "Cargo.toml"), "targets": [{"name": "tinycrate", "kind": ["lib"]}]}]}
    (tmp_path / "meta.json").write_text(json.dumps(meta))
    (tmp_path / "doc.json").write_text(json.dumps(fixture()))
    fake_cargo(tmp_path, monkeypatch, f'case "$2" in metadata) cat {tmp_path / "meta.json"};; rustdoc) {rustdoc};; esac\n')
    s = tmp_path / "site"
    s.mkdir()
    (s / "_smalldocs.yml").write_text(f"project:\n  type: website\napi:\n  language: rust\n  manifest: {crate / 'Cargo.toml'}\n")
    (s / "index.qmd").write_text("# Tiny\n")
    return s, crate


def test_lock_file_put_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "A cargo that ignores `resolver.lockfile-path` and writes the project's Cargo.lock: the file is removed, or put back as it was."
    write_lock = f'echo changed > "$PWD/Cargo.lock"; mkdir -p "$CARGO_TARGET_DIR/doc"; cp {tmp_path / "doc.json"} "$CARGO_TARGET_DIR/doc/tinycrate.json"'
    s, crate = fake_rustdoc(tmp_path, monkeypatch, write_lock)
    assert main(["api", "build", "--dir", str(s)]) == 0
    assert not (crate / "Cargo.lock").exists()
    (crate / "Cargo.lock").write_text("mine\n")
    assert main(["api", "build", "--dir", str(s)]) == 0
    assert (crate / "Cargo.lock").read_text() == "mine\n"


def test_json_where_cargo_writes_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    "cargo runs in the crate's folder, so its own config holds; its JSON is read under a target triple too; a JSON of an earlier run is never read."
    triple = f'echo "$PWD" > {tmp_path / "pwd"}; mkdir -p "$CARGO_TARGET_DIR/aarch64-apple-darwin/doc"; cp {tmp_path / "doc.json"} "$CARGO_TARGET_DIR/aarch64-apple-darwin/doc/tinycrate.json"'
    s, crate = fake_rustdoc(tmp_path, monkeypatch, triple)
    assert main(["api", "build", "--dir", str(s)]) == 0
    assert (tmp_path / "pwd").read_text().strip() == str(crate.resolve()) and (s / "api/tinycrate.qmd").exists()
    fake_cargo_dir = tmp_path / "bin"
    shutil.rmtree(fake_cargo_dir)
    fake_rustdoc_none = f'case "$2" in metadata) cat {tmp_path / "meta.json"};; esac\n'
    fake_cargo_dir.mkdir()
    (fake_cargo_dir / "cargo").write_text("#!/bin/sh\n" + fake_rustdoc_none)
    (fake_cargo_dir / "cargo").chmod(0o755)
    assert main(["api", "build", "--dir", str(s)]) == 2, "the JSON of the run before is deleted, not read"
    assert "wrote no tinycrate.json" in capsys.readouterr().err
