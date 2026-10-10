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

# Build the wheel and the sdist into dist/
build:
    rm -rf dist && uv build
