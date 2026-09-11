# UI Screenshot Refresh: v1.6.4/v1.6.5

This inventory tracks the product screenshots used by the root README and the
11 translated READMEs. It separates the one current v1.6.5 capture from the
historical v1.4.6 references that still document useful workflows but no longer
show the current navigation and controls.

## Status

| Status | Meaning |
| --- | --- |
| Current | The capture represents v1.6.5. |
| Historical | The capture remains useful as a workflow reference but shows the v1.4.6 layout. |
| Missing | There is no versioned capture for the v1.6.4/v1.6.5 surface. |

The current overview is `assets/figs/web-1.6.5/OVERVIEW.png`. It was introduced
in [#1263](https://github.com/HKUDS/DeepTutor/pull/1263).

## Existing Screenshot Inventory

| Surface | Existing asset | Status | v1.6.5 replacement needed |
| --- | --- | --- | --- |
| Home and main navigation | `assets/figs/web-1.6.5/OVERVIEW.png` | Current | Capture content, capabilities, and navigation states if they cannot be shown in one overview. |
| Chat workspace | `assets/figs/web-1.4.6+/home/00-overview.png` | Historical | Capture the v1.6.5 chat workspace and unified Activity/turn trace. |
| Partners overview | `assets/figs/web-1.4.6+/partners/00-partners overview.png` | Historical | Capture the current partners list and status controls. |
| Partner IM configuration | `assets/figs/web-1.4.6+/partners/02-IM config for each partner.png` | Historical | Capture the current channel-configuration page. |
| My Agents overview | `assets/figs/web-1.4.6+/myagents/00-overview.png` | Historical | Capture connected and imported agent states. |
| Claude Code subagent consultation | `assets/figs/web-1.4.6+/home/08-subagent demo with claude code.png` | Historical | Capture the current Activity/turn trace while a subagent runs. |
| Co-Writer overview | `assets/figs/web-1.4.6+/co-writer/00-overview.png` | Historical | Capture the current split view. |
| Co-Writer selection edit | `assets/figs/web-1.4.6+/co-writer/01-edit panel.png` | Historical | Capture the current edit-panel state. |
| Book library | `assets/figs/web-1.4.6+/book/00-book_overview.png` | Historical | Capture the current library and source selection. |
| Book quiz block | `assets/figs/web-1.4.6+/book/01-book-demo-quiz card.png` | Historical | Capture the current quiz block. |
| Book Manim block | `assets/figs/web-1.4.6+/book/02-book-demo-manim video.png` | Historical | Capture the current animation block. |
| Book interactive block | `assets/figs/web-1.4.6+/book/03-book-demo interactive module.png` | Historical | Capture the current interactive block. |
| Knowledge Center overview | `assets/figs/web-1.4.6+/knowledge/00-overview.png` | Historical | Capture the current KB list and engine states. |
| Knowledge base creation | `assets/figs/web-1.4.6+/knowledge/01-create knowledge base.png` | Historical | Capture the current creation and linking flow. |
| Learning Space overview | `assets/figs/web-1.4.6+/learning-space/00-overview.png` | Historical | Capture the current personalization and materials groups. |
| EduHub skill import | `assets/figs/web-1.4.6+/learning-space/07- download skills from eduhub.png` | Historical | Capture the current import and security gate. |
| Memory overview | `assets/figs/web-1.4.6+/memory/00-overview.png` | Historical | Capture the current memory layers. |
| Memory graph | `assets/figs/web-1.4.6+/memory/01-3 layer memory graph.png` | Historical | Capture the current evidence graph. |
| Settings overview | `assets/figs/web-1.4.6+/settings/00-setting overview.png` | Historical | Capture the live status strip and Readiness matrix. |
| Appearance settings | `assets/figs/web-1.4.6+/settings/01-appearance settings.png` | Historical | Capture the current appearance section if its layout changed. |

The encoded forms of spaces in the Markdown image URLs are intentional. The
table uses decoded names for readability.

## Missing v1.6.4/v1.6.5 Surfaces

Add versioned captures before documenting these surfaces with old screenshots:

- `Settings -> Workspace`;
- the Settings Readiness matrix;
- Content Workspace outputs and `workspace_present` file presentation;
- unified Activity and turn traces;
- Mastery Path question, handoff, learning board, mode switch, and coverage UI;
- Book generation activity controls;
- per-model API format, capability controls, and model-list pickers;
- Reading and Watching surfaces changed by v1.6.4.

Store captures under `assets/figs/web-1.6.5/<surface>/`. Prefer 1440x900 PNG
captures, the default theme, and stable numbered file names. Use dark mode only
when the layout differs materially.

## Capture Hygiene

Run against a clean temporary runtime home and a fresh content workspace.
Before committing an image, review it for:

- API keys, bearer tokens, account identifiers, or OAuth data;
- personal file names, emails, chat content, URLs, and upload names;
- private hostnames, ports, IP addresses, project paths, and organization data;
- temporary credentials or provider account balances;
- browser notifications, bookmarks, extensions, and system UI outside DeepTutor.

## Verification

1. Confirm every referenced image resolves from the README that references it.
2. Confirm the asset dimensions and capture theme before replacing a reference.
3. After a surface is refreshed, update its row in this inventory and replace
   the equivalent reference in the root README and all translated READMEs.
4. When the refresh is complete, remove the v1.4.6 references from the current
   product tour; do not present them as the current UI.
