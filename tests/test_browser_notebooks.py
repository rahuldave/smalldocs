"Check notebook lint, copied metadata, bundles and themed controls without executing notebook code."

import copy
import html as html_module
import json
import re
import tomllib
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from smalldocs import browser
from smalldocs.cli import main
from smalldocs.config import BuildError, ConfigError
from smalldocs.site import build


def notebook(
    code: str = "import numpy as np\n",  # One code cell
    front: str = "",  # Optional YAML front matter
) -> dict:  # A small Python notebook
    "Make a notebook for the build checks."
    cells = [{"cell_type": "code", "source": code, "metadata": {}, "outputs": [], "execution_count": None}]
    if front:
        cells.insert(0, {"cell_type": "raw", "metadata": {}, "source": f"---\n{front}\n---\n"})
    return {"cells": cells, "metadata": {"language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}


def project(
    root: Path,  # The temporary project folder
    config: str = "browser-notebooks: true\n",  # Its native config
) -> Path:  # The folder containing a notebook
    "Write a project with a notebook below two folder levels."
    (root / "_smalldocs.yml").write_text(config)
    folder = root / "guide/plot"
    folder.mkdir(parents=True)
    (folder / "lesson.ipynb").write_text(json.dumps(notebook(front="title: A plot")))
    return folder


@pytest.fixture
def fake_runtime(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    "Replace the optional JupyterLite build with a recorded static output folder."
    built = []

    def runtime(output: Path) -> None:
        "Write the directory that the real JupyterLite build supplies."
        output.mkdir(parents=True)
        built.append(output)

    monkeypatch.setattr(browser, "require_jupyterlite", lambda: None)
    monkeypatch.setattr(browser, "build_runtime", runtime)
    return built


def test_imports_map_packages_and_skip_the_standard_library() -> None:
    "Magics and multiline imports do not hide aliased or nested imports."
    nb = notebook("%matplotlib inline\n!echo setup\nimport os, numpy as np\nfrom sklearn.model_selection import (\n    train_test_split,\n)\nfrom PIL import Image\nif True:\n    import seaborn\nimport matplotlib.pyplot as plt\n")
    assert browser.dependencies(nb) == ["matplotlib", "numpy", "pillow", "scikit-learn", "seaborn"]
    assert browser.lint(nb) == []
    assert browser.dependencies(notebook("print('no packages')\n")) == []


def test_lint_rejects_disallowed_packages_and_other_kernels() -> None:
    "The disallow list is a lint gate, including when a notebook asks to run."
    nb = notebook("from torch import nn\nimport pymc\n", "browser-runnable: true")
    assert len(browser.lint(nb)) == 2
    nb["metadata"]["language_info"]["name"] = "R"
    assert "not Python" in browser.lint(nb)[0]
    nb["cells"] = []
    nb["metadata"] = {}
    assert browser.lint(nb) == ["no code cells"]


def test_metadata_is_generated_in_a_copy_and_replaces_old_requirements() -> None:
    "The generated cell is valid TOML and leaves the source and executable code intact."
    nb = notebook("import numpy\n", "title: Example")
    nb["cells"].insert(1, {"cell_type": "code", "source": '# /// script\n# dependencies = ["old"]\n# ///\nprint("keep")\n', "metadata": {}})
    original = copy.deepcopy(nb)
    prepared = browser.with_metadata(nb, ["numpy"])
    assert nb == original
    code = "".join(prepared["cells"][1]["source"])
    block = code.split("# /// script\n")[1].split("# ///")[0]
    assert tomllib.loads("\n".join(line.removeprefix("# ") for line in block.splitlines()))["dependencies"] == ["numpy"]
    assert prepared["cells"][2]["source"] == ['print("keep")\n']
    assert browser.with_metadata(prepared, ["numpy"]) == prepared


def test_bundle_keeps_data_paths_and_never_changes_source(tmp_path: Path) -> None:
    "Nested data and assets travel with the copy; outside files and unknown file types do not."
    folder = project(tmp_path)
    path = folder / "lesson.ipynb"
    before = path.read_bytes()
    (folder / "data/nested").mkdir(parents=True)
    (folder / "data/nested/values.csv").write_text("x\n1\n")
    (folder / "data/private.key").write_text("not included")
    (folder / "data/outside.txt").symlink_to(tmp_path / "_smalldocs.yml")
    target = tmp_path / "bundle.zip"
    names = browser.bundle(path, target, ["numpy"])
    assert names == ["lesson.ipynb", "data/nested/values.csv"]
    with zipfile.ZipFile(target) as archive:
        assert archive.read("data/nested/values.csv") == b"x\n1\n"
        assert "# /// script" in "".join(json.loads(archive.read("lesson.ipynb"))["cells"][1]["source"])
        assert "uvx juv run lesson.ipynb" in archive.read("README.md").decode()
    assert path.read_bytes() == before


@pytest.mark.parametrize("native", [True, False])
def test_build_adds_relative_controls_and_a_themed_loader(tmp_path: Path, fake_runtime: list[Path], native: bool) -> None:
    "Both config formats build eligible notebooks and preserve full paths for the loader."
    project(tmp_path)
    if not native:
        (tmp_path / "_smalldocs.yml").unlink()
        (tmp_path / "_quarto.yml").write_text("smalldocs:\n  browser-notebooks: true\nformat:\n  html:\n    theme: darkly\n")
    site = build(tmp_path, quiet=True)
    assert site.warnings == []
    assert fake_runtime == [tmp_path / "_site/lab"]
    html = (tmp_path / "_site/guide/plot/lesson.html").read_text()
    assert 'href="../../site_libs/notebooks.css"' in html
    href = html_module.unescape(re.search(r'href="([^"]*loader.html[^"]*)"', html)[1])
    assert href.startswith("../../lab/loader.html?")
    assert parse_qs(urlsplit(href).query) == {"zip": ["site_libs/notebooks/guide/plot/lesson.zip"], "path": ["guide/plot/lesson"], "notebook": ["lesson.ipynb"]}
    assert "Download and run" in html
    loader = (tmp_path / "_site/lab/loader.html").read_text()
    assert "../site_libs/themes/" in loader
    assert "../site_libs/notebooks.css" in loader
    assert "../site_libs/notebook-loader.js" in loader
    assert "sd-notebook-controls" not in loader
    assert not (tmp_path / "_site/guide/plot/lesson.ipynb").exists()
    manifest = json.loads((tmp_path / "_site/site_libs/notebooks.json").read_text())
    assert manifest["guide/plot/lesson.ipynb"]["dependencies"] == ["numpy"]


@pytest.mark.parametrize("front,code", [("browser-runnable: false", "import numpy"), ("browser-runnable: true", "import torch")])
def test_disabled_or_blocked_notebooks_get_no_artifacts(tmp_path: Path, fake_runtime: list[Path], front: str, code: str) -> None:
    "A per-page opt-out or disallowed import skips the runner and its source bundle."
    folder = project(tmp_path)
    (folder / "lesson.ipynb").write_text(json.dumps(notebook(code, front)))
    build(tmp_path, quiet=True)
    assert not fake_runtime
    assert not (tmp_path / "_site/lab").exists()
    assert not (tmp_path / "_site/site_libs/notebooks.css").exists()
    assert "Run in browser" not in (tmp_path / "_site/guide/plot/lesson.html").read_text()


def test_controls_quote_reserved_characters_in_notebook_paths(tmp_path: Path, fake_runtime: list[Path]) -> None:
    "URL fragments and percent signs in notebook names stay part of the bundle path."
    folder = project(tmp_path)
    (folder / "lesson.ipynb").rename(folder / "lesson #1%.ipynb")
    build(tmp_path, quiet=True)
    text = (tmp_path / "_site/guide/plot/lesson #1%.html").read_text()
    href = html_module.unescape(re.search(r'href="([^"]*loader.html[^"]*)"', text)[1])
    assert parse_qs(urlsplit(href).query)["zip"] == ["site_libs/notebooks/guide/plot/lesson%20%231%25.zip"]
    with zipfile.ZipFile(tmp_path / "_site/site_libs/notebooks/guide/plot/lesson #1%.zip") as archive:
        assert "uvx juv run 'lesson #1%.ipynb'" in archive.read("README.md").decode()


def test_default_stays_static_and_invalid_config_fails(tmp_path: Path, fake_runtime: list[Path]) -> None:
    "The opt-in setting is required and accepts only booleans."
    project(tmp_path, "{}\n")
    build(tmp_path, quiet=True)
    assert not fake_runtime
    assert "notebooks.css" not in (tmp_path / "_site/guide/plot/lesson.html").read_text()
    (tmp_path / "_smalldocs.yml").write_text("browser-notebooks: yes-please\n")
    with pytest.raises(ConfigError, match="true or false"):
        build(tmp_path, quiet=True)


def test_missing_optional_builder_keeps_previous_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    "A missing optional dependency fails before emptying a previous site."
    project(tmp_path, "{}\n")
    build(tmp_path, quiet=True)
    previous = (tmp_path / "_site/guide/plot/lesson.html").read_bytes()
    (tmp_path / "_smalldocs.yml").write_text("browser-notebooks: true\n")
    monkeypatch.setattr(browser.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(BuildError, match=r"smalldocs\[notebooks\]"):
        build(tmp_path, quiet=True)
    assert (tmp_path / "_site/guide/plot/lesson.html").read_bytes() == previous


def test_lint_cli_needs_no_optional_builder_or_site_output(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    "Lint reports dependencies and an exit code without building or executing a notebook."
    folder = project(tmp_path, "{}\n")
    assert main(["notebooks", "lint", str(tmp_path)]) == 0
    assert "PASS guide/plot/lesson.ipynb: numpy" in capsys.readouterr().out
    (folder / "lesson.ipynb").write_text(json.dumps(notebook("import torch")))
    assert main(["notebooks", "lint", str(tmp_path)]) == 1
    assert "package torch" in capsys.readouterr().out
    assert not (tmp_path / "_site").exists()
