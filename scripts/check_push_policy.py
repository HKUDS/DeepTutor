#!/usr/bin/env python3
"""Reject accidental protected-branch pushes and generated artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
import sys

from check_repo_hygiene import violation as tracked_path_violation


@dataclass(frozen=True)
class PushSpec:
    local_ref: str
    local_sha: str
    remote_ref: str
    remote_sha: str


def parse_push_specs(lines: list[str]) -> list[PushSpec]:
    specs: list[PushSpec] = []
    for line in lines:
        fields = line.split()
        if len(fields) != 4:
            raise ValueError(f"Malformed pre-push input: {line!r}")
        specs.append(PushSpec(*fields))
    return specs


def is_upstream_remote(remote_name: str, remote_url: str) -> bool:
    normalized_url = remote_url.rstrip("/").lower()
    return remote_name == "origin" or normalized_url.endswith("hkuds/deeptutor.git")


def allows_upstream_main_push() -> bool:
    result = subprocess.run(
        ["git", "config", "--bool", "deeptutor.allowUpstreamMainPush"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def pushed_paths(revision: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "--name-only", revision],
        check=True,
        capture_output=True,
    )
    return [path for path in result.stdout.decode("utf-8").split("\0") if path]


def policy_errors(
    specs: list[PushSpec],
    *,
    upstream_remote: bool,
    allow_upstream_main: bool,
) -> list[str]:
    errors: list[str] = []
    if upstream_remote:
        for spec in specs:
            if spec.remote_ref == "refs/heads/main" and not allow_upstream_main:
                errors.append("Direct pushes to upstream main are forbidden; use a pull request.")
            for path in pushed_paths(spec.local_sha):
                reason = tracked_path_violation(path)
                if reason:
                    errors.append(f"{spec.local_sha}:{path}: {reason}")
    return errors


def main() -> int:
    remote_name = sys.argv[1] if len(sys.argv) > 1 else ""
    remote_url = sys.argv[2] if len(sys.argv) > 2 else ""
    try:
        specs = parse_push_specs(sys.stdin.read().splitlines())
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1

    errors = policy_errors(
        specs,
        upstream_remote=is_upstream_remote(remote_name, remote_url),
        allow_upstream_main=allows_upstream_main_push(),
    )
    if errors:
        print("Push policy rejected this operation:", file=sys.stderr)
        print("\n".join(errors), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
