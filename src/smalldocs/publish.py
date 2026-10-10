"`smalldocs publish gh-pages`: put the built site on a branch and push it, without touching your working tree."

import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from .config import BuildError, load


def git(
    cwd: Path,  # Where to run git
    *args: str,  # Its arguments
    check: bool = True,  # Raise when git fails
) -> subprocess.CompletedProcess:  # What git did
    "Run git."
    r = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=cwd, capture_output=True, text=True)  # no hook of yours runs
    if check and r.returncode:
        raise BuildError(f"git {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return r


def publish(
    root: Path,  # The project folder
    branch: str = "gh-pages",  # The branch to publish to
    remote: str = "origin",  # The remote to push to
    render: bool = True,  # Build the site first
    message: str = "Built site",  # The commit message
) -> int:  # The exit code
    "Build the site, commit the output folder to `branch` in a temporary worktree, and push it."
    root = root.resolve()
    project = load(root)
    from .site import Site

    Site(project, quiet=True).check_output()  # the folder to publish must be a built site, never your sources
    if render:
        from .site import build

        site = build(root)
        for w in site.warnings:
            print(f"warning: {w}", file=sys.stderr)
    out = project.output
    if not (out / "index.html").exists() or not (out / "site_libs").is_dir():
        raise BuildError(f"{out} is not a built site (no index.html and site_libs); build the site first")
    top = Path(git(root, "rev-parse", "--show-toplevel").stdout.strip())
    if git(top, "remote", "get-url", remote, check=False).returncode:
        raise BuildError(f"this repository has no remote named {remote}")
    current = git(top, "symbolic-ref", "--short", "-q", "HEAD", check=False).stdout.strip()
    head = git(top, "ls-remote", "--symref", remote, "HEAD", check=False).stdout
    default = head.split("refs/heads/", 1)[1].split()[0] if head.startswith("ref: refs/heads/") else ""
    bad_name = branch == "HEAD" or branch.startswith(("refs/", "heads/", f"{remote}/"))
    if bad_name or git(top, "check-ref-format", "--branch", branch, check=False).returncode:
        raise BuildError(f"{branch!r} is not a branch name to publish to; give a plain name such as gh-pages")
    if branch in (current, default) or branch in ("main", "master"):
        raise BuildError(f"will not publish the site onto {branch}: it holds your sources. Publish to gh-pages, or another branch of its own")
    tmp = Path(tempfile.mkdtemp(prefix="smalldocs-publish-"))
    work = tmp / "site"
    temp_branch = ""
    try:
        has_remote = git(top, "ls-remote", "--exit-code", "--heads", remote, branch, check=False).returncode == 0
        git(top, "worktree", "add", "--detach", str(work))
        if has_remote:
            git(work, "fetch", remote, f"{branch}")
            names = set(git(work, "ls-tree", "--name-only", "FETCH_HEAD").stdout.split())
            shares = git(work, "merge-base", "FETCH_HEAD", "HEAD", check=False).returncode == 0
            if shares and not names & {"index.html", ".nojekyll"}:
                raise BuildError(f"{remote}/{branch} shares history with your code and holds no site; it looks like a branch of sources, so it is left alone")
            git(work, "checkout", "--detach", "FETCH_HEAD")
        else:
            temp_branch = f"smalldocs-publish-{uuid.uuid4().hex[:12]}"
            git(work, "checkout", "--orphan", temp_branch)
        for child in work.iterdir():
            if child.name != ".git":
                shutil.rmtree(child) if child.is_dir() else child.unlink()
        shutil.copytree(out, work, dirs_exist_ok=True)
        (work / ".nojekyll").touch()
        git(work, "add", "-A")
        if git(work, "diff", "--cached", "--quiet", check=False).returncode == 0 and has_remote:
            print(f"nothing changed on {branch}", file=sys.stderr)
            return 0
        git(work, "commit", "--no-verify", "-m", message)
        git(work, "push", "--no-verify", remote, f"HEAD:refs/heads/{branch}")
        print(f"published {out} to {remote}/{branch}", file=sys.stderr)
        return 0
    finally:
        git(top, "worktree", "remove", "--force", str(work), check=False)
        if temp_branch:
            git(top, "branch", "-D", temp_branch, check=False)
        shutil.rmtree(tmp, ignore_errors=True)
