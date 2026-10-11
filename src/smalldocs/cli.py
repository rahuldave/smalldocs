"The `smalldocs` command: render, preview, check, api and publish."

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .config import BuildError, ConfigError


def cmd_render(
    args: argparse.Namespace,  # The parsed command line
) -> int:  # The exit code
    "Build the site once."
    from .site import build

    site = build(args.dir, quiet=args.quiet)
    for w in site.warnings:
        print(f"warning: {w}", file=sys.stderr)
    return 1 if args.strict and site.warnings else 0


def cmd_preview(
    args: argparse.Namespace,  # The parsed command line
) -> int:  # The exit code
    "Build, serve, and rebuild on every change."
    from .serve import preview

    return preview(Path(args.dir), host=args.host, port=args.port, open_browser=not args.no_browser)


def cmd_check(
    args: argparse.Namespace,  # The parsed command line
) -> int:  # The exit code: 1 when there is anything to fix
    "Build into a scratch folder and list what smalldocs ignores, what it cannot read, and the broken links."
    from .check import check

    return check(Path(args.dir))


def cmd_api(
    args: argparse.Namespace,  # The parsed command line
) -> int:  # The exit code
    "Make or check the API reference."
    from .api import main as api_main

    return api_main(args.dir, args.action, args.name)


def cmd_publish(
    args: argparse.Namespace,  # The parsed command line
) -> int:  # The exit code
    "Build the site and push it to a branch for GitHub Pages."
    from .publish import publish

    return publish(Path(args.dir), branch=args.branch, remote=args.remote, render=not args.no_render, message=args.message)


def parser() -> argparse.ArgumentParser:  # The parser for every command
    "Describe the commands and their options."
    p = argparse.ArgumentParser(prog="smalldocs", description="Quarto-like websites from a _smalldocs.yml or _quarto.yml project, in pure Python.")
    p.add_argument("--version", action="version", version=f"smalldocs {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("render", help="build the site into its output-dir (default _site)")
    r.add_argument("dir", nargs="?", default=".", help="the project folder, with _smalldocs.yml or _quarto.yml")
    r.add_argument("--quiet", "-q", action="store_true", help="print only warnings and errors")
    r.add_argument("--strict", action="store_true", help="exit 1 when there is any warning")
    r.set_defaults(func=cmd_render)

    v = sub.add_parser("preview", help="build, serve on localhost, and rebuild and reload on every change")
    v.add_argument("dir", nargs="?", default=".", help="the project folder")
    v.add_argument("--port", type=int, default=4200, help="the port (default 4200)")
    v.add_argument("--host", default="127.0.0.1", help="the address to listen on (default 127.0.0.1)")
    v.add_argument("--no-browser", action="store_true", help="do not open a browser")
    v.set_defaults(func=cmd_preview)

    c = sub.add_parser("check", help="list ignored keys, Pandoc-only syntax and broken links; exit 1 if any")
    c.add_argument("dir", nargs="?", default=".", help="the project folder")
    c.set_defaults(func=cmd_check)

    a = sub.add_parser("api", help="the API reference: build its pages, check the docments, or print one module")
    a.add_argument("action", choices=["build", "check", "module", "list"], help="build: the pages; check: the gaps; module NAME: one module; list: every symbol")
    a.add_argument("name", nargs="?", help="the module, for `module`")
    a.add_argument("--dir", default=".", help="the project folder, whose config has the api settings")
    a.set_defaults(func=cmd_api)

    g = sub.add_parser("publish", help="build and push the site to the gh-pages branch")
    g.add_argument("target", nargs="?", default="gh-pages", choices=["gh-pages"], help="where to publish: gh-pages")
    g.add_argument("dir", nargs="?", default=".", help="the project folder")
    g.add_argument("--branch", default="gh-pages", help="the branch to push to (default gh-pages)")
    g.add_argument("--remote", default="origin", help="the remote to push to (default origin)")
    g.add_argument("--no-render", action="store_true", help="publish the output folder as it is")
    g.add_argument("--message", "-m", default="Built site", help="the commit message")
    g.set_defaults(func=cmd_publish)
    return p


def main(
    argv: list[str] | None = None,  # The arguments, without the program's name; None for `sys.argv`
) -> int:  # The exit code
    "Run the `smalldocs` command."
    args = parser().parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, BuildError) as e:
        print(f"smalldocs: {e}", file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
        if os.environ.get("SMALLDOCS_DEBUG"):
            raise
        print(f"smalldocs: {type(e).__name__}: {e} (set SMALLDOCS_DEBUG=1 to see where)", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
