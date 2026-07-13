#!/usr/bin/env python
"""Safely update a local DeepTutor git checkout.

The updater is intentionally conservative:
1. Fetch the remote for the current branch.
2. Show the local-vs-remote gap and ask for confirmation.
3. Fast-forward pull only when the branch can be updated safely.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class UpdateError(Exception):
    """Raised for user-actionable update failures."""


@dataclass(frozen=True)
class GitResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class BranchTarget:
    local_branch: str
    remote: str
    remote_branch: str
    remote_ref: str
    upstream: str | None
    source: str

    @property
    def display_remote_ref(self) -> str:
        return f"{self.remote}/{self.remote_branch}"


@dataclass(frozen=True)
class BranchGap:
    local_sha: str
    local_subject: str
    remote_sha: str
    remote_subject: str
    ahead: int
    behind: int
    incoming_commits: list[str]
    outgoing_commits: list[str]
    diff_stat: str
    dirty_entries: list[str]

    @property
    def is_up_to_date(self) -> bool:
        return self.ahead == 0 and self.behind == 0

    @property
    def is_fast_forwardable(self) -> bool:
        return self.ahead == 0 and self.behind > 0

    @property
    def is_diverged(self) -> bool:
        return self.ahead > 0 and self.behind > 0


class Git:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def run(
        self,
        args: Sequence[str],
        *,
        check: bool = True,
        timeout: int | None = 60,
    ) -> GitResult:
        cmd = ["git", *args]
        completed = subprocess.run(
            cmd,
            cwd=self.repo_root,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            text=True,
            timeout=timeout,
        )
        result = GitResult(
            args=tuple(args),
            returncode=completed.returncode,
            stdout=completed.stdout.strip(),
            stderr=completed.stderr.strip(),
        )
        if check and result.returncode != 0:
            message = result.stderr or result.stdout or f"git {' '.join(args)} failed"
            raise UpdateError(message)
        return result


def _print_section(title: str) -> None:
    print()
    print(f"== {title} ==")


def _print_list(title: str, items: list[str], *, empty: str) -> None:
    print(f"{title}:")
    if not items:
        print(f"  {empty}")
        return
    for item in items:
        print(f"  {item}")


def ensure_git_checkout(git: Git) -> None:
    inside = git.run(["rev-parse", "--is-inside-work-tree"]).stdout
    if inside != "true":
        raise UpdateError("This directory is not inside a git checkout.")


def current_branch(git: Git) -> str:
    branch = git.run(["branch", "--show-current"]).stdout
    if not branch:
        raise UpdateError(
            "Detached HEAD detected. Please switch to a branch before running the updater."
        )
    return branch


def git_config(git: Git, key: str) -> str | None:
    result = git.run(["config", "--get", key], check=False)
    if result.returncode != 0:
        return None
    return result.stdout or None


def available_remotes(git: Git) -> list[str]:
    remotes = git.run(["remote"], check=False).stdout.splitlines()
    return [remote.strip() for remote in remotes if remote.strip()]


def normalize_merge_ref(merge_ref: str | None, fallback_branch: str) -> str:
    if not merge_ref:
        return fallback_branch
    prefix = "refs/heads/"
    if merge_ref.startswith(prefix):
        return merge_ref[len(prefix) :]
    return merge_ref


def resolve_branch_target(git: Git, branch: str) -> BranchTarget:
    remote = git_config(git, f"branch.{branch}.remote")
    merge_ref = git_config(git, f"branch.{branch}.merge")

    if remote and remote != ".":
        remote_branch = normalize_merge_ref(merge_ref, branch)
        return BranchTarget(
            local_branch=branch,
            remote=remote,
            remote_branch=remote_branch,
            remote_ref=f"refs/remotes/{remote}/{remote_branch}",
            upstream=f"{remote}/{remote_branch}",
            source="configured upstream",
        )

    remotes = available_remotes(git)
    if not remotes:
        raise UpdateError("No git remote is configured for this checkout.")

    selected_remote = "origin" if "origin" in remotes else remotes[0]
    return BranchTarget(
        local_branch=branch,
        remote=selected_remote,
        remote_branch=branch,
        remote_ref=f"refs/remotes/{selected_remote}/{branch}",
        upstream=None,
        source=f"default remote '{selected_remote}' with matching branch name",
    )


def fetch_remote(git: Git, target: BranchTarget) -> None:
    print(f"Fetching latest refs from {target.remote} ...")
    git.run(["fetch", "--prune", target.remote], timeout=None)


def verify_remote_branch(git: Git, target: BranchTarget) -> None:
    result = git.run(
        ["rev-parse", "--verify", "--quiet", f"{target.remote_ref}^{{commit}}"],
        check=False,
    )
    if result.returncode == 0:
        return
    raise UpdateError(
        "Remote branch not found after fetch: "
        f"{target.display_remote_ref}. Set the branch upstream or push it first."
    )


def short_commit(git: Git, ref: str) -> tuple[str, str]:
    sha = git.run(["rev-parse", "--short", ref]).stdout
    subject = git.run(["log", "-1", "--format=%s", ref]).stdout
    return sha, subject


def log_lines(git: Git, revision_range: str, limit: int = 8) -> list[str]:
    result = git.run(
        ["log", "--oneline", "--decorate", f"--max-count={limit}", revision_range],
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        return []
    return result.stdout.splitlines()


def tracked_dirty_entries(git: Git) -> list[str]:
    git.run(["update-index", "-q", "--refresh"], check=False)
    result = git.run(["status", "--porcelain=v1", "--untracked-files=no"], check=False)
    if result.returncode != 0 or not result.stdout:
        return []
    return result.stdout.splitlines()


def analyze_gap(git: Git, target: BranchTarget) -> BranchGap:
    local_sha, local_subject = short_commit(git, "HEAD")
    remote_sha, remote_subject = short_commit(git, target.remote_ref)

    counts = git.run(["rev-list", "--left-right", "--count", f"HEAD...{target.remote_ref}"])
    ahead_str, behind_str = counts.stdout.split()
    ahead = int(ahead_str)
    behind = int(behind_str)

    diff_stat = ""
    if behind:
        diff_stat = git.run(
            ["diff", "--stat", "--compact-summary", f"HEAD..{target.remote_ref}"]
        ).stdout

    return BranchGap(
        local_sha=local_sha,
        local_subject=local_subject,
        remote_sha=remote_sha,
        remote_subject=remote_subject,
        ahead=ahead,
        behind=behind,
        incoming_commits=log_lines(git, f"HEAD..{target.remote_ref}"),
        outgoing_commits=log_lines(git, f"{target.remote_ref}..HEAD"),
        diff_stat=diff_stat,
        dirty_entries=tracked_dirty_entries(git),
    )


def print_gap(target: BranchTarget, gap: BranchGap) -> None:
    _print_section("Detected branch")
    print(f"Local branch:  {target.local_branch}")
    print(f"Remote branch: {target.display_remote_ref}")
    print(f"Selection:     {target.source}")
    if target.upstream:
        print(f"Upstream:      {target.upstream}")
    else:
        print("Upstream:      not configured")

    _print_section("Local vs remote")
    print(f"Local HEAD:    {gap.local_sha} {gap.local_subject}")
    print(f"Remote HEAD:   {gap.remote_sha} {gap.remote_subject}")
    print(f"Gap:           local is {gap.ahead} commit(s) ahead, {gap.behind} commit(s) behind")

    _print_list(
        "Incoming commits from remote",
        gap.incoming_commits,
        empty="none",
    )
    _print_list(
        "Local commits not on remote",
        gap.outgoing_commits,
        empty="none",
    )

    if gap.diff_stat:
        print("Incoming file summary:")
        for line in gap.diff_stat.splitlines():
            print(f"  {line}")

    if gap.dirty_entries:
        _print_list(
            "Tracked local changes",
            gap.dirty_entries,
            empty="none",
        )


def confirm_update(assume_yes: bool, target: BranchTarget, gap: BranchGap) -> bool:
    if assume_yes:
        return True

    if not sys.stdin.isatty():
        print()
        print("Confirmation required, but stdin is not interactive. Re-run with --yes to update.")
        return False

    print()
    answer = input(
        "Confirm this branch mapping and update "
        f"{target.local_branch} from {target.display_remote_ref}? [y/N] "
    ).strip()
    return answer.lower() in {"y", "yes"}


def ensure_safe_to_update(gap: BranchGap) -> None:
    if gap.dirty_entries:
        raise UpdateError(
            "Tracked local changes are present. Commit or stash them before updating."
        )
    if gap.is_diverged:
        raise UpdateError(
            "Local and remote branches have diverged. Resolve manually, then rerun the updater."
        )
    if gap.ahead > 0 and gap.behind == 0:
        raise UpdateError(
            "Local branch has commits not present on the remote, and there are no remote "
            "commits to pull."
        )
    if not gap.is_fast_forwardable:
        raise UpdateError("This branch cannot be updated with a safe fast-forward pull.")


def dependency_hints(changed_files: list[str]) -> list[str]:
    hints: list[str] = []
    if any(path == "pyproject.toml" or path.startswith("requirements/") for path in changed_files):
        hints.append("Backend dependencies changed: consider running python -m pip install -e .")
    if any(
        path in {"web/package.json", "web/package-lock.json", "web/pnpm-lock.yaml"}
        or path == "web/yarn.lock"
        for path in changed_files
    ):
        hints.append("Frontend dependencies changed: consider running cd web && npm install")
    return hints


def pull_updates(git: Git, target: BranchTarget) -> list[str]:
    old_sha = git.run(["rev-parse", "HEAD"]).stdout
    _print_section("Updating")
    git.run(["pull", "--ff-only", target.remote, target.remote_branch], timeout=None)
    new_sha = git.run(["rev-parse", "HEAD"]).stdout
    if old_sha == new_sha:
        return []
    changed = git.run(["diff", "--name-only", f"{old_sha}..{new_sha}"]).stdout
    return [line for line in changed.splitlines() if line.strip()]


def run_update(repo_root: Path, *, assume_yes: bool) -> int:
    git = Git(repo_root)
    ensure_git_checkout(git)
    branch = current_branch(git)
    target = resolve_branch_target(git, branch)
    fetch_remote(git, target)
    verify_remote_branch(git, target)
    gap = analyze_gap(git, target)
    print_gap(target, gap)

    if gap.dirty_entries:
        raise UpdateError(
            "Tracked local changes are present. Commit or stash them before updating."
        )
    if gap.is_diverged:
        raise UpdateError(
            "Local and remote branches have diverged. Resolve manually, then rerun the updater."
        )
    if gap.is_up_to_date:
        print()
        print("Already up to date. No update is needed.")
        return 0
    if gap.ahead > 0 and gap.behind == 0:
        print()
        print("No remote commits to pull. Local branch is ahead of the remote.")
        return 0

    if not confirm_update(assume_yes, target, gap):
        print("Update cancelled.")
        return 0

    ensure_safe_to_update(gap)
    changed_files = pull_updates(git, target)

    print()
    print(f"Updated {target.local_branch} from {target.display_remote_ref}.")
    if changed_files:
        print(f"Changed files: {len(changed_files)}")
    for hint in dependency_hints(changed_files):
        print(f"Next step: {hint}")
    print("Restart DeepTutor if it is currently running.")
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch, review, and fast-forward update a local DeepTutor checkout."
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip the interactive confirmation after printing the branch comparison.",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=PROJECT_ROOT,
        help="Path to the git checkout to update. Defaults to this DeepTutor repository.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run_update(args.repo.resolve(), assume_yes=args.yes)
    except KeyboardInterrupt:
        print()
        print("Update cancelled.")
        return 130
    except (OSError, subprocess.SubprocessError, UpdateError) as exc:
        print()
        print(f"Update failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
