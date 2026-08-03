"""Build the vendored CLI-Anything catalog snapshot.

Trims the two upstream registries to the fields DeepTutor reads and stamps the
commit the harness installs are pinned to. Install commands are kept *verbatim*:
turning one into an executable spec is a security-relevant transform, so it lives
in `loader.py` with tests rather than being baked into vendored data.
"""

from __future__ import annotations

import json
from pathlib import Path

PIN = "bc536c9bebb7c3d9f7bb2736a732609139c1acdb"
PIN_DATE = "2026-07-09"

KEEP = (
    "name",
    "display_name",
    "version",
    "description",
    "requires",
    "homepage",
    "source_url",
    "install_cmd",
    "entry_point",
    "skill_md",
    "category",
    "package_manager",
    "npx_cmd",
    "platform",
    "install_notes",
)

here = Path(__file__).parent
out: list[dict] = []
for path, origin in (("cli-registry.json", "harness"), ("cli-public_registry.json", "public")):
    for raw in json.loads((here / path).read_text(encoding="utf-8"))["clis"]:
        row = {key: raw[key] for key in KEEP if raw.get(key)}
        row["origin"] = origin
        out.append(row)

out.sort(key=lambda row: row["name"])
seen: dict[str, dict] = {}
for row in out:
    if row["name"] in seen:
        raise SystemExit(f"duplicate app id across registries: {row['name']}")
    seen[row["name"]] = row

payload = {
    "meta": {
        "source": "https://github.com/HKUDS/CLI-Anything",
        "registries": ["registry.json", "public_registry.json"],
        "commit": PIN,
        "commit_date": PIN_DATE,
        "note": (
            "Generated snapshot; do not hand-edit. `commit` is the reviewed "
            "CLI-Anything revision every first-party harness install is pinned to."
        ),
    },
    "apps": out,
}
target = here / "cli_apps_snapshot.json"
target.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"{len(out)} apps -> {target} ({target.stat().st_size:,} bytes)")
