"Write tests/fence_cases.json: how Pandoc reads each fenced-div case, and the differences smalldocs keeps, with why."

import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "tests"))
from test_fences import shape

from smalldocs.markdown import make_parser

CASES = [  # top level
 "::: {.a}\nx\n:::\n", "::: a\nx\n:::\n", ":::{.a}\nx\n:::\n", "::::: {.a}\nx\n:::::\n", "::: {.a}\nx\n::::::\n",
 "::: {.a}\nx\n", "::: {.a}\n::: {.b}\nx\n:::\n:::\n", "::: {.a}\n::: {.b}\nx\n:::\ny\n:::\nz\n",
 "::: {.a}\n```\n:::\n```\n:::\n", "::: {.a}\n~~~\n:::\n~~~\n:::\n", "::: {.a}\n````\n```\n:::\n````\n:::\n",
 "::: {.a}\n    :::\n:::\n", "   ::: {.a}\n   x\n   :::\n", "    ::: {.a}\n    x\n    :::\n",
 "para\n::: {.a}\nx\n:::\n", "::: {.a}\nx\n:::\npara\n", "::: {.a}\n# H\n\nx\n:::\n", "::: {.a} :::\nx\n:::\n",
 ":::\nx\n", "::: {.a}\n\n:::\n", "::: {.a}\n- l1\n- l2\n:::\n", "::: {.a}\n> q\n:::\n",
 # lists
 "- ::: {.a}\n  x\n  :::\n", "- item\n\n  ::: {.a}\n  x\n  :::\n", "- item\n\n  ::: {.a}\n  x\n\nafter\n",
 "- item\n\n  ::: {.a}\n  x\n:::\n\nafter\n", "- item\n\n  ::: {.a}\n  ::: {.b}\n  x\n:::\n:::\n\nafter\n",
 "- item\n\n  ::: {.a}\n  x\nlazy\n", "- item\n\n  ::: {.a}\n  x\n- next\n", "- item\n\n  ::: {.a}\n  x\n\n- next\n",
 "10. ::: {.a}\n    x\n    :::\n", "1. ::: {.a}\n   x\n   :::\n", "- a\n\n  - b\n\n    ::: {.a}\n    x\n    :::\n",
 "- a\n\n  - b\n\n    ::: {.a}\n    x\n\n  CC\n\nDD\n", "- a\n\n  - b\n\n    ::: {.a}\n    x\n    :::\n\n  CC\n",
 "- item\n\n  ::: {.a}\n  ```\n  :::\n  ```\n  :::\n", "- item\n\n  ::: {.a}\n  x\n\n  y\n  :::\nz\n",
 "- item\n\n  ::: {.a}\n  - inner\n  :::\n", "- item\n\n  ::: {.a}\n  x\n\n:::\n", "- item\n\n  ::: {.a}\n  x\n  :::\n  :::\n",
 "- item\n\n      ::: {.a}\n      x\n      :::\n",
 # quotes
 "> ::: {.a}\n> x\n> :::\n", "> ::: {.a}\n> x\n", "> ::: {.a}\n> x\nlazy\n", "> ::: {.a}\n> x\n\nafter\n", "> ::: {.a}\n> x\n:::\n",
 "> ::: {.a}\n> > ::: {.b}\n> > x\n> > :::\n> y\n> :::\n", "> - ::: {.a}\n>   x\n>   :::\n", "> 10. ::: {.a}\n>     x\n>     :::\n",
 # divs holding lists and quotes with fences
 "::: {.a}\n- ::: {.b}\n  x\n  :::\n:::\n", "::: {.a}\n- item\n:::\n", "::: {.a}\n> x\n:::\nafter\n",
 "::: {.a}\n- item\n\n  ::: {.b}\n  x\n:::\n:::\n",
 # markers before fences, inside divs
 "::: {.a}\n- ```\n  :::\n  ```\n:::\n", "::: {.a}\n> ::: {.b}\n> x\n> :::\n:::\n", "::: {.a}\n1. ::: {.b}\n   x\n   :::\n2. y\n:::\n",
 "::: {.a}\n- ::: {.b}\n  - ::: {.c}\n    x\n    :::\n  :::\n:::\n", "::: {.a}\n- item\n- ::: {.b}\n  x\n  :::\n- z\n:::\nafter\n",
 "- ::: {.a}\n  x\n  :::\n- ::: {.b}\n  y\n  :::\n", "- ::: {.a}\n  x\n\n  y\n  :::\n\n  z\n", "* ::: {.a}\n  x\n  :::\n", "1) ::: {.a}\n   x\n   :::\n",
 "- ::: {.a}\n  x\n", "- ::: {.a}\n  x\n\nafter\n", "> ::: {.a}\n> - ::: {.b}\n>   x\n>   :::\n> :::\n",
 "::: {.a}\n---\n:::\n", "::: {.a}\n- - -\n:::\n", "::: {.a}\nx\n- :::\n:::\n",
 "- item\n\n  ::: {.a}\n  x\n\n  ::: {.b}\n  y\n  :::\n  :::\n\nafter\n", "- item\n\n  ::: {.a}\n  x\n  - inner\n:::\n\nafter\n",
 # raw HTML
 "::: {.a}\nx\n<div>y</div>\n:::\n\nafter\n", "::: {.a}\n<div>\n```\n:::\n```\n</div>\n:::\n\nafter\n", "::: {.a}\n<!-- c -->\n:::\nafter\n",
 "- item\n\n  ::: {.a}\n  <span>y</span>\n  :::\n\nafter\n", "<div>\n:::\n</div>\n", "::: {.a}\n<details>\n<summary>s</summary>\n\nbody\n\n</details>\n:::\n",
 # empty and unusual
 "::: {.a}\n:::\n", "::: {.a}\n::: {.b}\n:::\n:::\n", "::: {.a}\n", "- ::: {.a}\n", "> ::: {.a}\n", "::: {.a}\n\n\n:::\n\n\nafter\n",
 "::: {.a}\nx\n:::::::\n", "::: {.a}\nx\n::: :::\n",
 '::: {.a}\n| a | b |\n|---|---|\n| 1 | 2 |\n:::\nafter\n',
 '- item\n\n  ::: {.a}\n  | a |\n  |---|\n  | 1 |\n  :::\n\nafter\n',
 '::: {.a}\n| a |\n|---|\n| 1 |\n\n: caption\n:::\nafter\n',
 '::: {.a}\n$$\nx\n$$\n:::\nafter\n',
 '::: {.a}\n$$x\n:::\n\ny $$\n',
 '::: {.a}\n<!--\n::: {.b}\nold\n:::\n-->\n:::\n\nafter\n',
 '::: {.a}\n<script>\nlet s = `\n:::\n`;\n</script>\n:::\n\nafter\n',
 '::: {.a}\n<pre>\n:::\n</pre>\n:::\n\nafter\n',
 '::: {.a}\n<div>\nx\n:::\n\nafter\n',
 '::: {.a}\n# H\n:::\nafter\n',
 '::: {.a}\nH\n===\n:::\nafter\n',
 '::: {.a}\nx\n***\n:::\nafter\n',
 '::: {.a}\n    code\n:::\nafter\n',
 '::: {.a}\n[r]: http://x\n:::\n[r]\n',
 '::: {.a}\nTerm\n\n:   def\n:::\nafter\n',
 '::: {.a}\nx[^1]\n\n[^1]: note\n:::\nafter\n',
 'Term\n\n:   ::: {.a}\n    x\n    :::\n',
 'x[^1]\n\n[^1]: ::: {.b}\n    y\n    :::\n',
 'x[^1]\n\n[^1]: note\n\n    ::: {.b}\n    y\n    :::\n',
 '::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\nx\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n\nafter\n',
 'x[^abcdef]\n\n[^abcdef]: ::: {.b}\n    y\n    :::\n\nafter\n',
 '-\t::: {.a}\n\tx\n\t:::\n\nafter\n',
 'Term\n\n~   ::: {.a}\n    x\n    :::\n',
 '> - ::: {.a}\n>   x\n:::\n\nafter\n',
 '- > ::: {.a}\n  > x\n  :::\n\nafter\n',
 '::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n- > - x\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n\nAFTER\n',
 '::: {.a}\n<div>\n<!--\n:::\n-->\n</div>\n:::\n\nafter\n',
 '::: {.a}\n| Key | Meaning |\n|---|---|\n| `<!--` | starts a comment |\n:::\n\nAfter\n',
 '::: {.a}\n| a |\n|---|\n| <!-- |\n:::\n\nAfter\n',
 '::: {.a}\n<p>Note <!-- todo\n:::\nstill comment -->\n</p>\n:::\nafter\n',
 '::: {.a}\n<div>\n<!-- a --> b <!-- c\n:::\n-->\n</div>\n:::\n\nafter\n',
 '::: {.a}\n<div>\n<!-- a\n--> b <!-- c\n:::\n-->\n</div>\n:::\n\nafter\n',
 'A[^1].\n\n[^1]:\t::: {.x}\n    in\n    :::\n\nAfter\n',
 'A[^1].\n\n[^1]:::: {.x}\n    in\n    :::\n\nAfter\n',
 '::: {.x}\n$$\n:::\n$$\n:::\n',
 '::: {.x}\ntext <!-- c\n:::\n-->\n:::\n',
 'Text.[^1]\n\n[^1]: \t::: {.x}\n    inside\n    :::\n\nafter\n',
 'Text.[^1]\n\n[^1]: - ::: {.x}\n      inside\n      :::\n\nafter\n',
 '> Text.[^1]\n>\n> [^1]: \t::: {.x}\n>     inside\n>     :::\n\nafter\n',
 '>- ::: {.x}\n>   inside\n>   :::\n\nafter\n',
 'Text.[^ab]\n\n[^ab]: -\t::: {.x}\n        inside\n        :::\n\nafter\n',
 'Text.[^ab]\n\n  [^ab]: - ::: {.x}\n       inside\n       :::\n\nafter\n',
 'Text.[^1]\n\n- item\n\n  [^1]: ::: {.x}\n      inside\n      :::\n\nafter\n',
 '> - ::: {.x}\n>\n>   inside\n>   :::\n\nafter\n',
 '- ::: {.x}\n\n      code\n\n  text\n  :::\n\nafter\n',
 '> ::: {.x}\n> > q\n> :::\n\nafter\n',
 '> ::: {.x}\n>    three\n>\n> + plus\n\nafter\n',
 '- ::: {.x}\n     three\n\n  + plus\n\nafter\n',
 '>- ::: {.x}\n>   :::\n\nafter\n',
 '> ::: {.x}\n> >\n\nafter\n',
 '- > ::: {.x}\n  > >\n\nafter\n',
]

LENIENT = "smalldocs reads more than Pandoc; pages that rely on it build today"
LISTS = "markdown-it's own rule for lists, quotes, footnotes, rules or raw HTML, not the fences"
PLAIN = "the same blocks; Pandoc and markdown-it differ on which text in a list, a definition or raw HTML gets a <p>"
MARKUP = "the same blocks, in Quarto's markup for maths or smalldocs' markup for footnotes"
KEPT = {  # the cases where smalldocs differs from Pandoc on purpose
    "Text.[^ab]\n\n[^ab]: -\t::: {.x}\n        inside\n        :::\n\nafter\n": LISTS,
    "Text.[^ab]\n\n  [^ab]: - ::: {.x}\n       inside\n       :::\n\nafter\n": MARKUP,
    "Text.[^1]\n\n- item\n\n  [^1]: ::: {.x}\n      inside\n      :::\n\nafter\n": LENIENT,
    "Text.[^1]\n\n[^1]: \t::: {.x}\n    inside\n    :::\n\nafter\n": LENIENT,
    "> Text.[^1]\n>\n> [^1]: \t::: {.x}\n>     inside\n>     :::\n\nafter\n": LENIENT,
    "Text.[^1]\n\n[^1]: - ::: {.x}\n      inside\n      :::\n\nafter\n": LISTS,
    '::: {.x}\n$$\n:::\n$$\n:::\n': 'a `:::` ends the div even inside `$$`, where Pandoc reads on as maths',
    '::: {.x}\ntext <!-- c\n:::\n-->\n:::\n': "a `:::` ends the div even after `<!--` in a paragraph; only an HTML block keeps a comment's `:::`",
    "A[^1].\n\n[^1]:\t::: {.x}\n    in\n    :::\n\nAfter\n": LENIENT,
    "A[^1].\n\n[^1]:::: {.x}\n    in\n    :::\n\nAfter\n": MARKUP,
    '::: {.a}\n<div>\n<!-- a --> b <!-- c\n:::\n-->\n</div>\n:::\n\nafter\n': PLAIN,
    '::: {.a}\n<div>\n<!-- a\n--> b <!-- c\n:::\n-->\n</div>\n:::\n\nafter\n': PLAIN,
    "x[^abcdef]\n\n[^abcdef]: ::: {.b}\n    y\n    :::\n\nafter\n": LENIENT,
    '::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n- > - x\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n\nAFTER\n': "markdown-it nests at most 20 levels and drops the rest of the page past them, as it does for lists nested that deep",
    '- item\n\n  ::: {.a}\n  x\n- next\n': PLAIN,
    '- ::: {.a}\n  x\n\n  y\n  :::\n\n  z\n': PLAIN,
    '- item\n\n  ::: {.a}\n  x\n  - inner\n:::\n\nafter\n': PLAIN,
    '::: {.a}\nx\n<div>y</div>\n:::\n\nafter\n': PLAIN,
    '<div>\n:::\n</div>\n': PLAIN,
    '::: {.a}\nTerm\n\n:   def\n:::\nafter\n': PLAIN,
    "::: {.a}\n$$\nx\n$$\n:::\nafter\n": MARKUP,
    "::: {.a}\nx[^1]\n\n[^1]: note\n:::\nafter\n": MARKUP,
    "x[^1]\n\n[^1]: note\n\n    ::: {.b}\n    y\n    :::\n": MARKUP,
    "x[^1]\n\n[^1]: ::: {.b}\n    y\n    :::\n": LENIENT,
    "::: {.a}\n<div>\nx\n:::\n\nafter\n": LISTS,
    "::: {.a}\nx\n***\n:::\nafter\n": LISTS,
    '::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\n::: {.a}\nx\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n:::\n\nafter\n': "markdown-it nests at most 20 levels: the deepest fence shows as text, and nothing after it is lost",
    "   ::: {.a}\n   x\n   :::\n": LENIENT,
    "para\n::: {.a}\nx\n:::\n": LENIENT,
    "::: {.a}\nx\n::: :::\n": LENIENT,
    "- item\n\n  ::: {.a}\n  x\n\n  y\n  :::\nz\n": LISTS,
    "> ::: {.a}\n> > ::: {.b}\n> > x\n> > :::\n> y\n> :::\n": LISTS,
    "::: {.a}\nx\n- :::\n:::\n": LISTS,
    "::: {.a}\n<div>\n```\n:::\n```\n</div>\n:::\n\nafter\n": LISTS,
    "::: {.a}\n- item\n\n  ::: {.b}\n  x\n:::\n:::\n": "Pandoc leaves a stray ::: here; smalldocs closes both divs",
}


def pandoc(
    text: str,  # Markdown
) -> str:  # Pandoc's HTML
    "Render Markdown with Quarto's Pandoc."
    return subprocess.run(["quarto", "pandoc", "-f", "markdown", "-t", "html"], input=text, capture_output=True, text=True, check=True).stdout


def main() -> None:
    "Write the cases; a case that differs from Pandoc and is not in KEPT stops it."
    md, rows, new = make_parser(), [], []
    for case in CASES:
        want, have = shape(pandoc(case)), shape(md.render(case))
        row = {"md": case, "pandoc": want}
        if want != have:
            if case not in KEPT:
                new.append(f"{case!r}\n  pandoc: {want}\n  ours:   {have}")
            row |= {"ours": have, "why": KEPT.get(case, "")}
        rows.append(row)
    if new:
        sys.exit("smalldocs differs from Pandoc:\n" + "\n".join(new))
    out = pathlib.Path(__file__).parent.parent / "tests" / "fence_cases.json"
    out.write_text(json.dumps(rows, indent=1) + "\n")
    print(f"wrote {len(rows)} cases, {sum('ours' in r for r in rows)} kept differences, to {out}")


if __name__ == "__main__":
    main()
