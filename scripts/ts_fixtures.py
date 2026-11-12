"""Write the TypeDoc JSON that the TypeScript API tests read, from the sources in `tests/fixtures/ts/`.

    uv run python scripts/ts_fixtures.py

It runs TypeDoc as `smalldocs api build` does: the library from its entry point, `src/index.ts`, and the
app from its folder, `src`. It drops what changes from one run to the next: the git links of the
sources and the map of symbols, which holds absolute paths. It needs Node and npx.
"""

import json
from pathlib import Path

from smalldocs.api_ts import run_typedoc

HERE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "ts"
FIXTURES = {"lib": "src/index.ts", "app": "src"}  # each fixture's folder, and its entry point


def stable(
    o: object,  # A part of TypeDoc's JSON
) -> object:  # The same, without `url` and `symbolIdMap`
    "Drop the parts of TypeDoc's JSON that change from one run or one machine to the next."
    if isinstance(o, dict):
        return {k: stable(v) for k, v in o.items() if k not in ("url", "symbolIdMap")}
    if isinstance(o, list):
        return [stable(v) for v in o]
    return o


def fixture(
    name: str,  # The fixture's folder in `tests/fixtures/ts`
    entry: str,  # Its entry point, from that folder
) -> dict:  # TypeDoc's JSON for it, without the parts that change
    "Run TypeDoc on one fixture."
    project = HERE / name
    return stable(run_typedoc(project, [project / entry]))


def main() -> None:
    "Write the JSON of each fixture beside its folder."
    for name, entry in FIXTURES.items():
        out = HERE / f"{name}.json"
        out.write_text(json.dumps(fixture(name, entry), indent=1) + "\n", encoding="utf-8")
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
