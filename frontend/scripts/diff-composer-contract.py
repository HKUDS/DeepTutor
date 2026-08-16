#!/usr/bin/env python3
import json
import sys
from pathlib import Path

KEYS = [
    "box",
    "className",
    "style.display",
    "style.height",
    "style.minHeight",
    "style.maxHeight",
    "style.paddingTop",
    "style.paddingRight",
    "style.paddingBottom",
    "style.paddingLeft",
    "style.marginTop",
    "style.marginRight",
    "style.marginBottom",
    "style.marginLeft",
    "style.borderTopWidth",
    "style.borderTopColor",
    "style.borderTopLeftRadius",
    "style.backgroundColor",
    "style.boxShadow",
    "style.fontSize",
    "style.fontWeight",
    "style.lineHeight",
    "style.color",
    "style.gap",
    "style.alignItems",
    "style.justifyContent",
    "disabled",
    "aria.label",
]

PARTS = [
    "messageInput", "container", "editorPart", "upper", "wrapper",
    "placeholder", "editable", "lower", "left", "right",
    "plus", "plugin", "model", "mic", "send",
]


def get(d, path):
    cur = d
    for p in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            return None
    return cur


def load(name):
    p = Path(__file__).parent / f"probe-composer-contract.{name}.json"
    return json.loads(p.read_text())


def compare(a_name, b_name, state="focusedEmpty"):
    a = load(a_name)
    b = load(b_name)
    sa = a["states"][state]
    sb = b["states"][state]
    print(f"\n======== {a_name} vs {b_name}  [{state}] ========")
    print(f"A url: {sa.get('url')}")
    print(f"B url: {sb.get('url')}")
    print(f"A active: {sa.get('active')}")
    print(f"B active: {sb.get('active')}")
    diffs = 0
    for part in PARTS:
        pa = sa["parts"].get(part) or {}
        pb = sb["parts"].get(part) or {}
        part_diffs = []
        for k in KEYS:
            va = get(pa, k)
            vb = get(pb, k)
            if va != vb:
                part_diffs.append((k, va, vb))
        if part_diffs:
            print(f"\n--- {part} ---")
            for k, va, vb in part_diffs:
                print(f"  {k}")
                print(f"    A: {va}")
                print(f"    B: {vb}")
                diffs += 1
    print(f"\ntoolbar A: {[(t.get('aria'), t.get('className'), t.get('box'), t.get('bg')) for t in sa.get('toolbarButtons', [])]}")
    print(f"toolbar B: {[(t.get('aria'), t.get('className'), t.get('box'), t.get('bg')) for t in sb.get('toolbarButtons', [])]}")
    print(f"\nDIFF COUNT: {diffs}")


if __name__ == "__main__":
    compare("traework-home", "askora-home", "focusedEmpty")
    compare("traework-home", "askora-home", "typed")
    if (Path(__file__).parent / "probe-composer-contract.askora-session.json").exists():
        compare("traework-session", "askora-session", "focusedEmpty")
        compare("traework-session", "askora-session", "typed")
