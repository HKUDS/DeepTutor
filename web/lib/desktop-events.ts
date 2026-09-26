/**
 * Event names and payload shapes the desktop shell and the web app agree on.
 *
 * Deliberately separate from `desktop-shell.ts`: the chat route only needs these
 * strings to listen for a file hand-off, and importing the whole IPC bridge to
 * get them drags the bridge into a route bundle that has no use for it (the
 * bridge is a no-op in a browser, but it still costs bytes on first paint).
 * `desktop-shell.ts` re-exports everything here, so its public surface is
 * unchanged.
 */

/** Events the shell broadcasts; the `deeptutor://` prefix is the shell's. */
export const SHELL_EVENTS = {
  openRequest: "deeptutor://open-request",
  notificationTarget: "deeptutor://notification-target",
  shellSettings: "deeptutor://shell-settings",
  updateReport: "deeptutor://update-report",
  downloadStarted: "deeptutor://download-started",
  downloadFinished: "deeptutor://download-finished",
} as const;

/**
 * DOM event the bridge re-broadcasts when a hand-off produced files.
 *
 * The chat composer already knows how to take `File` objects (that is what a
 * drag-and-drop or a paste gives it), so the shell's path-based hand-off is
 * converted into the same currency instead of growing a second upload path.
 */
export const DESKTOP_ATTACH_EVENT = "deeptutor:desktop-attach-files";

export interface DesktopAttachDetail {
  files: File[];
  source: string;
  /**
   * Set by whichever composer takes the batch, so the bridge knows the files
   * landed instead of leaving them queued forever.
   */
  acknowledged?: boolean;
}
