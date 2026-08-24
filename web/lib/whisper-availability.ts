import type { WhisperSeat } from "./whisper-transcript";

export const WHISPER_CAPABILITY_BY_SEAT: Record<WhisperSeat, string> = {
  visitor: "whisper_visitor",
  trainee: "whisper_trainee",
};

export const REQUIRED_WHISPER_CAPABILITIES = Object.values(
  WHISPER_CAPABILITY_BY_SEAT,
);

export type WhisperPluginStatus =
  | "checking"
  | "available"
  | "missing"
  | "error";

export function hasWhisperCapabilities(payload: unknown): boolean {
  if (
    typeof payload !== "object" ||
    payload === null ||
    !Array.isArray((payload as { capabilities?: unknown }).capabilities)
  ) {
    return false;
  }

  const names = new Set(
    (payload as { capabilities: unknown[] }).capabilities
      .map((capability) =>
        capability &&
        typeof capability === "object" &&
        "name" in capability &&
        typeof capability.name === "string"
          ? capability.name
          : null,
      )
      .filter((name): name is string => name !== null),
  );

  return REQUIRED_WHISPER_CAPABILITIES.every((name) => names.has(name));
}
