"use client";

import {
  ActivityOrb as SharedActivityOrb,
  type OrbState,
} from "@/components/activity";

import type { StreamingMode } from "./model";

/**
 * Which orb animation stands in for each phase of a chat turn.
 *
 * The orb states are semantic, so the status header can tell the phases
 * apart: the four hand-drawn marks it used to pick from collapsed five of the
 * modes onto a single glyph.
 *
 * Two orbs are shared by two modes each. `reasoning` is mostly a fallback and
 * sits next to `exploring` on the same "casting around" reading, and
 * `quizzing` shares `responding`'s orb; `connecting` and `listening` are
 * currently unspoken for (the latter is being kept for voice).
 */
const MODE_TO_ORB: Record<StreamingMode, OrbState> = {
  reasoning: "working",
  planning: "shaping",
  exploring: "working",
  responding: "solving",
  tool_using: "searching",
  reflecting: "weaving",
  quizzing: "solving",
  responded: "breathing",
};

/**
 * Per-mode overrides on the preset's baked speed.
 *
 * A finished turn keeps breathing rather than freezing, but at half pace: the
 * row is no longer reporting progress, so the motion should read as "still
 * here" and not as "still working".
 */
const MODE_SPEED: Partial<Record<StreamingMode, number>> = {
  responded: 0.5,
};

/** The orb for a chat phase. Sizing, ink and resolution live in the shared
 *  component; this file is only the mapping. */
export default function ChatActivityOrb({ mode }: { mode: StreamingMode }) {
  return (
    <SharedActivityOrb
      state={MODE_TO_ORB[mode]}
      speed={MODE_SPEED[mode] ?? 1}
    />
  );
}

export { MODE_TO_ORB, MODE_SPEED };
