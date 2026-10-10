"`smalldocs preview`: build the site, serve it on localhost, and rebuild and reload the browser on every change."

import contextlib
import functools
import http.server
import os
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

from .config import BuildError, ConfigError, load

IGNORE = {".git", ".venv", "venv", "node_modules", "__pycache__", ".quarto", "_freeze", ".pytest_cache", ".ruff_cache"}


def snapshot(
    root: Path,  # The project folder
    out: Path,  # The output folder, which is left out
) -> dict[str, float]:  # Each file's modification time
    "Note the modification time of every source file."
    found = {}
    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        dirnames[:] = [n for n in dirnames if n not in IGNORE and (d / n) != out]
        for f in filenames:
            p = d / f
            with contextlib.suppress(OSError):
                found[str(p)] = p.stat().st_mtime
    return found


class Handler(http.server.SimpleHTTPRequestHandler):
    "Serve the output folder, and the build number at `/__smalldocs__/version`."

    version = 0

    def do_GET(self) -> None:
        "Answer the build number, or a file."
        if self.path.split("?")[0].endswith("/__smalldocs__/version"):
            body = str(Handler.version).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self) -> None:
        "Ask the browser not to cache, so a reload shows the new build."
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(
        self,
        format: str,  # The message, with `%` fields
        *args: object,  # The values for the fields
    ) -> None:
        "Print nothing for each request."


def rebuild(
    root: Path,  # The project folder
) -> Path | None:  # The output folder, or None when the build failed
    "Build the site for preview, printing a failure instead of stopping."
    from .site import Site

    try:
        site = Site(load(root), quiet=True, preview=True)
        n = site.build()
        for w in site.warnings:
            print(f"warning: {w}", file=sys.stderr)
        print(f"built {n} page(s)", file=sys.stderr)
        return site.out
    except (BuildError, ConfigError) as e:
        print(f"smalldocs: {e}", file=sys.stderr)
    except Exception:
        traceback.print_exc()
    return None


def preview(
    root: Path,  # The project folder
    host: str = "127.0.0.1",  # The address to listen on
    port: int = 4200,  # The port
    open_browser: bool = True,  # Open the site in a browser
) -> int:  # The exit code
    "Build, serve and watch until stopped with Ctrl-C."
    root = root.resolve()
    out = rebuild(root)
    if out is None:
        return 2
    try:
        probe = socket.socket()
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((host, port))
        probe.close()
    except OSError:
        print(f"smalldocs: port {port} is in use; give another with --port", file=sys.stderr)
        return 2
    server = http.server.ThreadingHTTPServer((host, port), functools.partial(Handler, directory=str(out)))
    url = f"http://{host}:{port}/"
    print(f"serving {out} at {url} (Ctrl-C to stop)", file=sys.stderr)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if open_browser:
        webbrowser.open(url)
    seen = snapshot(root, out)
    try:
        while True:
            time.sleep(0.5)
            now = snapshot(root, out)
            if now != seen:
                changed = sorted({*now} ^ {*seen} | {k for k in now if seen.get(k) != now[k]})
                print(f"changed: {', '.join(os.path.relpath(c, root) for c in changed[:3])}{' ...' if len(changed) > 3 else ''}", file=sys.stderr)
                if rebuild(root) is not None:
                    Handler.version += 1
                seen = snapshot(root, out)  # what the build wrote, such as API pages, is not a change
    except KeyboardInterrupt:
        server.shutdown()
    return 0
