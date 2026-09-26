"use client";

import { ActivityOrb } from "@/components/activity";

/**
 * Slower than the 1.6 the comparison harness ran at, faster than the trace
 * orbs. A status header's orb sits beside a sentence explaining itself and
 * can afford to be calm; a 12px mark in a list of twenty rows has only its
 * motion to say "this one is running" — but at 1.6 it read as agitated.
 */
const LIVE_SPEED = 1.3;

/**
 * The ring's diameter as a fraction of the mark's box.
 *
 * 0.58, down from 0.7: at 12px the larger ring crowded the row and its 1px
 * CSS border was a quarter of the whole diameter, which is what read as
 * coarse.
 */
const RING_RATIO = 0.58;

/**
 * The settled mark: one circle, hollow grey / solid blue / solid amber.
 *
 * All three resting forms share a single element on purpose. They occupy the
 * same place at the same diameter, so moving between them is a fill and a
 * colour animating — not one shape being swapped for another the same size,
 * which reads as a flicker.
 *
 * Drawn as SVG rather than a CSS-bordered box: a 1px CSS border is 2 device
 * pixels on a retina screen and cannot go thinner, which on a 7px circle is
 * a heavy outline. An SVG stroke scales with the viewBox, so the ring can
 * carry a genuinely hairline edge.
 *
 * Deliberately not an orb frozen in place, either. A stopped session is not
 * "working slowly", it is *not working* — a static mark says that outright,
 * and costs no rAF in a sidebar that can hold twenty of them.
 */
function SettledMark({
  size,
  mark,
  kind,
}: {
  size: number;
  mark: SessionMark;
  kind: SessionKind;
}) {
  const filled = mark === "unread" || mark === "failed";
  const shape = `transition-[fill] duration-300 ease-out ${
    filled ? "fill-current" : "fill-transparent"
  }`;
  // Ink rides on `currentColor` and alpha on `opacity-*` rather than a colour
  // modifier. `stroke-muted-foreground/45` does work now that the theme colours
  // go through `color-mix` (see tailwind.config.js), but it would need one class
  // per resting state; here a single opacity carries all three, and the hover
  // lift animates that one property instead of a colour.
  return (
    <svg
      viewBox="0 0 12 12"
      width={size}
      height={size}
      className={`transition-[color,opacity] duration-300 ease-out ${
        mark === "failed"
          ? "text-amber-500 opacity-100 dark:text-amber-400"
          : mark === "unread"
            ? "text-blue-600 opacity-100 dark:text-blue-400"
            : "text-[var(--muted-foreground)] opacity-45 group-hover/session:opacity-75"
      }`}
    >
      {kind === "reading" ? (
        // A page: the ring stood on end with its corners let out. Same box,
        // stroke and ink, so it reads as the same mark in another key.
        <rect
          x="1.9"
          y="0.9"
          width="8.2"
          height="10.2"
          rx="2.4"
          stroke="currentColor"
          strokeWidth="1.25"
          className={shape}
        />
      ) : (
        <circle
          cx="6"
          cy="6"
          r="5.1"
          stroke="currentColor"
          strokeWidth="1.25"
          className={shape}
        />
      )}
    </svg>
  );
}

/**
 * What a session's mark has to say.
 *
 * - `running` — working right now
 * - `unread`  — finished while the reader was looking at something else
 * - `failed`  — its last turn ended badly
 * - `idle`    — finished and seen, or never started
 */
export type SessionMark = "running" | "unread" | "failed" | "idle";

/**
 * Which mark a session should carry.
 *
 * Shared so the two lists that render sessions cannot drift on the priority
 * order, which matters: a failed session that also finished unseen has to
 * read as failed, since that is the one a reader has to act on.
 *
 * `running` is taken from the live set rather than the stored status. The
 * runtime map behind that set holds running sessions only, whereas a stored
 * `status` can still say `running` for a turn that died long ago.
 */
export function deriveSessionMark(
  session: { session_id: string; status?: string },
  liveSessionIds: ReadonlySet<string> | undefined,
  unread: ReadonlySet<string>,
): SessionMark {
  if (liveSessionIds?.has(session.session_id)) return "running";
  if (!liveSessionIds && session.status === "running") return "running";
  if (session.status === "failed" || session.status === "rejected") {
    return "failed";
  }
  // A turn the reader stopped themselves is not news to them, so it never
  // reads as unread — and it is not a fault either, so no amber. Note this
  // only covers deliberate stops now: `handleNewChat` used to cancel the
  // previous conversation's turn behind the reader's back, which surfaced
  // here as a blue "unread" mark on an answer that had actually been killed.
  if (session.status === "cancelled") return "idle";
  if (unread.has(session.session_id)) return "unread";
  return "idle";
}

/**
 * Which surface a session belongs to, as far as the resting mark cares.
 *
 * Reading conversations sit in the same sidebar list as every other chat but
 * open beside their material, so they rest as a page rather than a ring. Only
 * the idle shape differs: running, unread and failed still say the same thing
 * in the same colour, because state is what the column is for.
 */
export type SessionKind = "chat" | "reading";

export function sessionKindOf(session: {
  preferences?: { workspace_mode?: unknown } | null;
}): SessionKind {
  return session.preferences?.workspace_mode === "immersive_reading"
    ? "reading"
    : "chat";
}

interface SessionAvatarProps {
  sessionId: string;
  mark?: SessionMark;
  kind?: SessionKind;
  size?: number;
  className?: string;
}

/**
 * A session's mark in a list: a live thought-orb while it runs, a hollow ring
 * once it stops.
 *
 * The two forms share one contracting motion — the orb shrinks as it fades
 * while the ring settles in from slightly larger — so a session finishing
 * reads as its orb condensing into the ring rather than as one mark being
 * swapped for another. Both are always mounted and cross-faded, because a
 * conditional cannot be animated and the transition is the point.
 *
 * Note this drops the per-session icon-and-colour identity the previous
 * version carried (a hash of the session id picked one of seventeen lucide
 * icons). That was deliberate: the identity now comes from the title text,
 * and the mark column says only what state the session is in.
 */
export function SessionAvatar({
  sessionId: _sessionId,
  mark = "idle",
  kind = "chat",
  size = 12,
  className = "",
}: SessionAvatarProps) {
  const ring = Math.round(size * RING_RATIO);
  const running = mark === "running";

  return (
    <span
      className={`relative inline-flex shrink-0 items-center justify-center ${className}`}
      style={{ width: size, height: size }}
      aria-hidden
    >
      <span
        className={`absolute inset-0 flex items-center justify-center transition-[opacity,transform] duration-300 ease-out ${
          running ? "scale-100 opacity-100" : "scale-[0.45] opacity-0"
        }`}
      >
        <ActivityOrb
          state="composing"
          speed={LIVE_SPEED}
          box={size}
          tone="live"
        />
      </span>
      <span
        className={`absolute inset-0 flex items-center justify-center transition-[opacity,transform] duration-300 ease-out ${
          running ? "scale-[1.55] opacity-0" : "scale-100 opacity-100"
        }`}
      >
        <SettledMark size={ring} mark={mark} kind={kind} />
      </span>
    </span>
  );
}
