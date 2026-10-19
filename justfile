# smalldocs: Quarto-like websites from a _quarto.yml project, in pure Python. Run `just` to see this list.

[private]
default:
    @just --list --unsorted

# Run the tests. Extra arguments go to pytest: just test -k listing
[positional-arguments]
test *args:
    uv run pytest "$@"

# Lint with ruff
lint:
    uv run ruff check .

# Build a site: just render ~/Projects/babykev/docs
[positional-arguments]
render *args:
    uv run smalldocs render "$@"

# Build smalldocs' own site into docs/_site and serve it with reload at http://127.0.0.1:4200
docs:
    uv run smalldocs preview docs

# Check the pages of the site against the writing guide (style/GUIDE.md). -v also shows the soft notes
style *args:
    #!/usr/bin/env sh
    set -e
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    python3 -c 'import json,sys; from pathlib import Path; [(Path(sys.argv[1]) / (str(p).replace("/", "__") + ".md")).write_text("\n\n".join("".join(c["source"]) for c in json.loads(p.read_text())["cells"] if c["cell_type"] == "markdown")) for p in Path("docs/guide").rglob("*.ipynb")]' "$tmp"
    python3 style/check.py README.md docs/*.qmd docs/guide/*.qmd docs/news/*.qmd "$tmp"/*.md {{ args }}

# Build the wheel and the sdist into dist/
build:
    rm -rf dist && uv build
