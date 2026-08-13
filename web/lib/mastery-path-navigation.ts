/** Build a fresh chat URL associated with existing persistent mastery state. */
export function newMasteryPathChatUrl(masteryPathId: string): string {
  const params = new URLSearchParams({
    capability: "mastery_path",
    mastery_path_id: masteryPathId,
  });
  return `/home?${params.toString()}`;
}
