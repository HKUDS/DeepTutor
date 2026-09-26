//! The main window, created in code.
//!
//! Phase 1/2 declared the window in `tauri.conf.json`. Phase 3 needs three
//! hooks that only exist on the *builder*, so the declaration moved here:
//!
//! * `on_navigation` — external links open in the user's browser instead of
//!   replacing the app, and `deeptutor://` links typed or clicked inside the UI
//!   take the same path as ones that arrive from the OS.
//! * `on_download` — exports land in ~/Downloads with a non-colliding name, and
//!   the UI is told where they went so it can offer "show in folder".
//! * `disable_drag_drop_handler` — Tauri's own file-drop handler is off, which
//!   is what lets the existing HTML5 drag-and-drop upload path keep working
//!   (Phase 0 flagged it as a WebView risk; this is the mitigation).

use std::path::{Path, PathBuf};
use std::sync::Mutex;

use tauri::webview::DownloadEvent;
use tauri::{App, Emitter, Manager, WebviewUrl, WebviewWindow, WebviewWindowBuilder};
use tauri_plugin_window_state::{StateFlags, WindowExt as _};

use crate::supervisor::Supervisor;

pub const MAIN_WINDOW: &str = "main";

/// What to do with a navigation the webview attempted.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NavAction {
    /// Keep it inside the app window.
    Allow,
    /// Block it and hand it to the system browser.
    External,
    /// Block it and queue it as an in-app hand-off.
    Handoff,
}

/// Create the DeepTutor window and attach its native behaviour.
pub fn create_main_window(app: &App) -> tauri::Result<WebviewWindow> {
    let supervisor = std::sync::Arc::clone(&app.state::<std::sync::Arc<Supervisor>>());
    let downloads = Downloads::default();

    let navigation_owner = std::sync::Arc::clone(&supervisor);
    let window = WebviewWindowBuilder::new(app, MAIN_WINDOW, WebviewUrl::App("index.html".into()))
        // Mirrors of the former `app.windows[0]` entry in tauri.conf.json.
        .title("DeepTutor")
        .inner_size(1100.0, 720.0)
        .min_inner_size(760.0, 520.0)
        .resizable(true)
        .center()
        .disable_drag_drop_handler()
        .on_navigation(move |url| {
            match classify_navigation(url, navigation_owner.frontend_port()) {
                NavAction::Allow => true,
                NavAction::External => {
                    open_external(url);
                    false
                }
                NavAction::Handoff => {
                    navigation_owner.push_open_urls(std::iter::once(url), "webview-link");
                    false
                }
            }
        })
        .on_download(move |webview, event| match event {
            DownloadEvent::Requested { url, destination } => {
                download_requested(&url, destination, &downloads, webview.app_handle());
                true
            }
            DownloadEvent::Finished { url, path, success } => {
                download_finished(&url, path, success, &downloads, webview.app_handle());
                true
            }
            _ => true,
        })
        .build()?;

    // `tauri-plugin-window-state` restores a window from its own
    // `on_window_ready` hook, and Tauri 2.11.6 never invokes that hook for any
    // window — so "remember size/position/full-screen" silently did nothing.
    // The plugin still *saves* state on window events and on exit, so calling
    // restore here is all that is missing.
    if let Err(error) = window.restore_state(StateFlags::all()) {
        eprintln!("could not restore the previous window state: {error}");
    }
    Ok(window)
}

/// In-app navigation policy. Pure, so the rules are unit-tested rather than
/// discovered by clicking around a running app.
///
/// `frontend_port` is the port the launcher said it is serving the UI from
/// (`Supervisor::frontend_port`). Loopback alone is *not* ours: any local
/// service is reachable from the webview, and the window carries the shell's IPC
/// grant, so a page on another port must open in the user's browser instead of
/// replacing the app.
pub fn classify_navigation(url: &tauri::Url, frontend_port: Option<u16>) -> NavAction {
    match url.scheme() {
        // The splash and any bundled asset.
        "tauri" | "asset" => NavAction::Allow,
        // Links the UI builds for itself (`deeptutor://settings`, say).
        "deeptutor" => NavAction::Handoff,
        "http" | "https" => {
            if is_our_frontend(url, frontend_port) {
                NavAction::Allow
            } else {
                NavAction::External
            }
        }
        // `about:blank`, `data:`, `blob:` are produced by the page itself.
        _ => NavAction::Allow,
    }
}

/// Is this the launcher's own UI, on the port it reported for this run?
///
/// The loopback spelling is not compared (`127.0.0.1` and `localhost` are the
/// same server), but the port is: an unknown port — including "the launcher has
/// not reported one yet" — is not ours.
fn is_our_frontend(url: &tauri::Url, frontend_port: Option<u16>) -> bool {
    match (frontend_port, url.port_or_known_default()) {
        (Some(expected), Some(actual)) => expected == actual && is_loopback(url),
        _ => false,
    }
}

/// The UI is served from the launcher's loopback port, which changes per run.
fn is_loopback(url: &tauri::Url) -> bool {
    matches!(
        url.host_str(),
        Some("localhost") | Some("127.0.0.1") | Some("::1") | Some("[::1]")
    )
}

fn open_external(url: &tauri::Url) {
    if let Err(error) = tauri_plugin_opener::open_url(url.as_str(), None::<&str>) {
        eprintln!("failed to open {url} in the system browser: {error}");
    }
}

/// Remembers the destination we chose, because macOS reports an empty path on
/// completion.
#[derive(Default)]
struct Downloads {
    last: Mutex<Option<PathBuf>>,
}

fn download_requested(
    url: &tauri::Url,
    destination: &mut PathBuf,
    downloads: &Downloads,
    app: &tauri::AppHandle,
) {
    if let Some(directory) = download_directory() {
        let name = destination
            .file_name()
            .map(|name| name.to_string_lossy().into_owned())
            .filter(|name| !name.is_empty())
            .unwrap_or_else(|| "deeptutor-download".to_string());
        let planned = unique_path(&directory, &name);
        if let Some(parent) = planned.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        *destination = planned.clone();
        if let Ok(mut last) = downloads.last.lock() {
            *last = Some(planned);
        }
    }
    let _ = app.emit(
        "deeptutor://download-started",
        serde_json::json!({ "url": url.as_str() }),
    );
}

fn download_finished(
    url: &tauri::Url,
    path: Option<PathBuf>,
    success: bool,
    downloads: &Downloads,
    app: &tauri::AppHandle,
) {
    let remembered = downloads.last.lock().ok().and_then(|mut last| last.take());
    // macOS hands back `None` even for successful downloads; the path we chose
    // in `Requested` is the only reliable answer there.
    let saved = path.or(remembered);
    let _ = app.emit(
        "deeptutor://download-finished",
        serde_json::json!({
            "url": url.as_str(),
            "success": success,
            "path": saved.as_ref().map(|path| path.to_string_lossy().into_owned()),
        }),
    );
}

/// `~/Downloads`, falling back to the platform default when it cannot be found.
fn download_directory() -> Option<PathBuf> {
    let home = if cfg!(windows) {
        std::env::var_os("USERPROFILE")
    } else {
        std::env::var_os("HOME")
    }?;
    Some(PathBuf::from(home).join("Downloads"))
}

/// `report.pdf` → `report (1).pdf` when the first name is taken.
fn unique_path(directory: &Path, name: &str) -> PathBuf {
    let candidate = directory.join(name);
    if !candidate.exists() {
        return candidate;
    }
    let path = Path::new(name);
    let stem = path
        .file_stem()
        .map(|stem| stem.to_string_lossy().into_owned())
        .unwrap_or_else(|| "download".to_string());
    let extension = path
        .extension()
        .map(|extension| extension.to_string_lossy().into_owned());
    for index in 1..1000 {
        let name = match &extension {
            Some(extension) => format!("{stem} ({index}).{extension}"),
            None => format!("{stem} ({index})"),
        };
        let candidate = directory.join(name);
        if !candidate.exists() {
            return candidate;
        }
    }
    directory.join(name)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn url(raw: &str) -> tauri::Url {
        tauri::Url::parse(raw).expect("test url")
    }

    #[test]
    fn the_loopback_ui_stays_inside_the_window() {
        // The port the launcher reported this run.
        assert_eq!(
            classify_navigation(&url("http://127.0.0.1:3782/chat/s-1"), Some(3782)),
            NavAction::Allow
        );
        // The same server under its other loopback spelling is still ours.
        assert_eq!(
            classify_navigation(&url("http://localhost:3782/settings"), Some(3782)),
            NavAction::Allow
        );
        assert_eq!(
            classify_navigation(&url("http://[::1]:3782/settings"), Some(3782)),
            NavAction::Allow
        );
        assert_eq!(
            classify_navigation(&url("tauri://localhost/index.html"), Some(3782)),
            NavAction::Allow
        );
    }

    #[test]
    fn external_links_leave_the_app() {
        assert_eq!(
            classify_navigation(&url("https://github.com/HKUDS/DeepTutor"), Some(3782)),
            NavAction::External
        );
        assert_eq!(
            classify_navigation(
                &url("https://accounts.google.com/o/oauth2/auth?x=1"),
                Some(3782)
            ),
            NavAction::External
        );
    }

    /// Another local service is not the app: it would inherit the window's IPC
    /// grant, so it opens in the user's browser. An unknown port (the launcher
    /// has not reported one, or has never been reached) fails closed too.
    #[test]
    fn another_loopback_service_is_not_navigated_to() {
        assert_eq!(
            classify_navigation(&url("http://127.0.0.1:9/health"), Some(3782)),
            NavAction::External
        );
        assert_eq!(
            classify_navigation(&url("http://localhost:8001/api/status"), Some(3782)),
            NavAction::External
        );
        assert_eq!(
            classify_navigation(&url("http://127.0.0.1:3782/chat"), None),
            NavAction::External
        );
        assert_eq!(
            classify_navigation(&url("http://127.0.0.1:3782/chat"), Some(8001)),
            NavAction::External
        );
    }

    #[test]
    fn in_page_deep_links_are_queued_instead_of_navigated() {
        assert_eq!(
            classify_navigation(&url("deeptutor://chat/abc"), Some(3782)),
            NavAction::Handoff
        );
    }

    #[test]
    fn downloads_never_overwrite_an_existing_file() {
        let directory =
            std::env::temp_dir().join(format!("deeptutor-downloads-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&directory);
        std::fs::create_dir_all(&directory).unwrap();
        assert_eq!(
            unique_path(&directory, "report.pdf"),
            directory.join("report.pdf")
        );
        std::fs::write(directory.join("report.pdf"), b"x").unwrap();
        assert_eq!(
            unique_path(&directory, "report.pdf"),
            directory.join("report (1).pdf")
        );
        std::fs::write(directory.join("report (1).pdf"), b"x").unwrap();
        assert_eq!(
            unique_path(&directory, "report.pdf"),
            directory.join("report (2).pdf")
        );
        // Extension-less names still get a distinct name.
        std::fs::write(directory.join("notes"), b"x").unwrap();
        assert_eq!(
            unique_path(&directory, "notes"),
            directory.join("notes (1)")
        );
        let _ = std::fs::remove_dir_all(&directory);
    }
}
