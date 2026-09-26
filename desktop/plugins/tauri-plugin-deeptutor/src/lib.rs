//! Shell-side commands for the DeepTutor desktop UI.
//!
//! The UI is served by the loopback Next.js server, i.e. it runs on a *remote*
//! origin as far as Tauri is concerned. Phase 0 measured the consequence: core
//! and plugin commands are reachable from that origin (given a capability with
//! `remote.urls`), but application commands are not — Tauri answers
//! `desktop_probe not allowed. Plugin not found` because they carry no ACL entry.
//!
//! So every shell capability the UI must call is exposed here, as a plugin
//! command with a permission the app capability can grant. That rule covers
//! Phase 3's native surface too: notifications, deep-link/file handoff, native
//! pickers, "reveal in folder" and the first-run choices all arrive as plugin
//! commands instead of application commands.

use std::path::{Path, PathBuf};
use std::sync::Arc;

use base64::Engine as _;
use serde::{Deserialize, Serialize};
use tauri::plugin::{Builder, TauriPlugin};
use tauri::{Manager, Runtime, State};
use tauri_plugin_dialog::DialogExt as _;

mod updater;

/// The shell's own language, as a code (`zh-CN` / `en`).
///
/// The plugin cannot import the shell crate, so this is the only shared
/// vocabulary: the shell owns the setting, the plugin asks for its code and
/// formats its own messages with it.
pub fn tr(locale: &str, zh: impl Into<String>, en: impl Into<String>) -> String {
    if locale.trim().to_ascii_lowercase().starts_with("en") {
        en.into()
    } else {
        zh.into()
    }
}

pub use updater::check as check_shell_update_async;
pub use updater::install as install_shell_update_async;
pub use updater::verify_download as verify_shell_update_download;
pub use updater::ShellUpdateInstall;

/// Largest file the UI may pull through the IPC bridge.
///
/// A file dropped on the Dock icon arrives as a *path*; the UI needs bytes to
/// reuse its own upload pipeline. Base64 over IPC costs ~1.3x the file size in
/// memory on both sides, so the bridge stops well below what the HTTP upload
/// path accepts and tells the user to pick the file from the app instead.
const MAX_LOCAL_FILE_BYTES: u64 = 64 * 1024 * 1024;

/// What the shell has to provide; implemented by the shell crate itself so this
/// plugin stays free of supervisor internals (and of a dependency cycle).
pub trait DesktopBackend: Send + Sync + 'static {
    /// Snapshot of the shell and launcher state, safe to show in the UI.
    fn status(&self) -> DesktopStatus;
    /// Restart the local backend + frontend without quitting the shell.
    fn restart(&self) -> Result<(), String>;
    /// Record which origin called in. Phase 0 leaned on this to prove the
    /// remote-URL grant actually reached the shell; keep it so a future ACL
    /// regression is visible in the log instead of silent.
    fn note_caller(&self, origin: &str);

    /// Current shell preferences plus the paths they act on (Phase 3).
    fn settings(&self) -> ShellSettingsSnapshot;
    /// Apply a partial update and return the new snapshot.
    fn update_settings(&self, patch: SettingsPatch) -> Result<ShellSettingsSnapshot, String>;
    /// The UI reports its first paint with its own elapsed time, so the shell
    /// can log where the launch time actually went.
    fn note_ui_ready(&self, elapsed_ms: u64);
    /// Post a system notification for a finished round.
    fn notify(&self, request: NotificationRequest) -> Result<NotificationOutcome, String>;
    /// Claim the session a notification pointed at, if the user has come back.
    fn take_notification_target(&self) -> Option<NotificationTarget>;
    /// Claim a pending `deeptutor://` / file-association handoff.
    fn take_open_request(&self) -> Option<OpenRequestPayload>;
    /// The language the shell's own messages should be written in.
    fn locale(&self) -> String;
    /// Allow the webview to read one path back (a handoff, or a picker result).
    fn allow_local_read(&self, path: &Path);
    /// Consume that allowance; false when the path was never handed over.
    fn take_local_read_permission(&self, path: &Path) -> bool;
    /// What the first-run wizard needs to render itself.
    fn first_run(&self) -> FirstRunState;
    /// Persist the wizard's answers. May ask the shell to restart.
    fn apply_first_run(&self, choices: FirstRunChoices) -> Result<FirstRunOutcome, String>;
    /// Read-only: what the runtime-pack catalog would offer, without downloading.
    fn preview_updates(&self) -> RuntimeUpdateReport;
    /// Preview, ask the user in a native dialog, then install.
    ///
    /// The installing half is deliberately *not* a plain "check" command: the
    /// catalog URL and the archive it names decide what gets executed, and this
    /// command is reachable from the loopback-served UI.
    fn confirm_and_install_runtime_update(&self) -> RuntimeUpdateReport;
}

/// Serialisable status payload. Field names are snake_case on purpose: the same
/// shape is written to `desktop/runtime.json`, so the UI reads one vocabulary.
#[derive(Debug, Clone, Serialize)]
pub struct DesktopStatus {
    /// Monotonic counter of launcher starts in this shell session.
    pub launch_count: u64,
    /// How many crash restarts have happened in this shell session.
    pub restarts: u64,
    /// Whether a launcher process is currently alive.
    pub launcher_running: bool,
    pub launcher_pid: Option<u32>,
    /// Human-readable last status line (progress or failure text).
    pub message: String,
    /// Deployment facts useful in bug reports.
    pub home: String,
    pub workdir: String,
    pub python: String,
    /// Active runtime pack, when the shell is running from one.
    pub pack: Option<String>,
    pub logs_dir: String,
    /// How many system notifications went out this session.
    pub notifications_posted: u64,
    /// Where the launch time went, once the UI has painted (see `startup.rs`
    /// in the shell). `None` until then.
    pub startup: Option<StartupTimings>,
    /// Window geometry, so a support log can show whether state restoration
    /// actually took effect (see `window.rs`: Tauri 2.11 never fires the
    /// window-state plugin's `on_window_ready`, so the shell restores itself).
    pub window: Option<WindowGeometry>,
    /// Latest `runtime.json` contents, when the launcher has written one.
    pub runtime: Option<RuntimeSnapshot>,
}

/// Where the main window currently is and how big it is.
#[derive(Debug, Clone, Serialize)]
pub struct WindowGeometry {
    pub width: u32,
    pub height: u32,
    pub x: i32,
    pub y: i32,
    pub maximized: bool,
    pub fullscreen: bool,
    pub visible: bool,
}

/// Launch timings, measured in the shell so they survive a slow webview.
///
/// The interesting question for a desktop app is "how long until the user sees
/// the real UI", which spans three things the shell owns: spending up the
/// launcher, the launcher reporting ready, and the loopback page painting.
#[derive(Debug, Clone, Serialize, Default)]
pub struct StartupTimings {
    /// Shell start → launcher spawned.
    pub spawn_ms: u64,
    /// Shell start → launcher reported ready.
    pub ready_ms: u64,
    /// Shell start → the UI said it had painted.
    pub ui_ms: u64,
    /// Ready → the UI said it had painted, i.e. the part the shell can still
    /// influence (window creation, navigation, first render).
    pub ready_to_ui_ms: u64,
}

/// The subset of the launcher's `--runtime-info` file the UI cares about.
#[derive(Debug, Clone, Serialize)]
pub struct RuntimeSnapshot {
    pub schema_version: u32,
    pub status: String,
    pub frontend_url: Option<String>,
    pub backend_url: Option<String>,
    pub backend_port: Option<u16>,
    pub frontend_port: Option<u16>,
    /// The token itself stays out of the webview; the UI only needs to know
    /// that the handshake produced one.
    pub token_present: bool,
}

/// Shell preferences as the settings page sees them (Phase 3).
#[derive(Debug, Clone, Serialize)]
pub struct ShellSettingsSnapshot {
    pub close_to_tray: bool,
    pub notifications: bool,
    /// Empty means "leave the web UI's own language alone".
    pub locale: String,
    pub first_run_completed: bool,
    pub pack_catalog: Option<String>,
    /// The data directory in force right now.
    pub home: String,
    /// The platform default, i.e. where the wizard looks for its bootstrap file.
    pub default_home: String,
    /// True when a data-directory choice is waiting for a relaunch.
    pub restart_required: bool,
}

/// Partial settings update. Absent fields keep their current value; an empty
/// `pack_catalog` string clears the setting (JSON has no `undefined`).
#[derive(Debug, Clone, Default, Deserialize)]
pub struct SettingsPatch {
    pub close_to_tray: Option<bool>,
    pub notifications: Option<bool>,
    pub locale: Option<String>,
    pub first_run_completed: Option<bool>,
    pub pack_catalog: Option<String>,
}

/// One finished round, as the UI reports it.
#[derive(Debug, Clone, Deserialize)]
pub struct NotificationRequest {
    pub title: String,
    pub body: String,
    /// In-app route the notification should return to.
    pub route: String,
    pub session_id: Option<String>,
    /// Free-form tag (`round_complete`, `export_ready`, …) for logs and tests.
    #[serde(default)]
    pub kind: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct NotificationOutcome {
    /// False when notifications are switched off in shell settings.
    pub delivered: bool,
    pub permission: String,
    pub detail: Option<String>,
}

/// Where a notification wants to take the user.
#[derive(Debug, Clone, Serialize)]
pub struct NotificationTarget {
    pub route: String,
    pub session_id: Option<String>,
    pub title: String,
    pub age_ms: u64,
}

/// A `deeptutor://` link or a file the OS asked us to open.
#[derive(Debug, Clone, Serialize)]
pub struct OpenRequestPayload {
    /// `route` for deep links, `file` for file associations / Dock drops.
    pub kind: String,
    pub route: Option<String>,
    pub path: Option<String>,
    /// Where the request came from (`deep-link`, `file-association`, `argv`).
    pub source: String,
    /// The raw URL or argument, for logs.
    pub raw: String,
    pub age_ms: u64,
}

/// Everything the first-run wizard needs before the launcher starts.
#[derive(Debug, Clone, Serialize)]
pub struct FirstRunState {
    pub completed: bool,
    pub locale: String,
    pub default_locale: String,
    pub close_to_tray: bool,
    pub notifications: bool,
    pub home: String,
    pub default_home: String,
    pub can_change_data_dir: bool,
}

/// The wizard's answers.
#[derive(Debug, Clone, Deserialize)]
pub struct FirstRunChoices {
    pub locale: String,
    /// Absolute path, or `None`/empty to keep the platform default.
    pub data_dir: Option<String>,
    pub close_to_tray: bool,
    pub notifications: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct FirstRunOutcome {
    pub restart_required: bool,
    pub settings: ShellSettingsSnapshot,
}

#[derive(Debug, Clone, Serialize)]
pub struct RuntimeUpdateReport {
    pub checked: bool,
    pub source: Option<String>,
    pub updated: bool,
    /// Why the check/install failed, when it did.
    ///
    /// Structured so a caller never has to match prose — the `detail` line is
    /// translated, this is not.
    pub error: Option<String>,
    pub active_pack: Option<String>,
    pub previous_pack: Option<String>,
    pub app_version: Option<String>,
    pub detail: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ShellUpdateReport {
    /// `available` | `up_to_date` | `error`.
    pub status: String,
    pub detail: String,
    /// Version the update channel offers, when there is one.
    pub available_version: Option<String>,
    /// The running shell's version.
    pub current_version: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct UpdateReport {
    pub runtime: RuntimeUpdateReport,
    pub shell: ShellUpdateReport,
}

/// One native file-picker filter.
#[derive(Debug, Clone, Deserialize)]
pub struct PickFilter {
    pub name: String,
    pub extensions: Vec<String>,
}

/// Options for the native panels. Every field is optional in practice.
///
/// `filters` needs its `#[serde(default)]` as much as `multiple` does: both the
/// first-run wizard and the UI send `{options: {title}}`, and a required `Vec`
/// makes that call fail with "missing field `filters`" — which the wizard then
/// reported nowhere (its error node was inside a hidden step), so "Choose
/// folder …" simply did nothing.
#[derive(Debug, Clone, Deserialize, Default)]
pub struct PickOptions {
    pub title: Option<String>,
    #[serde(default)]
    pub filters: Vec<PickFilter>,
    #[serde(default)]
    pub multiple: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct LocalFilePayload {
    pub path: String,
    pub name: String,
    pub size: u64,
    pub mime: Option<String>,
    pub base64: String,
}

struct BackendState(Arc<dyn DesktopBackend>);

#[tauri::command]
fn desktop_status<R: Runtime>(
    window: tauri::WebviewWindow<R>,
    backend: State<'_, BackendState>,
) -> DesktopStatus {
    if let Ok(url) = window.url() {
        backend.0.note_caller(url.as_str());
    }
    backend.0.status()
}

#[tauri::command]
async fn restart_service(backend: State<'_, BackendState>) -> Result<(), String> {
    // A restart waits for the launcher's process group to exit (up to a few
    // seconds). Doing that on the command thread would freeze the window, so it
    // moves to the blocking pool and the UI keeps painting.
    let backend = Arc::clone(&backend.0);
    tauri::async_runtime::spawn_blocking(move || backend.restart())
        .await
        .map_err(|error| error.to_string())?
}

#[tauri::command]
fn shell_settings(backend: State<'_, BackendState>) -> ShellSettingsSnapshot {
    backend.0.settings()
}

/// The window may change its own preferences, but not where updates come from.
///
/// The window is served from loopback, so any script running in it can call this
/// command. Letting that script choose the runtime-pack catalog would turn a
/// cross-site scripting bug into remote code execution — the pack is downloaded,
/// extracted and *executed*. The source therefore only lives in
/// `desktop/shell.json` and `DEEPTUTOR_DESKTOP_PACK_CATALOG`, which the machine's
/// owner writes; the snapshot still reports the value so the settings page can
/// show it.
fn remote_settings_patch(mut patch: SettingsPatch, locale: &str) -> Result<SettingsPatch, String> {
    if patch.pack_catalog.is_some() {
        return Err(tr(
            locale,
            "运行时更新源只能在 desktop/shell.json 或 DEEPTUTOR_DESKTOP_PACK_CATALOG 中配置",
            "The runtime update source can only be set in desktop/shell.json or DEEPTUTOR_DESKTOP_PACK_CATALOG",
        ));
    }
    patch.pack_catalog = None;
    Ok(patch)
}

#[tauri::command]
fn update_shell_settings(
    patch: SettingsPatch,
    backend: State<'_, BackendState>,
) -> Result<ShellSettingsSnapshot, String> {
    let locale = backend.0.locale();
    backend
        .0
        .update_settings(remote_settings_patch(patch, &locale)?)
}

/// The UI's own "I have painted" call.
///
/// `elapsed_ms` comes from `performance.now()` in the page, which starts when
/// the document does; the shell adds the time it spent before handing the window
/// over, so the two numbers line up on one axis.
// Explicitly camelCase: the page sends `elapsedMs`, and a rename mismatch here
// fails silently as a rejected promise while the app keeps working.
#[tauri::command(rename_all = "camelCase")]
fn note_ui_ready(elapsed_ms: u64, backend: State<'_, BackendState>) {
    backend.0.note_ui_ready(elapsed_ms);
}

#[tauri::command]
fn notify_round_complete(
    request: NotificationRequest,
    backend: State<'_, BackendState>,
) -> Result<NotificationOutcome, String> {
    backend.0.notify(request)
}

#[tauri::command]
fn take_notification_target(backend: State<'_, BackendState>) -> Option<NotificationTarget> {
    backend.0.take_notification_target()
}

#[tauri::command]
fn take_open_request(backend: State<'_, BackendState>) -> Option<OpenRequestPayload> {
    backend.0.take_open_request()
}

#[tauri::command]
fn first_run_state(backend: State<'_, BackendState>) -> FirstRunState {
    backend.0.first_run()
}

#[tauri::command]
fn apply_first_run(
    choices: FirstRunChoices,
    backend: State<'_, BackendState>,
) -> Result<FirstRunOutcome, String> {
    backend.0.apply_first_run(choices)
}

#[tauri::command]
async fn check_updates<R: Runtime>(
    app: tauri::AppHandle<R>,
    install: Option<bool>,
    backend: State<'_, BackendState>,
) -> Result<UpdateReport, String> {
    // Read-only by default. An install is still gated by a native confirmation
    // dialog inside the shell (`confirm_and_install_runtime_update`), because
    // this command is reachable from the loopback-served UI.
    let locale = backend.0.locale();
    let backend = Arc::clone(&backend.0);
    let install = install.unwrap_or(false);
    let runtime = tauri::async_runtime::spawn_blocking(move || {
        if install {
            backend.confirm_and_install_runtime_update()
        } else {
            backend.preview_updates()
        }
    })
    .await
    .map_err(|error| error.to_string())?;
    // The shell plane is async natively, so it is awaited instead of blocking a
    // pool thread — and it must never download, only answer.
    let shell = updater::check(&app, &locale).await;
    Ok(UpdateReport { runtime, shell })
}

/// Download and install the newest shell build, then leave the restart to the
/// caller (`restart_app`) so the UI can show the outcome first.
#[tauri::command]
async fn install_shell_update<R: Runtime>(
    app: tauri::AppHandle<R>,
    backend: State<'_, BackendState>,
) -> Result<ShellUpdateInstall, String> {
    let locale = backend.0.locale();
    updater::install(&app, &locale).await
}

/// Longest UI log line the shell keeps; the rest is dropped rather than
/// letting the loopback page grow `shell.log` without bound.
const MAX_LOG_EVENT_CHARS: usize = 2000;

/// Shell-side log line. The UI uses this for things the webview cannot report
/// (native dialogs it opened, file handoffs it handled).
#[tauri::command]
fn log_event(message: String, backend: State<'_, BackendState>) {
    let message: String = message.chars().take(MAX_LOG_EVENT_CHARS).collect();
    backend.0.note_caller(&format!("ui: {message}"));
}

/// Native open panel. Returns absolute paths; the caller ingests them with
/// `read_local_file`, which is why each picked path is granted a read here.
#[tauri::command]
async fn pick_files<R: Runtime>(
    window: tauri::WebviewWindow<R>,
    options: Option<PickOptions>,
    backend: State<'_, BackendState>,
) -> Result<Vec<String>, String> {
    let options = options.unwrap_or_default();
    let mut builder = window.dialog().file();
    if let Some(title) = options.title {
        builder = builder.set_title(title);
    }
    for filter in &options.filters {
        let extensions: Vec<&str> = filter.extensions.iter().map(String::as_str).collect();
        builder = builder.add_filter(&filter.name, &extensions);
    }
    let picked = if options.multiple {
        builder.blocking_pick_files()
    } else {
        builder.blocking_pick_file().map(|path| vec![path])
    };
    let mut paths = Vec::new();
    for path in picked.unwrap_or_default() {
        match path.into_path() {
            Ok(path) => {
                backend.0.allow_local_read(&path);
                paths.push(path.to_string_lossy().into_owned());
            }
            Err(error) => {
                let locale = backend.0.locale();
                return Err(tr(
                    &locale,
                    format!("无法解析所选路径: {error}"),
                    format!("Could not resolve the selected path: {error}"),
                ));
            }
        }
    }
    Ok(paths)
}

/// Hand a path to the OS file manager with the item selected.
#[tauri::command]
fn reveal_in_folder(path: String, backend: State<'_, BackendState>) -> Result<(), String> {
    tauri_plugin_opener::reveal_item_in_dir(PathBuf::from(&path)).map_err(|error| {
        let locale = backend.0.locale();
        tr(
            &locale,
            format!("无法在文件管理器中显示 {path}: {error}"),
            format!("Could not reveal {path} in the file manager: {error}"),
        )
    })
}

/// Native "choose a folder" panel — the first-run wizard's data directory.
///
/// Returns an empty string when the user cancels, so the caller can tell
/// "cancelled" apart from "chose the empty path".
#[tauri::command]
async fn pick_folder<R: Runtime>(
    window: tauri::WebviewWindow<R>,
    options: Option<PickOptions>,
    backend: State<'_, BackendState>,
) -> Result<String, String> {
    let options = options.unwrap_or_default();
    let mut builder = window.dialog().file();
    if let Some(title) = options.title {
        builder = builder.set_title(title);
    }
    match builder.blocking_pick_folder() {
        Some(folder) => folder
            .into_path()
            .map(|path| path.to_string_lossy().into_owned())
            .map_err(|error| {
                let locale = backend.0.locale();
                tr(
                    &locale,
                    format!("无法解析所选目录: {error}"),
                    format!("Could not resolve the selected folder: {error}"),
                )
            }),
        None => Ok(String::new()),
    }
}

/// Read a local file into the webview so it can travel the normal upload path.
///
/// Only paths the shell itself handed over (a Dock drop, a file association, an
/// "Open with") or the user picked in the native panel are readable. Accepting
/// arbitrary absolute paths would make any script in the loopback-served UI
/// enough to exfiltrate every readable file on the machine, so the allowance is
/// granted where the path enters the app and consumed here.
#[tauri::command]
fn read_local_file(
    path: String,
    backend: State<'_, BackendState>,
) -> Result<LocalFilePayload, String> {
    let path = PathBuf::from(&path);
    if !backend.0.take_local_read_permission(&path) {
        let locale = backend.0.locale();
        return Err(tr(
            &locale,
            format!(
                "{} 不是 DeepTutor 移交的文件；请使用应用内的上传入口或拖放",
                path.display()
            ),
            format!(
                "{} was not handed over by DeepTutor; use the in-app upload entry point or drag and drop",
                path.display()
            ),
        ));
    }
    let metadata = std::fs::metadata(&path)
        .map_err(|error| format!("无法读取 {}: {error}", path.display()))?;
    if !metadata.is_file() {
        let locale = backend.0.locale();
        return Err(tr(
            &locale,
            format!("{} 不是文件", path.display()),
            format!("{} is not a file", path.display()),
        ));
    }
    if metadata.len() > MAX_LOCAL_FILE_BYTES {
        let locale = backend.0.locale();
        return Err(tr(
            &locale,
            format!(
                "文件过大（{} MB），请使用应用内的上传入口",
                metadata.len() / (1024 * 1024)
            ),
            format!(
                "The file is too large ({} MB); use the in-app upload entry point",
                metadata.len() / (1024 * 1024)
            ),
        ));
    }
    let bytes =
        std::fs::read(&path).map_err(|error| format!("无法读取 {}: {error}", path.display()))?;
    let name = path
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .ok_or_else(|| {
            let locale = backend.0.locale();
            tr(
                &locale,
                format!("{} 没有文件名", path.display()),
                format!("{} has no file name", path.display()),
            )
        })?;
    Ok(LocalFilePayload {
        path: path.to_string_lossy().into_owned(),
        name,
        size: metadata.len(),
        mime: mime_for(&path),
        base64: base64::engine::general_purpose::STANDARD.encode(&bytes),
    })
}

/// Relaunch the shell in place (used after a data-directory change).
#[tauri::command]
fn restart_app<R: Runtime>(app: tauri::AppHandle<R>) {
    app.restart();
}

/// Best-effort MIME type from the extension. The webview builds a `File` from
/// the bytes, and the backend re-sniffs the content anyway.
fn mime_for(path: &std::path::Path) -> Option<String> {
    let extension = path.extension()?.to_str()?.to_ascii_lowercase();
    let mime = match extension.as_str() {
        "pdf" => "application/pdf",
        "epub" => "application/epub+zip",
        "md" | "markdown" => "text/markdown",
        "txt" | "text" | "log" => "text/plain",
        "html" | "htm" => "text/html",
        "json" => "application/json",
        "csv" => "text/csv",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "docx" => "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pptx" => "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "xlsx" => "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        _ => return None,
    };
    Some(mime.to_string())
}

/// Register the plugin. The caller passes the shell implementation.
pub fn init<R: Runtime>(backend: Arc<dyn DesktopBackend>) -> TauriPlugin<R> {
    // Turbofish on both parameters: `Builder` is `Builder<R, C = ()>`, and
    // leaving `C` to inference makes the chain resolve to the default runtime.
    Builder::<R, ()>::new("deeptutor")
        .invoke_handler(tauri::generate_handler![
            desktop_status,
            restart_service,
            shell_settings,
            update_shell_settings,
            note_ui_ready,
            notify_round_complete,
            take_notification_target,
            take_open_request,
            first_run_state,
            apply_first_run,
            check_updates,
            install_shell_update,
            log_event,
            pick_files,
            pick_folder,
            reveal_in_folder,
            read_local_file,
            restart_app
        ])
        .setup(move |app, _api| {
            // The trait object is cheap to clone and the closure runs once.
            app.manage(BackendState(Arc::clone(&backend)));
            Ok(())
        })
        .build()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The wizard and the UI both ask for a folder with `{options: {title}}` and
    /// nothing else. A required `Vec` field made that call fail with
    /// "missing field `filters`" before it ever reached the native panel.
    #[test]
    fn picker_options_without_filters_are_valid() {
        let titled: PickOptions =
            serde_json::from_str(r#"{"title":"选择文件夹"}"#).expect("title only");
        assert_eq!(titled.title.as_deref(), Some("选择文件夹"));
        assert!(titled.filters.is_empty());
        assert!(!titled.multiple);

        let bare: PickOptions = serde_json::from_str("{}").expect("empty options");
        assert!(bare.filters.is_empty());

        // Filters still deserialize when a caller does provide them.
        let filtered: PickOptions = serde_json::from_str(
            r#"{"filters":[{"name":"Documents","extensions":["pdf","epub"]}],"multiple":true}"#,
        )
        .expect("filters");
        assert_eq!(filtered.filters.len(), 1);
        assert_eq!(filtered.filters[0].name, "Documents");
        assert_eq!(filtered.filters[0].extensions, vec!["pdf", "epub"]);
        assert!(filtered.multiple);
    }

    /// The window is loopback-served and therefore only as trustworthy as a
    /// script tag: it may flip its own preferences, never the update source.
    #[test]
    fn the_remote_origin_cannot_choose_the_update_source() {
        let error = remote_settings_patch(
            SettingsPatch {
                pack_catalog: Some("https://attacker.example/runtime-packs.json".to_string()),
                ..SettingsPatch::default()
            },
            "zh-CN",
        )
        .unwrap_err();
        assert!(error.contains("shell.json"), "{error}");

        // An empty string means "clear it", which is equally out of bounds.
        assert!(remote_settings_patch(
            SettingsPatch {
                pack_catalog: Some(String::new()),
                ..SettingsPatch::default()
            },
            "en",
        )
        .is_err());

        let patch = remote_settings_patch(
            SettingsPatch {
                close_to_tray: Some(false),
                notifications: Some(true),
                locale: Some("en".to_string()),
                first_run_completed: None,
                pack_catalog: None,
            },
            "en",
        )
        .expect("ordinary preferences stay settable");
        assert_eq!(patch.locale.as_deref(), Some("en"));
        assert_eq!(patch.close_to_tray, Some(false));
        assert!(patch.pack_catalog.is_none());
    }
}
