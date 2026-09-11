/**
 * The activity vocabulary: how DeepTutor shows work in progress.
 *
 * Every surface that reports ongoing work — chat's reasoning trace, a book
 * compile, a co-writer run, deep research, the sidebar's live sessions —
 * composes these four pieces rather than growing its own spinner:
 *
 *   ActivityHeader   an orb + what is happening + how long
 *   ActivityStack    the rows under it, aligned to the orb's column
 *   ActivityDivider  a labelled break between groups of rows
 *   ActivityRow      one action, with its specifics folded away
 *   ActivityDetailGrid  the label/value layout inside level two
 *   ActivityMark     a list row's mark, for lists with no header orb above
 *
 * The contract is two levels. Level one is what a reader sees having clicked
 * nothing: one line per action. Level two is everything else. Nothing opens
 * itself except work the reader is meant to watch happen, which folds itself
 * away once it settles.
 */

export { ActivityHeader } from "./ActivityHeader";
export {
  ActivityDetailGrid,
  argumentRows,
  isPlumbingArg,
  type DetailRow,
} from "./ActivityDetailGrid";
export { ActivityMark, type MarkTone } from "./ActivityMark";
export { ActivityOrb, type OrbState, type OrbTone } from "./ActivityOrb";
export { ActivityRow } from "./ActivityRow";
export { ActivityDivider, ActivityStack } from "./ActivityStack";
export { StatusDot } from "./StatusDot";
export type { ActivityState } from "./types";
