//! Native chrome: menu bar, tray icon and the actions they trigger.
//!
//! Everything a user can reach from outside the web page lives here, so the
//! window contents stay the web app's business and this file stays a list of
//! "what the OS offers a desktop user".
//!
//! Phase 3 added the parts that make the shell feel like an app rather than a
//! browser window: the tray keeps the service alive when the window is hidden,
//! the app menu carries the two preferences a desktop user expects to be able
//! to flip from the menu bar, and "查看更新" answers about both update planes.

use std::sync::Arc;

use tauri::menu::{
    AboutMetadata, CheckMenuItemBuilder, Menu, MenuBuilder, MenuItemBuilder, MenuItemKind,
    PredefinedMenuItem, SubmenuBuilder,
};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, Runtime};
use tauri_plugin_dialog::{DialogExt as _, MessageDialogButtons, MessageDialogKind};

use crate::strings::{tr, Locale};
use crate::supervisor::Supervisor;
use crate::window::MAIN_WINDOW;
use tauri_plugin_deeptutor::{SettingsPatch, ShellUpdateReport, UpdateReport};

/// Menu ids, kept in one place so the handler cannot drift from the builder.
pub const MENU_RESTART_SERVICE: &str = "restart_service";
pub const MENU_OPEN_LOGS: &str = "open_logs";
pub const MENU_OPEN_SETTINGS: &str = "open_settings";
pub const MENU_RELOAD_UI: &str = "reload_ui";
pub const MENU_OPEN_DOCS: &str = "open_docs";
pub const MENU_CHECK_UPDATES: &str = "check_updates";
pub const MENU_TOGGLE_CLOSE_TO_TRAY: &str = "toggle_close_to_tray";
pub const MENU_TOGGLE_NOTIFICATIONS: &str = "toggle_notifications";
pub const TRAY_TOGGLE_WINDOW: &str = "tray_toggle_window";
pub const TRAY_QUIT: &str = "tray_quit";

const DOCS_URL: &str = "https://github.com/HKUDS/DeepTutor#readme";

/// Build and install the menu bar. Every item is bound to a local first: a
/// menu builder wants `&dyn IsMenuItem`, and inline `&Foo(app)?` temporaries do
/// not always live long enough inside an array.
pub fn install_menu<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    // The check marks must match the saved preferences the moment the menu is
    // drawn, so the supervisor is asked while the items are built.
    let preferences = app.state::<Arc<Supervisor>>().shell_settings();
    let locale = app.state::<Arc<Supervisor>>().locale();

    let check_updates = MenuItemBuilder::with_id(
        MENU_CHECK_UPDATES,
        tr(locale, "检查更新 …", "Check for updates …"),
    )
    .build(app)?;
    let settings = MenuItemBuilder::with_id(MENU_OPEN_SETTINGS, tr(locale, "设置 …", "Settings …"))
        .accelerator("CmdOrCtrl+,")
        .build(app)?;
    let close_to_tray = CheckMenuItemBuilder::with_id(
        MENU_TOGGLE_CLOSE_TO_TRAY,
        tr(
            locale,
            "关闭窗口时隐藏到托盘",
            "Hide to the tray when the window closes",
        ),
    )
    .checked(preferences.close_to_tray)
    .build(app)?;
    let notifications = CheckMenuItemBuilder::with_id(
        MENU_TOGGLE_NOTIFICATIONS,
        tr(locale, "回合完成时通知", "Notify when a round finishes"),
    )
    .checked(preferences.notifications)
    .build(app)?;
    let restart = MenuItemBuilder::with_id(
        MENU_RESTART_SERVICE,
        tr(locale, "重新启动本地服务", "Restart the local service"),
    )
    .build(app)?;
    let open_logs = MenuItemBuilder::with_id(
        MENU_OPEN_LOGS,
        tr(locale, "打开日志目录", "Open the log folder"),
    )
    .build(app)?;
    let docs = MenuItemBuilder::with_id(MENU_OPEN_DOCS, tr(locale, "使用文档", "Documentation"))
        .build(app)?;
    let reload = MenuItemBuilder::with_id(
        MENU_RELOAD_UI,
        tr(locale, "重新加载界面", "Reload the interface"),
    )
    .accelerator("CmdOrCtrl+R")
    .build(app)?;

    let about = PredefinedMenuItem::about(
        app,
        Some(&tr(locale, "关于 DeepTutor", "About DeepTutor")),
        Some(AboutMetadata::default()),
    )?;
    let services = PredefinedMenuItem::services(app, None)?;
    let hide = PredefinedMenuItem::hide(app, None)?;
    let hide_others = PredefinedMenuItem::hide_others(app, None)?;
    let show_all = PredefinedMenuItem::show_all(app, None)?;
    let quit =
        PredefinedMenuItem::quit(app, Some(&tr(locale, "退出 DeepTutor", "Quit DeepTutor")))?;

    let app_sep1 = PredefinedMenuItem::separator(app)?;
    let app_sep2 = PredefinedMenuItem::separator(app)?;
    let app_sep3 = PredefinedMenuItem::separator(app)?;
    let app_sep4 = PredefinedMenuItem::separator(app)?;
    let app_sep5 = PredefinedMenuItem::separator(app)?;
    let app_menu = SubmenuBuilder::new(app, "DeepTutor")
        .items(&[
            &about,
            &app_sep1,
            &check_updates,
            &app_sep2,
            &settings,
            &close_to_tray,
            &notifications,
            &app_sep3,
            &restart,
            &open_logs,
            &app_sep4,
            &services,
            &hide,
            &hide_others,
            &show_all,
            &app_sep5,
            &quit,
        ])
        .build()?;

    // The Edit menu is what makes ⌘C/⌘V work inside the webview at all.
    let undo = PredefinedMenuItem::undo(app, None)?;
    let redo = PredefinedMenuItem::redo(app, None)?;
    let cut = PredefinedMenuItem::cut(app, None)?;
    let copy = PredefinedMenuItem::copy(app, None)?;
    let paste = PredefinedMenuItem::paste(app, None)?;
    let select_all = PredefinedMenuItem::select_all(app, None)?;
    let edit_sep = PredefinedMenuItem::separator(app)?;
    let edit_menu = SubmenuBuilder::new(app, tr(locale, "编辑", "Edit"))
        .items(&[&undo, &redo, &edit_sep, &cut, &copy, &paste, &select_all])
        .build()?;

    let fullscreen = PredefinedMenuItem::fullscreen(app, None)?;
    #[cfg(debug_assertions)]
    let view_menu = {
        let sep = PredefinedMenuItem::separator(app)?;
        let devtools = MenuItemBuilder::with_id(
            "toggle_devtools",
            tr(locale, "开发者工具", "Developer tools"),
        )
        .accelerator("Alt+CmdOrCtrl+I")
        .build(app)?;
        SubmenuBuilder::new(app, tr(locale, "视图", "View"))
            .items(&[&reload, &fullscreen, &sep, &devtools])
            .build()?
    };
    #[cfg(not(debug_assertions))]
    let view_menu = SubmenuBuilder::new(app, tr(locale, "视图", "View"))
        .items(&[&reload, &fullscreen])
        .build()?;

    let minimize = PredefinedMenuItem::minimize(app, None)?;
    let maximize = PredefinedMenuItem::maximize(app, None)?;
    let close_window = PredefinedMenuItem::close_window(app, None)?;
    let window_sep = PredefinedMenuItem::separator(app)?;
    let window_menu = SubmenuBuilder::new(app, tr(locale, "窗口", "Window"))
        .items(&[&minimize, &maximize, &window_sep, &close_window])
        .build()?;

    let help_menu = SubmenuBuilder::new(app, tr(locale, "帮助", "Help"))
        .items(&[&docs])
        .build()?;

    let menu = MenuBuilder::new(app)
        .items(&[&app_menu, &edit_menu, &view_menu, &window_menu, &help_menu])
        .build()?;
    app.set_menu(menu)?;
    Ok(())
}

/// The tray's own menu, built separately so a language change can replace it.
fn tray_menu<R: Runtime>(app: &AppHandle<R>, locale: Locale) -> tauri::Result<Menu<R>> {
    // One item does both directions: the tray is the one affordance a user
    // reaches for when the window is out of sight, and a fixed label avoids a
    // menu rebuild whenever visibility changes.
    let toggle = MenuItemBuilder::with_id(
        TRAY_TOGGLE_WINDOW,
        tr(locale, "显示 / 隐藏主窗口", "Show / hide the main window"),
    )
    .build(app)?;
    let check_updates = MenuItemBuilder::with_id(
        MENU_CHECK_UPDATES,
        tr(locale, "检查更新 …", "Check for updates …"),
    )
    .build(app)?;
    let restart = MenuItemBuilder::with_id(
        MENU_RESTART_SERVICE,
        tr(locale, "重新启动本地服务", "Restart the local service"),
    )
    .build(app)?;
    let open_logs = MenuItemBuilder::with_id(
        MENU_OPEN_LOGS,
        tr(locale, "打开日志目录", "Open the log folder"),
    )
    .build(app)?;
    let quit = MenuItemBuilder::with_id(TRAY_QUIT, tr(locale, "退出 DeepTutor", "Quit DeepTutor"))
        .build(app)?;
    let sep1 = PredefinedMenuItem::separator(app)?;
    let sep2 = PredefinedMenuItem::separator(app)?;
    Menu::with_items(
        app,
        &[
            &toggle,
            &sep1,
            &check_updates,
            &restart,
            &open_logs,
            &sep2,
            &quit,
        ],
    )
}

/// Relabel the native chrome after a language change.
///
/// The menu bar is replaced wholesale (`set_menu`) and the tray gets the new
/// menu, so no label is left in the previous language until the next launch.
pub fn refresh_chrome<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    install_menu(app)?;
    if let Some(tray) = app.tray_by_id("deeptutor") {
        let locale = app.state::<Arc<Supervisor>>().locale();
        tray.set_menu(Some(tray_menu(app, locale)?))?;
    }
    Ok(())
}

/// Tray icon: the app keeps working while the window is hidden.
pub fn install_tray<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    let locale = app.state::<Arc<Supervisor>>().locale();
    let menu = tray_menu(app, locale)?;

    let mut builder = TrayIconBuilder::with_id("deeptutor")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                toggle_window(tray.app_handle());
            }
        });
    // A tray without an icon is invisible on macOS; the bundle icon comes from
    // `generate_context!`, so this only matters in stripped-down builds.
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    Ok(())
}

/// Handle every menu and tray id in one place.
pub fn on_menu_event<R: Runtime>(app: &AppHandle<R>, id: &str) {
    let supervisor = app.state::<Arc<Supervisor>>();
    match id {
        MENU_RESTART_SERVICE => {
            if let Err(error) = supervisor.restart() {
                supervisor.append_shell_log(&format!("restart failed: {error}"));
            }
            reveal(app);
        }
        MENU_OPEN_LOGS => {
            if let Err(error) = tauri_plugin_opener::open_path(supervisor.logs_dir(), None::<&str>)
            {
                supervisor.append_shell_log(&format!("open logs failed: {error}"));
            }
        }
        MENU_OPEN_SETTINGS => navigate(app, "/settings"),
        MENU_CHECK_UPDATES => spawn_check_updates(app),
        MENU_TOGGLE_CLOSE_TO_TRAY => {
            let current = supervisor.shell_settings().close_to_tray;
            toggle_preference(
                app,
                SettingsPatch {
                    close_to_tray: Some(!current),
                    ..SettingsPatch::default()
                },
            );
        }
        MENU_TOGGLE_NOTIFICATIONS => {
            let current = supervisor.shell_settings().notifications;
            toggle_preference(
                app,
                SettingsPatch {
                    notifications: Some(!current),
                    ..SettingsPatch::default()
                },
            );
        }
        MENU_RELOAD_UI => {
            if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
                let _ = window.eval("window.location.reload()");
            }
        }
        MENU_OPEN_DOCS => {
            if let Err(error) = tauri_plugin_opener::open_url(DOCS_URL, None::<&str>) {
                supervisor.append_shell_log(&format!("open docs failed: {error}"));
            }
        }
        #[cfg(debug_assertions)]
        "toggle_devtools" => {
            if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
                window.open_devtools();
            }
        }
        TRAY_TOGGLE_WINDOW => toggle_window(app),
        TRAY_QUIT => {
            supervisor.stop();
            app.exit(0);
        }
        _ => {}
    }
}

/// Bring the main window back from hidden or minimised.
pub fn reveal<R: Runtime>(app: &AppHandle<R>) {
    if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
        // Coming back is also the moment a "which session was that?" hand-off
        // can be delivered.
        app.state::<Arc<Supervisor>>().flush_notification_target();
    }
}

/// Show the window if it is out of the way, hide it if it is already there.
pub fn toggle_window<R: Runtime>(app: &AppHandle<R>) {
    let Some(window) = app.get_webview_window(MAIN_WINDOW) else {
        return;
    };
    let visible = window.is_visible().unwrap_or(false);
    let focused = window.is_focused().unwrap_or(false);
    if visible && focused {
        let _ = window.hide();
    } else {
        reveal(app);
    }
}

/// Persist a preference flipped from the menu, and keep the check mark honest.
///
/// The menu is the second writer of these two settings (the settings page is the
/// other), so the result — not the request — decides what the checkbox shows.
fn toggle_preference<R: Runtime>(app: &AppHandle<R>, patch: SettingsPatch) {
    let supervisor = app.state::<Arc<Supervisor>>();
    match supervisor.apply_settings_patch(patch) {
        Ok(snapshot) => {
            supervisor.append_shell_log(&format!(
                "preferences updated: close_to_tray={} notifications={}",
                snapshot.close_to_tray, snapshot.notifications
            ));
            // The settings page may be open and would otherwise show stale
            // toggles until the next navigation.
            let _ = app.emit(
                "deeptutor://shell-settings",
                serde_json::to_value(&snapshot).unwrap_or(serde_json::Value::Null),
            );
        }
        Err(error) => {
            supervisor.append_shell_log(&format!("preference update failed: {error}"));
        }
    }
    sync_preference_checks(app);
}

/// Redraw the check marks from the stored preferences.
pub fn sync_preference_checks<R: Runtime>(app: &AppHandle<R>) {
    let snapshot = app.state::<Arc<Supervisor>>().shell_settings();
    let Some(menu) = app.menu() else {
        return;
    };
    if let Some(MenuItemKind::Check(item)) = menu.get(MENU_TOGGLE_CLOSE_TO_TRAY) {
        let _ = item.set_checked(snapshot.close_to_tray);
    }
    if let Some(MenuItemKind::Check(item)) = menu.get(MENU_TOGGLE_NOTIFICATIONS) {
        let _ = item.set_checked(snapshot.notifications);
    }
}

/// Check both update planes off the main thread and report through the UI and a
/// native dialog.
///
/// A runtime pack is only installed after the user answers a native
/// confirmation (see `Supervisor::confirm_and_install_runtime_update`); the
/// shell plane already asks before downloading.
fn spawn_check_updates<R: Runtime>(app: &AppHandle<R>) {
    let app = app.clone();
    std::thread::Builder::new()
        .name("deeptutor-update-check".to_string())
        .spawn(move || {
            let supervisor = app.state::<Arc<Supervisor>>();
            // Runtime plane first: it is the one that installs silently once
            // confirmed, and a replaced pack only takes effect on the next
            // backend start.
            let runtime = supervisor.confirm_and_install_runtime_update();
            // A plain thread, so blocking on the updater's async API is safe.
            let locale = supervisor.locale();
            let shell = tauri::async_runtime::block_on(
                tauri_plugin_deeptutor::check_shell_update_async(&app, locale.code()),
            );
            let report = UpdateReport { runtime, shell };
            let summary = format_update_report(&report, locale);
            supervisor.append_shell_log(&format!(
                "update check: runtime(checked={} updated={} {}) shell({} {})",
                report.runtime.checked,
                report.runtime.updated,
                report.runtime.detail,
                report.shell.status,
                report.shell.detail
            ));
            let _ = app.emit(
                "deeptutor://update-report",
                serde_json::to_value(&report).unwrap_or(serde_json::Value::Null),
            );
            if report.shell.status == "available" {
                ask_to_install_shell_update(&app, &supervisor, &report.shell, locale);
                return;
            }
            // Non-blocking: this thread has no window to own the dialog, and the
            // plugin dispatches it onto the main thread for us.
            app.dialog()
                .message(summary)
                .title("DeepTutor 更新")
                .show(|_| {});
        })
        .expect("failed to spawn the update-check thread");
}

/// Offer the shell update the check just found, and install it on a yes.
///
/// Runs on the update-check thread: the dialog plugin marshals the prompt onto
/// the main thread, while the download stays here so a 250 MB artifact cannot
/// freeze the window.
fn ask_to_install_shell_update<R: Runtime>(
    app: &AppHandle<R>,
    supervisor: &Arc<Supervisor>,
    shell: &ShellUpdateReport,
    locale: Locale,
) {
    let version = shell
        .available_version
        .clone()
        .unwrap_or_else(|| "?".to_string());
    let answer = app
        .dialog()
        .message(tr(
            locale,
            format!(
                "发现新版本 {version}（当前 {}）。\n\n下载并安装后需要重启应用。",
                shell.current_version
            ),
            format!(
                "Version {version} is available (current {}).\n\nDownloading and installing needs an app restart.",
                shell.current_version
            ),
        ))
        .title(tr(locale, "DeepTutor 更新", "DeepTutor update"))
        .buttons(MessageDialogButtons::OkCancelCustom(
            tr(locale, "下载并安装", "Download and install"),
            tr(locale, "稍后", "Later"),
        ))
        .blocking_show();
    if !answer {
        supervisor.append_shell_log("shell update declined by the user");
        return;
    }
    let code = supervisor.locale().code().to_string();
    match tauri::async_runtime::block_on(tauri_plugin_deeptutor::install_shell_update_async(
        app, &code,
    )) {
        Ok(result) => {
            supervisor.append_shell_log(&format!(
                "shell update installed: {} ({})",
                result.version.unwrap_or_else(|| "?".to_string()),
                result.detail
            ));
            // Take the local service down before the process is replaced, so the
            // new build starts from a clean slate instead of inheriting ports.
            supervisor.stop();
            app.restart();
        }
        Err(error) => {
            supervisor.append_shell_log(&format!("shell update failed: {error}"));
            app.dialog()
                .message(format!("外壳更新失败：{error}"))
                .title("DeepTutor 更新")
                .kind(MessageDialogKind::Error)
                .show(|_| {});
        }
    }
}

/// Human-readable form of [`UpdateReport`], also asserted in this module's
/// tests so the wording cannot drift from the fields.
fn format_update_report(report: &UpdateReport, locale: Locale) -> String {
    let pack = report
        .runtime
        .app_version
        .as_deref()
        .map(|version| {
            tr(
                locale,
                format!("（当前 {version}）"),
                format!(" (current {version})"),
            )
        })
        .unwrap_or_default();
    tr(
        locale,
        format!(
            "运行时：{}{pack}\n外壳：{}",
            report.runtime.detail, report.shell.detail
        ),
        format!(
            "Runtime: {}{pack}\nShell: {}",
            report.runtime.detail, report.shell.detail
        ),
    )
}

/// Ask the web UI to open one of its own routes.
fn navigate<R: Runtime>(app: &AppHandle<R>, route: &str) {
    if let Some(window) = app.get_webview_window(MAIN_WINDOW) {
        let _ = window.eval(format!(
            "window.location.assign({});",
            serde_json::to_string(route).unwrap_or_else(|_| "\"/\"".to_string())
        ));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tauri_plugin_deeptutor::{RuntimeUpdateReport, ShellUpdateReport};

    fn report(
        checked: bool,
        updated: bool,
        detail: &str,
        version: Option<&str>,
        shell_status: &str,
        shell_detail: &str,
    ) -> UpdateReport {
        UpdateReport {
            runtime: RuntimeUpdateReport {
                checked,
                source: Some("https://example.test/runtime-packs.json".to_string()),
                updated,
                error: None,
                active_pack: Some("deeptutor-runtime-1.6.11".to_string()),
                previous_pack: None,
                app_version: version.map(str::to_string),
                detail: detail.to_string(),
            },
            shell: ShellUpdateReport {
                status: shell_status.to_string(),
                detail: shell_detail.to_string(),
                available_version: (shell_status == "available").then(|| "1.6.12".to_string()),
                current_version: "1.6.11".to_string(),
            },
        }
    }

    #[test]
    fn the_summary_names_both_update_planes() {
        let report = report(
            true,
            false,
            "运行时包已是最新",
            Some("1.6.11"),
            "up_to_date",
            "外壳已是最新（1.6.11）",
        );
        let text = format_update_report(&report, Locale::Zh);
        assert!(text.contains("运行时包已是最新"));
        assert!(text.contains("1.6.11"));
        assert!(text.contains("外壳：外壳已是最新"));
        // The same fields, in the other language: the shell must not leave a
        // user with a half-translated line.
        let english = format_update_report(&report, Locale::En);
        assert!(english.contains("Runtime: "), "{english}");
        assert!(english.contains("(current 1.6.11)"), "{english}");
        assert!(english.contains("Shell: "), "{english}");
    }

    #[test]
    fn an_unconfigured_runtime_source_says_what_to_configure() {
        let text = format_update_report(
            &report(
                false,
                false,
                "未配置运行时更新源：在 desktop/shell.json 写入 pack_catalog，或设置 DEEPTUTOR_DESKTOP_PACK_CATALOG。",
                None,
                "up_to_date",
                "外壳已是最新（1.6.11）",
            ),
            Locale::Zh,
        );
        assert!(text.contains("未配置运行时更新源"));
        assert!(text.contains("DEEPTUTOR_DESKTOP_PACK_CATALOG"));
    }

    #[test]
    fn an_available_shell_update_is_named_in_the_summary() {
        let text = format_update_report(
            &report(
                true,
                false,
                "运行时包已是最新",
                Some("1.6.11"),
                "available",
                "有新版本 1.6.12 可用（当前 1.6.11）",
            ),
            Locale::Zh,
        );
        assert!(text.contains("1.6.12"));
    }
}
