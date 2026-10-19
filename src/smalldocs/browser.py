"Prepare notebook downloads and a JupyterLite runner, using imports and a Pyodide disallow list."

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from .config import BuildError, ConfigError
from .notebook import source

if TYPE_CHECKING:
    from .layout import SiteNav
    from .site import Site

IMPORT_TO_PACKAGE = {
    "sklearn": "scikit-learn", "cv2": "opencv-python", "PIL": "pillow", "yaml": "pyyaml",
    "bs4": "beautifulsoup4", "attr": "attrs", "dateutil": "python-dateutil", "IPython": "ipython",
    "theano": "theano-pymc",
}
PYODIDE_DISALLOWED = {"torch", "pytorch", "pymc3", "pymc", "theano-pymc", "theano", "lxml"}
RUNTIME_MODULES = {"__future__", "mpl_toolkits", "js", "pyodide", "micropip", "piplite"}
BUNDLE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".csv", ".tsv", ".dat", ".txt", ".json",
    ".geojson", ".npy", ".npz", ".pickle", ".pkl", ".py",
}
ASSETS = Path(__file__).parent / "assets" / "notebooks"


def imports(
    notebook: dict,  # The source notebook
) -> set[str]:  # Its top-level import names
    "Find imports in Python cells, leaving IPython magic and shell lines out of the parser."
    found: set[str] = set()
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        code = "\n".join("" if line.lstrip().startswith(("%", "!", "?")) else line for line in source(cell).splitlines())
        try:
            tree = ast.parse(code)
        except SyntaxError:
            # Older notebooks may use Python syntax that the build's Python cannot parse.
            for line in code.splitlines():
                match = re.match(r"\s*(?:from\s+(\w+)(?:\.\w+)*\s+import|import\s+(.+))", line)
                if match:
                    found.update([match[1]] if match[1] else [part.strip().split()[0].split(".")[0] for part in match[2].split(",")])
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                found.add(node.module.split(".")[0])
    return found


def dependencies(
    notebook: dict,  # The source notebook
) -> list[str]:  # Sorted distribution names for its imports
    "Map imported modules to package names, excluding the standard library and the browser kernel."
    skip = sys.stdlib_module_names | RUNTIME_MODULES
    return sorted({IMPORT_TO_PACKAGE.get(name, name.lower()) for name in imports(notebook) if name not in skip})


def lint(
    notebook: dict,  # The source notebook
) -> list[str]:  # The reasons it cannot have a browser runner, empty when it passes
    "Check the Python kernel, code cells and package disallow list without running code."
    metadata = notebook.get("metadata", {})
    language = metadata.get("language_info", {}).get("name") or metadata.get("kernelspec", {}).get("language", "python")
    if language.lower() != "python":
        return [f"kernel language is {language}, not Python"]
    if not any(c.get("cell_type") == "code" and source(c).strip() for c in notebook.get("cells", [])):
        return ["no code cells"]
    return [f"package {name} is on the Pyodide disallow list" for name in dependencies(notebook) if name in PYODIDE_DISALLOWED]


def with_metadata(
    notebook: dict,  # The source notebook, which stays unchanged
    packages: list[str],  # The packages found from its imports
) -> dict:  # A copy with one generated PEP 723 cell
    "Put generated dependency metadata into a copy of a notebook."
    result = copy.deepcopy(notebook)
    cells = []
    for cell in result.get("cells", []):
        code = source(cell)
        if cell.get("cell_type") == "code" and "# /// script" in code:
            rest = re.sub(r"(?ms)^# /// script[^\n]*\n.*?^# ///[ \t]*(?:\n|$)", "", code)
            if not any(line.strip() and not line.lstrip().startswith("#") for line in rest.splitlines()):
                continue
            cell["source"] = rest.splitlines(keepends=True)
        cells.append(cell)
    lines = ["#| include: false\n", "\n", "# /// script\n", '# requires-python = ">=3.10"\n', "# dependencies = [\n"]
    lines += [f"#   {json.dumps(name)},\n" for name in packages]
    lines += ["# ]\n", "# ///\n"]
    position = 1 if cells and cells[0].get("cell_type") == "raw" else 0
    cells.insert(position, {
        "cell_type": "code", "id": "smalldocs-dependencies", "execution_count": None,
        "metadata": {"jupyter": {"source_hidden": True}}, "outputs": [], "source": lines,
    })
    result["cells"] = cells
    return result


def enabled(
    site: Site,  # The site being built
) -> bool:  # Whether browser notebooks are turned on
    "Read the opt-in setting, rejecting values other than true and false."
    value = site.project.smalldocs.get("browser-notebooks", False)
    if not isinstance(value, bool):
        raise ConfigError("browser-notebooks must be true or false")
    return value


def collect(
    site: Site,  # The site whose rendered pages have been discovered
) -> dict[str, dict]:  # Eligible notebooks, keyed by their source paths
    "Lint the site's notebooks and attach passing bundle entries to their pages."
    if not enabled(site):
        return {}
    entries = {}
    for page in site.pages.values():
        if page.src.suffix != ".ipynb" or page.meta.get("browser-runnable") is False:
            continue
        notebook = json.loads((site.root / page.src).read_text(encoding="utf-8-sig"))
        reasons = lint(notebook)
        if reasons:
            site.say(f"{page.src}: browser runner skipped: {'; '.join(reasons)}")
            continue
        entry = {
            "zip": f"site_libs/notebooks/{page.src.with_suffix('.zip')}",
            "notebook": page.src.name, "path": str(page.src.with_suffix("")),
            "dependencies": dependencies(notebook),
        }
        entries[str(page.src)] = entry
        page.env["notebook_bundle"] = entry
    return entries


def require_jupyterlite() -> None:  # Raise BuildError when an optional dependency is missing
    "Check that the optional JupyterLite builder and Pyodide kernel are installed."
    if any(importlib.util.find_spec(name) is None for name in ("jupyterlite_core", "jupyterlite_pyodide_kernel")):
        raise BuildError("browser notebooks need JupyterLite; install it with: pip install 'smalldocs[notebooks]'")


def build_runtime(
    output: Path,  # The lab folder inside the site output
) -> None:  # The JupyterLite files written to output
    "Build the same static JupyterLite apps and Pyodide kernel used by the website runner."
    require_jupyterlite()
    from jupyter_core.paths import jupyter_path

    with tempfile.TemporaryDirectory(prefix="smalldocs-jupyter-") as folder:
        root = Path(folder)
        # Use a temporary working folder so JupyterLite's build database stays out of the project.
        command = [sys.executable, "-m", "jupyterlite_core.app", "build", "--lite-dir", str(root), "--output-dir", str(output)]
        spec = importlib.util.find_spec("jupyterlite_pyodide_kernel")
        candidates = [Path(sys.prefix) / "share/jupyter/labextensions", Path(spec.origin).parent.parent / "share/jupyter/labextensions"]
        known = {Path(path).resolve() for path in jupyter_path("labextensions")}
        for candidate in candidates:
            if candidate.resolve() not in known and (candidate / "@jupyterlite/pyodide-kernel-extension").is_dir():
                command.append(f"--FederatedExtensionAddon.extra_labextensions_path={candidate}")
                break
        result = subprocess.run(command, cwd=root, capture_output=True, text=True)
        if result.returncode:
            raise BuildError(f"JupyterLite build failed:\n{result.stdout}\n{result.stderr}")
    config = json.loads((output / "jupyter-lite.json").read_text())
    if not any(e.get("name") == "@jupyterlite/pyodide-kernel-extension" for e in config["jupyter-config-data"].get("federated_extensions", [])):
        raise BuildError("JupyterLite built without its Pyodide kernel; reinstall smalldocs[notebooks]")


def bundle(
    path: Path,  # The source notebook
    destination: Path,  # The generated zip file
    packages: list[str],  # Packages to put in its PEP 723 cell
) -> list[str]:  # The paths inside the zip
    "Bundle a notebook copy with the files under its assets and data folders."
    notebook = with_metadata(json.loads(path.read_text(encoding="utf-8-sig")), packages)
    destination.parent.mkdir(parents=True, exist_ok=True)
    names = [path.name]
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(path.name, json.dumps(notebook, indent=1, ensure_ascii=False) + "\n")
        for folder in (path.parent / "assets", path.parent / "data"):
            if not folder.is_dir():
                continue
            for file in sorted(folder.rglob("*")):
                if file.is_file() and file.suffix.lower() in BUNDLE_EXTENSIONS and file.resolve().is_relative_to(path.parent.resolve()):
                    name = file.relative_to(path.parent).as_posix()
                    archive.write(file, name)
                    names.append(name)
        archive.writestr("README.md", f"Run this notebook with:\n\n    uvx juv run {shlex.quote(path.name)}\n")
    return names


def build(
    site: Site,  # The site being built
    nav: SiteNav,  # Its navigation, also used by the themed loading page
    entries: dict[str, dict],  # The passing notebook entries
) -> None:  # The browser notebook files written into the site
    "Write bundles, their manifest, and the themed JupyterLite loading page."
    if not entries:
        return
    from . import layout
    from .site import Page

    site.say("Building browser notebooks with JupyterLite")
    build_runtime(site.out / "lab")
    for name, entry in entries.items():
        entry["files"] = bundle(site.root / name, site.out / entry["zip"], entry["dependencies"])
    (site.out / "site_libs/notebooks.json").write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    for name in ("notebooks.css", "notebook-loader.js"):
        shutil.copy2(ASSETS / name, site.out / "site_libs" / name)
    meta = {**site.project.html_options(), "toc": False, "page-navigation": False}
    loader = Page(
        src=PurePosixPath("lab/loader.html"), out=PurePosixPath("lab/loader.html"),
        front={"title": "Run in browser"}, meta=meta, body="", html=(ASSETS / "loader.html").read_text(encoding="utf-8"),
        env={"notebook_loader": True},
    )
    (site.out / "lab/loader.html").write_text(layout.page(site, nav, loader), encoding="utf-8")
