#!/usr/bin/env python3
"""Workspace governance tooling for managing git worktrees safely.

Enforces the three-tier workspace governance model:
1. Control Checkout (main repository root): clean, tracks main/dev.
2. Task Worktrees: isolated environments for feature/issue work.
3. Archive-Before-Retire: lossless snapshot (diff patch + untracked tarball + SHA256 manifest)
   before worktree retirement.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

DEFAULT_ARCHIVE_DIR = Path(
    os.environ.get("DEEPTUTOR_ARCHIVE_DIR", "/Users/Shared/DeepTutor-worktree-archives")
)
DEFAULT_WORKTREE_PARENT = Path(
    os.environ.get("DEEPTUTOR_WORKTREE_PARENT", "/Users/Shared")
)


def _run_cmd(
    args: list[str],
    *,
    cwd: Path | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=check,
    )


def _git(
    args: list[str], *, cwd: Path | None = None, check: bool = False
) -> subprocess.CompletedProcess[str]:
    return _run_cmd(["git", *args], cwd=cwd, check=check)


@dataclass
class WorkspaceInfo:
    path: str
    head_sha: str
    branch: str
    is_main: bool
    is_clean: bool
    dirty_files: list[str] = field(default_factory=list)
    untracked_files: list[str] = field(default_factory=list)
    listening_ports: list[int] = field(default_factory=list)
    archived: bool = False
    safe_to_retire: bool = False
    retirement_blockers: list[str] = field(default_factory=list)


def inspect_workspace(
    worktree_path: Path, repo_root: Path, archive_dir: Path = DEFAULT_ARCHIVE_DIR
) -> WorkspaceInfo:
    path_resolved = worktree_path.resolve()
    repo_resolved = repo_root.resolve()
    is_main = path_resolved == repo_resolved

    rev_parse = _git(["rev-parse", "HEAD"], cwd=path_resolved)
    head_sha = rev_parse.stdout.strip() if rev_parse.returncode == 0 else "unknown"

    branch_res = _git(["branch", "--show-current"], cwd=path_resolved)
    branch = (
        branch_res.stdout.strip()
        if branch_res.returncode == 0 and branch_res.stdout.strip()
        else "(detached)"
    )

    status_res = _git(["status", "--porcelain=v1", "--untracked-files=all"], cwd=path_resolved)
    dirty_files: list[str] = []
    untracked_files: list[str] = []
    if status_res.returncode == 0:
        for line in status_res.stdout.splitlines():
            if not line.strip():
                continue
            prefix = line[:2]
            file_name = line[3:].strip()
            if prefix == "??":
                untracked_files.append(file_name)
            else:
                dirty_files.append(file_name)

    is_clean = len(dirty_files) == 0 and len(untracked_files) == 0

    listening_ports: list[int] = []
    try:
        lsof_res = _run_cmd(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"])
        if lsof_res.returncode == 0:
            for line in lsof_res.stdout.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 9:
                    name_field = parts[8]
                    port_str = name_field.rsplit(":", 1)[-1]
                    if port_str.isdigit():
                        port = int(port_str)
                        if port not in listening_ports:
                            listening_ports.append(port)
    except Exception:
        pass

    archived = False
    if archive_dir.exists():
        for meta_file in archive_dir.glob("**/meta.json"):
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                if meta.get("path") == str(path_resolved) or meta.get("name") == path_resolved.name:
                    archived = True
                    break
            except Exception:
                continue

    blockers: list[str] = []
    if is_main:
        blockers.append("Cannot retire the control checkout (main repository root).")
    if not is_clean and not archived:
        blockers.append(
            f"Worktree has {len(dirty_files)} dirty and {len(untracked_files)} untracked files and is not archived."
        )

    safe_to_retire = len(blockers) == 0

    return WorkspaceInfo(
        path=str(path_resolved),
        head_sha=head_sha,
        branch=branch,
        is_main=is_main,
        is_clean=is_clean,
        dirty_files=dirty_files,
        untracked_files=untracked_files,
        listening_ports=listening_ports,
        archived=archived,
        safe_to_retire=safe_to_retire,
        retirement_blockers=blockers,
    )


def list_worktrees(repo_root: Path, archive_dir: Path = DEFAULT_ARCHIVE_DIR) -> list[WorkspaceInfo]:
    res = _git(["worktree", "list", "--porcelain"], cwd=repo_root)
    if res.returncode != 0:
        return []
    worktrees: list[Path] = []
    for line in res.stdout.splitlines():
        if line.startswith("worktree "):
            wt_path = Path(line[len("worktree ") :].strip())
            if wt_path.exists():
                worktrees.append(wt_path)
    return [inspect_workspace(wt, repo_root, archive_dir) for wt in worktrees]


def create_workspace(
    name: str,
    *,
    base_branch: str = "dev",
    repo_root: Path,
    target_parent: Path = DEFAULT_WORKTREE_PARENT,
) -> WorkspaceInfo:
    branch_name = f"codex/{name}" if not name.startswith("codex/") else name
    worktree_dir_name = f"DeepTutor-worktrees-{name.replace("codex/", "").replace("/", "-")}"
    target_dir = target_parent / worktree_dir_name

    if target_dir.exists():
        raise ValueError(f"Target worktree directory already exists: {target_dir}")

    res = _git(
        ["worktree", "add", "-b", branch_name, str(target_dir), f"origin/{base_branch}"],
        cwd=repo_root,
    )
    if res.returncode != 0:
        res = _git(
            ["worktree", "add", "-b", branch_name, str(target_dir), base_branch],
            cwd=repo_root,
        )
        if res.returncode != 0:
            raise RuntimeError(f"Failed to create worktree: {res.stderr.strip()}")

    main_node_modules = repo_root / "web" / "node_modules"
    wt_node_modules = target_dir / "web" / "node_modules"
    if main_node_modules.exists() and not wt_node_modules.exists():
        try:
            wt_node_modules.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(str(main_node_modules), str(wt_node_modules))
        except Exception:
            pass

    return inspect_workspace(target_dir, repo_root)


def archive_workspace(
    worktree_path: Path,
    repo_root: Path,
    *,
    archive_dir: Path = DEFAULT_ARCHIVE_DIR,
    label: str = "",
) -> Path:
    worktree_path = worktree_path.resolve()
    if not worktree_path.exists():
        raise ValueError(f"Worktree path does not exist: {worktree_path}")

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    target_name = f"{timestamp}-{worktree_path.name}"
    if label:
        target_name = f"{timestamp}-{label}-{worktree_path.name}"
    out_dir = archive_dir / target_name
    out_dir.mkdir(parents=True, exist_ok=True)

    info = inspect_workspace(worktree_path, repo_root, archive_dir)

    diff_res = _git(["diff", "HEAD", "--binary"], cwd=worktree_path)
    patch_file = out_dir / "changes.patch"
    patch_file.write_bytes(
        diff_res.stdout.encode("utf-8") if isinstance(diff_res.stdout, str) else diff_res.stdout
    )

    untracked_archive = out_dir / "untracked.tar.gz"
    if info.untracked_files:
        file_list_path = out_dir / "_untracked_files.txt"
        file_list_path.write_text("\n".join(info.untracked_files), encoding="utf-8")
        tar_cmd = ["tar", "-czf", str(untracked_archive), "-T", str(file_list_path)]
        _run_cmd(tar_cmd, cwd=worktree_path)
        if file_list_path.exists():
            file_list_path.unlink()

    meta = {
        "name": worktree_path.name,
        "path": str(worktree_path),
        "archived_at": time.time(),
        "archived_date": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "head_sha": info.head_sha,
        "branch": info.branch,
        "dirty_files": info.dirty_files,
        "untracked_files": info.untracked_files,
        "is_clean": info.is_clean,
    }
    meta_file = out_dir / "meta.json"
    meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    manifest_lines: list[str] = []
    for item in sorted(out_dir.glob("*")):
        if item.is_file() and item.name != "manifest.sha256":
            digest = hashlib.sha256(item.read_bytes()).hexdigest()
            manifest_lines.append(f"{digest}  {item.name}")
    manifest_file = out_dir / "manifest.sha256"
    manifest_file.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")

    return out_dir


def verify_archive(archive_dir: Path) -> bool:
    manifest_file = archive_dir / "manifest.sha256"
    if not manifest_file.exists():
        return False
    for line in manifest_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            return False
        expected_hash, filename = parts[0], parts[1].strip()
        target_file = archive_dir / filename
        if not target_file.exists():
            return False
        actual_hash = hashlib.sha256(target_file.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            return False
    return True


def retire_workspace(
    worktree_path: Path,
    repo_root: Path,
    *,
    archive_dir: Path = DEFAULT_ARCHIVE_DIR,
    force: bool = False,
) -> bool:
    info = inspect_workspace(worktree_path, repo_root, archive_dir)
    if info.is_main:
        raise ValueError("Refusing to retire control checkout (main repo).")

    if not force and not info.safe_to_retire:
        archive_workspace(worktree_path, repo_root, archive_dir=archive_dir)

    res = _git(
        ["worktree", "remove", "--force" if force else "", str(worktree_path)], cwd=repo_root
    )
    if res.returncode != 0:
        _git(["worktree", "prune"], cwd=repo_root)
        if worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)

    _git(["worktree", "prune"], cwd=repo_root)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="DeepTutor Workspace Governance Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # audit
    audit_p = subparsers.add_parser(
        "audit", help="Audit all registered git worktrees and their status"
    )
    audit_p.add_argument("--json", action="store_true", help="Output JSON format")
    audit_p.add_argument("--repo", default=".", help="Repository root path")

    # create
    create_p = subparsers.add_parser("create", help="Create an isolated task worktree")
    create_p.add_argument("name", help="Task / feature name")
    create_p.add_argument("--base", default="dev", help="Base branch (default: dev)")
    create_p.add_argument("--repo", default=".", help="Repository root path")

    # archive
    archive_p = subparsers.add_parser(
        "archive", help="Create a lossless snapshot archive of a worktree"
    )
    archive_p.add_argument("path", help="Worktree directory path")
    archive_p.add_argument(
        "--out", default=str(DEFAULT_ARCHIVE_DIR), help="Archive destination directory"
    )
    archive_p.add_argument("--label", default="", help="Optional label for the archive")
    archive_p.add_argument("--repo", default=".", help="Repository root path")

    # verify
    verify_p = subparsers.add_parser("verify", help="Verify archive checksum manifest")
    verify_p.add_argument("archive_path", help="Path to archive directory")
    verify_p.add_argument("--repo", default=".", help="Repository root path")

    # retire
    retire_p = subparsers.add_parser("retire", help="Safely retire a finished worktree")
    retire_p.add_argument("path", help="Worktree directory path")
    retire_p.add_argument(
        "--force", action="store_true", help="Force retirement without clean check"
    )
    retire_p.add_argument("--repo", default=".", help="Repository root path")

    args = parser.parse_args()
    repo_root = Path(getattr(args, "repo", ".")).resolve()

    if args.command == "audit":
        worktrees = list_worktrees(repo_root)
        if args.json:
            print(json.dumps([asdict(w) for w in worktrees], indent=2))
        else:
            print(f"=== DeepTutor Workspace Audit ({len(worktrees)} worktrees) ===")
            for w in worktrees:
                status = (
                    "CLEAN"
                    if w.is_clean
                    else f"DIRTY ({len(w.dirty_files)} modified, {len(w.untracked_files)} untracked)"
                )
                main_tag = " [MAIN CONTROL]" if w.is_main else ""
                archived_tag = " [ARCHIVED]" if w.archived else ""
                print(f"- {w.path}{main_tag}")
                print(f"  Branch: {w.branch} @ {w.head_sha[:8]} | Status: {status}{archived_tag}")
                if w.retirement_blockers:
                    print(f"  Blockers: {"; ".join(w.retirement_blockers)}")
        return 0

    if args.command == "create":
        info = create_workspace(args.name, base_branch=args.base, repo_root=repo_root)
        print(f"Workspace created successfully at: {info.path}")
        print(f"Branch: {info.branch}")
        return 0

    if args.command == "archive":
        out = archive_workspace(
            Path(args.path), repo_root, archive_dir=Path(args.out), label=args.label
        )
        valid = verify_archive(out)
        print(f"Archive created at: {out} (checksum verified: {valid})")
        return 0 if valid else 1

    if args.command == "verify":
        valid = verify_archive(Path(args.archive_path))
        print(f"Archive verified: {"PASS" if valid else "FAIL"}")
        return 0 if valid else 1

    if args.command == "retire":
        retire_workspace(Path(args.path), repo_root, force=args.force)
        print(f"Worktree retired successfully: {args.path}")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
