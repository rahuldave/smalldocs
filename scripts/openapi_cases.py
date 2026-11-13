"""Write `tests/openapi/tiny.json`, the OpenAPI document of the tiny FastAPI app, with the file and line of each route.

    uv run python scripts/openapi_cases.py

It runs smalldocs' own FastAPI program, `api_openapi.PROGRAM`, on `tests/openapi/tiny_app.py`, with FastAPI from
uv's cache: `uv run --no-project --with fastapi`. The file of each route is written from the folder of the
fixtures, so the document is the same on every machine.
"""

import json
import os
import subprocess
from pathlib import Path

from smalldocs.api_openapi import PROGRAM

HERE = Path(__file__).resolve().parent.parent / "tests" / "openapi"


def main() -> None:
    "Run the program on the tiny app, and write its document."
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "SMALLDOCS_FASTAPI_APP": "tiny_app:app"}
    words = ["uv", "run", "--no-project", "--with", "fastapi", "python", "-c", PROGRAM]
    doc = json.loads(subprocess.run(words, cwd=HERE, env=env, capture_output=True, text=True, check=True).stdout)
    for item in doc["paths"].values():
        for op in item.values():
            where = op.get("x-smalldocs-source")
            if where:
                where["file"] = Path(where["file"]).resolve().relative_to(HERE).as_posix()
    (HERE / "tiny.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {HERE / 'tiny.json'}")


if __name__ == "__main__":
    main()
