"""Write the rustdoc JSON that the tests of the Rust API pages read, from the crate in tests/fixtures/rust/tinycrate.

    uv run python scripts/rust_fixtures.py

It runs rustdoc of the nightly toolchain, which writes format 61 today, and of the stable toolchain with
RUSTC_BOOTSTRAP=1, which writes format 57. The tests only read the JSON, so they need no Rust. Each file
keeps the crate's own items and only the paths and crates they name, so that it stays small.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "rust"
CRATE = HERE / "tinycrate"


def ids_in(
    value: object,  # Any part of rustdoc's JSON
) -> set[str]:  # Every id it names: in an `id` key, a list of ids, or the values of `links`
    "Collect the ids that a part of the JSON refers to."
    out: set[str] = set()
    if isinstance(value, dict):
        for k, v in value.items():
            if k == "id" and isinstance(v, int):
                out.add(str(v))
            elif k == "links" and isinstance(v, dict):
                out |= {str(i) for i in v.values()}
            elif k in ("items", "impls", "fields", "variants", "implementations") and isinstance(v, list):
                out |= {str(i) for i in v if isinstance(i, int)}
            out |= ids_in(v)
    elif isinstance(value, list):
        for v in value:
            out |= ids_in(v)
    return out


def trim(
    data: dict,  # rustdoc's JSON of the crate
) -> dict:  # The same JSON with only the crate's items, and the paths and crates they name
    "Keep the crate's own items, one auto-trait impl and one blanket impl of each type, and only the paths and external crates they refer to."
    index = {k: v for k, v in data["index"].items() if v["crate_id"] == 0}
    for item in list(index.values()):
        inner = item["inner"].get("struct") or item["inner"].get("enum") if isinstance(item["inner"], dict) else None
        if not inner:
            continue
        kept, seen = [], set()
        for i in inner["impls"]:
            impl = index[str(i)]["inner"]["impl"]
            sort = "blanket" if impl["blanket_impl"] else "auto" if impl["is_synthetic"] else str(i)
            if sort not in seen:
                seen.add(sort)
                kept.append(i)
            else:
                index.pop(str(i))
        inner["impls"] = kept
    named = ids_in(index)
    paths = {k: v for k, v in data["paths"].items() if v["crate_id"] == 0 or k in named}
    parents = {tuple(v["path"][:-1]) for v in paths.values()}
    paths |= {k: v for k, v in data["paths"].items() if tuple(v["path"]) in parents}  # a type, to link its methods
    crates = {str(v["crate_id"]) for v in paths.values()}
    external = {k: {"name": v["name"], "html_root_url": v.get("html_root_url")} for k, v in data["external_crates"].items() if k in crates}
    keep = ("root", "crate_version", "includes_private", "format_version")
    return {**{k: data[k] for k in keep}, "index": index, "paths": paths, "external_crates": external}


def run(
    toolchain: str,  # `nightly` or `stable`
    private: bool,  # Document private items too
) -> dict | None:  # rustdoc's JSON, or `None` when the toolchain is missing
    "Run rustdoc of one toolchain on a copy of the fixture crate, so that cargo writes nothing into the repository."
    with tempfile.TemporaryDirectory() as tmp:
        crate = Path(tmp) / "tinycrate"
        shutil.copytree(CRATE, crate)  # stable cargo writes Cargo.lock into the crate
        env = {**os.environ, "CARGO_TARGET_DIR": str(Path(tmp) / "target"), "RUSTUP_AUTO_INSTALL": "0"}
        if toolchain == "stable":
            env["RUSTC_BOOTSTRAP"] = "1"  # only to write the older format for the tests; smalldocs itself needs nightly
        flags = ["-Z", "unstable-options", "--output-format", "json", *(["--document-private-items"] if private else [])]
        args = ["cargo", f"+{toolchain}", "rustdoc", "--manifest-path", str(crate / "Cargo.toml"), "--lib", "--", *flags]
        done = subprocess.run(args, capture_output=True, text=True, env=env)
        if done.returncode != 0:
            print(f"{toolchain}: {done.stderr.strip().splitlines()[-1] if done.stderr.strip() else 'failed'}", file=sys.stderr)
            return None
        return json.loads((Path(tmp) / "target" / "doc" / "tinycrate.json").read_text())


def main() -> int:  # The exit code: 1 when nightly is missing
    "Write the fixtures: format 61 from nightly, public and private, and format 57 from stable."
    for toolchain, privates in (("nightly", (False, True)), ("stable", (False,))):
        for private in privates:
            data = run(toolchain, private)
            if data is None:
                if toolchain == "nightly":
                    return 1
                continue
            out = HERE / f"tinycrate-{data['format_version']}{'-private' if private else ''}.json"
            out.write_text(json.dumps(trim(data), indent=1, sort_keys=True) + "\n")
            print(f"wrote {out.relative_to(HERE.parent.parent.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
