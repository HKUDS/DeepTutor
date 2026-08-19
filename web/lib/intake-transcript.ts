export type IntakeSeat = "visitor" | "trainee" | "supervisor";

export type IntakeMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  stage?: string;
  source?: string;
  localSeat?: IntakeSeat;
};

export {
  looksLikeCrisisRedirect,
  parseRoomIdFromContent,
} from "@/lib/whisper-transcript";

export function filterMessagesForSeat(
  messages: IntakeMessage[],
  seat: IntakeSeat,
): IntakeMessage[] {
  if (seat !== "visitor") return messages;
  return messages.filter((msg) => {
    if (msg.stage === "supervisor") return false;
    if (msg.source === "intake_trainee" && msg.stage === "debrief") return false;
    return true;
  });
}

/** Trainee-facing crisis summary from intake_trainee._CRISIS_SUMMARY. */
export function looksLikeIntakeTraineeCrisisSummary(text: string): boolean {
  const t = (text || "").toLowerCase();
  return (
    t.includes("intake session was closed for crisis referral") ||
    t.includes("no further supervisor coaching")
  );
}

export function looksLikeIntakeRoomEnded(text: string): boolean {
  const t = (text || "").toLowerCase();
  return (
    t.includes("intake session has ended") ||
    t.includes("room has ended")
  );
}
