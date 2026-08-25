#!/usr/bin/env python3
"""Operate the local Git worktree governance workflow.

The primary checkout is a deployment/control surface. Product work belongs on
short-lived branches in linked worktrees, and retirements must be clean and
remotely backed up.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
from typing import Iterable

BRANCH_PATTERN = re.compile(
    r"^codex/(feat|fix|docs|chore|refactor|test|perf)/"
    r"[a-z0-9]+(?:-[a-z0-9]+)*$"
)
DEFAULT_ARCHIVE_ROOT = Path("/Users/Shared/DeepTutor-worktree-archives")


def _git(
    arguments: list[str], *, cwd: Path, check: bool = True
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
    )
    if check and completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(message or f"git {' '.join(arguments)} failed")
    return completed


@dataclass(frozen=True)
class WorktreeState:
    path: str
    branch: str
    head: str
    is_primary: bool
    modified_count: int
    untracked_count: int
    dirty_count: int
    remote: str | None
    retirement_ready: bool
    blockers: tuple[str, ...]
    error: str | None = None

    @property
    def is_clean(self) -> bool:
        return self.dirty_count == 0


def _worktree_paths(repo: Path) -> list[Path]:
    result = _git(["worktree", "list", "--porcelain"], cwd=repo)
    paths: list[Path] = []
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            path = Path(line.removeprefix("worktree ").strip())
            if path.exists():
                paths.append(path.resolve())
    return paths


def _branch_remote(repo: Path, branch: str, head: str) -> str | None:
    if not branch or branch == "(detached)":
        return None
    for remote in ("myfork", "origin"):
        remote_ref = f"refs/remotes/{remote}/{branch}"
        exists = _git(
            ["show-ref", "--verify", "--quiet", remote_ref],
            cwd=repo,
            check=False,
        )
        if exists.returncode == 0:
            remote_head = _git(["rev-parse", remote_ref], cwd=repo, check=False)
            if remote_head.stdout.strip() == head:
                return remote
    return None


def inspect_worktree(path: Path, repo: Path) -> WorktreeState:
    path = path.resolve()
    head_result = _git(["rev-parse", "HEAD"], cwd=path, check=False)
    if head_result.returncode != 0:
        message = head_result.stderr.strip() or "unable to inspect worktree"
        return WorktreeState(
            path=str(path),
            branch="(inaccessible)",
            head="unknown",
            is_primary=False,
            modified_count=0,
            untracked_count=0,
            dirty_count=0,
            remote=None,
            retirement_ready=False,
            blockers=(f"worktree is inaccessible: {message}",),
            error=message,
        )
    branch_result = _git(["branch", "--show-current"], cwd=path, check=False)
    branch = branch_result.stdout.strip() or "(detached)"
    status_result = _git(["status", "--porcelain=v1", "--untracked-files=all"], cwd=path)

    modified = 0
    untracked = 0
    for entry in status_result.stdout.splitlines():
        if not entry:
            continue
        if entry.startswith("??"):
            untracked += 1
        else:
            modified += 1

    is_primary = path == repo.resolve()
    remote = _branch_remote(repo, branch, head_result.stdout.strip())
    blockers: list[str] = []
    if is_primary:
        blockers.append("primary/control checkout cannot be retired")
    if modified or untracked:
        blockers.append(f"{modified} modified and {untracked} untracked entries remain")
    if branch == "(detached)":
        blockers.append("detached HEAD has no branch backup")
    elif remote is None:
        blockers.append("branch head is not present on myfork or origin")

    return WorktreeState(
        path=str(path),
        branch=branch,
        head=head_result.stdout.strip(),
        is_primary=is_primary,
        modified_count=modified,
        untracked_count=untracked,
        dirty_count=modified + untracked,
        remote=remote,
        retirement_ready=not blockers,
        blockers=tuple(blockers),
    )


def audit(repo: Path) -> tuple[list[WorktreeState], int]:
    states = [inspect_worktree(path, repo) for path in _worktree_paths(repo)]
    stash_result = _git(["stash", "list"], cwd=repo)
    stash_count = len([line for line in stash_result.stdout.splitlines() if line.strip()])
    return states, stash_count


def _print_audit(states: Iterable[WorktreeState], stash_count: int) -> None:
    states = list(states)
    clean = sum(state.is_clean for state in states)
    ready = sum(state.retirement_ready for state in states)
    print(f"worktrees={len(states)} clean={clean} retirement_ready={ready} stashes={stash_count}")
    for state in states:
        marker = " primary" if state.is_primary else ""
        remote = state.remote or "-"
        print(
            f"{state.path}: {state.branch}@{state.head[:10]} "
            f"dirty={state.dirty_count} remote={remote}{marker}"
        )
        for blocker in state.blockers:
            print(f"  blocker: {blocker}")


def _strict_failure(states: list[WorktreeState], stash_count: int) -> str | None:
    primary = next((state for state in states if state.is_primary), None)
    failures: list[str] = []
    if primary is None:
        failures.append("primary checkout is not registered with this repository")
    else:
        if primary.branch != "main":
            failures.append(f"primary checkout must remain on main, found {primary.branch}")
        if not primary.is_clean:
            failures.append(
                "primary checkout is dirty; move work to a linked worktree "
                "before starting or consolidating another task"
            )
    if stash_count:
        failures.append(
            f"{stash_count} stash entries remain; commit work to a topic branch "
            "or archive it before strict audit passes"
        )
    return "; ".join(failures) or None


def normalize_branch(name: str) -> str:
    branch = name.removeprefix("refs/heads/").removeprefix("codex/")
    branch = f"codex/{branch}"
    if not BRANCH_PATTERN.fullmatch(branch):
        raise ValueError("branch must match codex/{feat|fix|docs|chore|refactor|test|perf}/slug")
    return branch


def create_worktree(name: str, repo: Path, parent: Path) -> WorktreeState:
    branch = normalize_branch(name)
    primary = inspect_worktree(repo, repo)
    if primary.branch != "main" or not primary.is_clean:
        raise RuntimeError("primary checkout must be clean and on main before creating work")

    slug = branch.removeprefix("codex/").replace("/", "-")
    path = parent / f"DeepTutor-{slug}"
    if path.exists():
        raise FileExistsError(f"worktree path already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    _git(["worktree", "add", "-b", branch, str(path), "main"], cwd=repo)
    return inspect_worktree(path, repo)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _untracked_paths(worktree: Path) -> list[Path]:
    result = _git(["ls-files", "--others", "--exclude-standard", "-z"], cwd=worktree)
    return [worktree / Path(item) for item in result.stdout.split("\0") if item]


def archive_worktree(worktree: Path, repo: Path, archive_root: Path, label: str = "") -> Path:
    state = inspect_worktree(worktree, repo)
    if state.is_primary:
        raise ValueError("cannot archive the primary/control checkout")

    safe_label = re.sub(r"[^a-z0-9-]+", "-", label.lower()).strip("-") if label else "snapshot"
    destination = archive_root / f"{state.head[:12]}-{safe_label}"
    if destination.exists():
        raise FileExistsError(f"archive already exists: {destination}")
    destination.mkdir(parents=True)

    patch = destination / "tracked-changes.patch"
    diff = _git(["diff", "HEAD", "--binary"], cwd=worktree)
    patch.write_text(diff.stdout, encoding="utf-8")

    untracked = _untracked_paths(worktree)
    untracked_archive = destination / "untracked.tar.gz"
    if untracked:
        with tarfile.open(untracked_archive, "x:gz") as archive:
            for path in untracked:
                archive.add(path, arcname=path.relative_to(worktree), recursive=True)

    metadata = {
        "path": state.path,
        "branch": state.branch,
        "head": state.head,
        "modified_count": state.modified_count,
        "untracked_count": state.untracked_count,
        "untracked_names": [str(path.relative_to(worktree)) for path in untracked],
    }
    metadata_path = destination / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    files = [item for item in destination.iterdir() if item.is_file()]
    manifest = destination / "SHA256SUMS"
    manifest.write_text(
        "".join(
            f"{_sha256(item)}  {item.name}\n" for item in sorted(files, key=lambda item: item.name)
        ),
        encoding="utf-8",
    )
    return destination


def verify_archive(archive: Path) -> bool:
    manifest = archive / "SHA256SUMS"
    if not manifest.is_file():
        return False
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, name = line.split(maxsplit=1)
        path = archive / name.strip()
        if not path.is_file() or _sha256(path) != digest:
            return False
    return True


def retire_worktree(worktree: Path, repo: Path) -> None:
    state = inspect_worktree(worktree, repo)
    if not state.retirement_ready:
        details = "; ".join(state.blockers)
        raise RuntimeError(f"worktree is not safe to retire: {details}")
    _git(["worktree", "remove", str(worktree)], cwd=repo)
    _git(["worktree", "prune"], cwd=repo)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser("audit", help="inspect all worktrees and stashes")
    audit_parser.add_argument("--json", action="store_true", help="emit JSON")
    audit_parser.add_argument("--strict", action="store_true", help="fail on control drift")

    create_parser = subparsers.add_parser("create", help="create a clean task worktree")
    create_parser.add_argument("branch", help="type/slug, such as fix/player-clock")
    create_parser.add_argument("--parent", type=Path, default=Path("/tmp"))

    archive_parser = subparsers.add_parser("archive", help="snapshot a worktree locally")
    archive_parser.add_argument("worktree", type=Path)
    archive_parser.add_argument("--output-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    archive_parser.add_argument("--label", default="")

    verify_parser = subparsers.add_parser("verify-archive", help="verify archive checksums")
    verify_parser.add_argument("archive", type=Path)

    retire_parser = subparsers.add_parser("retire", help="remove a clean, backed-up worktree")
    retire_parser.add_argument("worktree", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = args.repo.resolve()

    if args.command == "audit":
        states, stash_count = audit(repo)
        if args.json:
            payload = {
                "worktrees": [asdict(state) for state in states],
                "stash_count": stash_count,
            }
            print(json.dumps(payload, indent=2))
        else:
            _print_audit(states, stash_count)
        if args.strict:
            failure = _strict_failure(states, stash_count)
            if failure:
                print(f"strict audit FAIL: {failure}", file=sys.stderr)
                return 1
            print("strict audit PASS")
        return 0

    if args.command == "create":
        state = create_worktree(args.branch, repo, args.parent)
        print(f"created {state.path} on {state.branch}")
        return 0

    if args.command == "archive":
        archive = archive_worktree(args.worktree.resolve(), repo, args.output_root, args.label)
        valid = verify_archive(archive)
        print(f"archive={archive} verified={valid}")
        return 0 if valid else 1

    if args.command == "verify-archive":
        valid = verify_archive(args.archive.resolve())
        print(f"archive verified: {valid}")
        return 0 if valid else 1

    if args.command == "retire":
        retire_worktree(args.worktree.resolve(), repo)
        print(f"retired {args.worktree.resolve()}")
        return 0

    raise AssertionError("unreachable command")


if __name__ == "__main__":
    raise SystemExit(main())
