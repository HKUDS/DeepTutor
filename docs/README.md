# DeepTutor Documentation

Public documentation for DeepTutor, published at [https://docs.deeptutor.info](https://docs.deeptutor.info). The site is Astro and Starlight. This file is the authoring guide for `docs/`.

Three sites stay separate:

| Surface | Role |
| --- | --- |
| `docs/` | This site. End users, self-hosters, and integrators. |
| [deeptutor.info](https://deeptutor.info/) | Marketing site. Its source is not in this repository. The docs homepage reproduces that landing. |
| `docs-for-dev/` | Internal notes. Unpublished, and not linked from the sidebar. A public page may link to a file on GitHub when the reader needs the internal manual. |

The repository root `README.md` is the GitHub project page. It is not the source of truth for this site.

## Design

Diátaxis decides the job of a page. The sidebar follows the reader's path. A quadrant name never appears in a folder, a slug, or a sidebar label.

Every page except the splash homepage sets exactly one `quadrant` in frontmatter. One page, one job. A first-success lesson and the durable task page are two pages that link to each other. Do not fold the task page's controls, fields, or ratings into the lesson, and do not turn the task page into a lesson.

| Value | Job |
| --- | --- |
| `tutorial` | One path to a first success. After each key step, say what the reader should see. One plain sentence of why, then a link. No alternate branches, parameters, or architecture. |
| `how-to` | Steps for one task. Link out for theory and for parameter lists. |
| `reference` | Parameters, schemas, and catalogs. Prefer a code source over a second prose copy. Place it last in its sidebar group. |
| `explanation` | How a design fits together. No procedures. Use it for an area's front door or a concept page at the end of the group. |

Welcome (`welcome.mdx`) is the front door. Each card names the goal the reader can reach: a title, one sentence, and a link. Install cards open the install tutorials. The six study cards open the Learn lessons, not the how-to pages.

### Sidebar

Add a page under the group that owns the task, with a `zh-CN` label. Inside a group, put the explanation home first, how-tos next, and reference or remaining concept pages last. Keep an existing URL when only the sidebar membership changes.

| Group | What belongs here |
| --- | --- |
| Get started | Welcome, install choices, Desktop, Docker, providers, changelog |
| Learn (`learn/`, label 跟着做) | End-user lessons: one connected study session, study with your materials, solve a photo, practice a topic, research a question, make one figure, follow a path |
| Learning workspace | Workspace how-tos from Workspaces through Calendar. Agent loop and memory stay last. The study-session lesson is listed under Learn; its file can remain `learning-workspace/index.md` |
| Multimodal studio | Which generator to use, then Visualize, Math Animator, and Video Lesson. The Learn figure lesson uses Visualize only and links here |
| Customize | Overview, then personas, skills, MCP, CLI apps, EduHub, agents, RAG |
| Channels | Create a partner, then domestic and international IM. Channel schema last |
| Self-hosting | Runtime home, then install and operations how-tos, then troubleshooting. Desktop editions and configuration files last |
| Developers | Architecture; then CLI, REPL, Python SDK, agent handoff, and contributing; then capabilities, commands, turn protocol, and HTTP API |

The Python SDK is a tutorial for someone embedding DeepTutor. It stays under Developers. Learn is only for a person using the product.

Home, Learning, and Resources follow the active workspace. Partners and Personalization belong to the account. Say that when a page could mix the two.

### Install paths

Desktop (`get-started/desktop/`) is the only default install tutorial. Docker (`get-started/docker/`) is a second tutorial and stops at the first successful run; mark that page `tutorial`. Host folders, reverse proxies, local models, and upgrades stay on `self-hosting/docker/`.

PyPI, source, CLI-only, multi-user, and troubleshooting are self-hosting how-tos. `get-started/` explains the choice and links to them. It does not repeat their steps.

### Tutorial voice

Write tutorials as a person guiding the reader. Use "you", active voice, and short sentences. Match the meaning across English and Chinese. English follows the Google and Microsoft developer style. Chinese should read as written Chinese, not as a translation.

On the first use of a product term such as provider, profile, capability, skill, or MCP, add a short clause that says what it does. Leave code blocks, commands, environment variables, paths, API fields, UI labels, links, images, heading levels, and MDX components unchanged when editing prose.

Do not use "simply", "just", "easy", "easily", or "obviously", or the Chinese 只需, 很容易, 轻松, and 显然.

### Facts that must stay accurate

Settings in the product are **Settings → Models & services** (设置 → 模型与服务). Configuration lives in `data/user/settings/*.json`. Process environment variables override only a few startup values. `.env.example` documents Podman host ports, not application settings.

Desktop data and logs:

| | macOS | Windows |
| --- | --- | --- |
| Data | `~/Library/Application Support/Open DeepTutor/workspace/data` | `%LOCALAPPDATA%\Open DeepTutor\workspace\data` |
| Logs | `~/Library/Application Support/Open DeepTutor/logs/runtime.log` | `%LOCALAPPDATA%\Open DeepTutor\logs\runtime.log` |

Public download links use the unversioned files on the latest GitHub Release. Packaging and signing stay in `apps/desktop/README.md`. The changelog keeps the five newest user-visible releases. Older notes point at GitHub Releases and `assets/releases/`.

Hand-write a reference page when the prose is the guide. Generate or check it when the page would drift from code:

- `docs/scripts/generate_reference.py` rewrites the capability table and appends the HTTP route index from `deeptutor/modules/manifests/*.json` and `deeptutor/api/router_index.json`. Run it after those sources change, then commit the generated Markdown.
- `channels/schema.md` stays hand-written in both locales. `check_docs.py` requires every config field declared under `deeptutor/partners/channels` to appear in the matching section. Channel how-tos describe the platform steps and link here for fields.

Move content to the successor page before deleting the old one, and add a redirect.

## Homepage

`src/components/HomeLanding.astro` renders the marketing landing for both locales: navigation, hero, product shot, eight places, and four install tabs in this order: PyPI, Docker, source, CLI. Both `index.mdx` files import that component and do not set Starlight `hero` frontmatter. Desktop install stays on the Welcome cards, not on this landing.

The Docs button and the Docs nav item open Welcome (`/welcome/` and `/zh-cn/welcome/`). Eight-place and footer links use the current docs slugs. Community and Collaborate stay on deeptutor.info. `src/styles/landing.css` hides the Starlight header, sidebar, and the splash `<h1 id="_top">`. Hide that heading, not the content panel that contains the landing.

## Languages

English is the source locale at `/`. Simplified Chinese is the mirror at `/zh-cn/`, with the same relative path. Other README languages do not get Starlight locales.

Add both files together:

```text
src/content/docs/learning-workspace/chat.md
src/content/docs/zh-cn/learning-workspace/chat.md
```

Starlight rewrites Markdown links between locales. It does not rewrite `href` values in MDX or Astro components. Chinese `LinkCard`, hero actions, and landing links must start with `/zh-cn/`.

Quote a frontmatter `description` that contains a colon.

## Layout

```text
src/content/docs/            English pages
src/content/docs/zh-cn/      Simplified Chinese pages
src/components/              HomeLanding, header, social icons
src/styles/                  global.css, starlight.css, landing.css
public/screenshots/dev/      Product screenshots and their manifest
astro.config.mjs             Locales, sidebar, redirects
src/content.config.ts        Docs schema, including quadrant
scripts/check_docs.py        Locale, quadrant, screenshot, channel, and link checks
scripts/generate_reference.py
```

When a slug moves, add both `/old/` and `/zh-cn/old/` to `redirects` in `astro.config.mjs`, pointing at the final slug. Prefer that final slug in new links. Do not rewrite a short fragment such as `/partners/` across the tree; it also appears inside paths like `data/partners/`.

Legacy `/explore/`, `/ecosystem/`, `/partners/`, `/tutorbot/`, `/cli/`, and `/contributing/` URLs already redirect. Leave the pre-existing `/docs` redirect conflict alone.

## Screenshots

Use `public/screenshots/dev/` and refer to files as `/screenshots/dev/<name>.png`. Images that also exist in `assets/figs/web-dev/` must keep that manifest's SHA-256. Capture new shots from a local DeepTutor UI with synthetic demo data. Do not include personal history, credentials, or private paths.

## Local development

Use Node.js 22, the version CI installs.

```bash
cd docs
npm ci
npm run dev
```

Build and preview:

```bash
npm run build
npm run preview
```

Set `ASTRO_TELEMETRY_DISABLED=1` if the Astro telemetry directory cannot be created.

## Checks

From the repository root, before opening a PR:

```bash
python3 docs/scripts/check_docs.py
cd docs && ASTRO_TELEMETRY_DISABLED=1 npm run build && cd ..
python3 docs/scripts/check_docs.py dist
```

`check_docs.py` checks that English and Chinese paths match, that every page except the splash homepage has `quadrant`, that copied screenshots match `assets/figs/web-dev/manifest.json`, and that channel schema pages name the source fields. `dist` also checks that internal links in the built HTML resolve. GitHub Actions runs the same steps in `.github/workflows/docs.yml`.

After changing a module manifest or `router_index.json`:

```bash
python3 docs/scripts/generate_reference.py
```
