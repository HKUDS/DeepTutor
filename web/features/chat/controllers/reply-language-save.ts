/** Keep a composer draft if its session language could not be saved. */
export async function waitForReplyLanguageSave(
  pending: Promise<void> | null,
  content: string,
  restoreDraft: (content: string) => void,
): Promise<boolean> {
  if (!pending) return true;
  try {
    await pending;
    return true;
  } catch {
    restoreDraft(content);
    return false;
  }
}
