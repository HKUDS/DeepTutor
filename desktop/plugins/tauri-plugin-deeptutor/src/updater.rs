//! The **shell** update plane: the running `.app` / installer itself.
//!
//! The desktop app updates in two independent planes (see
//! `docs-for-user/DESKTOP_TAURI_PLAN.md` §决策 4):
//!
//! * the **runtime pack** — Python, Node and the web bundle, checked and
//!   installed by the shell crate (`--update-pack`, `check_updates`);
//! * the **shell** — this window, its menus and its native plugins, which is
//!   what `tauri-plugin-updater` handles here.
//!
//! Keeping both in one place is what lets the UI show a single honest answer:
//! "runtime is up to date, shell has 1.6.11 available" instead of two
//! half-truths.

use serde::Serialize;
use tauri::{AppHandle, Runtime};
use tauri_plugin_updater::UpdaterExt as _;

use crate::{tr, ShellUpdateReport};

/// Outcome of an attempted shell install.
#[derive(Debug, Clone, Serialize)]
pub struct ShellUpdateInstall {
    pub installed: bool,
    /// Version that was installed, when one was.
    pub version: Option<String>,
    pub detail: String,
}

/// Ask the update channel what it has, without downloading anything.
///
/// Never fails: a broken channel is a *report*, not an error the caller has to
/// handle — the settings page shows the difference between "up to date" and
/// "cannot reach the channel" either way.
pub async fn check<R: Runtime>(app: &AppHandle<R>, locale: &str) -> ShellUpdateReport {
    let current_version = app.package_info().version.to_string();
    let updater = match app.updater() {
        Ok(updater) => updater,
        Err(error) => {
            return ShellUpdateReport {
                status: "error".to_string(),
                detail: tr(
                    locale,
                    format!("更新通道不可用：{error}"),
                    format!("The update channel is unavailable: {error}"),
                ),
                available_version: None,
                current_version,
            }
        }
    };
    match updater.check().await {
        Ok(Some(update)) => ShellUpdateReport {
            status: "available".to_string(),
            detail: tr(
                locale,
                format!(
                    "有新版本 {} 可用（当前 {}）",
                    update.version, update.current_version
                ),
                format!(
                    "Version {} is available (current {})",
                    update.version, update.current_version
                ),
            ),
            available_version: Some(update.version.clone()),
            current_version: update.current_version.clone(),
        },
        Ok(None) => ShellUpdateReport {
            status: "up_to_date".to_string(),
            detail: tr(
                locale,
                format!("外壳已是最新（{current_version}）"),
                format!("The shell is up to date ({current_version})"),
            ),
            available_version: None,
            current_version,
        },
        Err(error) => ShellUpdateReport {
            status: "error".to_string(),
            detail: tr(
                locale,
                format!("检查外壳更新失败：{error}"),
                format!("Could not check for shell updates: {error}"),
            ),
            available_version: None,
            current_version,
        },
    }
}

/// Download, verify and install the newest shell build.
///
/// The signature is checked inside the plugin's `download` (a mismatched
/// artifact never reaches `install`), so reaching the install step already
/// means the bytes came from whoever holds the updater private key.
pub async fn install<R: Runtime>(
    app: &AppHandle<R>,
    locale: &str,
) -> Result<ShellUpdateInstall, String> {
    let updater = app.updater().map_err(|error| {
        tr(
            locale,
            format!("更新通道不可用：{error}"),
            format!("The update channel is unavailable: {error}"),
        )
    })?;
    let update = updater
        .check()
        .await
        .map_err(|error| {
            tr(
                locale,
                format!("检查外壳更新失败：{error}"),
                format!("Could not check for shell updates: {error}"),
            )
        })?
        .ok_or_else(|| {
            tr(
                locale,
                "外壳已经是最新版本",
                "The shell is already up to date",
            )
        })?;

    let version = update.version.clone();
    let mut downloaded = 0usize;
    update
        .download_and_install(
            |chunk, total| {
                downloaded += chunk;
                // One line per ~16 MB: enough to see progress in shell.log
                // without turning an update into thousands of log lines.
                if downloaded % (16 * 1024 * 1024) < chunk {
                    match total {
                        Some(total) => eprintln!(
                            "shell update: {} / {} MB",
                            downloaded / (1024 * 1024),
                            total / (1024 * 1024)
                        ),
                        None => eprintln!("shell update: {} MB", downloaded / (1024 * 1024)),
                    }
                }
            },
            || {},
        )
        .await
        .map_err(|error| {
            tr(
                locale,
                format!("安装外壳更新失败：{error}"),
                format!("Installing the shell update failed: {error}"),
            )
        })?;

    Ok(ShellUpdateInstall {
        installed: true,
        version: Some(version.clone()),
        detail: tr(
            locale,
            format!("已安装 {version}，重启应用后生效"),
            format!("Installed {version}; it takes effect after a restart"),
        ),
    })
}

/// Download and verify the newest shell build **without installing it**.
///
/// Exists for release verification: a published artifact whose signature does
/// not match the committed public key is a bricked update channel, and this
/// catches it before any user does.
pub async fn verify_download<R: Runtime>(
    app: &AppHandle<R>,
    locale: &str,
) -> Result<ShellUpdateInstall, String> {
    let updater = app
        .updater()
        .map_err(|error| format!("更新通道不可用：{error}"))?;
    let update = updater
        .check()
        .await
        .map_err(|error| format!("检查外壳更新失败：{error}"))?
        .ok_or_else(|| "外壳已经是最新版本".to_string())?;
    let version = update.version.clone();
    let bytes = update.download(|_, _| {}, || {}).await.map_err(|error| {
        tr(
            locale,
            format!("下载或校验外壳更新失败：{error}"),
            format!("Downloading or verifying the shell update failed: {error}"),
        )
    })?;
    Ok(ShellUpdateInstall {
        installed: false,
        version: Some(version.clone()),
        detail: tr(
            locale,
            format!(
                "已下载并校验 {version}（{} MB，未安装）",
                bytes.len() / (1024 * 1024)
            ),
            format!(
                "Downloaded and verified {version} ({} MB, not installed)",
                bytes.len() / (1024 * 1024)
            ),
        ),
    })
}
