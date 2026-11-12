"""The API reference, made from the code: docstrings, types and docments, as plain Markdown and as site pages.

    smalldocs api build          one page per module into the site, and the index of names for links
    smalldocs api check          what is typed and documented, and every gap; exit 1 if any
    smalldocs api module NAME    one module as plain Markdown
    smalldocs api list           every module, class, method and function, one line each

Types come from the annotations, the description of a parameter from its docment (the comment beside
it, read by fastcore), and the summary from the docstring. A dataclass shows its constructor, a pydantic
model its fields with their descriptions or the comment beside each, a TypedDict its keys with the comment
beside each, and a click command its function and its options. The settings are `api` in `_smalldocs.yml`,
or `smalldocs.api` in `_quarto.yml`:

    api:
      packages: [mypkg]                   # importable packages to document
      out: api                            # the folder of pages, inside the site
      root: ..                            # the repository's root, from the site's folder
      source: https://github.com/me/mypkg/blob/main   # where `source` links point
      check: ["*.py", "docs/*.py", "tests/**/*.py"]  # more files that `check` holds to the convention, from the root
"""

import ast
import builtins
import importlib
import importlib.util
import inspect
import json
import re
import sys
import textwrap
import tokenize
import types
import typing
from dataclasses import dataclass, is_dataclass
from pathlib import Path
from pkgutil import walk_packages
from types import FunctionType, ModuleType

from fastcore.docments import docments

from .config import glob_regex

EMPTY = inspect.Parameter.empty
TOOL_COMMENT = re.compile(r"(type|noqa|pragma|fmt|pyright|mypy|pylint|ruff)\b")  # `# type: ignore` and its kind say nothing of a field
HEADING = re.compile(r"^(#+) (?:class )?(\S+)$")

Code = FunctionType | type


@dataclass(frozen=True)
class Symbol:
    "One line of the inventory: a module, a class, a method or a function, and where it is."

    module: str  # The module's full name, such as `mypkg.api`
    name: str  # `render` or `Choice._check`: the name inside the module; empty for the module
    kind: str  # `module`, `class`, `method` or `function`
    summary: str  # The first line of the docstring, or empty when there is none
    line: int  # The line the definition starts on; 1 for a module


# ---------------------------------------------------------------- finding what to document


def package_modules(
    package: str,  # The name of an importable package, or of a single module
) -> list[ModuleType]:  # The package, when its `__init__` defines code, then its public modules and its subpackages', in name order
    "Import every public module of a package, its subpackages' too, in name order; the package itself when it defines code."
    pkg = importlib.import_module(package)
    if not hasattr(pkg, "__path__"):
        return [pkg]
    names = sorted(m.name for m in walk_packages(pkg.__path__, prefix=f"{package}.") if not any(p.startswith("_") for p in m.name.split(".")))
    mods = [pkg, *(importlib.import_module(n) for n in names)]
    return [m for m in mods if not hasattr(m, "__path__") or own(m)]  # a package's `__init__` only when it defines code


def file_modules(
    files: list[Path],  # Python files that are not part of a package
    root: Path | None = None,  # The folder that names start from; `None` names each file by its full path
) -> list[ModuleType]:  # One module per file, named by its path, in the order given
    "Import Python files as modules of their own, named by their paths from the root, such as `tests/test_x.py`."
    mods = []
    for file in files:
        name = file.relative_to(root).as_posix() if root and file.is_relative_to(root) else file.as_posix()
        spec = importlib.util.spec_from_file_location(name, file)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {name}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        mods.append(mod)
    return mods


def module(
    name: str,  # The module's short name, `api`, or its full name, `mypkg.api`
    packages: list[str],  # The packages to look in
) -> ModuleType:  # The imported module; `LookupError` when there is no such module
    "Find one module by its short name or its full name."
    for pkg in packages:
        for mod in package_modules(pkg):
            if name in (mod.__name__, mod.__name__.rpartition(".")[2]):
                return mod
    raise LookupError(name)


def doc(
    obj: object,  # A module, class or function
) -> str:  # Its own docstring, cleaned of its indentation; empty when there is none
    "Read an object's own docstring, cleaned of its indentation; empty when there is none."
    return inspect.cleandoc(obj.__doc__) if isinstance(obj.__doc__, str) else ""


def summary(
    obj: object,  # A module, class or function
) -> str:  # The first line of its docstring; empty when there is none
    "Read the first line of an object's docstring."
    return doc(obj).partition("\n")[0]


def line_of(
    sym: Code,  # A function, method or class
) -> int:  # The line its definition starts on
    "Find the line a symbol's definition starts on, to keep symbols in source order."
    try:
        return inspect.getsourcelines(sym)[1]
    except (OSError, TypeError):
        return 0


def unwrapped(
    obj: object,  # Anything a module or a class holds under a name
) -> object:  # The function inside it when it is a decorator's wrapper or a click command; otherwise the object itself
    "See through a decorator that kept the function, as `functools.wraps`, a fixture and a click command do."
    if is_command(obj):
        return obj.callback  # a click command or group keeps its function in `callback`
    inner = getattr(obj, "__func__", obj)
    return inspect.unwrap(inner) if callable(inner) and hasattr(inner, "__wrapped__") else inner


def is_command(
    obj: object,  # Anything a module holds under a name
) -> bool:  # Whether it is a click command or group, found by its shape, without importing click
    "Tell whether an object is a click command: it has a function in `callback`, a list in `params` and a `name`."
    if inspect.isclass(obj) or inspect.isfunction(obj):
        return False
    try:
        return inspect.isfunction(getattr(obj, "callback", None)) and isinstance(getattr(obj, "params", None), list) and isinstance(getattr(obj, "name", None), str)
    except Exception:  # an object whose attributes fail
        return False


def command_of(
    func: FunctionType,  # A function
    mod: ModuleType,  # The module it was written in
) -> object | None:  # The click command or group in the module whose function it is; `None` when there is none
    "Find the click command that a function is the callback of, to list its options."
    for o in vars(mod).values():
        if is_command(o) and o.callback is func:
            return o
    return None


def own(
    mod: ModuleType,  # An imported module
    private: bool = False,  # Include names that start with an underscore
) -> list[Code]:  # The functions and classes the module defines, in source order
    "List the functions and classes a module defines itself, in source order; not its imports."
    exported = getattr(mod, "__all__", None)
    found = [
        o
        for n, o in ((n, unwrapped(o)) for n, o in vars(mod).items())
        if (private or not n.startswith("_"))
        and not is_dunder(n)
        and (exported is None or private or n in exported)
        and (inspect.isfunction(o) or inspect.isclass(o))
        and getattr(o, "__module__", None) == mod.__name__
    ]
    return sorted({id(o): o for o in found}.values(), key=line_of)  # a function and its command are one entry


def is_dunder(
    name: str,  # An attribute name
) -> bool:  # Whether it is one of Python's own, written `__like_this__`
    "Tell whether a name is one of Python's own, such as `__init__`: a dataclass writes those."
    return name.startswith("__") and name.endswith("__")


def methods(
    klass: type,  # A class
    private: bool = False,  # Include names that start with one underscore
) -> list[FunctionType]:  # The methods the class defines, in source order
    "List the methods a class defines itself, in source order, not what it inherits."
    found = [(n, unwrapped(o)) for n, o in vars(klass).items() if not is_dunder(n)]
    own_ = [o for n, o in found if (private or not n.startswith("_")) and inspect.isfunction(o)]
    return sorted({id(o): o for o in own_}.values(), key=line_of)  # an alias, `abandon = discard`, is one entry


def entries(
    mod: ModuleType,  # An imported module
    private: bool = False,  # Include private names, and names outside `__all__`
) -> list[tuple[Code, int]]:  # Each function, class and method, with its heading level: 2 at the top, 3 for a method
    "List the symbols of a module in the order of its page, each class followed by its methods."
    return [(s, lvl) for t in own(mod, private=private) for s, lvl in [(t, 2), *((m, 3) for m in (methods(t, private=private) if inspect.isclass(t) else []))]]


def held(
    mod: ModuleType,  # An imported module
    shown: bool = False,  # Hold only what the module's page shows
) -> list[Code]:  # Every function, class and method in it, private ones and those outside `__all__` too; or only those its page shows
    "List everything `check` holds to the convention: every function, class and method, or only what the page shows."
    return [s for s, _ in entries(mod, private=not shown)]


def inventory(
    packages: list[str],  # The names of importable packages
) -> list[Symbol]:  # One entry per public module, class, method and function, in source order
    "List every public module, class, method and function of the packages, with its summary."
    out = []
    for pkg in packages:
        for mod in package_modules(pkg):
            out.append(Symbol(mod.__name__, "", "module", summary(mod), 1))
            for top in own(mod):
                kind = "class" if inspect.isclass(top) else "function"
                out.append(Symbol(mod.__name__, top.__qualname__, kind, summary(top), line_of(top)))
                if inspect.isclass(top):
                    out += [Symbol(mod.__name__, m.__qualname__, "method", summary(m), line_of(m)) for m in methods(top)]
    return out


# ---------------------------------------------------------------- writing it as Markdown


def name_of(
    anno: object,  # A type, as an annotation holds it
    mod: ModuleType,  # The module the annotation was written in
) -> str | None:  # The name that module gives the type, or `None` when it has none
    "Find what a module calls a type: an alias such as `JSONContent`, or the name it imported."
    for name, value in vars(mod).items():
        if name.startswith("_") or inspect.ismodule(value) or value is None:
            continue
        if isinstance(value, type) and getattr(builtins, value.__name__, None) is value and name != value.__name__:
            continue  # `Number = int` must not rename every `int`; `ModuleType` is no builtin name and stays
        named = (typing.TypeVar, typing.ParamSpec, typing.TypeVarTuple, typing.NewType)
        if not (isinstance(value, (type, *named)) or typing.get_origin(value) is not None or type(value).__name__ == "TypeAliasType"):
            continue  # a constant or an instance is no name for a type
        try:
            if value is anno or (typing.get_origin(value) is not None and value == anno):
                return name
        except Exception:  # an object whose == fails, such as an array
            continue
    return None


def type_text(
    anno: object,  # A type, as an annotation holds it
    mod: ModuleType,  # The module the annotation was written in
) -> str:  # The type as the source would write it
    "Write a type the way the source does: `JSONContent`, not the union it stands for."
    if isinstance(anno, str):
        return anno
    if isinstance(anno, typing.ForwardRef):
        return anno.__forward_arg__
    if isinstance(anno, list):  # the arguments of a Callable
        return "[" + ", ".join(type_text(a, mod) for a in anno) + "]"
    if name := name_of(anno, mod):
        return name
    origin, args = typing.get_origin(anno), typing.get_args(anno)
    if origin in (typing.Union, types.UnionType):
        return " | ".join(type_text(a, mod) for a in args)
    if origin is typing.Literal:
        return f"Literal[{', '.join(repr(a) for a in args)}]"
    if origin is not None:
        return f"{type_text(origin, mod)}[{', '.join(type_text(a, mod) for a in args)}]"
    if anno is None or anno is type(None):
        return "None"
    if anno is Ellipsis:
        return "..."
    if isinstance(anno, type):
        return anno.__name__
    named = [n for n, v in vars(mod).items() if v is anno and not n.startswith("_")]
    if named:
        return named[0]  # an object used as a type, such as fastcore's `Head`: its name, not its repr with an address
    return re.sub(r" at 0x[0-9a-f]+", "", repr(anno)).replace("typing.", "")  # no memory address, so a page is the same at each build


def default_text(
    value: object,  # A parameter's default value
) -> str:  # It as Python: a function by its name, anything else by its repr
    "Write a default value; a function's repr holds its memory address, which changes at each build, so a function is written by its name."
    if inspect.isfunction(value) or inspect.isbuiltin(value) or inspect.ismethod(value):
        return value.__qualname__
    if isinstance(value, (set, frozenset)) and value and type(value).__repr__ in (set.__repr__, frozenset.__repr__):
        # a set of strings is in the order of the hash seed, so sort it to keep the page the same: numbers as numbers, the rest by
        # their text, because `<` between sets means "is a subset of" and orders nothing. Only the set at the top level is sorted
        numbers = all(isinstance(v, (int, float)) for v in value)
        ordered = sorted(value) if numbers else sorted(value, key=default_text)
        items = ", ".join(default_text(v) for v in ordered)
        return f"{{{items}}}" if type(value) is set else f"{type(value).__name__}({{{items}}})"
    return re.sub(r" at 0x[0-9a-f]+", "", repr(value))  # no memory address, as in `type_text`


def signature_of(
    sym: Code,  # A function, method or class
) -> inspect.Signature:  # Its signature; for a class with an `__init__`, never only `(*args, **kwargs)`
    "Read a signature; when a metaclass's `__call__` hides a class's `__init__`, read that of `__init__`."
    sig = inspect.signature(sym)
    kinds = [p.kind for p in sig.parameters.values()]
    if inspect.isclass(sym) and kinds == [inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD] and sym.__init__ is not object.__init__:
        return inspect.signature(sym.__init__)  # its own `__init__`, or one it inherits
    return sig


def signature(
    sym: Code,  # A function, method or class
    mod: ModuleType,  # The module it was written in
) -> str:  # Its parameters and return as one line of Python, without the name
    "Write a signature as one line of Python: each parameter with its type and default."
    sig, parts, star = signature_of(sym), [], False
    for p in sig.parameters.values():
        if p.name in ("self", "cls"):
            continue
        if p.kind is p.KEYWORD_ONLY and not star:
            parts.append("*")
        star = star or p.kind in (p.KEYWORD_ONLY, p.VAR_POSITIONAL)
        prefix = {p.VAR_POSITIONAL: "*", p.VAR_KEYWORD: "**"}.get(p.kind, "")
        text = prefix + p.name
        if p.annotation is not EMPTY:
            text += f": {type_text(p.annotation, mod)}"
        if p.default is not EMPTY:
            text += f" = {default_text(p.default)}"
        parts.append(text)
    if inspect.isclass(sym) or sig.return_annotation is EMPTY:
        return f"({', '.join(parts)})"
    return f"({', '.join(parts)}) -> {type_text(sig.return_annotation, mod)}"


def cell(
    text: str,  # The text of one cell
) -> str:  # The same text with every `|` escaped
    "Make text safe inside a Markdown table cell."
    return text.replace("|", "\\|")


def table(
    rows: list[list[str]],  # The cells of each row
    head: list[str],  # The column titles
) -> str:  # A Markdown table; empty when there are no rows
    "Write a Markdown table, or nothing when there are no rows."
    if not rows:
        return ""
    lines = [head, ["---"] * len(head), *rows]
    return "\n".join("| " + " | ".join(cell(c) for c in row) + " |" for row in lines)


def safe_docments(
    sym: Code,  # A function, method or class
) -> dict:  # Each parameter's annotation, default and docment, under its name, and `return`
    "Read the docments, or, for code with no source (made by `exec`, or compiled), the signature alone."
    try:
        return docments(sym, full=True, args_kwargs=True)
    except (OSError, TypeError, SyntaxError):
        from types import SimpleNamespace

        try:
            sig = inspect.signature(sym)
        except (TypeError, ValueError):
            return {}
        out = {n: SimpleNamespace(anno=p.annotation, default=p.default, docment=None) for n, p in sig.parameters.items()}
        out["return"] = SimpleNamespace(anno=sig.return_annotation, default=EMPTY, docment=None)
        return out


def starred(
    sym: Code,  # A function, method or class
) -> set[str]:  # The names of its `*args` and `**kwargs`, which take no default and are never required
    "Find the names of the `*args` and `**kwargs` of a function."
    try:
        params = signature_of(sym).parameters.values()
    except (TypeError, ValueError):
        return set()
    return {p.name for p in params if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD)}


def params_table(
    sym: Code,  # A function, method or dataclass
    mod: ModuleType,  # The module it was written in
) -> str:  # A Markdown table of its parameters and its return: type, default, description
    "Describe a function by its parameters and its return: type, default, docment."
    rows = []
    for name, d in safe_docments(sym).items():
        if name in ("self", "cls"):
            continue
        anno = "" if d.anno is EMPTY else type_text(d.anno, mod)
        if name == "return":
            if d.anno is not EMPTY and d.anno is not None and d.anno != "None":
                rows.append(["returns", anno, "", d.docment or ""])
            continue
        default = "" if name in starred(sym) else "required" if d.default is EMPTY else f"`{default_text(d.default)}`"
        rows.append([f"`{name}`", anno, default, d.docment or ""])
    return table(rows, ["Parameter", "Type", "Default", "Description"])


def is_model(
    klass: type,  # A class
) -> bool:  # Whether it is a pydantic model, found by its shape, without importing pydantic
    "Tell whether a class is a pydantic model: it has a dict of `model_fields` whose values say if they are required."
    fields = getattr(klass, "model_fields", None)
    return isinstance(fields, dict) and all(hasattr(f, "is_required") for f in fields.values())


def fields_table(
    model: type,  # A pydantic model class
    mod: ModuleType,  # The module it was written in
) -> str:  # A Markdown table of its fields: type, default, description
    "Describe a pydantic model by its fields, because its constructor signature says nothing."
    said = field_descriptions(model)
    rows = []
    for name, f in model.model_fields.items():
        default = "required" if f.is_required() else f"`{default_text(f.default)}`"
        rows.append([f"`{name}`", type_text(f.annotation, mod), default, said.get(name, "")])
    return table(rows, ["Field", "Type", "Default", "Description"])


def field_descriptions(
    model: type,  # A pydantic model class
) -> dict[str, str]:  # For each field that has one, its description
    "Describe each field of a model: its `description` when it has one, or else the comment beside it."
    said = key_comments(model)
    return {n: f.description or said[n] for n, f in model.model_fields.items() if f.description or n in said}


def class_comments(
    klass: type,  # A class
) -> dict[str, str]:  # For each name annotated in the class body, the comment beside it
    "Read the comment beside each annotated name in one class body, such as `title: str  # The title`."
    try:
        lines, _ = inspect.getsourcelines(klass)
    except (OSError, TypeError):
        return {}
    src = textwrap.dedent("".join(lines))
    try:
        body = ast.parse(src).body[0]
        comments = {t.start[0]: t.string.lstrip("#").strip() for t in tokenize.generate_tokens(iter(src.splitlines(True)).__next__) if t.type == tokenize.COMMENT}
    except (SyntaxError, tokenize.TokenError):
        return {}
    out = {}
    for node in getattr(body, "body", []):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            said = comments.get(node.lineno) or comments.get(node.end_lineno or node.lineno)  # on the first line, or the last
            if said and not TOOL_COMMENT.match(said):
                out[node.target.id] = said
    return out


def key_comments(
    klass: type,  # A TypedDict or a model class
) -> dict[str, str]:  # For each key that has one, the comment beside it, from the class and the classes it inherits
    "Read the docments of a TypedDict's keys or a model's fields: the comment beside each, a subclass's first."
    out: dict[str, str] = {}
    for k in reversed(parents(klass)):
        if k.__module__ not in ("builtins", "typing", "typing_extensions") and not k.__module__.startswith("pydantic"):
            out.update(class_comments(k))
    return out


def parents(
    klass: type,  # A class
) -> list[type]:  # The class, then the classes it inherits, nearest first
    "List a class and its parents; a TypedDict's parents are in `__orig_bases__`, because its `__mro__` is that of a dict."
    if not typing.is_typeddict(klass):
        return list(getattr(klass, "__mro__", (klass,)))
    out = [klass]
    for b in getattr(klass, "__orig_bases__", ()):
        if typing.is_typeddict(b):
            out += [p for p in parents(b) if p not in out]
    return out


def options_table(
    command: object,  # A click command or group
) -> str:  # A Markdown table of its options and arguments: names, default, help
    "Describe a click command's options and arguments, as its `--help` does."
    rows = []
    for p in command.params:
        if getattr(p, "param_type_name", "") == "argument":
            names = f"`{getattr(p, 'human_readable_name', p.name)}`"  # an argument by its name in `--help`, such as `NAME`
        else:
            names = ", ".join(f"`{o}`" for o in [*getattr(p, "opts", []), *getattr(p, "secondary_opts", [])])
        if getattr(p, "metavar", None) and getattr(p, "param_type_name", "") != "argument":
            names += f" `{p.metavar}`"
        default = getattr(p, "default", None)
        unset = default is None or callable(default) or repr(default).startswith("Sentinel.")  # click 8.3 marks no default with `Sentinel.UNSET`
        shown = "" if unset or getattr(p, "is_flag", False) else f"`{default!r}`"
        rows.append([names, shown, getattr(p, "help", None) or ""])
    return table(rows, ["Option", "Default", "Help"])


def keys_table(
    klass: type,  # A TypedDict class
    mod: ModuleType,  # The module it was written in
) -> str:  # A Markdown table of its keys: type, description
    "Describe a TypedDict by its keys, because calling it says nothing."
    said = key_comments(klass)
    rows = [[f"`{n}`", type_text(a, mod), said.get(n, "")] for n, a in klass.__annotations__.items()]
    return table(rows, ["Key", "Type", "Description"])


def has_init(
    klass: type,  # A class
) -> bool:  # Whether it has a constructor of its own, written by hand or by `dataclass`
    "Tell whether a class has a constructor of its own to show, as a dataclass does."
    return is_dataclass(klass) or "__init__" in vars(klass)


def entry(
    sym: Code,  # A function, method or class
    level: int,  # The heading level of its entry: 2 for a top-level symbol, 3 for a method
) -> str:  # The Markdown of one entry
    "Write one symbol: a heading, its signature, its docstring and the table of its parameters."
    mod = sys.modules[sym.__module__]
    is_class = inspect.isclass(sym)
    head = f"{'#' * level} {'class ' if is_class else ''}{sym.__qualname__}"
    if is_class and is_model(sym):
        parts = [head, doc(sym), fields_table(sym, mod)]
    elif is_class and typing.is_typeddict(sym):
        parts = [head, doc(sym), keys_table(sym, mod)]
    elif is_class and not has_init(sym):
        parts = [head, doc(sym)]
    else:
        prefix = "async " if inspect.iscoroutinefunction(sym) else ""
        code = f"```python\n{prefix}{sym.__qualname__}{signature(sym, mod)}\n```"
        parts = [head, code, doc(sym), params_table(sym, mod)]
        command = None if is_class else command_of(sym, mod)
        if command is not None:
            parts.append(options_table(command))
    return "\n\n".join(p for p in parts if p)


def module_markdown(
    mod: ModuleType,  # An imported module
) -> str:  # The whole module as plain Markdown
    "Write one module as plain Markdown: its docstring, then an entry for each public symbol."
    parts = [f"# {mod.__name__}", doc(mod)]
    parts += [entry(sym, level) for sym, level in entries(mod)]
    return "\n\n".join(p for p in parts if p) + "\n"


def markdown(
    name: str,  # The module's short name, `api`, or its full name, `mypkg.api`
    packages: list[str],  # The packages to look in
) -> str:  # The whole module as plain Markdown
    "Write one module, found by name, as plain Markdown."
    return module_markdown(module(name, packages))


# ---------------------------------------------------------------- checking the convention


def gaps_of(
    sym: Code,  # A function, method or class
) -> list[str]:  # One message per gap; empty when the symbol is fully typed and documented
    "Find what one symbol is missing: a docstring, a type, a docment, or a field description."
    name, out = f"{sym.__module__}:{sym.__qualname__}", []
    if not doc(sym):
        out.append(f"{name}: no docstring")
    is_class = inspect.isclass(sym)
    if is_class and is_model(sym):
        said = field_descriptions(sym)
        return out + [f"{name}.{n}: no description" for n in sym.model_fields if n not in said]
    if is_class and typing.is_typeddict(sym):
        said = key_comments(sym)
        return out + [f"{name}.{n}: no docment" for n in sym.__annotations__ if n not in said]
    if is_class and not has_init(sym):
        return out
    for pname, d in safe_docments(sym).items():
        if pname in ("self", "cls"):
            continue
        if pname == "return":
            if d.anno is EMPTY and not is_class:
                out.append(f"{name}: no return type")
            elif d.anno is not None and d.anno != "None" and not d.docment and not is_class:  # `None` is a string under `from __future__ import annotations`
                out.append(f"{name}: no return docment")
            continue
        if d.anno is EMPTY:
            out.append(f"{name}({pname}): no type")
        if not d.docment:
            out.append(f"{name}({pname}): no docment")
    return out


def gaps(
    mod: ModuleType,  # An imported module
    shown: bool = False,  # Look only at what the module's page shows
) -> dict[str, list[str]]:  # The gaps of each symbol under its name, the module's under its own
    "Find every gap in a module, under the module's name and then under each symbol's."
    out = {mod.__name__: [] if doc(mod) else [f"{mod.__name__}: no module docstring"]}
    for sym in held(mod, shown):
        out[sym.__qualname__] = gaps_of(sym)
    return out


def check(
    packages: list[str],  # The packages to hold to the convention
    files: list[Path],  # More Python files to hold to it, such as the tests
    root: Path | None = None,  # The folder that the names of the files start from
    shown: bool = False,  # Hold the packages only to what their pages show; the files are held in full
) -> int:  # The exit code: 0 when nothing is missing, 1 otherwise
    "Print how much of each module is typed and documented, then every gap, then the total."
    found, done, total = [], 0, 0
    pkg_mods = [m for p in packages for m in package_modules(p)]
    mods = pkg_mods + file_modules(files, root)
    width = max((len(m.__name__) for m in mods), default=10)
    for i, mod in enumerate(mods):
        missing = gaps(mod, shown and i < len(pkg_mods))
        found += missing.pop(mod.__name__)
        complete = sum(not g for g in missing.values())
        print(f"{mod.__name__:{width}s} {complete:3d} of {len(missing):3d}")
        found += [message for g in missing.values() for message in g]
        done, total = done + complete, total + len(missing)
    print("\n".join(["", *found]) if found else "")
    print(f"{done} of {total} functions, methods and classes are typed and documented")
    return 1 if found else 0


# ---------------------------------------------------------------- the site's pages


@dataclass
class Settings:
    "What the api settings say: `api` in `_smalldocs.yml`, or `smalldocs.api` in `_quarto.yml`."

    site: Path  # The site's folder, which holds the config
    packages: list[str]  # The packages to document
    out: str = "api"  # The folder of pages, inside the site
    root: Path | None = None  # The repository's root, for source links and the files of `check`
    source: str = ""  # The URL that a file's path is added to for its `source` link
    check: tuple[str, ...] = ()  # Globs, from the root, of more files that `check` holds to the convention; `**/` is any folders or none
    linkify: bool = True  # Whether a name in backticks links to its entry
    shown: bool = False  # Whether `check` holds the packages only to what their pages show, from `check-shown`
    language: str = "python"  # The language of the code: `python`, `rust` or `typescript`
    entry: tuple[str, ...] = ()  # TypeScript: the entry points, files or folders, from the site's folder
    tsconfig: str = ""  # TypeScript: the tsconfig, from the site's folder; empty lets TypeDoc find it
    manifest: Path | None = None  # Rust: the crate's Cargo.toml; `None` is the one at the root
    toolchain: str = "nightly"  # Rust: the toolchain that runs rustdoc
    private: bool = False  # Rust: document private items too

    @classmethod
    def read(
        cls,
        site: Path,  # The site's folder
        conf: dict,  # The `smalldocs.api` section
    ) -> "Settings":  # The settings, with defaults
        "Read the settings from the config."
        language = str(conf.get("language", "python"))
        if language not in ("python", "rust", "typescript"):
            raise ValueError(f"the api settings: language must be python, rust or typescript, not {language!r}")
        if language != "python":
            return cls.read_other(site, conf, language)
        pkgs = conf.get("packages") or conf.get("package") or []
        pkgs = [pkgs] if isinstance(pkgs, str) else list(pkgs)
        if not pkgs:
            raise ValueError("the api settings need packages: the importable packages to document")
        at_root = (site / "pyproject.toml").exists() or (site / ".git").exists()
        root = (site / str(conf.get("root", "." if at_root else ".."))).resolve()
        chk = conf.get("check") or []
        shown = conf.get("check-shown", False)
        if not isinstance(shown, bool):
            raise ValueError(f"check-shown must be true or false, not {shown!r}")
        return cls(site, pkgs, str(conf.get("out", "api")).strip("/"), root, str(conf.get("source", "")).rstrip("/"), tuple([chk] if isinstance(chk, str) else chk), conf.get("linkify", True) is not False, shown)

    @classmethod
    def read_other(
        cls,
        site: Path,  # The site's folder
        conf: dict,  # The `api` section
        language: str,  # `rust` or `typescript`
    ) -> "Settings":  # The settings, with defaults
        "Read the settings of a crate or a TypeScript package, which has no packages to import."
        marks = ("Cargo.toml", "package.json", ".git")
        root = (site / str(conf.get("root", "." if any((site / m).exists() for m in marks) else ".."))).resolve()
        flags = {k: conf.get(k, False) for k in ("check-shown", "private")}
        for k, v in flags.items():
            if not isinstance(v, bool):
                raise ValueError(f"{k} must be true or false, not {v!r}")
        manifest = (site / str(conf["manifest"])).resolve() if conf.get("manifest") else None
        entry = conf.get("entry") or []
        entry = [entry] if isinstance(entry, str) else entry
        if not isinstance(entry, list) or not all(isinstance(e, str) for e in entry):
            raise ValueError(f"entry must be a path or a list of paths, not {entry!r}")
        tsconfig = conf.get("tsconfig", "")
        if not isinstance(tsconfig, str):
            raise ValueError(f"tsconfig must be a path, not {tsconfig!r}")
        out = str(conf.get("out", "api")).strip("/")
        source = str(conf.get("source", "")).rstrip("/")
        toolchain = conf.get("toolchain", "nightly")
        if not isinstance(toolchain, str):
            raise ValueError(f"toolchain must be text, such as nightly or \"nightly-2026-11-11\", not {toolchain!r}; put a number in quotes")
        return cls(
            site, [], out, root, source, (), conf.get("linkify", True) is not False, flags["check-shown"], language, tuple(entry), tsconfig, manifest, toolchain, flags["private"]
        )  # fmt: skip

    def importable(self) -> None:
        "Let the packages import from the repository: its root and its `src` folder go on `sys.path`."
        if self.language != "python":
            return  # a crate or a TypeScript package is read by its own tool, not imported
        for p in (self.root, self.root / "src") if self.root else ():
            if p.is_dir() and str(p) not in sys.path:
                sys.path.insert(0, str(p))

    def package_files(self) -> set[Path]:  # The folders of the documented packages, and the files of single modules
        "Find where the documented packages are, so that `check` does not import their files a second time."
        out = set()
        for name in self.packages:
            spec = importlib.util.find_spec(name)
            if spec is None:
                continue
            out |= {Path(p).resolve() for p in spec.submodule_search_locations or []}
            if spec.origin and not spec.submodule_search_locations:
                out.add(Path(spec.origin).resolve())
        return out

    def check_files(self) -> list[Path]:  # The files the globs of `check` find
        "Find the files of `check`."
        if not self.root:
            return []
        documented = self.package_files()
        out = []
        for f in sorted(self.root.rglob("*.py")):
            r = f.relative_to(self.root).as_posix()
            if any(part.startswith(".") for part in Path(r).parts) or "site-packages" in r:
                continue
            if f.resolve() in documented or any(d in f.resolve().parents for d in documented):
                continue  # a file of a documented package is checked as part of its package
            if any(glob_regex(g.lstrip("/")).match(r) for g in self.check):
                out.append(f)
        return out


def source_link(
    s: Settings,  # The settings
    sym: Symbol,  # One entry of the inventory
) -> str:  # A Markdown link to the line that defines it, or empty when there is no `source`
    "Link a symbol to the line that defines it."
    if not s.source:
        return ""
    path = Path(importlib.import_module(sym.module).__file__ or "").resolve()
    try:
        file = path.relative_to(s.root) if s.root else path
    except ValueError:
        return ""
    return f"[source]({s.source}/{file.as_posix()}#L{sym.line}){{.source-link}}"


def page(
    s: Settings,  # The settings
    mod: ModuleType,  # One module
    syms: list[Symbol],  # The inventory entries of that module, the module's own first
) -> str:  # The text of its `.qmd` page
    "Turn one module's Markdown into a page: front matter, an id and a source link for each heading."
    by_name = {x.name: x for x in syms if x.name}
    head = next(x for x in syms if not x.name)
    body = module_markdown(mod).split("\n", 1)[1].strip()
    if head.summary and body.startswith(head.summary):
        body = body[len(head.summary) :].strip()
    out, fence = [], False
    for line in body.split("\n"):
        if line.startswith("```"):
            fence = not fence
        m = None if fence else HEADING.match(line)
        if m and m.group(2) in by_name:
            sym = by_name[m.group(2)]
            link = source_link(s, sym)
            out += [f"{line} {{#{sym.name}}}", *(["", link] if link else [])]
        else:
            out.append(line)
    front = f"---\ntitle: {json.dumps(head.module)}\ndescription: {json.dumps(head.summary)}\n---\n\n"
    return front + "\n".join(out) + "\n"


def build(
    s: Settings,  # The settings
) -> list[Path]:  # The pages written
    "Write one reference page per module, and `_symbols.json`, the index of names that links use."
    if s.language != "python":
        return language_module(s).build(s)
    s.importable()
    out_dir = (s.site / s.out).resolve()
    site = s.site.resolve()
    if site not in out_dir.parents:
        raise ValueError(f"api.out {s.out!r} must be a folder inside the site, such as api")
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = out_dir / ".smalldocs-api"
    before = set(manifest.read_text(encoding="utf-8").split("\n")) if manifest.exists() else set()
    index: dict[str, str] = {}
    syms = inventory(s.packages)
    mods = [m for p in s.packages for m in package_modules(p)]
    shorts = [m.__name__.rpartition(".")[2] for m in mods]
    written = []
    for mod in mods:
        short = mod.__name__.rpartition(".")[2]
        stem = short if shorts.count(short) == 1 else mod.__name__
        mine = [x for x in syms if x.module == mod.__name__]
        f = out_dir / f"{stem}.qmd"
        text = page(s, mod, mine)
        if not f.exists() or f.read_text(encoding="utf-8") != text:
            f.write_text(text, encoding="utf-8")
        written.append(f)
        for x in mine:
            if x.name:
                target = f"/{s.out}/{stem}.qmd#{x.name}"
                index.setdefault(x.name, target)
                index[f"{mod.__name__}.{x.name}"] = target
    names = {f.name for f in written}
    for stale in sorted(before - names):
        f = out_dir / stale
        if stale.endswith(".qmd") and "/" not in stale and f.is_file():
            f.unlink()  # only a page that an earlier build wrote, and this one did not
    manifest.write_text("\n".join(sorted(names)), encoding="utf-8")
    sym = s.site / "_symbols.json"
    text = json.dumps(index, indent=1)
    if not sym.exists() or sym.read_text(encoding="utf-8") != text:
        sym.write_text(text, encoding="utf-8")
    return written


# ---------------------------------------------------------------- the pages of Rust and TypeScript, which `api_rust` and `api_ts` write


MARK = "# written by smalldocs api build; a build writes over it"  # The first line of the front matter of each Rust or TypeScript page
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")  # A line that opens or closes a fenced code block
HTML_START = re.compile(  # what may follow a `<` that starts HTML on purpose: a common tag in lower case, an autolink or a comment
    r"(?:/?(?:b|i|p|s|u|br|hr|h[1-6]|em|strong|del|ins|abbr|code|pre|kbd|sub|sup|span|div|img|details|summary|table|thead|tbody|tr|td|th|ul|ol|li|dl|dt|dd"
    r"|blockquote)(?=[\s>/])|a\s|/a>|https?://|mailto:|[^\s<>@`]+@[^\s<>@`]+>|!--)"
)  # in lower case only, so that a generic such as `Wrapper<B>` is text; `<a>` alone, as in "the <a> element", is text too


def language_module(
    s: Settings,  # The settings of a Rust or TypeScript project
) -> ModuleType:  # `smalldocs.api_rust` or `smalldocs.api_ts`
    "Load the module that reads the language, only when it is needed."
    return importlib.import_module({"typescript": "smalldocs.api_ts", "rust": "smalldocs.api_rust"}[s.language])


def escape_angles(
    text: str,  # Markdown, of one line or more
) -> str:  # The same text with each `<` that starts no HTML tag, autolink or comment written `&lt;`; code spans and fenced code blocks stay as they are
    "Escape a stray `<`, such as in `Vec<u8>` or `vs <Opp>` written outside backticks, so that it shows as text and starts no HTML."
    out: list[str] = []
    prose: list[str] = []
    fence = ""
    for line in text.split("\n"):
        m = FENCE.match(line)
        if fence:
            out.append(line)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not line.strip()[len(m.group(1)) :].strip():
                fence = ""
            continue
        if m:
            out.extend(escape_prose("\n".join(prose)).split("\n") if prose else [])
            prose.clear()
            fence = m.group(1)
            out.append(line)
            continue
        prose.append(line)
    if prose:
        out.extend(escape_prose("\n".join(prose)).split("\n"))
    return "\n".join(out)


def escape_prose(
    text: str,  # Markdown prose, outside a code block
) -> str:  # The same text with each stray `<` written `&lt;`; code spans stay as they are
    "Escape the stray `<` of prose that holds no code block."

    def one(
        m: re.Match,  # A code span, or a `<`
    ) -> str:  # The code span as it is, or the `<`, escaped unless it starts a tag
        "Escape one `<`."
        if m.group(1):
            return m.group(1)
        return "<" if HTML_START.match(text, m.end()) else "&lt;"

    return re.sub(r"((`+)(?:(?!\n[ \t]*\n)[\s\S])*?(?<!`)\2(?!`))|<", one, text)


def type_cell(
    text: str,  # A type, as Rust or TypeScript writes it
) -> str:  # It as plain text, as the Python pages write types, with Markdown's, maths' and HTML's signs escaped; `table` escapes `|`
    "Write a type in a table cell as plain text, so that `&`, `<`, `>`, `*`, `_`, `$`, `~`, `^`, quotes, a backtick, `[` and `]` show as they are."
    text = re.sub(r"([\\`*_$~^'\"\[\]])", r"\\\1", text)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def front_matter(
    title: str,  # The page's title
    description: str | None = None,  # Its description; `None` writes none
) -> str:  # The front matter, with the mark of a build first, and the blank line after it
    "Begin a Rust or TypeScript page, marked as written by a build, so that a lost manifest leaves no page frozen."
    said = f"description: {yaml_text(description.replace('&lt;', '<'))}\n" if description is not None else ""  # a description is plain text, not Markdown
    return f"---\n{MARK}\ntitle: {yaml_text(title)}\n{said}---\n\n"


def yaml_text(
    text: str,  # Any text
) -> str:  # It as a YAML string in double quotes, with every character that is not ASCII as it is, as YAML reads an emoji
    "Quote text for front matter; JSON's `\\ud83e\\udd80` for an emoji is two broken characters to PyYAML."
    out = json.dumps(text, ensure_ascii=False)
    return out.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029").replace("\u0085", "\\u0085").replace("\ufeff", "\\ufeff")


def out_folder(
    s: Settings,  # The settings
) -> Path:  # The folder of pages, resolved
    "Find the folder of pages, and refuse one that is the site or outside it, before any tool runs."
    out_dir = (s.site / s.out).resolve()
    if s.site.resolve() not in out_dir.parents:
        raise ValueError(f"api.out {s.out!r} must be a folder inside the site, such as api")
    return out_dir


def inside(
    out_dir: Path,  # The folder of pages
    rel: str,  # A path in it, from the manifest or from a page's place
) -> Path | None:  # The file, when the path is a `.qmd` that stays inside the folder; `None` otherwise
    "Check that a page's path stays inside `out`: relative, no `..`, no empty part, no backslash, a `.qmd`."
    parts = rel.split("/")
    if not rel.endswith(".qmd") or rel.startswith("/") or "\\" in rel or any(x in ("", ".", "..") for x in parts):
        return None
    f = out_dir / rel
    return f if out_dir in f.resolve().parents else None


def built_before(
    out_dir: Path,  # The folder of pages
) -> set[str]:  # The pages that the last build wrote, from its manifest, as paths from the folder
    "Read the manifest of the last build."
    manifest = out_dir / ".smalldocs-api"
    return set(manifest.read_text(encoding="utf-8").split("\n")) - {""} if manifest.exists() else set()


def page_key(
    rel: str,  # A page's path in the folder of pages, such as `components/Badge.qmd` or `utils/format.ipynb`
) -> str:  # The page it makes on the site, without its suffix, in lower case: `.md`, `.qmd` and `.ipynb` of one name are one page, as on macOS
    "Name the page that a source makes, so that two sources of one page are found."
    stem, dot, suffix = rel.rpartition(".")
    return (stem if dot and suffix in ("qmd", "md", "ipynb") else rel).casefold()


def marked(
    f: Path,  # A page
) -> bool:  # Whether a build wrote it, by the mark at its start
    "Read a page's mark."
    with f.open(encoding="utf-8", errors="replace") as h:
        return h.read(len(MARK) + 5) == f"---\n{MARK}\n"


def hand_written(
    out_dir: Path,  # The folder of pages
) -> set[str]:  # The pages in it that no build wrote, as paths from the folder
    "Find the pages that someone wrote in the folder of pages, which a build never writes over: a `.md`, an `.ipynb`, or a `.qmd` without the mark."
    if not out_dir.is_dir():
        return set()
    found = (f for f in out_dir.rglob("*") if f.suffix in (".qmd", ".md", ".ipynb") and f.is_file())
    return {f.relative_to(out_dir).as_posix() for f in found if f.suffix != ".qmd" or not marked(f)}


def listing(
    rows: list[tuple[str, str, str]],  # Each page: its name, its link and its summary
) -> str:  # A Markdown table with a link to each page by its name, and its summary; empty when there are none
    "List some pages of the reference, in a table."
    return table([[f"[`{name}`]({href})", summary] for name, href, summary in rows], ["Name", "Summary"])


def folder_listing(
    out: str,  # The folder of pages in the site, such as `api`
    folder: str,  # A folder of pages in it, such as `components`; empty for `out` itself
    summaries: dict[str, str],  # The summary of each page, by its path in `out`, such as `components/Badge.qmd`
) -> str:  # The table of the folder's pages and subfolders, each a link, in name order; a subfolder links to its `index.qmd`
    "List what one folder of the reference holds, for its `index.qmd`."
    prefix, rows = f"{folder}/" if folder else "", {}
    for rel in summaries:
        if not rel.startswith(prefix):
            continue
        head, sep, _ = rel[len(prefix) :].partition("/")
        if sep:
            rows.setdefault(head, (head, f"/{out}/{prefix}{head}/index.qmd", summaries.get(f"{prefix}{head}/index.qmd", "")))
        elif head != "index.qmd":
            rows[head] = (head.removesuffix(".qmd"), f"/{out}/{prefix}{head}", summaries[rel])
    return listing(sorted(rows.values(), key=lambda r: r[0].casefold()))


def folder_indexes(
    out: str,  # The folder of pages in the site, such as `api`
    summaries: dict[str, str],  # The summary of each page that the build writes, by its path in `out`
    taken: set[str],  # The pages that someone wrote, which a build never writes over
    description: str = "",  # The description of the index of `out` itself, such as the crate's summary
) -> dict[str, str]:  # The text of each folder's `index.qmd` that no page of the build, and no one, has written
    "Write an `index.qmd` for each folder of pages that has none: titled by its folder, with a table of its pages and subfolders."
    folders = {""} | {rel.rsplit("/", 1)[0] for rel in summaries if "/" in rel}
    folders |= {"/".join(f.split("/")[:k]) for f in list(folders) for k in range(1, f.count("/") + 1)}
    gone = {page_key(t) for t in taken} | {page_key(r) for r in summaries}
    out_pages = {}
    for folder in sorted(folders):
        key = f"{folder}/index.qmd" if folder else "index.qmd"
        if page_key(key) not in gone:
            title = folder.rpartition("/")[2] or "Reference"  # the sidebar shows no section for `out` itself, as Quarto does
            out_pages[key] = front_matter(title, description or None if not folder else None) + folder_listing(out, folder, summaries) + "\n"
    return out_pages


def write_reference(
    s: Settings,  # The settings
    pages: dict[str, str],  # The text of each page, by its path in the folder of pages
    index: dict[str, str],  # The index of names for links, for `_symbols.json`
    taken: set[str],  # The pages that someone wrote, from `hand_written`
) -> list[Path]:  # The pages written
    "Write the pages, the manifest and `_symbols.json`; delete only the marked pages that an earlier build listed and this one does not write in that spelling."
    out_dir = out_folder(s)
    held = {page_key(t): t for t in taken}
    for rel in pages:
        if inside(out_dir, rel) is None:
            raise ValueError(f"a page would leave api.out: {rel!r}")
        if page_key(rel) in held:
            raise ValueError(f"{out_dir / held[page_key(rel)]} exists and no earlier API build wrote it (it has no mark); move it, or remove it, and build again")
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = out_dir / ".smalldocs-api"
    before = built_before(out_dir)
    for stale in sorted(before - set(pages)):  # first, so that a page renamed only in case, `Chip` to `chip`, takes its new spelling on macOS
        f = inside(out_dir, stale)
        if f is not None and f.is_file() and marked(f):
            f.unlink()  # only a page that an earlier build wrote and listed, and this one does not write as it is spelt
            for d in f.parents:
                if d == out_dir or any(d.iterdir()):
                    break
                d.rmdir()  # a folder the pages left empty
    written: list[Path] = []
    mine: set[str] = set()
    done = False
    try:
        for rel, text in pages.items():
            f = out_dir / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            if not f.exists() or f.read_text(encoding="utf-8") != text:
                f.write_text(text, encoding="utf-8")
            written.append(f)
            mine.add(rel)
        done = True
    finally:
        manifest.write_text("\n".join(sorted(mine if done else before | mine)), encoding="utf-8")  # a stopped build keeps what it wrote
    sym = s.site / "_symbols.json"
    text = json.dumps(index, indent=1)
    if not sym.exists() or sym.read_text(encoding="utf-8") != text:
        sym.write_text(text, encoding="utf-8")
    return written


def build_from_config(
    project: "object",  # A loaded `config.Project`
) -> list[Path]:  # The pages written
    "Build the reference pages that `smalldocs.api` asks for, before the site is rendered."
    from .config import BuildError

    try:
        s = Settings.read(project.root, project.smalldocs.get("api") or {})
        return build(s)
    except ImportError as e:
        raise BuildError(f"the api settings: cannot import the package: {e}. Install smalldocs in the same environment as the package") from e
    except ValueError as e:
        raise BuildError(str(e)) from e


def main(
    site: str,  # The site's folder, whose config has the api settings
    action: str,  # `build`, `check`, `module` or `list`
    name: str | None = None,  # The module, for `module`
    shown: bool = False,  # For `check`: hold the packages only to what their pages show, as `check-shown: true` does
) -> int:  # The exit code
    "Run one `smalldocs api` command."
    from .config import load

    project = load(site)
    conf = project.smalldocs.get("api")
    if not conf:
        where = "api" if project.native else "smalldocs.api"
        print(f"smalldocs api: {project.file} has no {where} section; see `smalldocs api --help`", file=sys.stderr)
        return 2
    try:
        if shown and action != "check":
            print(f"smalldocs api {action}: --shown is for check only", file=sys.stderr)
            return 2
        s = Settings.read(project.root, conf)
        s.shown = s.shown or shown
        return run(s, action, name)
    except (ValueError, ImportError) as e:
        print(f"smalldocs api: {e}", file=sys.stderr)
        return 2


def run(
    s: Settings,  # The settings
    action: str,  # `build`, `check`, `module` or `list`
    name: str | None,  # The module, for `module`
) -> int:  # The exit code
    "Run one `smalldocs api` command with its settings read."
    s.importable()
    if action == "build":
        pages = build(s)
        print(f"wrote {len(pages)} page(s) to {s.site / s.out}")
        return 0
    if s.language != "python":
        if action == "check":
            return language_module(s).check(s, s.shown)
        print(f"smalldocs api {action}: for Python only; {s.language} has build and check", file=sys.stderr)
        return 2
    if action == "check":
        return check(s.packages, s.check_files(), s.root, s.shown)
    if action == "list":
        found = inventory(s.packages)
        names = [f"{x.module}.{x.name}" if x.name else x.module for x in found]
        width = max((len(n) for n in names), default=10)
        for x, n in zip(found, names, strict=True):
            print(f"{x.kind:9s} {n:{width}s}  {x.summary}")
        return 0
    if action == "module":
        if not name:
            print("smalldocs api module: name a module", file=sys.stderr)
            return 2
        try:
            print(markdown(name, s.packages), end="")
        except LookupError:
            names = ", ".join(m.__name__ for p in s.packages for m in package_modules(p))
            print(f"smalldocs api: no module {name!r}. The modules: {names}", file=sys.stderr)
            return 2
        return 0
    return 2
