// Vendored from Jakubantalik/Libraries, packages/thinking-orbs
// (MIT, source commit 3862ffa345217443b63696a8c331a0664eea4b04). See THIRD_PARTY_NOTICES.md at the repo root.
//
// Local changes, each marked "DeepTutor local addition/change" at its site:
//  - `engine/core.ts`  — an optional `Tint` threaded through the painters, so
//    the dots take the host row's `currentColor` instead of upstream's flat
//    greyscale. The depth ramp is preserved: `white` now fades the tint
//    toward the substrate rather than toward grey — capped part-way, so an
//    inline-size orb keeps its hue instead of washing out.
//  - `theme.ts`        — `useResolvedInk` / `parseTint`, which read that
//    colour off computed style and re-read it on app theme flips.
//  - `types.ts`, `ThinkingOrb.tsx` — a `superSample` prop, because the
//    upstream `min(2, dpr)` bitmap cap leaves inline-size dots blurred by
//    their own antialiasing.
//
// Upstream is a single-maintainer package a few versions old; vendoring
// trades its upgrade path for the ability to make the two changes above and
// removes the dependency risk. Re-syncing means re-applying those three
// hunks by hand.

export { ThinkingOrb } from './ThinkingOrb';

export type { ThinkingOrbProps, OrbState, OrbSize, OrbTheme } from './types';

// Power-user surface: the resolved presets + raw frame painters, for
// consumers driving their own canvas outside React.
export { resolvePreset, STATE_TO_MODE, type ModeKey, type Resolved } from './presets';
export { MODE_DRAWS } from './engine/registry';
