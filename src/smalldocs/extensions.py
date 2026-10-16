"Theme extensions: `smalldocs add` copies them from a git repository into `_extensions/`, and `theme:` finds them there."

import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

from .config import CONFIG_FILES, BuildError, ConfigError, read_yaml

ASSETS = Path(__file__).parent / "assets"
EXTENSIONS = "_extensions"
SPEC = "smalldocs.yml"  # The file that makes an extension a smalldocs theme
SOURCE = ".source"  # The file that `smalldocs add` writes: where the extension came from
QUARTO_SPECS = ("_extension.yml", "_extension.yaml")
SPEC_KEYS = ("css", "logo", "favicon")
PLAIN = ("default", "bootstrap", "none")  # Bootstrap with no theme
URL = re.compile(r"""url\(\s*(['"]?)([^'")]+?)\1\s*\)|@import\s+(['"])([^'"]+)\3""")


def bundled() -> list[str]:  # The Bootswatch themes, and `bootstrap`
    "List the themes that come with smalldocs."
    return sorted(p.name.split(".")[0] for p in (ASSETS / "vendor" / "bootswatch").glob("*.min.css"))


def is_bootstrap(
    css: str,  # The text of a stylesheet
) -> bool:  # Whether it holds Bootstrap 5.3, as a Bootswatch theme does
    "Tell whether a stylesheet is a whole Bootstrap 5.3 theme: its variables, its colour modes and its components."
    return all(k in css for k in ("--bs-body-bg", "[data-bs-theme=dark]", ".navbar", ".btn", ".dropdown-menu", ".container"))


def css_name(
    name: str,  # A Bootswatch name, such as `cosmo`, or a CSS file, such as `styles/my.min.css`
) -> str:  # The file's name in `site_libs/themes`, such as `cosmo.min.css`
    "Name a theme's CSS file in the site: `cosmo` and `my.css` become `cosmo.min.css` and `my.min.css`, and `x.min.css` stays."
    base = PurePosixPath(name).name
    base = base.removesuffix(".css")
    return base.removesuffix(".min") + ".min.css"


@dataclass
class Extension:
    "A theme in `_extensions/<name>/` or `_extensions/<org>/<name>/`."

    name: str  # What `theme:` calls it: the name of its folder
    path: Path  # Its folder
    spec: dict = field(default_factory=dict)  # What its `smalldocs.yml` holds

    @property
    def where(self) -> str:  # Its folder, from the project root, such as `_extensions/ac215`
        "Say where the extension is, for messages."
        parts = self.path.parts
        return "/".join(parts[parts.index(EXTENSIONS) :]) if EXTENSIONS in parts else str(self.path)

    def file(
        self,
        key: str,  # A key of `smalldocs.yml` that names a file, such as `logo`
        value: object,  # Its value
    ) -> PurePosixPath:  # The file, from the extension's folder
        "Check that a file the extension names is inside its folder and is there."
        if not isinstance(value, str) or not value:
            raise BuildError(f"{self.where}/{SPEC}: {key} must be a file in the folder")
        rel = PurePosixPath(posixpath.normpath(value))
        top = self.path.resolve()
        real = (self.path / rel).resolve()
        # a symbolic link that leaves the folder could publish any file of the computer
        if rel.is_absolute() or not rel.parts or rel.parts[0] == ".." or top not in real.parents or not real.is_file():
            raise BuildError(f"{self.where}/{SPEC}: {key} {value!r} is not a file in {self.where}")
        return rel

    def modes(self) -> list[str]:  # `light`, and `dark` when the theme has one
        "List the modes of the theme: `css: x.css` has one, and `css: {light, dark}` can have two."
        css = self.spec.get("css")
        if isinstance(css, dict):
            return [m for m in ("light", "dark") if css.get(m)] or ["light"]
        return ["light"]

    def css(
        self,
        mode: str,  # `light` or `dark`
    ) -> PurePosixPath:  # The CSS file for that mode, from the extension's folder
        "Find the CSS of a mode; a theme with one file uses it in both modes."
        css = self.spec.get("css")
        if isinstance(css, dict):
            unknown = sorted(set(css) - {"light", "dark"})
            if unknown:
                raise BuildError(f"{self.where}/{SPEC}: css takes light: and dark:, not {', '.join(map(str, unknown))}")
            css = css.get(mode) or css.get("light") or css.get("dark")
        if not css:
            raise BuildError(f"{self.where}/{SPEC}: css is missing; give a CSS file, or light: and dark:")
        return self.file("css", css)


def read_spec(
    folder: Path,  # An extension's folder
) -> dict:  # What its `smalldocs.yml` holds
    "Read an extension's `smalldocs.yml`."
    spec = read_yaml(folder / SPEC) or {}
    if not isinstance(spec, dict):
        raise ConfigError(f"{folder / SPEC}: the top level must be a mapping of keys")
    return spec


def find(
    root: Path,  # The project folder
) -> dict[str, list[Path]]:  # Each theme's name, and the folders that hold a theme of that name
    "Find the themes in `_extensions/<name>/` and `_extensions/<org>/<name>/`: the folders with a `smalldocs.yml`."
    out: dict[str, list[Path]] = {}
    for folder in installed(root):
        if (folder / SPEC).is_file():
            out.setdefault(folder.name, []).append(folder)
    return out


def installed(
    root: Path,  # A project folder, or a cloned repository
) -> list[Path]:  # Each extension's folder, for smalldocs or for Quarto
    "List the extensions in `_extensions/`: the folders, one or two levels down, with a `smalldocs.yml` or an `_extension.yml`."
    base = root / EXTENSIONS
    if base.is_symlink() or not base.is_dir():
        return []
    top = base.resolve()

    def is_ext(d: Path) -> bool:  # Whether the folder is an extension
        return top in d.resolve().parents and d.is_dir() and not d.is_symlink() and any((d / f).is_file() and not (d / f).is_symlink() for f in (SPEC, *QUARTO_SPECS))

    out = []
    for d in sorted(base.iterdir()):
        if d.name.startswith(".") or not d.is_dir() or d.is_symlink():
            continue
        if is_ext(d):
            out.append(d)
        else:
            out += [e for e in sorted(d.iterdir()) if not e.name.startswith(".") and is_ext(e)]
    return out


def lookup(
    root: Path,  # The project folder
    name: str,  # A name in `theme:`
) -> Extension | None:  # The extension, or None when no extension has the name
    "Find the theme extension of a name; a name found twice, or also a Bootswatch name, is an error."
    folders = find(root).get(name, [])
    if len(folders) > 1:
        where = " and ".join(Extension(name, f).where for f in folders)
        raise BuildError(f"theme {name!r} is in {where}: keep one")
    if not folders:
        return None
    ext = Extension(name, folders[0], read_spec(folders[0]))
    if name in bundled() or name in PLAIN:
        raise BuildError(f"theme {name!r} is a Bootswatch theme and also {ext.where}: rename the folder")
    return ext


def css_files(
    css: Path,  # A CSS file in an extension
    ext: Extension,  # The extension
    warn: Callable[[str], None],  # Called with a warning
) -> list[Path]:  # The files it uses through `url(...)` and `@import`, and the files those use
    "Find the local files that a stylesheet uses: fonts, images and other stylesheets in the extension's folder."
    top = ext.path.resolve()
    found: list[Path] = []
    todo, seen = [css], {css.resolve()}
    while todo:
        f = todo.pop()
        for m in URL.finditer(f.read_text(encoding="utf-8-sig", errors="replace")):
            ref = (m.group(2) or m.group(4) or "").strip()
            if not ref or ref.startswith(("#", "/", "data:")) or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:|^//", ref):
                continue
            ref = re.split(r"[?#]", ref)[0]
            dep = (f.parent / ref).resolve()
            if dep in seen:
                continue
            seen.add(dep)
            where = f"{ext.where}/{f.resolve().relative_to(top).as_posix()}"
            if top not in dep.parents:
                warn(f"{where}: {ref} is outside the extension; it is not copied")
            elif not dep.is_file():
                warn(f"{where}: {ref} is not a file; it is not copied")
            else:
                found.append(dep)
                if dep.suffix == ".css":
                    todo.append(dep)
    return found


# ---------------------------------------------------------------- smalldocs add


@dataclass
class Source:
    "Where `smalldocs add` gets extensions: a local folder, or a git repository at a ref."

    text: str  # The source as given; a local path is made absolute, so that `.source` works from any folder
    url: str  # The folder, or the URL that git clones
    ref: str | None = None  # The branch, tag or commit; None for the default branch
    folder: bool = False  # Whether the source is a local folder, copied as it is


def parse_source(
    text: str,  # `org/repo`, `org/repo@ref`, a git URL, a local git repository, or a local folder
) -> Source:  # Where to get the extensions
    "Read the source of `smalldocs add`: `org/repo` is GitHub over ssh, and `@ref` picks a branch, tag or commit."
    if text.startswith("-"):
        raise ConfigError(f"{text}: a source cannot start with -")
    url, ref = text, None
    left, at, right = text.rpartition("@")
    # `git@host:org/repo` has an @ that is not a ref, and so does `https://user@host/repo`. A folder named `a@b` is a folder
    plausible = at and right and ":" not in right and ("/" in left or ":" in left) and not re.match(r"^[\w+.-]+://[^/]*$", left)
    if plausible and not Path(text).expanduser().is_dir():
        url, ref = left, right
    path = Path(url).expanduser()
    if path.is_dir():
        if (path / ".git").exists() or ((path / "HEAD").is_file() and (path / "objects").is_dir()):
            return Source(str(path.resolve()) + (f"@{ref}" if ref else ""), path.resolve().as_uri(), ref)
        if (path / EXTENSIONS).is_dir():
            if ref:
                raise ConfigError(f"{text}: a folder that is not a git repository has no ref; leave out @{ref}")
            return Source(str(path.resolve()), str(path.resolve()), None, folder=True)
        raise ConfigError(f"{text} has no {EXTENSIONS} folder and is not a git repository")
    if re.fullmatch(r"[\w.-]+/[\w.-]+", url):
        return Source(text, f"git@github.com:{url.removesuffix('.git')}.git", ref)
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://|^[\w.-]+@[\w.-]+:", url):
        return Source(text, url, ref)
    raise ConfigError(f"{text}: give org/repo, org/repo@ref, a git URL, or a local folder")


def git(
    *args: str,  # The arguments of git
    cwd: Path | None = None,  # Where to run it
) -> subprocess.CompletedProcess:  # What git returned
    "Run git, and keep what it prints for the message when it fails."
    try:
        return subprocess.run(["git", "-c", "advice.detachedHead=false", *args], cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise BuildError("git is not installed: smalldocs add needs git to clone a repository") from e


def clone(
    src: Source,  # A git repository and a ref
    dest: Path,  # An empty folder
) -> str:  # The commit that was cloned
    "Clone one commit of a repository: `git clone --depth 1`, or a fetch of the commit when the ref is a commit."
    r = git("clone", "--depth", "1", "--quiet", *(["--branch", src.ref] if src.ref else []), "--", src.url, str(dest))
    if r.returncode and src.ref and re.fullmatch(r"[0-9a-f]{40}", src.ref):
        shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir()
        r = git("init", "--quiet", cwd=dest)
        if not r.returncode:
            r = git("fetch", "--depth", "1", "--quiet", "--", src.url, src.ref, cwd=dest)
        if not r.returncode:
            r = git("checkout", "--quiet", "FETCH_HEAD", cwd=dest)
    if r.returncode:
        raise BuildError(f"git could not clone {src.url}{'@' + src.ref if src.ref else ''}:\n{r.stderr.strip()}")
    return git("rev-parse", "HEAD", cwd=dest).stdout.strip()


def copy_extension(
    src: Path,  # An extension's folder in the clone or the local folder
    dest: Path,  # Its folder in the site
    warn: Callable[[str], None],  # Called with a warning
) -> None:
    "Copy an extension's folder without `.git`, `.source` or symbolic links."

    def skip(folder: str, names: list[str]) -> set[str]:  # The names in a folder to leave out
        out = {n for n in names if n in (".git", SOURCE)}
        for n in set(names) - out:
            if (Path(folder) / n).is_symlink():
                warn(f"{Path(folder, n).relative_to(src.parent)} is a symbolic link; it is not copied")
                out.add(n)
        return out

    shutil.copytree(src, dest, ignore=skip)


def ask_tty(
    question: str,  # The question, which ends with `[y/N] `
) -> bool | None:  # The answer; None when there is no terminal to ask in
    "Ask a yes or no question in the terminal."
    if not sys.stdin.isatty():
        return None
    return input(question).strip().lower() in ("y", "yes")


def add(
    text: str,  # The source: `org/repo`, `org/repo@ref`, a git URL, or a local folder
    root: Path | str = ".",  # The project folder
    force: bool = False,  # Replace an extension that is already there, without asking
    ask: Callable[[str], bool | None] = ask_tty,  # Asks before an extension is replaced
) -> list[Path]:  # The folders that were added
    "Copy each extension of a repository or a folder into the project's `_extensions/`, and note where it came from."
    root = Path(root).resolve()
    config = next((n for n in CONFIG_FILES if (root / n).is_file()), None)
    if config is None:
        raise ConfigError(f"{root} has no _smalldocs.yml or _quarto.yml")
    if (root / EXTENSIONS).exists() and not (root / EXTENSIONS).is_dir():
        raise BuildError(f"{root / EXTENSIONS} is a file, not a folder")
    src = parse_source(text)
    warnings: list[str] = []
    added: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="smalldocs-add-") as tmp:
        if src.folder:
            base, commit = Path(src.url), None
        else:
            base = Path(tmp) / "repo"
            print(f"Cloning {src.url}{' at ' + src.ref if src.ref else ''}", file=sys.stderr)
            commit = clone(src, base)
        found = installed(base)
        if not found:
            raise BuildError(f"{text} has no extension: no {EXTENSIONS}/<name>/ with a {SPEC} or an _extension.yml")
        for folder in found:
            rel = folder.relative_to(base / EXTENSIONS)
            dest = root / EXTENSIONS / rel
            where = f"{EXTENSIONS}/{rel.as_posix()}"
            if dest.exists() or dest.is_symlink():
                inner = [e for e in installed(root) if dest in e.parents]
                if inner:
                    names = ", ".join(f"{EXTENSIONS}/{e.relative_to(root / EXTENSIONS).as_posix()}" for e in inner)
                    raise BuildError(f"{where} holds other extensions, {names}: move them before you add {where}")
                if not force:
                    answer = ask(f"{where} is already there. Replace it? [y/N] ")
                    if answer is None:
                        raise BuildError(f"{where} is already there: give --force to replace it")
                    if not answer:
                        print(f"Kept {where}", file=sys.stderr)
                        continue
                shutil.rmtree(dest) if dest.is_dir() and not dest.is_symlink() else dest.unlink()
            dest.parent.mkdir(parents=True, exist_ok=True)
            copy_extension(folder, dest, warnings.append)
            note = {"source": src.text, "ref": src.ref, "commit": commit}
            (dest / SOURCE).write_text(yaml.safe_dump(note, sort_keys=False), encoding="utf-8")
            added.append(dest)
            print(f"Added {where}{f' at {commit[:7]}' if commit else ''}")
            if not (dest / SPEC).is_file():
                print(f"  It has no {SPEC}, so it is not a smalldocs theme.")
                continue
            if folder.name in bundled() or folder.name in PLAIN:
                print(f"  Its name is also a Bootswatch theme, so theme: {folder.name} is an error. Rename the folder.")
                continue
            if config.startswith("_smalldocs"):
                print(f"  Use it with this line in {config}:\n    theme: {folder.name}")
            else:
                print(f"  Use it with these lines in {config}:\n    smalldocs:\n      theme: {folder.name}")
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    return added


def read_source(
    folder: Path,  # An extension's folder
) -> dict:  # Its `.source`: `source`, `ref` and `commit`; empty when it has none
    "Read where an extension came from."
    try:
        note = yaml.safe_load((folder / SOURCE).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return note if isinstance(note, dict) else {}


def themes(
    root: Path | str = ".",  # The project folder
) -> int:  # The exit code
    "Print the bundled themes, and the project's extensions with where each came from."
    root = Path(root).resolve()
    print("Bundled themes, from Bootswatch 5.3.8:")
    names = bundled()
    for i in range(0, len(names), 8):
        print("  " + ", ".join(names[i : i + 8]))
    print("  bootstrap: Bootstrap with no theme")
    exts = installed(root)
    if not exts:
        print(f"\nNo extensions in {EXTENSIONS}/. Add one with: smalldocs add org/repo")
        return 0
    print(f"\nExtensions in {EXTENSIONS}/:")
    for folder in exts:
        ext = Extension(folder.name, folder)
        if (folder / SPEC).is_file():
            try:
                ext.spec = read_spec(folder)
                kind = "theme, " + " and ".join(ext.modes())
            except ConfigError as e:
                kind = f"theme with an error: {e}"
        else:
            kind = f"not a smalldocs theme: it has no {SPEC}"
        print(f"  {ext.where}  ({kind})")
        note = read_source(folder)
        if note.get("source"):
            commit = f", commit {str(note['commit'])[:7]}" if note.get("commit") else ""
            print(f"    from {note['source']}{commit}")
            again = str(note["source"])
            latest = again.removesuffix(f"@{note['ref']}") if note.get("ref") else again
            if latest != again:
                print(f"    again:  smalldocs add {again} --force")
            print(f"    newest: smalldocs add {latest} --force")
        else:
            print("    no .source: it was not added with smalldocs add")
    return 0
