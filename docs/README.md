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
src/content.config.ts        # docs schema, including the quadrant field
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

The public site stays English and Simplified Chinese. Sidebar groups follow product areas (Get started, Learning workspace, Multimodal studio, Customize, Channels, Self-hosting, Developers). Page slugs stay on their current paths until a later directory move; the sidebar already hangs existing pages under those groups.

## Diátaxis quadrant

Every page except the splash homepage (`index.mdx`) sets exactly one `quadrant` in frontmatter:

| Value | Job |
| --- | --- |
| `tutorial` | One shortest path to a first success. No alternate install or feature branches. |
| `how-to` | Steps for one task. Link out for theory and parameter lists. |
| `reference` | Parameters, schemas, and catalogs. Prefer a code source over a second prose copy. |
| `explanation` | How a design fits together. No procedures. |

Do not put the quadrant name in the sidebar label or the folder name. The homepage is the only page without the field.

## Current Docs Map

Sidebar groups and the paths they currently open:

- **Get started** — `get-started/` including Desktop quickstart and Changelog. Docker still opens the existing install page.
- **Learning workspace** — `explore/` study pages (Chat, practice, mastery, knowledge, books, reading, notebook, memory).
- **Multimodal studio** — generation still opens Chat until dedicated guides exist.
- **Customize** — `explore/personalization`, `explore/subagents`, and `ecosystem/`.
- **Channels** — `explore/partners`, `partners/`, with domestic and international IM grouped in the sidebar.
- **Self-hosting** — PyPI, source, CLI-only, multi-user, settings, troubleshooting.
- **Developers** — `cli/` and `contributing.md`.

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

def pages(base: Path):
    found = set()
    for pattern in ('*.md', '*.mdx'):
        for path in base.rglob(pattern):
            rel = path.relative_to(base).as_posix()
            if rel.startswith('zh-cn/'):
                continue
            found.add(rel)
    return found

en = pages(root)
zh = pages(root / 'zh-cn')
print('only_en', sorted(en - zh))
print('only_zh', sorted(zh - en))

missing_quadrant = []
for path in list(root.rglob('*.md')) + list(root.rglob('*.mdx')):
    rel = path.relative_to(root).as_posix()
    if rel in {'index.mdx', 'zh-cn/index.mdx'}:
        continue
    text = path.read_text(encoding='utf-8')
    end = text.find('\n---', 3)
    if 'quadrant:' not in text[:end]:
        missing_quadrant.append(rel)
print('missing_quadrant', missing_quadrant)
PY
```

Both lists should be empty; otherwise language switching can fall back to the wrong locale.
