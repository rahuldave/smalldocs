"Write src/smalldocs/quarto_keys.py: the names of Quarto's page options for HTML, read from Quarto's schema."

import pathlib
import subprocess
import sys

import yaml


def schema_dir() -> pathlib.Path:  # Quarto's share/schema folder
    "Find the schema of the installed Quarto."
    quarto = pathlib.Path(subprocess.run(["which", "quarto"], capture_output=True, text=True, check=True).stdout.strip()).resolve()
    return quarto.parent.parent / "share" / "schema"


def html_names(
    q: pathlib.Path,  # Quarto's schema folder
) -> tuple[list[str], str]:  # The option names that apply to HTML, and Quarto's version
    "List the page options in the document-*.yml files that apply to the html format."
    aliases = yaml.safe_load((q / "format-aliases.yml").read_text())["aliases"]

    def expand(f: str) -> set[str]:  # The formats a name or $alias stands for
        names, out = {f}, set()
        while names:
            n = names.pop()
            if n.startswith("$"):
                names |= set(aliases.get(n[1:], []))
            else:
                out.add(n)
        return out

    def for_html(tags: dict | None) -> bool:  # Whether an option applies to html
        fmts = (tags or {}).get("formats")
        if not fmts:
            return True
        pos = set().union(*[expand(f) for f in fmts if not f.startswith("!")])
        neg = set().union(*[expand(f[1:]) for f in fmts if f.startswith("!")])
        return "html" in pos or (not pos and "html" not in neg)

    names = set()
    for f in sorted(q.glob("document-*.yml")):
        for opt in yaml.safe_load(f.read_text()) or []:
            if isinstance(opt, dict) and "name" in opt and for_html(opt.get("tags")):
                names.add(opt["name"])
    version = subprocess.run(["quarto", "--version"], capture_output=True, text=True).stdout.strip()
    return sorted(names), version


def main() -> int:  # The exit code
    "Write the module."
    names, version = html_names(schema_dir())
    lines = "\n".join(f'        "{n}",' for n in names)
    out = pathlib.Path(__file__).parent.parent / "src" / "smalldocs" / "quarto_keys.py"
    out.write_text(
        f'"The names of Quarto {version}\'s page options for HTML, from its schema. scripts/quarto_keys.py writes this file."\n\n'
        f"QUARTO_PAGE_OPTIONS = frozenset(\n    {{\n{lines}\n    }}\n)\n"
    )
    print(f"{len(names)} options from Quarto {version}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
