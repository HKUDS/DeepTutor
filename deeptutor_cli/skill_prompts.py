"""
Interactive taxonomy pickers for ``skill publish`` / ``skill update``.

Terminal prompts that mirror EduHub's web upload form: a required single-select
``track`` plus the optional multi-select facets (language is single-select with
a default). Selections can be pre-filled — from SKILL.md frontmatter on publish,
or from the current skill's labels on update — so the common path is just
pressing Enter through the prompts.

Kept presentation-only and dependency-light (rich console + ``typer.prompt``)
so the publish/update commands stay readable and these are easy to unit-test.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import typer

from deeptutor.services.skill.taxonomy import (
    AUDIENCE_OPTIONS,
    DOMAIN_TREE,
    FORM_OPTIONS,
    LANGUAGE_OPTIONS,
    STAGE_OPTIONS,
    TRACK_OPTIONS,
    Option,
    is_valid_track,
)

from .common import console


def _render_options(options: Sequence[Option], selected: set[str], locale: str) -> None:
    for i, opt in enumerate(options, 1):
        mark = "[green]●[/]" if opt.value in selected else "[dim]○[/]"
        console.print(f"  {mark} [bold]{i}[/]. {opt.label(locale)}  [dim]{opt.value}[/]")


def _parse_indices(raw: str, count: int) -> list[int] | None:
    """Parse ``"1, 3 4"`` into 0-based indices; None if any token is invalid."""
    out: list[int] = []
    for tok in raw.replace(",", " ").split():
        if not tok.isdigit():
            return None
        n = int(tok)
        if not (1 <= n <= count):
            return None
        if n - 1 not in out:
            out.append(n - 1)
    return out


def select_one(
    options: Sequence[Option],
    title: str,
    *,
    hint: str = "",
    default: str | None = None,
    locale: str = "zh",
) -> str:
    """Prompt for exactly one value. Enter accepts ``default`` when given."""
    console.print(f"\n[bold]{title}[/]" + (f"  [dim]{hint}[/]" if hint else ""))
    _render_options(options, {default} if default else set(), locale)
    default_idx = next((i + 1 for i, o in enumerate(options) if o.value == default), None)
    suffix = f"（回车=默认 {default_idx}）" if default_idx else ""
    while True:
        raw = typer.prompt(f"  输入编号{suffix}", default="", show_default=False).strip()
        if not raw and default_idx:
            return options[default_idx - 1].value
        idx = _parse_indices(raw, len(options))
        if idx and len(idx) == 1:
            return options[idx[0]].value
        console.print("  [red]请输入一个有效编号。[/]")


def select_many(
    options: Sequence[Option],
    title: str,
    *,
    hint: str = "可多选，逗号分隔；回车=保留当前；输入 - 清空",
    preselected: Sequence[str] = (),
    locale: str = "zh",
) -> list[str]:
    """Prompt for zero or more values. Enter keeps ``preselected``; ``-`` clears."""
    current = [v for v in preselected if any(o.value == v for o in options)]
    console.print(f"\n[bold]{title}[/]  [dim]{hint}[/]")
    _render_options(options, set(current), locale)
    while True:
        raw = typer.prompt("  输入编号", default="", show_default=False).strip()
        if not raw:
            return list(current)
        if raw == "-":
            return []
        idx = _parse_indices(raw, len(options))
        if idx is not None:
            return [options[i].value for i in idx]
        console.print("  [red]请输入有效编号（逗号分隔），或回车/-。[/]")


def select_domains(
    *,
    preselected: Sequence[str] = (),
    locale: str = "zh",
) -> list[str]:
    """Two-level domain picker: pick top-level groups, then optional children.

    A group with chosen children contributes those children; a group with none
    contributes the group itself — matching the web form's ``resolveDomains``.
    """
    pre_roots = {v.split(".")[0] for v in preselected}
    root_options = [Option(n.value, n.zh, n.en) for n in DOMAIN_TREE]
    roots = select_many(
        root_options,
        "领域 (domains) — 可多选；选中后可再挑细分",
        preselected=[r for r in pre_roots if any(o.value == r for o in root_options)],
        locale=locale,
    )

    result: list[str] = []
    for root in roots:
        node = next((n for n in DOMAIN_TREE if n.value == root), None)
        if node is None or not node.children:
            result.append(root)
            continue
        pre_children = [v for v in preselected if v.startswith(f"{root}.")]
        children = select_many(
            list(node.children),
            f"  「{node.label(locale)}」的细分 — 可多选；回车=用「{node.label(locale)}」整体",
            hint="可多选，逗号分隔；回车=保留当前/整体；输入 - 清空",
            preselected=pre_children,
            locale=locale,
        )
        result.extend(children if children else [root])
    return result


def _as_list(defaults: dict[str, Any], key: str) -> list[str]:
    value = defaults.get(key)
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        return [s.strip() for s in value.split(",") if s.strip()]
    return []


def collect_classification(defaults: dict[str, Any], *, locale: str = "zh") -> dict[str, str]:
    """Walk the full tagging flow (track + facets), pre-filled from ``defaults``.

    Shared by ``skill publish`` (defaults = SKILL.md frontmatter) and
    ``skill update`` (defaults = the current skill's labels). Returns the
    comma-joined ``overrides`` dict ``publish_to_hub`` expects.
    """
    track_default = str(defaults.get("track") or "")
    track = select_one(
        TRACK_OPTIONS,
        "主类目 track — 必选",
        hint="这个技能服务什么场景？",
        default=track_default if is_valid_track(track_default) else None,
        locale=locale,
    )
    lang_default = str(defaults.get("language") or "zh")
    language = select_one(
        LANGUAGE_OPTIONS,
        "语言 language — 必选",
        hint="技能与用户交流所用的语言",
        default=lang_default if any(o.value == lang_default for o in LANGUAGE_OPTIONS) else "zh",
        locale=locale,
    )
    domains = select_domains(preselected=_as_list(defaults, "domains"), locale=locale)
    stages = select_many(
        STAGE_OPTIONS,
        "学段 stages — 可选；空=全学段通用",
        preselected=_as_list(defaults, "stages"),
        locale=locale,
    )
    forms = select_many(
        FORM_OPTIONS,
        "形式 forms — 可选；技能如何与用户交互",
        preselected=_as_list(defaults, "forms"),
        locale=locale,
    )
    audiences = select_many(
        AUDIENCE_OPTIONS,
        "受众 audiences — 可选；空=面向学习者",
        preselected=_as_list(defaults, "audiences"),
        locale=locale,
    )
    tags_default = ",".join(_as_list(defaults, "tags"))
    tags = typer.prompt(
        "\n标签 tags — 比领域更细，逗号分隔，可空",
        default=tags_default,
        show_default=bool(tags_default),
    ).strip()

    return {
        "track": track,
        "language": language,
        "domains": ",".join(domains),
        "stages": ",".join(stages),
        "forms": ",".join(forms),
        "audiences": ",".join(audiences),
        "tags": tags,
    }


__all__ = ["collect_classification", "select_domains", "select_many", "select_one"]
