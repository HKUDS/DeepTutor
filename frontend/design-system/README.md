---
name: "TraeWork"
---

# TraeWork

TraeWork is a Light-mode design library for building consistent product surfaces. Visual behavior resolves through the new Light tokens while legacy token names remain as compatibility aliases.

## Open the Showcases

All pages are static HTML and link the shared files in this directory.

| Showcase | Path |
|---|---|
| Component previews | `preview/component-*.html` |
| UI Kit - Dashboard | `ui_kits/dashboard/index.html` |
| UI Kit - Dashboard 2 | `ui_kits/dashboard-2/index.html` |
| UI Kit - Pricing doc | `ui_kits/pricing-doc/index.html` |
| UI Kit - Skills library | `ui_kits/skills-library/index.html` |
| UI Kit - Product overview | `ui_kits/product-overview/index.html` |
| UI Kit - Comment threads plan | `ui_kits/comment-threads-plan/index.html` |
| UI Kit - HTML effectiveness doc | `ui_kits/html-effectiveness-doc/index.html` |
| UI Kit - Landing | `ui_kits/landing/index.html` |
| UI Kit - Dev Explorer | `ui_kits/dev-explorer/index.html` |
| UI Kit - Settings | `ui_kits/settings/index.html` |

## Consumption Contract

| Layer | Files | Use |
|---|---|---|
| Tokens | `colors_and_type.css`, `css.json` | Light-mode design language and compatibility aliases |
| Components | `components.css`, `components/index.json`, `components/{slug}.json`, `preview/component-*.html` | Stable atoms, component markup, classes, consumed tokens, DOM anatomy, assets, and provenance |
| UI Kits | `ui_kits/{type}/index.html`, `ui_kits/{type}/quality-report.json`, `uikit-plan.json` | Page-level showcase evidence and component usage map |
| Icons | `assets/icons/*.svg` | Canonical bundled TraeWork icons |

Start with `library-consumption.json` when consuming this package from another project. `ui_kits/*` pages are showcases, not production page templates; copy reusable component markup from `preview/` and write the downstream page shell for the target canvas.

## Machine-readable Data Shape

- `library-consumption.json` is the routing contract for downstream consumers. Use it to choose whether the task needs tokens, components, icons, or UI kit evidence.
- `css.json` is not a flat `--token: value` map. It is grouped under top-level keys such as `color`, `font`, `radius`, `spacing`, `size`, and `shadow`; some groups are nested, while radius, spacing, and size are flat maps.
- `components/{slug}.json` files are component contracts. The most useful fields are `tokensConsumed`, `domAnatomy`, `assetsConsumed`, `coverageMatrix`, and `provenance`.
- `ui_kits/*/quality-report.json` records showcase usage evidence. Read `previewClassReuseRate` and `componentUsageBasis` before treating a UI kit page as strong component reuse evidence.

## Token Highlights

| Group | Examples |
|---|---|
| Surface | `--bg-base-default`, `--bg-base-secondary`, `--bg-overlay-l1..l4` |
| Brand | `--bg-brand`, `--bg-brand-hover`, `--bg-brand-popup` |
| Text / Icon | `--text-default`, `--text-secondary`, `--icon-tertiary`, `--icon-size-12..24` |
| Border | `--border-neutral-l1..l3`, `--border-contrast`, `--border-brand` |
| Type | `--body-base-*`, `--body-lg-*`, `--heading-*`, `--code-editor-*`, `--font-family-metric` |
| Radii | `--radius-0`, `--radius-2..32`, `--radius-full`, plus semantic aliases |
| Spacing | `--spacer-0`, `--spacer-2..64` |

## Known Limitations

- Component contracts are medium-confidence implementation contracts for the current package. Validate against rendered previews before treating them as final design intent.
- UI kit pages are visual showcases. Low `previewClassReuseRate` or `componentUsageBasis: "semantic-fallback"` means the page is weak component reuse evidence even when it is visually useful.
- Legacy preview-shell CSS has been removed from the consumption contract. Preview-only layout helpers are inline in `preview/component-*.html`; stable atoms live in `components.css`.
- Component sections in `components.css` mirror preview marker blocks. The extraction script is not shipped in this package, so do not claim a fresh regeneration unless the extraction path is available and verified.

## Authoring Rules

1. Use the tokens in `colors_and_type.css`; do not add raw colors or new ad hoc scales.
2. Prefer `.ds-*` primitives from `components.css` before adding page-local UI styles.
3. Keep Light mode as the shipped mode for this library. Do not add dark overrides unless the migration scope changes.
4. Keep existing file names and directories stable for downstream consumers.
5. Use bundled TraeWork SVG assets only from `assets/icons/`.
6. Use `currentColor` CSS masks for monochrome icons inside token-colored buttons, so icon color follows the button variant token. Keep `<img>` for multi-color brand artwork. When a mask rule comes from `components.css`, write `--icon-url` paths relative to `components.css`; when the rule is page-local, write paths relative to that page.
7. Keep component previews and core CSS directly openable with `file://`; do not add root-level preview helper CSS or new remote critical assets.
