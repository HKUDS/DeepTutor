"""Check the working tree before pushing a docs or CLI/API change."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def surface_inputs_changed(base: str) -> bool:
    patterns = json.loads((ROOT / ".github/docs-surface-paths.json").read_text())["surface"]
    # Compare the working tree with the fork point, including committed branch edits.
    ancestor = subprocess.check_output(
        ["git", "merge-base", base, "HEAD"], cwd=ROOT, text=True
    ).strip()
    diff = ["git", "diff", "--no-renames", "--name-only", "-z", ancestor, "--", *patterns]
    untracked = ["git", "ls-files", "--others", "--exclude-standard", "-z", "--", *patterns]
    return bool(
        subprocess.check_output(diff, cwd=ROOT) or subprocess.check_output(untracked, cwd=ROOT)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base", default="HEAD", help="include commits since this ref (default: HEAD)"
    )
    parser.add_argument(
        "--update-surface",
        action="store_true",
        help="regenerate the CLI/API snapshot before checking pages",
    )
    parser.add_argument(
        "--build", action="store_true", help="also build the site and check its links"
    )
    args = parser.parse_args()
    python = sys.executable
    if args.update_surface or surface_inputs_changed(args.base):
        export = [python, "scripts/export_docs_surface.py"]
        if not args.update_surface:
            export.append("--check")
        subprocess.run(export, cwd=ROOT, check=True)
    else:
        print(
            f"No CLI/API inputs changed relative to {args.base}. Skipping live export.", flush=True
        )

    subprocess.run([python, "docs/scripts/check_docs.py"], cwd=ROOT, check=True)
    subprocess.run([python, "-m", "pytest", "-q", "docs/tests"], cwd=ROOT, check=True)
    if args.build:
        subprocess.run(
            ["npm.cmd" if sys.platform == "win32" else "npm", "run", "build"],
            cwd=ROOT / "docs",
            check=True,
        )
        subprocess.run([python, "docs/scripts/check_docs.py", "links"], cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
