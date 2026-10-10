"`smalldocs check`: build into a scratch folder, and list what smalldocs ignores, cannot read, and the broken links."

import re
import sys
import tempfile
from pathlib import Path

from .config import load

# Pandoc syntax that smalldocs does not read, with what to say about it.
PANDOC_ONLY = [
    (re.compile(r"^\s*\+[-=:+]+\+\s*$", re.M), "a grid table; write a pipe table"),
    (re.compile(r"(?<![\w`])\[-?@[\w:.-]+"), "a citation; smalldocs has no bibliography"),
    (re.compile(r"\\begin\{(?!aligned|align|equation|matrix|pmatrix|bmatrix|cases|array)"), "raw LaTeX; it is not rendered"),
    (re.compile(r"@(fig|tbl|sec|eq|lst)-[\w-]+"), "a cross-reference; write a link to the id"),
    (re.compile(r"^\s*```\s*\{(python|r|julia|ojs)\b", re.M), "an executable cell; smalldocs shows it but does not run it"),
]


def scan(
    text: str,  # The Markdown of a page
) -> list[tuple[int, str]]:  # The line and the message for each thing smalldocs will not render as Quarto does
    "Find Pandoc-only syntax in a page, outside code blocks."
    found, fence = [], None
    lines = text.split("\n")
    for n, line in enumerate(lines, 1):
        m = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            continue
        for pat, msg in PANDOC_ONLY:
            if pat.search(line):
                found.append((n, msg))
        if m:
            fence = m.group(1)
    return found


def check(
    root: Path,  # The project folder
) -> int:  # 0 when there is nothing to report, 1 otherwise
    "Build the site into a scratch folder and report every warning, Pandoc-only feature and broken link."
    from .site import Site

    project = load(root)
    site = Site(project, quiet=True)
    with tempfile.TemporaryDirectory(prefix="smalldocs-check-") as tmp:
        site.out = Path(tmp) / "_site"
        site.build()
    problems = list(site.warnings)
    for page in site.pages.values():
        if page.src.suffix == ".ipynb":
            continue
        for line, msg in scan((site.root / page.src).read_text(encoding="utf-8")):
            problems.append(f"{page.src}:{line}: {msg}")
    for p in problems:
        print(p)
    print(f"{len(site.pages)} page(s); {len(problems)} thing(s) to look at", file=sys.stderr)
    return 1 if problems else 0
