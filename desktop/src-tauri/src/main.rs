//! DeepTutor desktop shell.
//!
//! A supervisor thread owns the Python launcher, the window is handed over to
//! the loopback UI once the launcher reports ready, every command the UI may
//! call lives in `tauri-plugin-deeptutor` (Tauri's ACL only grants *plugin*
//! commands to a remote origin), and the interpreter comes from a runtime pack
//! when one is installed.
//!
//! Headless modes (no window) exist for installers, CI and debugging:
//! `--self-check`, `--pack-status`, `--install-pack <file|url>`, `--rollback-pack`.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod app;
mod deeplink;
mod handoff;
mod notify;
mod pack_tree;
mod runtime_info;
mod runtime_pack;
mod settings;
mod strings;
mod supervisor;
mod window;

use std::path::PathBuf;
use std::sync::Arc;

use tauri::{Manager, RunEvent, WindowEvent};
use tauri_plugin_deep_link::DeepLinkExt;
use tauri_plugin_deeptutor::DesktopBackend;

use runtime_pack::{InstalledPack, PackInstaller};
use supervisor::{ShellConfig, Supervisor};

/// Everything a CI run, an installer script or a debugging session needs,
/// without opening a window.
enum Headless {
    SelfCheck {
        require_python: bool,
    },
    /// First-run state, as the wizard would read it.
    FirstRunStatus,
    /// Answer the wizard from a script (installers, CI, support).
    CompleteFirstRun {
        locale: String,
        data_dir: Option<String>,
        close_to_tray: bool,
        notifications: bool,
    },
    ShellSettings,
    CheckUpdates {
        catalog: Option<String>,
    },
    PackStatus,
    PackCatalog {
        source: String,
    },
    InstallPack {
        source: String,
        sha256: Option<String>,
    },
    /// Apply an incremental runtime update on top of the active pack.
    ApplyDelta {
        source: String,
        sha256: Option<String>,
    },
    UpdatePack {
        source: String,
    },
    /// Download and verify the newest shell build without installing it.
    VerifyShellUpdate,
    /// Install the newest shell build in place. Used by verification scripts and
    /// by a support "update this machine now" runbook; the GUI asks first.
    InstallShellUpdate,
    /// Print a pack tree's fingerprint (see `pack_tree::tree_digest`), optionally
    /// tokenising extra roots that an earlier build directory left behind.
    PackFingerprint {
        directory: PathBuf,
        stale_roots: Vec<String>,
    },
    RollbackPack,
}

fn headless_mode(args: &[String]) -> Option<Headless> {
    let flag = |name: &str| args.iter().any(|arg| arg == name);
    let value = |name: &str| {
        args.iter()
            .position(|arg| arg == name)
            .and_then(|index| args.get(index + 1))
            .cloned()
    };
    if flag("--self-check") {
        return Some(Headless::SelfCheck {
            require_python: flag("--require-python"),
        });
    }
    if flag("--first-run-status") {
        return Some(Headless::FirstRunStatus);
    }
    if flag("--shell-settings") {
        return Some(Headless::ShellSettings);
    }
    if flag("--complete-first-run") {
        return Some(Headless::CompleteFirstRun {
            locale: value("--locale").unwrap_or_else(|| "zh-CN".to_string()),
            data_dir: value("--data-dir"),
            close_to_tray: !flag("--no-close-to-tray"),
            notifications: !flag("--no-notifications"),
        });
    }
    if flag("--check-updates") {
        return Some(Headless::CheckUpdates {
            catalog: value("--catalog"),
        });
    }
    if flag("--verify-shell-update") {
        return Some(Headless::VerifyShellUpdate);
    }
    if flag("--install-shell-update") {
        return Some(Headless::InstallShellUpdate);
    }
    if let Some(directory) = value("--pack-fingerprint") {
        let stale_roots = args
            .iter()
            .enumerate()
            .filter(|(_, arg)| arg.as_str() == "--stale-root")
            .filter_map(|(index, _)| args.get(index + 1).cloned())
            .collect();
        return Some(Headless::PackFingerprint {
            directory: PathBuf::from(directory),
            stale_roots,
        });
    }
    if flag("--pack-status") {
        return Some(Headless::PackStatus);
    }
    if let Some(source) = value("--pack-catalog") {
        return Some(Headless::PackCatalog { source });
    }
    if flag("--update-pack") {
        return Some(Headless::UpdatePack {
            source: value("--catalog").unwrap_or_default(),
        });
    }
    if flag("--rollback-pack") {
        return Some(Headless::RollbackPack);
    }
    if let Some(source) = value("--apply-delta") {
        return Some(Headless::ApplyDelta {
            source,
            sha256: value("--sha256"),
        });
    }
    value("--install-pack").map(|source| Headless::InstallPack {
        source,
        sha256: value("--sha256"),
    })
}

fn print_json(value: &serde_json::Value) {
    println!(
        "{}",
        serde_json::to_string_pretty(value).unwrap_or_else(|_| "{}".to_string())
    );
}

/// The Tauri context, from a single `generate_context!()` expansion.
///
/// The macro embeds static resources (the Info.plist among them), so expanding
/// it twice in one binary is a duplicate-symbol link error. Both the windowed
/// entry point and the headless gates go through here.
fn tauri_context() -> tauri::Context {
    tauri::generate_context!()
}

/// A Tauri app with no window, built only so headless gates can reach the
/// plugin-native APIs (the updater channel in particular).
///
/// The event loop is never run: `Builder::build` returns as soon as the plugins
/// are set up, which is all `AppHandle::updater()` needs.
fn headless_app() -> Option<tauri::App> {
    tauri::Builder::default()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .build(tauri_context())
        .map_err(|error| eprintln!("headless app build failed: {error}"))
        .ok()
}

/// The language the headless gates write their messages in.
fn shell_locale(config: &ShellConfig) -> strings::Locale {
    let setting = settings::ShellSettings::load(&config.home).locale;
    strings::Locale::resolve(&setting, &supervisor::default_locale())
}

/// The shell plane of the update check, for headless runs.
fn headless_shell_update_report(
    locale: &strings::Locale,
) -> tauri_plugin_deeptutor::ShellUpdateReport {
    match headless_app() {
        Some(app) => tauri::async_runtime::block_on(
            tauri_plugin_deeptutor::check_shell_update_async(app.handle(), locale.code()),
        ),
        None => tauri_plugin_deeptutor::ShellUpdateReport {
            status: "error".to_string(),
            detail: strings::tr(
                *locale,
                "无法初始化更新通道（无窗口应用构建失败）",
                "Could not initialise the update channel (the headless app failed to build)",
            ),
            available_version: None,
            current_version: env!("CARGO_PKG_VERSION").to_string(),
        },
    }
}

fn pack_summary(pack: &InstalledPack) -> serde_json::Value {
    serde_json::json!({
        "pack_id": pack.pack_id,
        "dir": pack.dir,
        "app_version": pack.manifest.app_version,
        "platform": pack.manifest.platform,
        "python": pack.manifest.python_path(&pack.dir),
        "node_dir": pack.manifest.node_dir(&pack.dir),
    })
}

fn run_headless(mode: Headless) -> i32 {
    let config = ShellConfig::resolve();
    match mode {
        Headless::PackFingerprint {
            directory,
            stale_roots,
        } => match pack_tree::tree_digest(&directory, &stale_roots) {
            Ok(digest) => {
                print_json(&serde_json::json!({
                    "shell": "deeptutor-desktop",
                    "mode": "pack-fingerprint",
                    "directory": directory,
                    "stale_roots": stale_roots,
                    "sha256": digest.sha256,
                    "files": digest.files,
                    "bytes": digest.bytes,
                }));
                0
            }
            Err(error) => {
                eprintln!("无法计算指纹: {error}");
                1
            }
        },

        Headless::ShellSettings => {
            let supervisor = Supervisor::new_shared(config);
            print_json(
                &serde_json::to_value(supervisor.shell_settings())
                    .unwrap_or(serde_json::Value::Null),
            );
            0
        }

        Headless::FirstRunStatus => {
            let supervisor = Supervisor::new_shared(config);
            let state = supervisor.first_run_state();
            print_json(&serde_json::json!({
                "shell": "deeptutor-desktop",
                "mode": "first-run-status",
                "settings": supervisor.shell_settings(),
                "first_run": {
                    "completed": state.completed,
                    "locale": state.locale,
                    "default_locale": state.default_locale,
                    "close_to_tray": state.close_to_tray,
                    "notifications": state.notifications,
                    "home": state.home,
                    "default_home": state.default_home,
                    "can_change_data_dir": state.can_change_data_dir,
                },
            }));
            0
        }

        Headless::CompleteFirstRun {
            locale,
            data_dir,
            close_to_tray,
            notifications,
        } => {
            let supervisor = Supervisor::new_shared(config);
            match supervisor.apply_first_run(tauri_plugin_deeptutor::FirstRunChoices {
                locale,
                data_dir,
                close_to_tray,
                notifications,
            }) {
                Ok(outcome) => {
                    print_json(&serde_json::json!({
                        "shell": "deeptutor-desktop",
                        "mode": "complete-first-run",
                        "restart_required": outcome.restart_required,
                        "settings": outcome.settings,
                    }));
                    0
                }
                Err(error) => {
                    eprintln!("首次设置写入失败: {error}");
                    1
                }
            }
        }

        Headless::CheckUpdates { catalog } => {
            // The check reads its source from the settings or this env var, and a
            // headless run must not rewrite the user's settings just to look.
            if let Some(catalog) = catalog {
                std::env::set_var("DEEPTUTOR_DESKTOP_PACK_CATALOG", catalog);
            }
            let locale = shell_locale(&config);
            let supervisor = Supervisor::new_shared(config);
            // Read-only on purpose: this gate must never download a pack, and
            // it must never restart a service from a process about to exit.
            let runtime = supervisor.preview_runtime_updates(None);
            let shell = headless_shell_update_report(&locale);
            let failed = runtime.error.is_some() || shell.status == "error";
            print_json(&serde_json::json!({
                "shell": "deeptutor-desktop",
                "mode": "check-updates",
                "runtime": runtime,
                "shell_update": shell,
            }));
            i32::from(failed)
        }

        Headless::VerifyShellUpdate => {
            // Release verification: fetch the published artifact and check its
            // signature against the committed public key, without installing.
            let Some(app) = headless_app() else {
                eprintln!("无法初始化更新通道（无窗口应用构建失败）");
                return 1;
            };
            let locale = shell_locale(&config);
            match tauri::async_runtime::block_on(
                tauri_plugin_deeptutor::verify_shell_update_download(app.handle(), locale.code()),
            ) {
                Ok(result) => {
                    print_json(&serde_json::json!({
                        "shell": "deeptutor-desktop",
                        "mode": "verify-shell-update",
                        "installed": result.installed,
                        "version": result.version,
                        "detail": result.detail,
                    }));
                    0
                }
                Err(error) => {
                    eprintln!("外壳更新校验失败: {error}");
                    1
                }
            }
        }

        Headless::InstallShellUpdate => {
            let Some(app) = headless_app() else {
                eprintln!("无法初始化更新通道（无窗口应用构建失败）");
                return 1;
            };
            let locale = shell_locale(&config);
            match tauri::async_runtime::block_on(
                tauri_plugin_deeptutor::install_shell_update_async(app.handle(), locale.code()),
            ) {
                Ok(result) => {
                    print_json(&serde_json::json!({
                        "shell": "deeptutor-desktop",
                        "mode": "install-shell-update",
                        "installed": result.installed,
                        "version": result.version,
                        "detail": result.detail,
                    }));
                    0
                }
                Err(error) => {
                    eprintln!("安装外壳更新失败: {error}");
                    1
                }
            }
        }

        Headless::SelfCheck { require_python } => {
            let candidates: Vec<serde_json::Value> = config
                .interpreter_candidates()
                .into_iter()
                .map(|candidate| {
                    serde_json::json!({
                        "path": candidate.path,
                        "source": candidate.source,
                        "exists": candidate.path.exists(),
                    })
                })
                .collect();
            let resolved = config.resolve_interpreter();
            let python_ok = resolved.is_ok();
            print_json(&serde_json::json!({
                "shell": "deeptutor-desktop",
                "mode": "self-check",
                "home": config.home,
                "workdir": config.workdir,
                "state_path": config.state_path,
                "logs_dir": config.logs_dir,
                "active_pack": config.active_pack().map(|pack| pack.pack_id),
                "shell_settings": Supervisor::new_shared(config.clone()).shell_settings(),
                "python": resolved
                    .as_ref()
                    .ok()
                    .map(|candidate| candidate.path.to_string_lossy().into_owned()),
                "python_source": resolved.as_ref().ok().map(|candidate| candidate.source),
                "python_ok": python_ok,
                "python_error": resolved.as_ref().err(),
                "python_candidates": candidates,
                "remote_ipc_probe": config.probe_remote_ipc,
                "catalog_pubkey_configured": config.catalog_pubkey.is_some(),
            }));
            // `--require-python` turns the diagnostic into a gate.
            i32::from(!python_ok && require_python)
        }

        Headless::PackStatus => {
            let installer =
                PackInstaller::new(&config.home).with_catalog_pubkey(config.catalog_pubkey.clone());
            let state = installer.state();
            let installed: Vec<serde_json::Value> = installer
                .installed()
                .iter()
                .filter_map(|pack_id| installer.load(pack_id).ok())
                .map(|pack| pack_summary(&pack))
                .collect();
            print_json(&serde_json::json!({
                "shell": "deeptutor-desktop",
                "mode": "pack-status",
                "home": config.home,
                "platform": runtime_pack::host_platform(),
                "active_pack": state.active_pack,
                "previous_pack": state.previous_pack,
                "installed": installed,
            }));
            0
        }

        Headless::PackCatalog { source } => {
            let installer =
                PackInstaller::new(&config.home).with_catalog_pubkey(config.catalog_pubkey.clone());
            match installer.catalog(&source) {
                Ok(catalog) => {
                    let host = runtime_pack::host_platform();
                    let available: Vec<serde_json::Value> = catalog
                        .packs
                        .iter()
                        .filter(|release| release.platform == host)
                        .map(|release| {
                            serde_json::json!({
                                "pack_id": release.pack_id,
                                "app_version": release.app_version,
                                "url": release.url,
                                "size": release.size,
                            })
                        })
                        .collect();
                    print_json(&serde_json::json!({
                        "shell": "deeptutor-desktop",
                        "mode": "pack-catalog",
                        "source": source,
                        "platform": host,
                        "active_pack": installer.state().active_pack,
                        "available": available,
                    }));
                    0
                }
                Err(error) => {
                    eprintln!("读取运行时包清单失败: {error}");
                    1
                }
            }
        }

        Headless::UpdatePack { source } => {
            if source.is_empty() {
                eprintln!("--update-pack 需要 --catalog <url|path>");
                return 2;
            }
            let installer =
                PackInstaller::new(&config.home).with_catalog_pubkey(config.catalog_pubkey.clone());
            match installer.update_from_catalog(&source) {
                Ok(Some(pack)) => {
                    let state = installer.state();
                    print_json(&serde_json::json!({
                        "shell": "deeptutor-desktop",
                        "mode": "update-pack",
                        "updated": true,
                        "active_pack": state.active_pack,
                        "previous_pack": state.previous_pack,
                        "pack": pack_summary(&pack),
                    }));
                    0
                }
                Ok(None) => {
                    print_json(&serde_json::json!({
                        "shell": "deeptutor-desktop",
                        "mode": "update-pack",
                        "updated": false,
                        "active_pack": installer.state().active_pack,
                    }));
                    0
                }
                Err(error) => {
                    eprintln!("更新运行时包失败: {error}");
                    1
                }
            }
        }

        Headless::InstallPack { source, sha256 } => {
            let installer =
                PackInstaller::new(&config.home).with_catalog_pubkey(config.catalog_pubkey.clone());
            let result = if source.starts_with("http://") || source.starts_with("https://") {
                match sha256.as_deref() {
                    Some(expected) => installer.install_from_url(&source, expected, None),
                    None => Err("从 URL 安装必须提供 --sha256".to_string()),
                }
            } else {
                installer.install_archive(std::path::Path::new(&source), sha256.as_deref())
            };
            match result {
                Ok(pack) => {
                    print_json(&serde_json::json!({
                        "shell": "deeptutor-desktop",
                        "mode": "install-pack",
                        "home": config.home,
                        "installed": pack_summary(&pack),
                        "active_pack": installer.state().active_pack,
                    }));
                    0
                }
                Err(error) => {
                    eprintln!("安装运行时包失败: {error}");
                    1
                }
            }
        }

        Headless::RollbackPack => {
            let installer =
                PackInstaller::new(&config.home).with_catalog_pubkey(config.catalog_pubkey.clone());
            match installer.rollback() {
                Ok(pack) => {
                    print_json(&serde_json::json!({
                        "shell": "deeptutor-desktop",
                        "mode": "rollback-pack",
                        "active_pack": installer.state().active_pack,
                        "rolled_back_to": pack_summary(&pack),
                    }));
                    0
                }
                Err(error) => {
                    eprintln!("回滚失败: {error}");
                    1
                }
            }
        }

        Headless::ApplyDelta { source, sha256 } => {
            let installer =
                PackInstaller::new(&config.home).with_catalog_pubkey(config.catalog_pubkey.clone());
            let result = if source.starts_with("http://") || source.starts_with("https://") {
                match sha256.as_deref() {
                    Some(expected) => installer.install_delta_from_url(&source, expected, None),
                    None => Err("从 URL 应用增量必须提供 --sha256".to_string()),
                }
            } else {
                installer.install_delta_archive(std::path::Path::new(&source), sha256.as_deref())
            };
            match result {
                Ok(pack) => {
                    print_json(&serde_json::json!({
                        "shell": "deeptutor-desktop",
                        "mode": "apply-delta",
                        "home": config.home,
                        "installed": pack_summary(&pack),
                        "active_pack": installer.state().active_pack,
                        "previous_pack": installer.state().previous_pack,
                    }));
                    0
                }
                Err(error) => {
                    eprintln!("应用增量失败: {error}");
                    1
                }
            }
        }
    }
}

/// Flags that exist only to fill in an environment variable `ShellConfig` reads.
///
/// Done before anything resolves its config, so they work for the headless
/// gates as well as for a windowed run.
fn apply_env_flags(args: &[String]) {
    if args.iter().any(|arg| arg == "--remote-ipc-probe") {
        // The loopback IPC self-test is diagnostic and off by default; this flag
        // is how a support run turns it on.
        std::env::set_var("DEEPTUTOR_DESKTOP_PROBE", "1");
    }
    if let Some(index) = args.iter().position(|arg| arg == "--catalog-pubkey") {
        if let Some(value) = args.get(index + 1) {
            std::env::set_var("DEEPTUTOR_DESKTOP_PACK_CATALOG_PUBKEY", value);
        }
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    apply_env_flags(&args);
    if let Some(mode) = headless_mode(&args) {
        std::process::exit(run_headless(mode));
    }

    let config = ShellConfig::resolve();
    let supervisor = Supervisor::new_shared(config);
    let backend: Arc<dyn DesktopBackend> = supervisor.clone();

    tauri::Builder::default()
        // Single instance is registered first: it decides whether this process
        // is the one that owns the app or just focuses the existing window.
        .plugin(tauri_plugin_single_instance::init(|app, argv, _cwd| {
            // On Windows/Linux a second launch is how a deep link or a file
            // association reaches the running app, so the arguments are part of
            // the hand-off rather than noise.
            let supervisor = app.state::<Arc<Supervisor>>();
            supervisor.push_open_args(argv, "argv");
            app::reveal(app);
        }))
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_deep_link::init())
        // Shell self-update. The commands the UI calls live in the deeptutor
        // plugin (which owns both update planes); this registers the native
        // implementation and reads `plugins.updater` from tauri.conf.json.
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_deeptutor::init(backend))
        .setup({
            let supervisor = Arc::clone(&supervisor);
            move |app| {
                app.manage(Arc::clone(&supervisor));
                let handle = app.handle().clone();
                supervisor.attach_app(handle.clone());
                // Phase 3: `deeptutor://` links and file associations. The
                // plugin turns macOS's `RunEvent::Opened` into this event, and
                // a cold start can itself be one (the OS launched us *because*
                // a PDF was double-clicked), so the launch arguments are drained
                // as well.
                {
                    let supervisor = Arc::clone(&supervisor);
                    app.deep_link().on_open_url(move |event| {
                        let urls = event.urls();
                        supervisor.push_open_urls(urls.iter(), "deep-link");
                    });
                }
                if let Ok(Some(urls)) = app.deep_link().get_current() {
                    supervisor.push_open_urls(urls.iter(), "deep-link");
                }
                supervisor.push_open_args(std::env::args().collect::<Vec<_>>(), "argv");
                app::install_menu(&handle)?;
                app::install_tray(&handle)?;
                let window = window::create_main_window(app)?;
                supervisor.attach_window(window);
                app.on_menu_event(|handle, event| {
                    app::on_menu_event(handle, event.id().as_ref());
                });
                supervisor.start();
                Ok(())
            }
        })
        .build(tauri_context())
        .expect("failed to build the DeepTutor desktop shell")
        .run(|app_handle, event| match event {
            RunEvent::Exit => {
                // The launcher also watches this PID, but a normal quit can
                // stop its two children immediately instead of within 2s.
                app_handle.state::<Arc<Supervisor>>().stop();
            }
            // Close-window policy: hide to the tray (the default) or really
            // quit. The window is never actually destroyed, because the tray
            // could not bring it back.
            RunEvent::WindowEvent {
                label,
                event: WindowEvent::CloseRequested { api, .. },
                ..
            } => {
                if label != window::MAIN_WINDOW {
                    return;
                }
                let supervisor = app_handle.state::<Arc<Supervisor>>();
                api.prevent_close();
                if supervisor.shell_settings().close_to_tray {
                    if let Some(window) = app_handle.get_webview_window(&label) {
                        let _ = window.hide();
                    }
                    supervisor.append_shell_log("window hidden to tray");
                } else {
                    supervisor.stop();
                    app_handle.exit(0);
                }
            }
            // Clicking the Dock icon (or the app being activated with nothing in
            // front) is also the moment a notification's "come back to this
            // session" hand-off can be delivered.
            #[cfg(target_os = "macos")]
            RunEvent::Reopen { .. } => app::reveal(app_handle),
            _ => {}
        });
}
