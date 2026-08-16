---
name: "TraeWork Design System"
---

# TraeWork Design System

## Library Layout

```
TraeWork/
├── colors_and_type.css        # Authoritative Light token source + compatibility aliases
├── css.json                   # Machine-readable token projection
├── components.css             # Stable atoms + component definitions from preview marker blocks
├── library-consumption.json   # Downstream consumption contract
├── uikit-plan.json            # Component whitelist + UIKit screen blueprint
├── assets/icons/              # Canonical bundled SVG icons
├── components/                # Component contracts with token, DOM, asset, and provenance metadata
├── preview/                   # Component preview pages
└── ui_kits/                   # Page-level Light-mode showcases
```

## Source Boundary

This skill operates on the files shipped in this TraeWork package. Do not assume access to original Figma, product, or upstream design-source evidence unless the user explicitly provides it. Current component contracts use `sourceKind: "preview-contract"` and medium confidence, so treat preview pages, `components.css`, and component JSON as the executable contract, not as proof of original design intent.

## Required Consumption Order

1. Read `README.md` first for package scope, known limitations, and authoring rules.
2. Read `library-consumption.json` to choose the correct layer for the task.
3. Read `uikit-plan.json` for the current component whitelist and UIKit blueprint.
4. Read `colors_and_type.css` and `css.json` for tokens.
5. Read `components/index.json` and `components/{slug}.json` for component relationships.
6. Read `components.css` and the closest `preview/component-*.html` for reusable markup.
7. Use `ui_kits/*/index.html` only as page-level showcase evidence, not as a production page template.

## Design Principles

- Light mode only: do not add Dark-mode token blocks, theme toggles, or `prefers-color-scheme` behavior unless the project explicitly reopens Dark-mode migration.
- Token-first: every color, radius, spacing, and typography choice must resolve to the existing TraeWork tokens or component classes.
- Quiet by default: neutral surfaces, restrained borders, and typography carry the hierarchy. Use brand color only when an action or status truly needs it.
- Type-first, decoration-last: solve hierarchy with copy, layout, font size, weight, and spacing before adding icons or illustrations.
- Keep the product baseline at `body-base` (`14px / 20px`). Smaller text is reserved for existing micro or dense primitives only.
- Use one locale per screen. If the prompt does not explicitly request Chinese, default to English copy.

## Brand Essentials

- Theme scope: Light mode only for this migration.
- Brand accent: `--bg-brand`.
- Page surface: `--bg-base-default`.
- Card / panel surface: `--bg-base-secondary`.
- Body baseline: `--body-base-font-size`, `--body-base-line-height`.
- Default container radius: `--radius-8`; default card/dialog radius: `--radius-12`.
- Metric display numbers use `--font-family-metric`; compact numeric values use `--code-editor-font-family`.

## Token And Color Discipline

- Do not hardcode new palettes, raw status hues, or ad hoc alpha overlays. Use the semantic tokens in `colors_and_type.css`.
- Brand color is scarce: use it for the primary brand action, brand identity moments, and small meaningful status accents. Do not use brand color for generic hover rows, inactive borders, tab underlines, or decorative fills.
- Interactive neutral states should move through the overlay ladder: default surface, `--bg-overlay-l1`, `--bg-overlay-l2`, then `--bg-overlay-l3` for pressed or selected states.
- Status colors are semantic. Use `--status-*-default` and matching `--status-*-surface-*` only for actual info, success, warning, alert, or error meaning.
- When a token already encodes alpha, do not add extra `opacity` on top of it.

## Compatibility Contract

Standard variables remain available and must not be removed without a breaking-change note:

- `--radius-2 / 4 / 6 / 8 / 10 / 12 / 16 / 20 / 24 / 32`
- `--radius-xs / sm / md / lg / xl`
- `--color-*`
- `--bg-layout-1`, `--bg-layout-2`, `--border-1`
- `--brand-green-*`
- `--brand-1..4`

The alias values intentionally resolve to the new Light-mode visual system.

## Layout And Surface Discipline

- Default page background is `--bg-base-default`; cards and panels use `--bg-base-secondary`; fields and inline controls use `--bg-overlay-l1`; floating menus use `--bg-menu`.
- Step surface depth one level at a time. Do not place `--bg-base-default` panels inside `--bg-base-secondary` containers, because it visually cuts through the surface.
- Page padding defaults to `--spacer-32` on desktop and `--spacer-16` on mobile.
- Inter-container gaps must breathe: use at least `--spacer-16` between related cards, `--spacer-24` between different card groups, `--spacer-32` between page sections, and `--spacer-48` between major regions.
- Do not use `--spacer-4`, `--spacer-6`, or `--spacer-8` as the gap between containers. Those are for icon-label pairs, inline controls, and tight row internals.
- Avoid nested bordered or filled containers. Do not put `.ds-card` inside `.ds-card`; use a single surface with internal dividers and spacing.

## Typography And Data

- Use typography tokens as complete sets: family, size, line-height, weight, and letter-spacing should come from the same text style.
- Body copy, controls, list rows, table cells, form labels, helper text, tags, and chips default to `body-base` unless an existing component defines a denser style.
- Compact numeric values, counts, IDs, table numbers, chart axes, code, and keyboard hints use `--code-editor-font-family` with tabular figures.
- Large KPI, scorecard, analytics, revenue, usage, and conversion display numbers use `--font-family-metric`, not mono.
- Hero and marketing display text is typeset content, not data; do not apply mono or numeric utility styles to it.

## Components

Use these classes as the stable component API:

| Group | Classes |
|---|---|
| Action | `.ds-btn`, `.ds-btn-group` |
| Form | `.ds-input`, `.ds-textarea`, `.ds-select`, `.ds-check`, `.ds-radio`, `.ds-switch`, `.ds-slider` |
| Display | `.ds-card`, `.ds-tag`, `.ds-avatar`, `.ds-table`, `.ds-progress`, `.ds-code`, `.ds-kbd` |
| Navigation | `.ds-tabs`, `.ds-breadcrumb`, `.ds-pagination`, `.ds-menu` |
| Overlay | `.ds-dialog`, `.ds-popover` |
| Feedback | `.ds-notif`, `.ds-alert`, `.ds-skeleton` |

The component inventory is TraeWork-specific. Do not add or infer components solely to match another design-system package; extend only when the TraeWork source evidence requires it.

## Iconography

Icon dimensions refer to rendered width and height, regardless of the SVG `viewBox`.

- Use local TraeWork SVG assets from `assets/icons/`; do not add external icon libraries, icon fonts, emoji icons, CDN icon packs, or runtime-generated icon packages.
- Functional monochrome icons should use local SVG assets from `assets/icons/` with reserved dimensions and decorative `aria-hidden="true"` when paired with visible text. Inside token-colored controls such as `.ds-btn`, prefer `currentColor` CSS masks with verified local URLs so icons inherit the button variant color in direct `file://` previews. Resolve `--icon-url` paths against the CSS rule that consumes them: `components.css` for shared component rules, or the page file for page-local rules. Use `<img>` for multi-color brand artwork.
- Preserve SVG geometry, viewBox, fill/stroke model, and visual proportions. Do not rewrite paths, normalize strokes, or hand-draw replacement glyphs.
- Default icons must render at `16px` by `16px`.
- Compact icons may render at `14px` by `14px` in dense controls, menus, input adornments, tags, and other tight UI rows.
- Large supporting icons may render at `24px` by `24px` on copy-led pages or cards where the icon is used as a stronger visual anchor.
- Do not introduce other icon sizes unless the component explicitly requires an exception and the exception is documented with the component.
- Every icon placeholder must reserve its final width and height before the asset loads to avoid layout shift.
- Do not mix icon sources or visual styles in a single view.
- If a matching icon asset is missing, choose text, choose a semantically close local SVG, or remove the icon. Do not substitute an external glyph.

## Component Usage Rules

- Compose new UI from `.ds-*` primitives before adding page-local styles.
- Use at most one brand CTA per view. If two actions have equal weight, demote both to neutral variants.
- Form focus uses contrast and neutral overlays, not brand glow or decorative rings.
- Cards use surface tint and borders for elevation. Avoid drop shadows unless an existing component already defines them.
- Selected rows, menu items, tabs, and pagination states use neutral overlays. Do not use brand fill for generic selection.
- Notifications and alerts keep body text neutral; status is conveyed through the icon and status surface/border tokens.
- Tables should use row dividers and inline status tags. Do not tint whole rows for status.

## Visual Composition

- Prefer refined component composition over decorative illustration. Big visual cards should be assembled from `.ds-card`, `.ds-tag`, `.ds-avatar`, `.ds-progress`, `.ds-code`, `.ds-table`, text styles, and 1px rule lines.
- Avoid decorative SVG backgrounds, gradient blobs, icon clusters used as decoration, mascots, glow effects, fake charts, and arbitrary abstract shapes.
- If illustration is necessary, keep it flat, token-based, and restrained: use `currentColor` plus at most one brand accent.
- Charts must use chart and semantic tokens for series, axes, labels, legends, tooltips, and backgrounds. Do not introduce random chart palettes.

## Motion And Interaction

- Keep motion short and functional: 120ms for hover or focus, 200ms for component state changes, and 300ms maximum for layout reveal.
- Prefer opacity and small translation. Translation should stay within 4px; avoid scale above 1.05.
- State changes must not shift layout geometry. Hover, active, selected, and disabled states should preserve component size.
- Respect `prefers-reduced-motion` by removing nonessential transitions and translation.

## Accessibility

- Maintain readable contrast: 4.5:1 for body text and at least 3:1 for icons and large text.
- Focus must remain visible. Do not remove focus rings without an equivalent.
- Interactive elements must be keyboard reachable in visual order.
- Icon-only buttons must provide an `aria-label`.
- Decorative icons and illustrations should use `aria-hidden="true"`; meaningful SVGs need accessible text.

## Authoring Rules

1. Do not change file names or directory names.
2. Do not hardcode a new palette. Use semantic tokens from `colors_and_type.css`.
3. Keep old token aliases intact for downstream compatibility.
4. Keep component CSS inside the matching `preview/component-*.html` marker block, then mirror those changes in `components.css`.
5. Keep preview-only layout, demo, and showcase helper styles outside component marker blocks so they do not enter `components.css`.
6. Do not add root-level preview-shell CSS files. Preview-only helpers belong inline in `preview/component-*.html`; stable `.ds-*` atoms belong in `components.css`.
7. Update these maintenance notes when changing stable `.ds-*` component APIs; call out any breaking change explicitly.
8. Use local TraeWork SVG assets from `assets/icons/`, and follow the Iconography rules above; do not add external icon libraries.
9. Preserve Light-mode behavior unless the project explicitly reopens Dark-mode migration.
10. Keep `components/{slug}.json`, `components/index.json`, `library-consumption.json`, `uikit-plan.json`, and `ui_kits/*/quality-report.json` synchronized when component APIs or UIKit usage changes.
11. Before shipping, compare against the closest preview or UI kit and verify surface depth, icon size, typography scale, brand color usage, and accessibility labels.
