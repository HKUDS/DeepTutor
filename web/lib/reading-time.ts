/**
 * Effective reading-time accounting, shared by every Reader surface (#1988).
 *
 * The clock runs only while the page is visible, the window has focus, and
 * the learner interacted recently — or read-aloud / media playback is
 * running. Nothing here touches the DOM: the heartbeat hook feeds it DOM
 * signals so the accounting itself stays unit-testable.
 *
 * Idle grace: #1988 describes a 60-second input lookback, but the acceptance
 * pins the credited grace to one heartbeat ("two active minutes plus idle
 * and hidden time record about two minutes, within one heartbeat"), so the
 * clock runs at most `READING_TIME_IDLE_GRACE_MS` past the last interaction.
 * A new interaction restarts it immediately, and read-aloud or playback
 * keeps the clock running without input.
 */

/** How often the client sends a heartbeat beat. */
export const READING_TIME_BEAT_INTERVAL_MS = 30_000;

/** The clock stops this long after the learner's last interaction. */
export const READING_TIME_IDLE_GRACE_MS = 30_000;

/** Accumulation resolution; sub-second active time is not credited. */
export const READING_TIME_TICK_MS = 1_000;

export interface ReadingActivityState {
  visible: boolean;
  focused: boolean;
  /** Read-aloud or media playback keeps the clock running without input. */
  playing: boolean;
  lastInputAt: number | null;
}

export function isReadingActive(
  state: ReadingActivityState,
  now: number,
  idleGraceMs: number = READING_TIME_IDLE_GRACE_MS,
): boolean {
  if (!state.visible || !state.focused) return false;
  if (state.playing) return true;
  return state.lastInputAt !== null && now - state.lastInputAt <= idleGraceMs;
}

/** Counts active seconds between beats; each beat claims and resets the sum. */
export class ReadingTimeAccumulator {
  private pendingSeconds = 0;

  constructor(private readonly state: () => ReadingActivityState) {}

  /** One tick of the wall clock; call once per READING_TIME_TICK_MS. */
  tick(now: number, idleGraceMs?: number): void {
    if (isReadingActive(this.state(), now, idleGraceMs)) this.pendingSeconds += 1;
  }

  /** Claim the seconds accumulated since the previous beat. */
  takeBeat(): number {
    const claimed = this.pendingSeconds;
    this.pendingSeconds = 0;
    return claimed;
  }

  get pending(): number {
    return this.pendingSeconds;
  }
}
