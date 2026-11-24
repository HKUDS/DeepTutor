# DeepTutor Documentation

This directory contains the public DeepTutor documentation site (`docs.deeptutor.info`), built with [Astro](https://astro.build/) and [Starlight](https://starlight.astro.build/).

## Stack

- Astro + Starlight
- English source locale at `/` (`src/content/docs/`)
- Simplified Chinese mirror at `/zh-cn/` (`src/content/docs/zh-cn/`)
- Static screenshots and icons in `public/`

## Local Development

```bash
cd docs
npm install
npm run dev
```

Build the static site:

```bash
npm run build
```

Preview the built output:

```bash
npm run preview
```

## Documentation Layout

```text
src/content/docs/            # English docs (root locale /)
src/content/docs/zh-cn/      # Simplified Chinese docs (locale /zh-cn/)
astro.config.mjs             # Starlight config, sidebar, redirects, i18n
src/components/              # Custom header / social icon components
src/styles/                  # Global & Starlight theme styles
public/screenshots/          # Documentation screenshots
```

When adding a docs page, add both locale files in the same relative path. Example:

```text
src/content/docs/partners/channels.md
src/content/docs/zh-cn/partners/channels.md
```

Then add a sidebar item in `astro.config.mjs` with a Chinese translation label.

## Current Docs Map

- `get-started/` — install paths, providers, Docker, multi-user, troubleshooting
- `explore/` — Chat, Partners, Co-Writer, Book, Knowledge, Space, Memory, Settings
- `partners/` — Partner architecture and channel configuration
- `ecosystem/` — Skills, MCP, CLI apps, EduHub, RAG integrations
- `cli/` — CLI, command reference, agent handoff, Python SDK, server API
- `contributing.md` — Contributing guide

## Screenshot Policy

Prefer screenshots synced from canonical assets or freshly captured from a running local DeepTutor UI using synthetic demo data (never personal history, credentials, or private paths). Keep docs references under `/screenshots/...` and verify the files exist before building.

## Checks

Before opening a PR, run from `docs/`:

```bash
npm run build
```

And check EN / ZH locale parity from the repository root:

```bash
python3 - <<'PY'
from pathlib import Path
root = Path('docs/src/content/docs')
en = {
    p.relative_to(root).as_posix()
    for p in root.rglob('*.md')
    if not p.relative_to(root).as_posix().startswith('zh-cn/')
}
zh = {p.relative_to(root / 'zh-cn').as_posix() for p in (root / 'zh-cn').rglob('*.md')}
print('only_en', sorted(en - zh))
print('only_zh', sorted(zh - en))
PY
```

Both lists should be empty; otherwise language switching can fall back to the wrong locale.
