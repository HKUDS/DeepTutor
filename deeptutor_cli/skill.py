"""
CLI Skill Commands
==================

Manage local skills and install packages from external hubs (EduHub, ClawHub, …).

Hub references use ``<hub>:<slug>[@version]``; the hub prefix defaults to
``eduhub`` (DeepTutor's native open skill registry). Installs run the full
import gate: hub security verdict →
safe extraction → frontmatter adaptation (``always`` stripped, flat
``bins``/``env`` folded into ``requires``) → provenance in ``.hub-lock.json``.

In a multi-user deployment this CLI operates the owner (admin) workspace, so
an installed skill lands in the admin catalog and stays invisible to other
users until a grant assigns it.
"""

from __future__ import annotations

from rich.table import Table
import typer

from .common import console


def _resolve_token(explicit: str | None, hub: str) -> str | None:
    """Publish token precedence: --token → env → ``skill login`` store."""
    import os

    from deeptutor.services.skill import credentials

    return (
        explicit
        or os.environ.get("DEEPTUTOR_HUB_TOKEN")
        or os.environ.get("EDUHUB_TOKEN")
        or credentials.get_stored_token(hub)
    )


def _summary_table(
    title: str,
    *,
    hub: str,
    slug: str,
    version: str,
    overrides: dict[str, str],
) -> Table:
    """Confirmation table for the resolved classification (publish/update)."""
    from deeptutor.services.skill.taxonomy import domain_label, track_label

    def shown(key: str, empty: str, *, as_domain: bool = False) -> str:
        vals = [v for v in overrides.get(key, "").split(",") if v]
        if not vals:
            return empty
        return "、".join(domain_label(v) if as_domain else v for v in vals)

    table = Table(title=title, show_header=False, title_style="bold")
    table.add_column("字段", style="dim")
    table.add_column("值")
    table.add_row("hub", hub)
    table.add_row("slug", slug)
    table.add_row("version", version or "[red]缺失[/]")
    track = overrides.get("track", "")
    table.add_row("track", f"{track_label(track)} [dim]{track}[/]" if track else "[red]缺失[/]")
    table.add_row("language", overrides.get("language", ""))
    table.add_row("domains", shown("domains", "[dim]通用[/]", as_domain=True))
    table.add_row("stages", shown("stages", "[dim]全学段[/]"))
    table.add_row("forms", shown("forms", "[dim]—[/]"))
    table.add_row("audiences", shown("audiences", "[dim]学习者[/]"))
    table.add_row("tags", shown("tags", "[dim]—[/]"))
    return table


def register(app: typer.Typer) -> None:
    @app.command("search")
    def skill_search(
        query: str = typer.Argument(..., help="Natural-language search query."),
        hub: str | None = typer.Option(
            None, "--hub", help="Hub to search (default from settings)."
        ),
        limit: int = typer.Option(10, "--limit", min=1, max=50, help="Max results."),
    ) -> None:
        """Search a skill hub."""
        from deeptutor.services.skill.hub import HubError, default_hub, get_hub_provider

        target = (hub or default_hub()).strip().lower()
        try:
            refs = get_hub_provider(target).search(query, limit=limit)
        except HubError as exc:
            console.print(f"[bold red]Search failed:[/] {exc}")
            raise typer.Exit(code=1)
        if not refs:
            console.print("[dim]No skills matched.[/]")
            return
        table = Table(title=f"{target}: {query}")
        table.add_column("Ref", style="bold")
        table.add_column("Version")
        table.add_column("Summary")
        for ref in refs:
            table.add_row(
                f"{ref.hub}:{ref.slug}",
                ref.version or "-",
                ref.summary[:100] or ref.display_name,
            )
        console.print(table)
        console.print("[dim]Install with: deeptutor skill install <ref>[/]")

    @app.command("install")
    def skill_install(
        ref: str = typer.Argument(..., help="Skill ref: <hub>:<slug>[@version]."),
        name: str | None = typer.Option(
            None, "--name", help="Install under a different local skill name."
        ),
        force: bool = typer.Option(
            False, "--force", help="Overwrite an existing skill with the same name."
        ),
        allow_unverified: bool = typer.Option(
            False,
            "--allow-unverified",
            help="Install even when the hub flags the package as suspicious.",
        ),
    ) -> None:
        """Install a skill from a hub into the local skill library."""
        from deeptutor.services.skill.hub import HubError, install_from_hub
        from deeptutor.services.skill.service import (
            InvalidSkillNameError,
            SkillExistsError,
            SkillImportError,
            get_skill_service,
        )

        service = get_skill_service()
        try:
            outcome = install_from_hub(
                ref,
                service=service,
                rename_to=name,
                force=force,
                allow_unverified=allow_unverified,
            )
        except SkillExistsError as exc:
            console.print(
                f"[bold red]Skill `{exc}` already exists.[/] Re-run with --force to replace it."
            )
            raise typer.Exit(code=1)
        except (HubError, SkillImportError, InvalidSkillNameError) as exc:
            console.print(f"[bold red]Install failed:[/] {exc}")
            raise typer.Exit(code=1)

        info = outcome.result.info
        verdict = outcome.verdict
        verdict_style = {"ok": "green", "suspicious": "red"}.get(verdict.status, "yellow")
        console.print(
            f"[bold green]Installed[/] [bold]{info.name}[/]"
            + (f" [dim]({outcome.ref.hub}@{outcome.ref.version})[/]" if outcome.ref.version else "")
        )
        console.print(
            f"  verdict: [{verdict_style}]{verdict.status}[/]"
            + (f" [dim]{verdict.detail}[/]" if verdict.detail else "")
        )
        if verdict.status != "ok":
            console.print(
                f"  [yellow]Review before use:[/] [dim]{service.root / info.name / 'SKILL.md'}[/]"
            )
        for entry in service.summary_entries():
            if entry.name == info.name and not entry.available:
                console.print(f"  [yellow]unavailable until:[/] {', '.join(entry.missing)}")
        for rel, reason in outcome.result.skipped:
            console.print(f"  [dim]skipped {rel} — {reason}[/]")

    @app.command("login")
    def skill_login(
        provider: str | None = typer.Argument(
            None, help="登录方式：github | google（不填则在终端询问）。"
        ),
        hub: str | None = typer.Option(None, "--hub", help="Target hub (default from settings)."),
        no_browser: bool = typer.Option(
            False, "--no-browser", help="不自动打开浏览器，只打印授权链接。"
        ),
    ) -> None:
        """浏览器授权登录到 skill hub，令牌保存在本地供 publish / update 使用。"""
        from deeptutor.services.skill import credentials
        from deeptutor.services.skill.hub import HubError, default_hub, get_hub_provider
        from deeptutor.services.skill.taxonomy import Option

        from .skill_login import hub_origin_from_base, run_login
        from .skill_prompts import select_one

        target_hub = (hub or default_hub()).strip().lower()
        try:
            provider_obj = get_hub_provider(target_hub)
        except HubError as exc:
            console.print(f"[bold red]{exc}[/]")
            raise typer.Exit(code=1)
        base_url = getattr(provider_obj, "base_url", None)
        if not base_url:
            console.print(f"[bold red]Hub `{target_hub}` 不支持网页登录（非 clawhub 型）。[/]")
            raise typer.Exit(code=1)
        origin = hub_origin_from_base(str(base_url))

        prov = (provider or "").strip().lower()
        if prov not in ("github", "google"):
            prov = select_one(
                [Option("github", "GitHub", "GitHub"), Option("google", "Google", "Google")],
                "选择登录方式",
            )

        console.print(f"[dim]在浏览器完成 {prov} 授权（hub: {target_hub}）…[/]")
        result = run_login(
            origin,
            prov,
            on_url=lambda u: console.print(
                f"  若浏览器未自动打开，请手动访问：\n  [underline]{u}[/]"
            ),
            open_browser=not no_browser,
        )
        if result.error or not result.token:
            console.print(f"[bold red]登录失败：[/] {result.error or '未收到令牌'}")
            raise typer.Exit(code=1)
        try:
            credentials.store_token(target_hub, result.token, login=result.login)
        except RuntimeError as exc:
            console.print(f"[bold red]令牌保存失败：[/] {exc}")
            raise typer.Exit(code=1)
        who = f" as @{result.login}" if result.login else ""
        console.print(f"[bold green]已登录[/] {target_hub}{who}，令牌已保存到本地。")

    @app.command("logout")
    def skill_logout(
        hub: str | None = typer.Option(None, "--hub", help="Target hub (default from settings)."),
    ) -> None:
        """清除本地保存的某个 hub 登录令牌。"""
        from deeptutor.services.skill import credentials
        from deeptutor.services.skill.hub import default_hub

        target_hub = (hub or default_hub()).strip().lower()
        if credentials.clear_token(target_hub):
            console.print(f"[green]已登出[/] {target_hub}。")
        else:
            console.print(f"[dim]{target_hub} 本来就没有保存的令牌。[/]")

    @app.command("publish")
    def skill_publish(
        directory: str = typer.Argument(..., help="Skill directory containing SKILL.md."),
        version: str | None = typer.Option(
            None, "--version", help="semver to publish; overrides SKILL.md `version:`."
        ),
        slug: str | None = typer.Option(
            None, "--slug", help="Override slug (default: SKILL.md slug/name)."
        ),
        track: str | None = typer.Option(
            None, "--track", help="Track (skips the track prompt when set)."
        ),
        hub: str | None = typer.Option(None, "--hub", help="Target hub (default from settings)."),
        token: str | None = typer.Option(
            None, "--token", help="Publish token; else env / `deeptutor skills login`."
        ),
        yes: bool = typer.Option(
            False,
            "--yes",
            "-y",
            help="Non-interactive: take classification from SKILL.md/flags as-is (CI).",
        ),
    ) -> None:
        """Publish a skill: interactively tag it (track + facets), then upload.

        Pre-flights the package format, walks the required track (one-of) and
        optional facets — pre-filled from SKILL.md frontmatter — shows a summary
        for confirmation, then publishes. ``--yes`` skips the prompts for CI.
        """
        import sys

        from deeptutor.services.skill.hub import (
            HubError,
            default_hub,
            preflight_skill_dir,
            publish_to_hub,
            read_skill_metadata,
            resolve_publish_identity,
        )
        from deeptutor.services.skill.service import SkillImportError

        from .skill_prompts import collect_classification

        target_hub = (hub or default_hub()).strip().lower()

        # ── step 3: local format pre-flight ────────────────────────────────
        pre = preflight_skill_dir(directory)
        for warning in pre.warnings:
            console.print(f"[yellow]⚠[/] {warning}")
        if not pre.ok:
            console.print("[bold red]格式预检未通过，请先修复：[/]")
            for err in pre.errors:
                console.print(f"  [red]✗[/] {err}")
            console.print("  [dim]格式规范见 https://eduhub.deeptutor.info/skill-format.md[/]")
            raise typer.Exit(code=1)
        console.print(
            f"[green]✓[/] 格式预检通过 "
            f"[dim]({pre.file_count} 个文件, {pre.total_bytes // 1024} KB)[/]"
        )

        fm = read_skill_metadata(directory)
        interactive = (not yes) and sys.stdin.isatty()
        overrides: dict[str, str] = {}
        eff_version = (version or str(fm.get("version") or "")).strip()

        if interactive:
            # step 4: required track + optional facets, pre-filled from frontmatter
            overrides = collect_classification({**fm, "track": track or fm.get("track")})
            if not eff_version:
                eff_version = typer.prompt("\n版本号 version (semver)", default="1.0.0").strip()
            # step 5: confirmation summary
            preview_slug, _ = resolve_publish_identity(directory, slug=slug, version=eff_version)
            console.print(
                _summary_table(
                    "确认发布信息",
                    hub=target_hub,
                    slug=preview_slug,
                    version=eff_version,
                    overrides=overrides,
                )
            )
            if not typer.confirm("确认提交？", default=True):
                console.print("[dim]已取消。[/]")
                raise typer.Exit(code=0)
        else:
            # Non-interactive (CI): track must come from --track or frontmatter.
            eff_track = track or str(fm.get("track") or "")
            if not eff_track:
                console.print(
                    "[bold red]缺少 track。[/] 加 --track，或在 SKILL.md 写 track:，"
                    "或去掉 --yes 走交互式打标。"
                )
                raise typer.Exit(code=1)

        tok = _resolve_token(token, target_hub)
        if not tok:
            console.print(
                "[bold red]未登录。[/] 运行 [bold]deeptutor skills login[/] 完成浏览器授权，"
                "或用 --token / $DEEPTUTOR_HUB_TOKEN 传入令牌。"
            )
            raise typer.Exit(code=1)

        try:
            outcome = publish_to_hub(
                directory,
                token=tok,
                version=eff_version or None,
                slug=slug,
                track=track,
                hub=target_hub,
                overrides=overrides or None,
            )
        except (HubError, SkillImportError) as exc:
            console.print(f"[bold red]Publish failed:[/] {exc}")
            raise typer.Exit(code=1)

        console.print(
            f"[bold green]Published[/] [bold]{outcome.slug}@{outcome.version}[/] → {outcome.hub}"
        )
        console.print(
            f"  [dim]install with:[/] deeptutor skill install {outcome.hub}:{outcome.slug}"
        )

    @app.command("update")
    def skill_update(
        directory: str | None = typer.Argument(
            None, help="新版本的 skill 目录（升级新版本时用；回退不需要）。"
        ),
        hub: str | None = typer.Option(None, "--hub", help="Target hub (default from settings)."),
        token: str | None = typer.Option(
            None, "--token", help="Publish token; else env / `deeptutor skills login`."
        ),
    ) -> None:
        """维护已发布技能：列出我的技能 → 选一个 → 回退旧版本，或发布新版本。

        升级新版本时，打标环节默认沿用该技能当前的 track 与各维度标签；回退则
        把 ``latest`` 指针指回某个更旧的已发布版本，不新建版本。
        """
        import sys

        from deeptutor.services.skill.hub import (
            HubError,
            default_hub,
            get_hub_provider,
            preflight_skill_dir,
            publish_to_hub,
        )
        from deeptutor.services.skill.service import SkillImportError
        from deeptutor.services.skill.taxonomy import Option

        from .skill_prompts import collect_classification, select_one

        target_hub = (hub or default_hub()).strip().lower()
        if not sys.stdin.isatty():
            console.print("[bold red]update 是交互式命令，请在终端中运行。[/]")
            raise typer.Exit(code=1)

        tok = _resolve_token(token, target_hub)
        if not tok:
            console.print(
                "[bold red]未登录。[/] 运行 [bold]deeptutor skills login[/] 完成浏览器授权，"
                "或用 --token 传入令牌。"
            )
            raise typer.Exit(code=1)

        provider = get_hub_provider(target_hub)
        lister = getattr(provider, "list_my_skills", None)
        if not callable(lister):
            console.print(f"[bold red]Hub `{target_hub}` 不支持列出已发布技能。[/]")
            raise typer.Exit(code=1)
        try:
            mine = [s for s in lister(tok) if s.get("slug")]
        except HubError as exc:
            console.print(f"[bold red]获取失败：[/] {exc}")
            raise typer.Exit(code=1)
        if not mine:
            console.print(f"[dim]你还没有在 {target_hub} 发布过技能。[/]")
            raise typer.Exit(code=0)

        # ── step 3: pick a skill, then pick the action ────────────────────
        skill_opts = [
            Option(
                str(s["slug"]),
                f"{s.get('displayName') or s['slug']}  v{s.get('version') or '-'}",
                str(s["slug"]),
            )
            for s in mine
        ]
        chosen_slug = select_one(skill_opts, "选择要更新的技能")
        chosen = next(s for s in mine if s.get("slug") == chosen_slug)
        versions = [str(v) for v in (chosen.get("versions") or [])]
        current = str(chosen.get("version") or "")

        action = select_one(
            [
                Option("rollback", "回退版本（把 latest 指回旧版本）", "Roll back"),
                Option("upgrade", "发布新版本", "Publish a new version"),
            ],
            f"对 {chosen_slug} 做什么？",
        )

        # ── rollback: move latest to an older version ─────────────────────
        if action == "rollback":
            if len([v for v in versions if v != current]) == 0:
                console.print(f"[dim]{chosen_slug} 只有一个版本（{current}），无法回退。[/]")
                raise typer.Exit(code=0)
            version_opts = [Option(v, "← 当前 latest" if v == current else "", v) for v in versions]
            target_version = select_one(version_opts, "回退 latest 到哪个版本？")
            if target_version == current:
                console.print("[dim]已是当前 latest，无需回退。[/]")
                raise typer.Exit(code=0)
            if not typer.confirm(
                f"把 {chosen_slug} 的 latest 从 {current or '-'} 回退到 {target_version}？",
                default=True,
            ):
                console.print("[dim]已取消。[/]")
                raise typer.Exit(code=0)
            tag_setter = getattr(provider, "set_dist_tag", None)
            if not callable(tag_setter):
                console.print(f"[bold red]Hub `{target_hub}` 不支持回退 latest。[/]")
                raise typer.Exit(code=1)
            try:
                tag_setter(chosen_slug, version=target_version, token=tok)
            except HubError as exc:
                console.print(f"[bold red]回退失败：[/] {exc}")
                raise typer.Exit(code=1)
            console.print(
                f"[bold green]已回退[/] {chosen_slug} 的 latest → [bold]{target_version}[/]"
            )
            return

        # ── upgrade: publish a new version (tags default to current) ──────
        if not directory:
            directory = typer.prompt("新版本的 skill 目录路径").strip()
        pre = preflight_skill_dir(directory)
        for warning in pre.warnings:
            console.print(f"[yellow]⚠[/] {warning}")
        if not pre.ok:
            console.print("[bold red]格式预检未通过，请先修复：[/]")
            for err in pre.errors:
                console.print(f"  [red]✗[/] {err}")
            raise typer.Exit(code=1)
        console.print(
            f"[green]✓[/] 格式预检通过 "
            f"[dim]({pre.file_count} 个文件, {pre.total_bytes // 1024} KB)[/]"
        )

        overrides = collect_classification(chosen)
        new_version = typer.prompt(
            f"\n新版本号 version (semver，当前 latest = {current or '-'})"
        ).strip()

        console.print(
            _summary_table(
                "确认升级信息",
                hub=target_hub,
                slug=chosen_slug,
                version=new_version,
                overrides=overrides,
            )
        )
        if not typer.confirm("确认发布新版本？", default=True):
            console.print("[dim]已取消。[/]")
            raise typer.Exit(code=0)

        try:
            outcome = publish_to_hub(
                directory,
                token=tok,
                version=new_version or None,
                slug=chosen_slug,
                hub=target_hub,
                overrides=overrides,
            )
        except (HubError, SkillImportError) as exc:
            console.print(f"[bold red]Update failed:[/] {exc}")
            raise typer.Exit(code=1)
        console.print(
            f"[bold green]Updated[/] [bold]{outcome.slug}@{outcome.version}[/] → {outcome.hub}"
        )

    @app.command("list")
    def skill_list() -> None:
        """List local skills, including hub provenance."""
        from deeptutor.services.skill.service import get_skill_service

        service = get_skill_service()
        table = Table(title="Skills")
        table.add_column("Name", style="bold")
        table.add_column("Source")
        table.add_column("Origin")
        table.add_column("Description")
        for info in service.list_skills():
            origin = service.hub_origin(info.name)
            origin_label = "-"
            if origin:
                version = str(origin.get("version") or "").strip()
                origin_label = str(origin.get("hub") or "hub") + (f"@{version}" if version else "")
            table.add_row(info.name, info.source, origin_label, info.description[:80])
        console.print(table)

    @app.command("remove")
    def skill_remove(
        name: str = typer.Argument(..., help="Skill name to remove."),
    ) -> None:
        """Remove a user-layer skill (builtin skills are read-only)."""
        from deeptutor.services.skill.service import (
            InvalidSkillNameError,
            SkillNotFoundError,
            SkillReadOnlyError,
            get_skill_service,
        )

        try:
            get_skill_service().delete(name)
        except (SkillNotFoundError, InvalidSkillNameError):
            console.print(f"[bold red]Skill not found:[/] {name}")
            raise typer.Exit(code=1)
        except SkillReadOnlyError as exc:
            console.print(f"[bold red]{exc}[/]")
            raise typer.Exit(code=1)
        console.print(f"[green]Removed[/] {name}")
