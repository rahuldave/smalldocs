"Highlight code with Pygments, in the classes that Pandoc and Quarto use (`kw`, `st`, `co`, ...)."

import html

from pygments import lex
from pygments.lexers import DiffLexer, get_lexer_by_name
from pygments.token import Comment, Error, Generic, Keyword, Name, Number, Operator, String, Token
from pygments.util import ClassNotFound

# Most specific first: a token takes the class of the first type it is a subtype of.
CLASSES = [
    (Keyword.Namespace, "im"),
    (Keyword.Constant, "cn"),
    (Keyword.Type, "dt"),
    (Keyword, "kw"),
    (Name.Builtin.Pseudo, "va"),
    (Name.Builtin, "bu"),
    (Name.Function, "fu"),
    (Name.Decorator, "at"),
    (Name.Exception, "dt"),
    (Name.Constant, "cn"),
    (Name.Variable, "va"),
    (Name.Tag, "kw"),
    (Name.Attribute, "at"),
    (String.Char, "ch"),
    (String.Escape, "sc"),
    (String.Interpol, "ss"),
    (String.Regex, "ss"),
    (String.Doc, "st"),
    (String, "st"),
    (Number.Float, "fl"),
    (Number.Hex, "bn"),
    (Number.Oct, "bn"),
    (Number.Bin, "bn"),
    (Number, "dv"),
    (Comment.Preproc, "pp"),
    (Comment.Special, "do"),
    (Comment, "co"),
    (Operator.Word, "kw"),
    (Operator, "op"),
    (Error, "er"),
]
CONTROL = {
    "if", "elif", "else", "for", "while", "return", "break", "continue", "try", "except", "finally", "raise",
    "with", "yield", "match", "case", "do", "switch", "await", "then", "fi", "done", "esac",
}  # fmt: skip
# A diff's lines take classes of their own (Pygments' short names), which smalldocs.css colours red and green.
DIFF_CLASSES = {Generic.Deleted: "gd", Generic.Inserted: "gi", Generic.Subheading: "gu", Generic.Heading: "gh"}
ALIASES = {"patch": "diff", "sh": "bash", "shell": "bash", "zsh": "bash", "console": "console", "py": "python", "js": "javascript", "yml": "yaml"}


def css_class(
    ttype: object,  # A Pygments token type
    value: str,  # The text of the token
) -> str:  # Pandoc's class for it, or empty for plain text
    "Find Pandoc's highlight class for a Pygments token."
    for t, cls in CLASSES:
        if ttype in t:
            return "cf" if cls == "kw" and value in CONTROL else cls
    return ""


def highlight(
    code: str,  # The code
    lang: str,  # Its language, as written after the fence; empty for none
) -> str:  # HTML, escaped, with a span for each highlighted token
    "Highlight code as Quarto does, or only escape it when the language is unknown."
    if not lang:
        return html.escape(code)
    try:
        lexer = get_lexer_by_name(ALIASES.get(lang.lower(), lang.lower()), stripnl=False, ensurenl=False)
    except ClassNotFound:
        return html.escape(code)
    diff = isinstance(lexer, DiffLexer)
    # Many lexers read whole lines, and drop or misread a last line with no newline. So the code gets one,
    # and the output drops it again. A lexer that changes the text keeps the code as written.
    tokens = [t for t in lex(code + "\n", lexer) if t[1]]
    if tokens and tokens[-1][1].endswith("\n") and "".join(v for _, v in tokens) == code + "\n":
        tokens[-1] = (tokens[-1][0], tokens[-1][1][:-1])
    else:
        tokens = list(lex(code, lexer))
    out = []
    for ttype, value in tokens:
        cls = DIFF_CLASSES.get(ttype, "") if diff else css_class(ttype, value.strip()) if ttype is not Token.Text else ""
        out.append(f'<span class="{cls}">{html.escape(value)}</span>' if cls and value.strip() else html.escape(value))
    return "".join(out)
