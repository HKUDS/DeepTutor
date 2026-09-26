"use client";

/**
 * Bridge to the DeepTutor desktop shell (Tauri v2).
 *
 * The shell serves this UI from a loopback origin, so the only shell powers the
 * web app may reach are the ones `tauri-plugin-deeptutor` exposes as plugin
 * commands (see `desktop/plugins/tauri-plugin-deeptutor`). Everything here is a
 * thin, typed wrapper over those commands.
 *
 * Every entry point is safe to call in a browser: `isDesktopShell()` returns
 * false, the async helpers reject with a readable error, and nothing touches
 * `window.__TAURI__` at module scope. Web and CLI mode therefore behave exactly
 * as they did before this module existed — desktop features simply stay off.
 */

export interface DesktopShellStatus {
  launch_count: number;
  restarts: number;
  launcher_running: boolean;
  launcher_pid: number | null;
  message: string;
  home: string;
  workdir: string;
  python: string;
  pack: string | null;
  logs_dir: string;
  notifications_posted: number;
  /** Launch timings, once this page has reported its first paint. */
  startup: {
    spawn_ms: number;
    ready_ms: number;
    ui_ms: number;
    ready_to_ui_ms: number;
  } | null;
  /** Main-window geometry; `null` before the window exists. */
  window: {
    width: number;
    height: number;
    x: number;
    y: number;
    maximized: boolean;
    fullscreen: boolean;
    visible: boolean;
  } | null;
  runtime: {
    schema_version: number;
    status: string;
    frontend_url: string | null;
    backend_url: string | null;
    backend_port: number | null;
    frontend_port: number | null;
    token_present: boolean;
  } | null;
}

export interface ShellSettingsSnapshot {
  close_to_tray: boolean;
  notifications: boolean;
  /** `""` means the shell has no opinion and the app keeps its own language. */
  locale: string;
  first_run_completed: boolean;
  pack_catalog: string | null;
  home: string;
  default_home: string;
  restart_required: boolean;
}

export interface ShellSettingsPatch {
  close_to_tray?: boolean;
  notifications?: boolean;
  locale?: string;
  // No `pack_catalog`: the window is loopback-served, so the shell refuses to
  // let it choose where updates come from (see `remote_settings_patch` in
  // `plugins/tauri-plugin-deeptutor`). The snapshot still reports the value.
}

export interface NotificationRequest {
  title: string;
  body: string;
  route: string;
  session_id?: string | null;
  kind?: string | null;
}

export interface NotificationOutcome {
  delivered: boolean;
  permission: string;
  detail: string | null;
}

export interface NotificationTarget {
  route: string;
  session_id: string | null;
  title: string;
  age_ms: number;
}

/**
 * A hand-off the operating system gave the shell: a `deeptutor://` link, a file
 * association, or a file dropped on the Dock icon.
 */
export interface OpenRequestPayload {
  kind: "route" | "file" | string;
  route: string | null;
  path: string | null;
  source: string;
  raw: string;
  age_ms: number;
}

export interface LocalFilePayload {
  path: string;
  name: string;
  size: number;
  mime: string | null;
  base64: string;
}

export interface PickFilter {
  name: string;
  extensions: string[];
}

export interface PickOptions {
  title?: string;
  filters?: PickFilter[];
  multiple?: boolean;
}

export interface UpdateReport {
  runtime: {
    checked: boolean;
    source: string | null;
    updated: boolean;
    /** Why the check/install failed, when it did (the `detail` line is prose). */
    error?: string | null;
    active_pack: string | null;
    previous_pack: string | null;
    app_version: string | null;
    detail: string;
  };
  shell: {
    /** `available` | `up_to_date` | `error`. */
    status: string;
    detail: string;
    /** Version the update channel offers, when there is one. */
    available_version: string | null;
    current_version: string;
  };
}

export interface ShellUpdateInstall {
  installed: boolean;
  version: string | null;
  detail: string;
}

/**
 * Event names, the attach event and its payload shape live in their own module
 * so a route that only listens for a hand-off does not import the IPC bridge.
 * Re-exported here to keep this module the one place callers import from.
 */
export {
  DESKTOP_ATTACH_EVENT,
  SHELL_EVENTS,
  type DesktopAttachDetail,
} from "@/lib/desktop-events";

interface TauriGlobal {
  core?: { invoke?: (command: string, args?: unknown) => Promise<unknown> };
  event?: {
    listen?: (
      event: string,
      handler: (event: { payload: unknown }) => void,
    ) => Promise<() => void>;
  };
}

function tauriGlobal(): TauriGlobal | null {
  if (typeof window === "undefined") return null;
  const global = (window as unknown as { __TAURI__?: TauriGlobal }).__TAURI__;
  return global && global.core && typeof global.core.invoke === "function"
    ? global
    : null;
}

/** Is this page running inside the DeepTutor desktop shell? */
export function isDesktopShell(): boolean {
  return tauriGlobal() !== null;
}

export class DesktopShellUnavailableError extends Error {
  constructor() {
    super("This action is only available in the DeepTutor desktop app.");
    this.name = "DesktopShellUnavailableError";
  }
}

/**
 * Call a shell command. Rejects outside the desktop shell rather than throwing
 * synchronously, so callers can use one `try`/`finally` for both modes.
 */
export async function desktopInvoke<T>(
  command: string,
  args?: Record<string, unknown>,
): Promise<T> {
  const global = tauriGlobal();
  if (!global?.core?.invoke) throw new DesktopShellUnavailableError();
  return (await global.core.invoke(
    `plugin:deeptutor|${command}`,
    args,
  )) as T;
}

/**
 * Subscribe to a shell event. Returns a no-op unsubscribe in the browser, and
 * when the global event API is not part of this build (`withGlobalTauri` only
 * guarantees the core module) — callers that need delivery in that case also
 * poll their own queue, see `DesktopBridge`.
 */
export function onShellEvent<T>(
  event: string,
  handler: (payload: T) => void,
): () => void {
  const listen = tauriGlobal()?.event?.listen;
  if (!listen) return () => {};
  let unlisten: (() => void) | null = null;
  let cancelled = false;
  void listen(event, (message) => handler(message.payload as T)).then((stop) => {
    if (cancelled) stop();
    else unlisten = stop;
  });
  return () => {
    cancelled = true;
    unlisten?.();
  };
}

export function shellStatus(): Promise<DesktopShellStatus> {
  return desktopInvoke<DesktopShellStatus>("desktop_status");
}

export function shellSettings(): Promise<ShellSettingsSnapshot> {
  return desktopInvoke<ShellSettingsSnapshot>("shell_settings");
}

export function updateShellSettings(
  patch: ShellSettingsPatch,
): Promise<ShellSettingsSnapshot> {
  return desktopInvoke<ShellSettingsSnapshot>("update_shell_settings", { patch });
}

export function restartLocalService(): Promise<void> {
  return desktopInvoke<void>("restart_service");
}

export function notifyRoundComplete(
  request: NotificationRequest,
): Promise<NotificationOutcome> {
  return desktopInvoke<NotificationOutcome>("notify_round_complete", { request });
}

export function takeNotificationTarget(): Promise<NotificationTarget | null> {
  return desktopInvoke<NotificationTarget | null>("take_notification_target");
}

export function takeOpenRequest(): Promise<OpenRequestPayload | null> {
  return desktopInvoke<OpenRequestPayload | null>("take_open_request");
}

export function revealInFolder(path: string): Promise<void> {
  return desktopInvoke<void>("reveal_in_folder", { path });
}

export function readLocalFile(path: string): Promise<LocalFilePayload> {
  return desktopInvoke<LocalFilePayload>("read_local_file", { path });
}

export function pickFiles(options?: PickOptions): Promise<string[]> {
  return desktopInvoke<string[]>("pick_files", { options: options ?? {} });
}

export function pickFolder(options?: { title?: string }): Promise<string> {
  return desktopInvoke<string>("pick_folder", { options: options ?? {} });
}

/**
 * Ask about both update planes.
 *
 * Read-only by default. `install` only covers the **runtime pack** plane, and
 * even then the shell asks for a native confirmation before it downloads and
 * executes anything — the caller cannot install by passing a flag alone.
 */
export function checkUpdates(options?: {
  install?: boolean;
}): Promise<UpdateReport> {
  return desktopInvoke<UpdateReport>("check_updates", {
    install: options?.install ?? false,
  });
}

/**
 * Download, verify and install a new shell build.
 *
 * Verified by the shell against the update signing key before anything is
 * installed; the caller restarts the app afterwards (`restartApp`).
 */
export function installShellUpdate(): Promise<ShellUpdateInstall> {
  return desktopInvoke<ShellUpdateInstall>("install_shell_update");
}

export function restartApp(): Promise<void> {
  return desktopInvoke<void>("restart_app");
}

/**
 * Tell the shell the UI has painted, for the startup timing line in
 * `desktop/logs/shell.log`. Called once per page load by `DesktopBridge`.
 */
export function noteUiReady(elapsedMs: number): Promise<void> {
  return desktopInvoke<void>("note_ui_ready", { elapsedMs });
}

export function shellLog(message: string): Promise<void> {
  return desktopInvoke<void>("log_event", { message });
}

/** The shell's log directory, for the "open logs" affordance. */
export async function openShellLogs(
  status?: DesktopShellStatus | null,
): Promise<void> {
  const resolved = status ?? (await shellStatus());
  await revealInFolder(resolved.logs_dir);
}

/**
 * Rebuild a `File` from a shell hand-off.
 *
 * Base64 travels over IPC as text; the shell caps the size (64 MiB) so this
 * never becomes the way a 2 GB video gets into the composer.
 */
export function fileFromLocalFile(payload: LocalFilePayload): File {
  const binary = atob(payload.base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return new File([bytes], payload.name, {
    type: payload.mime ?? "application/octet-stream",
  });
}
