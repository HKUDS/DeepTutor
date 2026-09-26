//! Owns the Python launcher and hands the window over to it when ready.
//!
//! Deliberately thin: port selection, settings persistence, the frontend build
//! and the update handshake all stay in `deeptutor/runtime/launcher.py` so the
//! desktop path cannot drift from CLI/Web behaviour. This module only does what
//! the shell alone can do — spawn, watch, restart, navigate, clean up.

use std::fs::{self, OpenOptions};
use std::io::Write as _;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, OnceLock, Weak};
use std::time::{Duration, Instant};

use tauri::{AppHandle, WebviewWindow};
use tauri_plugin_deeptutor::{
    DesktopBackend, DesktopStatus, FirstRunChoices, FirstRunOutcome, FirstRunState,
    NotificationOutcome, NotificationRequest, NotificationTarget, OpenRequestPayload,
    RuntimeSnapshot, RuntimeUpdateReport, SettingsPatch, ShellSettingsSnapshot, StartupTimings,
    WindowGeometry,
};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_notification::NotificationExt;

use crate::handoff::OpenQueue;
use crate::notify::NotificationCenter;
use crate::runtime_info::{RuntimeInfo, SUPPORTED_SCHEMA_VERSION};
use crate::runtime_pack::{InstalledPack, PackInstaller, PackRelease};
use crate::settings::{Bootstrap, ShellSettings};
use crate::strings::{tr, tr_code, Locale};

/// The launcher can spend minutes on a first production frontend build; this
/// timeout only exists so a wedged child does not leave a splash forever.
const READY_TIMEOUT: Duration = Duration::from_secs(300);
const POLL_INTERVAL: Duration = Duration::from_millis(250);
const TERM_GRACE: Duration = Duration::from_secs(5);
/// Crash restarts before the shell stops retrying and reports the failure.
const MAX_CRASH_RESTARTS: u32 = 3;
const CRASH_BACKOFF_BASE: Duration = Duration::from_secs(2);

#[derive(Debug, Clone)]
pub struct ShellConfig {
    /// Runtime home: owns `data/`, `desktop/` and (Phase 2) `runtimes/`.
    pub home: PathBuf,
    /// The platform default home, i.e. where `bootstrap.json` is looked for.
    /// Different from `home` once the first-run wizard moves the data directory.
    pub default_home: PathBuf,
    /// Working directory for the launcher: the checkout in Phase 0/1, the
    /// runtime pack afterwards.
    pub workdir: PathBuf,
    /// Explicit interpreter from `DEEPTUTOR_DESKTOP_PYTHON`, when set.
    pub python_override: Option<PathBuf>,
    pub state_path: PathBuf,
    pub logs_dir: PathBuf,
    /// Run the loopback IPC self-test once the window is handed over.
    ///
    /// Off by default: the probe exists to prove Tauri's remote-origin ACL still
    /// reaches the shell, and leaving it on in a shipped build means every
    /// launch evals a script into the live UI and (when the restart leg existed)
    /// bounced the local service seconds after the user saw it. `--remote-ipc-probe`
    /// or `DEEPTUTOR_DESKTOP_PROBE=1` turns it on for a diagnostic run.
    pub probe_remote_ipc: bool,
    /// minisign public key for the runtime-pack catalog, from the environment.
    ///
    /// The windowed shell prefers the updater key from `tauri.conf.json` when
    /// this is unset (see `Supervisor::catalog_pubkey`); the headless gates have
    /// no app handle and use this.
    pub catalog_pubkey: Option<String>,
}

impl ShellConfig {
    pub fn resolve() -> Self {
        Self::resolve_full(&|key| std::env::var(key).ok(), &Bootstrap::read_home)
    }

    /// Same as [`ShellConfig::resolve`] with an injectable environment read, so
    /// the resolution rules can be tested without touching the real machine or a
    /// real bootstrap file.
    #[cfg(test)]
    pub fn resolve_with(read_env: &dyn Fn(&str) -> Option<String>) -> Self {
        Self::resolve_full(read_env, &|_| None)
    }

    /// Full form: environment *and* the bootstrap pointer are injectable.
    pub fn resolve_full(
        read_env: &dyn Fn(&str) -> Option<String>,
        read_bootstrap: &dyn Fn(&Path) -> Option<PathBuf>,
    ) -> Self {
        let env = |key: &str| env_path_from(read_env(key));
        let default_home = resolve_home_with(&env);
        // A bootstrap pointer only ever *redirects* the default home; the
        // pointer itself is always read from the default location, so a broken
        // pointer cannot compound into a second profile.
        let home = read_bootstrap(&default_home).unwrap_or_else(|| default_home.clone());
        let workdir = env("DEEPTUTOR_DESKTOP_WORKDIR").unwrap_or_else(|| home.clone());
        Self {
            state_path: home.join("desktop").join("runtime.json"),
            logs_dir: home.join("desktop").join("logs"),
            python_override: env("DEEPTUTOR_DESKTOP_PYTHON"),
            probe_remote_ipc: env_flag(read_env, "DEEPTUTOR_DESKTOP_PROBE"),
            catalog_pubkey: read_env("DEEPTUTOR_DESKTOP_PACK_CATALOG_PUBKEY")
                .map(|value| value.trim().to_string())
                .filter(|value| !value.is_empty()),
            default_home,
            home,
            workdir,
        }
    }

    /// Interpreters to try, most specific first.
    ///
    /// The workdir venv matters: someone who simply runs the shell from a
    /// checkout has a `.venv` next to the source, not inside the app-data home.
    /// Phase 0 shipped without that candidate, so the shell fell through to the
    /// system Python and reported a bare "exit code 1".
    pub fn interpreter_candidates(&self) -> Vec<InterpreterCandidate> {
        let mut candidates = Vec::new();
        if let Some(explicit) = self.python_override.clone() {
            candidates.push(InterpreterCandidate {
                path: explicit,
                source: "DEEPTUTOR_DESKTOP_PYTHON",
                must_exist: true,
            });
        }
        // A runtime pack is the installed-product path: it needs no environment
        // variables at all, which is the whole point of Phase 2.
        if let Some(pack) = self.active_pack() {
            candidates.push(InterpreterCandidate {
                path: pack.manifest.python_path(&pack.dir),
                source: "runtime pack",
                must_exist: true,
            });
        }
        candidates.push(InterpreterCandidate {
            path: venv_python(&self.home),
            source: "<home>/.venv",
            must_exist: true,
        });
        if self.workdir != self.home {
            candidates.push(InterpreterCandidate {
                path: venv_python(&self.workdir),
                source: "<workdir>/.venv",
                must_exist: true,
            });
        }
        for name in path_python_names() {
            candidates.push(InterpreterCandidate {
                path: PathBuf::from(name),
                source: "PATH",
                must_exist: false,
            });
        }
        candidates
    }

    /// The runtime pack the shell was told to use, if any.
    pub fn active_pack(&self) -> Option<InstalledPack> {
        PackInstaller::new(&self.home).active()
    }

    /// First candidate that can actually import the launcher.
    ///
    /// Probing costs a few hundred milliseconds and buys a failure message a
    /// user can act on, instead of a launcher that exits 1 for reasons the
    /// dialog never mentions.
    pub fn resolve_interpreter(&self) -> Result<InterpreterCandidate, String> {
        let mut tried: Vec<String> = Vec::new();
        for candidate in self.interpreter_candidates() {
            if candidate.must_exist && !candidate.path.exists() {
                tried.push(format!("{} — 不存在", candidate.path.display()));
                continue;
            }
            if probe_interpreter(&candidate.path) {
                return Ok(candidate);
            }
            tried.push(format!(
                "{} — 无法导入 deeptutor_cli",
                candidate.path.display()
            ));
        }
        Err(format!(
            "找不到可用的 DeepTutor 运行环境。已尝试：\n{}\n\n\
             修复方式（任选其一）：\n\
             1) 在仓库根目录创建虚拟环境：uv venv && uv pip install -e \".[cli,server]\"\n\
             2) 设置 DEEPTUTOR_DESKTOP_PYTHON 指向可用的解释器\n\
             3) 运行 `deeptutor-desktop --self-check` 查看解析结果",
            tried.join("\n")
        ))
    }
}

/// One interpreter candidate plus where it came from, for diagnostics.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InterpreterCandidate {
    pub path: PathBuf,
    pub source: &'static str,
    /// PATH lookups cannot be pre-checked; venv paths can.
    pub must_exist: bool,
}

fn env_path_from(raw: Option<String>) -> Option<PathBuf> {
    let raw = raw?;
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return None;
    }
    Some(PathBuf::from(trimmed))
}

/// A boolean-ish environment variable: only explicit truthy values count.
fn env_flag(read_env: &dyn Fn(&str) -> Option<String>, key: &str) -> bool {
    matches!(
        read_env(key).as_deref().map(str::trim),
        Some("1") | Some("true") | Some("yes") | Some("on")
    )
}

/// `DEEPTUTOR_HOME` wins so a developer can point the shell at a checkout.
fn resolve_home_with(env: &dyn Fn(&str) -> Option<PathBuf>) -> PathBuf {
    if let Some(explicit) = env("DEEPTUTOR_HOME") {
        return explicit;
    }
    if cfg!(windows) {
        if let Some(appdata) = env("LOCALAPPDATA") {
            return appdata.join("DeepTutor");
        }
    }
    if let Some(home) = env("HOME") {
        if cfg!(target_os = "macos") {
            return home
                .join("Library")
                .join("Application Support")
                .join("DeepTutor");
        }
        return home.join(".local").join("share").join("DeepTutor");
    }
    PathBuf::from("DeepTutor")
}

fn venv_python(root: &Path) -> PathBuf {
    let venv = root.join(".venv");
    if cfg!(windows) {
        venv.join("Scripts").join("python.exe")
    } else {
        venv.join("bin").join("python")
    }
}

fn path_python_names() -> &'static [&'static str] {
    if cfg!(windows) {
        &["python.exe", "python"]
    } else {
        &["python3", "python"]
    }
}

/// Does this interpreter have DeepTutor's CLI installed?
fn probe_interpreter(path: &Path) -> bool {
    let mut command = Command::new(path);
    command
        .arg("-c")
        .arg("import deeptutor_cli.main")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    command
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

/// Outcome of one launch attempt.
enum Handshake {
    /// A quit (or a newer generation) interrupted the wait.
    Shutdown,
    /// Fatal: the launcher could not start or never became ready.
    Failed(String),
    Ready,
}

/// How a launcher that had already reported ready stopped.
enum Monitor {
    Shutdown,
    Exited(i32),
}

pub struct Supervisor {
    config: ShellConfig,
    window: Mutex<Option<WebviewWindow>>,
    child: Mutex<Option<Child>>,
    last_status: Mutex<String>,
    /// Phase 3: user preferences, the notification bookkeeping and pending OS
    /// hand-offs. All three outlive a launcher restart by design.
    settings: Mutex<ShellSettings>,
    notifications: NotificationCenter,
    handoffs: OpenQueue,
    /// Set when a first-run choice (the data directory) only takes effect on
    /// the next launch.
    restart_required: AtomicBool,
    stopping: AtomicBool,
    /// Bumped on every start so a superseded supervisor thread exits instead of
    /// polling (and navigating) alongside its replacement.
    generation: AtomicU64,
    launch_count: AtomicU64,
    restarts: AtomicU64,
    /// The port the window was last handed over to.
    ///
    /// The navigation policy needs it *after* a restart deletes the launcher's
    /// state file (and while the replacement is still starting), so it is kept
    /// here rather than re-read every time.
    frontend_port: Mutex<Option<u16>>,
    restart_lock: Mutex<()>,
    /// Set once by `new_shared`; lets a `&self` method (the IPC restart path)
    /// spawn the next supervisor thread.
    self_ref: OnceLock<Weak<Supervisor>>,
    /// Set once by `attach_app`; used for the native failure dialog.
    app: OnceLock<AppHandle>,
    /// The interpreter the launcher was actually started with, for diagnostics.
    interpreter: Mutex<Option<InterpreterCandidate>>,
    /// Launch timings, filled in as the launch progresses (Phase 4).
    started_at: Instant,
    spawn_ms: AtomicU64,
    ready_ms: AtomicU64,
    ui_ms: AtomicU64,
}

impl Supervisor {
    pub fn new_shared(config: ShellConfig) -> Arc<Self> {
        let settings = ShellSettings::load(&config.home);
        let notifications = NotificationCenter::new(settings.notifications);
        let supervisor = Arc::new(Self {
            config,
            window: Mutex::new(None),
            child: Mutex::new(None),
            last_status: Mutex::new("starting".to_string()),
            settings: Mutex::new(settings),
            notifications,
            handoffs: OpenQueue::new(),
            restart_required: AtomicBool::new(false),
            stopping: AtomicBool::new(false),
            generation: AtomicU64::new(0),
            launch_count: AtomicU64::new(0),
            restarts: AtomicU64::new(0),
            frontend_port: Mutex::new(None),
            restart_lock: Mutex::new(()),
            self_ref: OnceLock::new(),
            app: OnceLock::new(),
            interpreter: Mutex::new(None),
            started_at: Instant::now(),
            spawn_ms: AtomicU64::new(0),
            ready_ms: AtomicU64::new(0),
            ui_ms: AtomicU64::new(0),
        });
        let _ = supervisor.self_ref.set(Arc::downgrade(&supervisor));
        supervisor
    }

    pub fn attach_window(&self, window: WebviewWindow) {
        *self.window.lock().expect("window lock poisoned") = Some(window);
    }

    pub fn attach_app(&self, app: AppHandle) {
        let _ = self.app.set(app);
    }

    pub fn start(&self) {
        let generation = self.generation.fetch_add(1, Ordering::SeqCst) + 1;
        self.spawn_thread(generation);
    }

    fn spawn_thread(&self, generation: u64) {
        let Some(this) = self.self_ref.get().and_then(Weak::upgrade) else {
            return;
        };
        std::thread::Builder::new()
            .name("deeptutor-supervisor".to_string())
            .spawn(move || this.run(generation))
            .expect("failed to spawn the supervisor thread");
    }

    fn is_current(&self, generation: u64) -> bool {
        self.generation.load(Ordering::SeqCst) == generation
            && !self.stopping.load(Ordering::SeqCst)
    }

    fn run(&self, generation: u64) {
        let locale = self.locale();
        let mut crashes = 0u32;
        // The first-run wizard runs in the splash (app origin). Nothing is
        // spawned until it has been answered: the launcher's `--home` depends on
        // the answer, and a half-configured first profile is worse than a
        // second of patience.
        if !self.await_first_run(generation) {
            return;
        }
        loop {
            if !self.is_current(generation) {
                return;
            }
            match self.handshake(generation) {
                Handshake::Shutdown => return,
                Handshake::Failed(message) => {
                    self.fail(&message);
                    return;
                }
                Handshake::Ready => {}
            }
            match self.monitor(generation) {
                Monitor::Shutdown => return,
                Monitor::Exited(code) => {
                    crashes += 1;
                    if crashes > MAX_CRASH_RESTARTS {
                        self.fail(&format!(
                            "本地服务连续 {MAX_CRASH_RESTARTS} 次异常退出（最后退出码 {code}），已停止自动重启。"
                        ));
                        return;
                    }
                    self.restarts.fetch_add(1, Ordering::SeqCst);
                    let backoff = CRASH_BACKOFF_BASE * (1u32 << (crashes - 1));
                    self.set_status(&format!(
                        "本地服务异常退出（退出码 {code}），{} 秒后自动重启（第 {crashes}/{MAX_CRASH_RESTARTS} 次）...",
                        backoff.as_secs()
                    ));
                    if !self.sleep_interruptible(backoff, generation) {
                        return;
                    }
                    self.set_status(&tr(
                        locale,
                        "正在重启本地服务 ...",
                        "Restarting the local service ...",
                    ));
                }
            }
        }
    }

    /// Block the launch until the wizard has been answered (or the app quits).
    fn await_first_run(&self, generation: u64) -> bool {
        let locale = self.locale();
        if !self.needs_first_run() {
            return true;
        }
        self.set_status(&tr(
            locale,
            "首次启动：请在下方完成设置 ...",
            "First launch: finish the setup below ...",
        ));
        // Without this line, "the app opened but nothing ever started" has no
        // trace at all: the gate deliberately spawns no process to inspect.
        self.append_shell_log("waiting for the first-run wizard to be completed");
        let started = Instant::now();
        let mut announced = false;
        loop {
            if !self.is_current(generation) {
                return false;
            }
            if !self.needs_first_run() {
                return true;
            }
            // A splash that never loads must not look like a hang; say what we
            // are waiting for, once, and keep waiting (the tray can still quit).
            if !announced && started.elapsed() > Duration::from_secs(120) {
                announced = true;
                self.append_shell_log("still waiting for the first-run wizard to be completed");
                self.set_status(&tr(
                    locale,
                    "仍在等待完成首次设置（可在托盘菜单退出）...",
                    "Still waiting for the first-run setup (you can quit from the tray menu) ...",
                ));
            }
            std::thread::sleep(POLL_INTERVAL);
        }
    }

    /// The language the shell's own surfaces speak.
    pub fn locale(&self) -> Locale {
        let setting = self
            .settings
            .lock()
            .map(|settings| settings.locale.clone())
            .unwrap_or_default();
        Locale::resolve(&setting, &default_locale())
    }

    fn needs_first_run(&self) -> bool {
        self.settings
            .lock()
            .map(|settings| settings.needs_first_run())
            .unwrap_or(false)
    }

    /// Spawn the launcher and wait for its ready handshake.
    fn handshake(&self, generation: u64) -> Handshake {
        let locale = self.locale();
        self.set_status(&tr(
            locale,
            "正在启动本地服务 ...",
            "Starting the local service ...",
        ));
        if let Err(error) = self.spawn_launcher() {
            return Handshake::Failed(error);
        }

        let deadline = Instant::now() + READY_TIMEOUT;
        loop {
            if !self.is_current(generation) {
                return Handshake::Shutdown;
            }
            if let Some(info) = RuntimeInfo::read(&self.config.state_path) {
                // Only trust state written by *our* launcher. A leftover file
                // from a previous run reads as an instant "stopped" failure (or
                // worse, navigates to a dead port) — the Phase 0 bug this guard
                // exists for.
                let expected_pid = self.launcher_pid().map(|pid| pid as i32);
                if expected_pid.is_some() && info.pid != expected_pid {
                    std::thread::sleep(POLL_INTERVAL);
                    continue;
                }
                if info.schema_version != SUPPORTED_SCHEMA_VERSION {
                    return Handshake::Failed(tr(
                        locale,
                        format!(
                            "运行时状态文件版本不受支持 ({})，请更新桌面应用。",
                            info.schema_version
                        ),
                        format!(
                            "The runtime state file version ({}) is not supported; update the desktop app.",
                            info.schema_version
                        ),
                    ));
                }
                match info.status.as_str() {
                    "ready" => {
                        return match info.frontend_url.clone() {
                            Some(url) => {
                                self.ready_ms.store(
                                    self.started_at.elapsed().as_millis() as u64,
                                    Ordering::SeqCst,
                                );
                                self.open(&url);
                                Handshake::Ready
                            }
                            None => Handshake::Failed(
                                tr(locale, "运行时状态缺少 frontend_url，无法打开界面。", "The runtime state has no frontend_url, so the window cannot be opened."),
                            ),
                        };
                    }
                    "stopped" => {
                        return Handshake::Failed(tr(
                            locale,
                            "本地服务在就绪前退出，请查看日志。",
                            "The local service exited before it was ready; check the logs.",
                        ))
                    }
                    _ => {}
                }
            }
            if let Some(code) = self.take_exit_code() {
                // "Exit code 1" alone sends people to the wrong place; the last
                // lines of the launcher log are what actually name the cause.
                let mut message = format!("本地服务启动失败（退出码 {code}）。");
                let tail = self.launcher_log_tail(6);
                if !tail.is_empty() {
                    message.push_str("\n\n");
                    message.push_str(&tail);
                }
                return Handshake::Failed(message);
            }
            if Instant::now() >= deadline {
                return Handshake::Failed(
                    tr(
                        locale,
                        "本地服务启动超时，请查看日志。",
                        "The local service did not start in time; check the logs.",
                    )
                    .to_string(),
                );
            }
            std::thread::sleep(POLL_INTERVAL);
        }
    }

    /// Keep watching a launcher that already reported ready.
    fn monitor(&self, generation: u64) -> Monitor {
        loop {
            if !self.is_current(generation) {
                return Monitor::Shutdown;
            }
            if let Some(code) = self.take_exit_code() {
                self.append_shell_log(&format!("launcher exited with code {code}"));
                return Monitor::Exited(code);
            }
            std::thread::sleep(POLL_INTERVAL);
        }
    }

    /// Sleep in small slices so a quit or a manual restart still wins promptly.
    fn sleep_interruptible(&self, total: Duration, generation: u64) -> bool {
        let deadline = Instant::now() + total;
        while Instant::now() < deadline {
            if !self.is_current(generation) {
                return false;
            }
            std::thread::sleep(POLL_INTERVAL);
        }
        true
    }

    fn spawn_launcher(&self) -> Result<(), String> {
        let locale = self.locale();
        if let Err(error) = fs::create_dir_all(&self.config.logs_dir) {
            return Err(tr(
                locale,
                format!("无法创建日志目录: {error}"),
                format!("Could not create the log directory: {error}"),
            ));
        }
        let interpreter = self.config.resolve_interpreter()?;
        self.append_shell_log(&format!(
            "using interpreter {} (from {})",
            interpreter.path.display(),
            interpreter.source
        ));
        if let Ok(mut cache) = self.interpreter.lock() {
            *cache = Some(interpreter.clone());
        }
        // Start from a clean slate: the launcher writes "starting" only after
        // its own imports, and the poll loop must not read last run's file in
        // that window.
        let _ = fs::remove_file(&self.config.state_path);
        let stdout = OpenOptions::new()
            .create(true)
            .append(true)
            .open(self.config.logs_dir.join("launcher.log"))
            .map_err(|error| {
                tr(
                    locale,
                    format!("无法打开日志文件: {error}"),
                    format!("Could not open the log file: {error}"),
                )
            })?;
        let stderr = stdout.try_clone().map_err(|error| {
            tr(
                locale,
                format!("无法复用日志句柄: {error}"),
                format!("Could not duplicate the log handle: {error}"),
            )
        })?;

        let mut command = Command::new(&interpreter.path);
        command
            .arg("-m")
            .arg("deeptutor_cli.main")
            .arg("start")
            .arg("--home")
            .arg(&self.config.home)
            .arg("--no-browser")
            .arg("--auto-ports")
            .arg("--runtime-info")
            .arg(&self.config.state_path)
            .arg("--parent-pid")
            .arg(std::process::id().to_string())
            .current_dir(&self.config.workdir)
            .env("DEEPTUTOR_DESKTOP_SHELL", "1")
            .env("DEEPTUTOR_HOME", &self.config.home)
            .env("DEEPTUTOR_LAUNCHER_PID", std::process::id().to_string())
            .stdin(Stdio::null())
            .stdout(Stdio::from(stdout))
            .stderr(Stdio::from(stderr));

        // A pack brings its own Node; the launcher finds it through PATH
        // (`shutil.which("node")`) and would otherwise need the user to have one.
        if let Some(pack) = self.config.active_pack() {
            let node_dir = pack.manifest.node_dir(&pack.dir);
            if node_dir.exists() {
                let mut paths = vec![node_dir.clone()];
                if let Some(current) = std::env::var_os("PATH") {
                    paths.extend(std::env::split_paths(&current));
                }
                if let Ok(joined) = std::env::join_paths(paths) {
                    command.env("PATH", joined);
                }
                self.append_shell_log(&format!(
                    "runtime pack {} active; node from {}",
                    pack.pack_id,
                    node_dir.display()
                ));
            }
        }

        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            // Own process group: SIGTERM to the group reaches uvicorn and Node,
            // including children the launcher spawned for itself.
            command.process_group(0);
        }
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            command.creation_flags(CREATE_NO_WINDOW);
        }

        let child = command.spawn().map_err(|error| {
            tr(
                locale,
                format!(
                    "无法启动 Python launcher ({})：{error}",
                    interpreter.path.display()
                ),
                format!(
                    "Could not start the Python launcher ({}): {error}",
                    interpreter.path.display()
                ),
            )
        })?;
        *self.child.lock().expect("child lock poisoned") = Some(child);
        self.launch_count.fetch_add(1, Ordering::SeqCst);
        self.spawn_ms.store(
            self.started_at.elapsed().as_millis() as u64,
            Ordering::SeqCst,
        );
        Ok(())
    }

    /// The installer every catalog read goes through.
    fn installer(&self) -> PackInstaller {
        PackInstaller::new(&self.config.home).with_catalog_pubkey(self.catalog_pubkey())
    }

    /// The minisign key the runtime catalog must be signed with.
    ///
    /// An environment override wins (headless runs, CI, support), otherwise the
    /// key the shell plane already trusts from `tauri.conf.json` is reused: one
    /// keypair for both planes, and nothing the webview can reach can weaken it.
    pub fn catalog_pubkey(&self) -> Option<String> {
        if let Some(explicit) = self.config.catalog_pubkey.clone() {
            return Some(explicit);
        }
        let app = self.app.get()?;
        let updater = app.config().plugins.0.get("updater")?.clone();
        let pubkey = updater.get("pubkey")?.as_str()?.trim().to_string();
        (!pubkey.is_empty()).then_some(pubkey)
    }

    fn take_exit_code(&self) -> Option<i32> {
        let mut guard = self.child.lock().expect("child lock poisoned");
        let child = guard.as_mut()?;
        match child.try_wait() {
            Ok(Some(status)) => Some(status.code().unwrap_or(-1)),
            Ok(None) => None,
            Err(_) => Some(-1),
        }
    }

    fn launcher_pid(&self) -> Option<u32> {
        let guard = self.child.lock().ok()?;
        guard.as_ref().map(|child| child.id())
    }

    fn child_running(&self) -> bool {
        let mut guard = match self.child.lock() {
            Ok(guard) => guard,
            Err(_) => return false,
        };
        match guard.as_mut() {
            Some(child) => matches!(child.try_wait(), Ok(None)),
            None => false,
        }
    }

    fn open(&self, url: &str) {
        let locale = self.locale();
        self.set_status(&format!("已就绪：{url}"));
        let parsed = match tauri::Url::parse(url) {
            Ok(parsed) => parsed,
            Err(error) => {
                self.append_shell_log(&format!("invalid frontend url {url}: {error}"));
                return;
            }
        };
        // Remember where the UI lives before navigating: from here on the
        // navigation policy treats exactly this port as "ours" and everything
        // else on loopback as somebody else's page.
        if let Ok(mut guard) = self.frontend_port.lock() {
            *guard = parsed.port_or_known_default();
        }
        let result = {
            let guard = self.window.lock().expect("window lock poisoned");
            match guard.as_ref() {
                Some(window) => window.navigate(parsed).map_err(|error| error.to_string()),
                None => Err(tr(
                    locale,
                    "窗口尚未创建",
                    "The window has not been created yet",
                )
                .to_string()),
            }
        };
        if let Err(error) = result {
            self.append_shell_log(&format!("navigate failed: {error}"));
            return;
        }
        self.verify_remote_ipc();
    }

    /// The port the window is (or is about to be) serving the UI from.
    ///
    /// Remembered from the last hand-over; before the first one, read from the
    /// launcher's state file. `None` means "not yet known", and the navigation
    /// policy treats an unknown port as not ours rather than trusting all of
    /// loopback.
    pub fn frontend_port(&self) -> Option<u16> {
        if let Ok(guard) = self.frontend_port.lock() {
            if let Some(port) = *guard {
                return Some(port);
            }
        }
        let url = RuntimeInfo::read(&self.config.state_path)?.frontend_url?;
        tauri::Url::parse(&url).ok()?.port_or_known_default()
    }

    /// Probe IPC from *inside* the loopback page, when asked to.
    ///
    /// The splash runs on the app origin, where IPC needs no `remote` grant, so
    /// a successful call there proves nothing about the capability the real UI
    /// depends on. These evals run in the loopback document and report through
    /// the URL fragment, because the interesting failure is "the bridge is
    /// missing or rejected", which IPC itself cannot report.
    ///
    /// Verified 2026-09-24 (Phase 0): core/plugin commands reach the shell from
    /// the loopback origin and the remote grant works, but application commands
    /// do not — hence `plugin:deeptutor|desktop_status`.
    ///
    /// Diagnostic only (`--remote-ipc-probe`): it evals into the live UI, and it
    /// used to call `restart_service` on its first round, which bounced the
    /// local service seconds after every launch.
    fn verify_remote_ipc(&self) {
        if !self.config.probe_remote_ipc {
            return;
        }
        let script = PROBE_SCRIPT;
        for attempt in 1..=3 {
            std::thread::sleep(Duration::from_secs(3));
            self.append_shell_log(&format!("remote-ipc probe dispatched (attempt {attempt})"));
            {
                let guard = self.window.lock().expect("window lock poisoned");
                let Some(window) = guard.as_ref() else {
                    return;
                };
                if window.eval(script).is_err() {
                    self.append_shell_log("remote-ipc probe eval failed");
                    return;
                }
            }
            let deadline = Instant::now() + Duration::from_secs(4);
            while Instant::now() < deadline {
                if let Some(report) = self.probe_report() {
                    self.append_shell_log(&format!("remote-ipc probe result: {report}"));
                    self.clear_probe_hash();
                    return;
                }
                std::thread::sleep(POLL_INTERVAL);
            }
        }
        self.append_shell_log("remote-ipc probe: no report from the loopback page");
    }

    /// Read the `#deeptutorProbe=...` report the evaled script leaves behind.
    fn probe_report(&self) -> Option<String> {
        let guard = self.window.lock().ok()?;
        let window = guard.as_ref()?;
        let fragment = window.url().ok()?.fragment().map(str::to_string)?;
        let marker = "deeptutorProbe=";
        let index = fragment.find(marker)?;
        Some(fragment[index + marker.len()..].to_string())
    }

    fn clear_probe_hash(&self) {
        self.with_window(|window| {
            let _ = window.eval(
                "try { history.replaceState(null, '', location.pathname + location.search); } catch (e) {}",
            );
        });
    }

    pub fn set_status(&self, text: &str) {
        if let Ok(mut status) = self.last_status.lock() {
            *status = text.to_string();
        }
        let script = format!("window.setStatus({});", json_string(text));
        self.with_window(|window| {
            let _ = window.eval(&script);
        });
    }

    /// Surface a fatal shell error and make sure nothing keeps running behind it.
    pub fn fail(&self, message: &str) {
        let locale = self.locale();
        self.append_shell_log(message);
        if let Ok(mut status) = self.last_status.lock() {
            *status = message.to_string();
        }
        let script = format!("window.showError({});", json_string(message));
        self.with_window(|window| {
            let _ = window.set_title("DeepTutor — 启动失败");
            let _ = window.eval(&script);
        });
        // A failed handshake must not leave a half-started backend/frontend
        // pair running behind an error splash.
        self.terminate_child();
        // A splash the user may not be looking at is not enough. This runs on
        // the supervisor thread, so blocking_show cannot deadlock the UI.
        if let Some(app) = self.app.get() {
            let _ = app
                .dialog()
                .message(message.to_string())
                .title(tr(
                    locale,
                    "DeepTutor 启动失败",
                    "DeepTutor failed to start",
                ))
                .kind(MessageDialogKind::Error)
                .blocking_show();
        }
    }

    fn with_window<F: FnOnce(&WebviewWindow)>(&self, action: F) {
        let guard = match self.window.lock() {
            Ok(guard) => guard,
            Err(_) => return,
        };
        if let Some(window) = guard.as_ref() {
            action(window);
        }
    }

    /// Append to `desktop/logs/shell.log`; never fails the caller.
    pub fn append_shell_log(&self, message: &str) {
        if fs::create_dir_all(&self.config.logs_dir).is_err() {
            return;
        }
        let path = self.config.logs_dir.join("shell.log");
        if let Ok(mut handle) = OpenOptions::new().create(true).append(true).open(path) {
            let _ = writeln!(handle, "[shell] {message}");
        }
    }

    pub fn logs_dir(&self) -> &Path {
        &self.config.logs_dir
    }

    /// Last non-empty lines of `launcher.log`, for the failure dialog.
    fn launcher_log_tail(&self, lines: usize) -> String {
        let Ok(text) = fs::read_to_string(self.config.logs_dir.join("launcher.log")) else {
            return String::new();
        };
        let mut tail: Vec<&str> = text
            .lines()
            .filter(|line| !line.trim().is_empty())
            .rev()
            .take(lines)
            .collect();
        tail.reverse();
        tail.join("\n")
    }

    /// SIGTERM the launcher's process group, then SIGKILL after a grace period.
    /// Safe to call when nothing is running.
    fn terminate_child(&self) {
        let mut guard = match self.child.lock() {
            Ok(guard) => guard,
            Err(_) => return,
        };
        let Some(child) = guard.as_mut() else {
            return;
        };
        signal_group(child, true);
        let deadline = Instant::now() + TERM_GRACE;
        loop {
            match child.try_wait() {
                Ok(Some(_)) => break,
                Ok(None) if Instant::now() < deadline => {
                    std::thread::sleep(Duration::from_millis(100))
                }
                Ok(None) => {
                    signal_group(child, false);
                    let _ = child.kill();
                    let _ = child.wait();
                    break;
                }
                Err(_) => break,
            }
        }
        *guard = None;
    }

    /// Quit path: stop watching and take the launcher down. Idempotent.
    pub fn stop(&self) {
        if self.stopping.swap(true, Ordering::SeqCst) {
            return;
        }
        self.terminate_child();
    }

    /// Manual restart from the UI or the menu.
    pub fn restart(&self) -> Result<(), String> {
        let locale = self.locale();
        let _guard = self.restart_lock.lock().map_err(|_| {
            tr(locale, "重启锁不可用", "The restart lock is unavailable").to_string()
        })?;
        if self.stopping.load(Ordering::SeqCst) {
            return Err(tr(
                locale,
                "应用正在退出，无法重启",
                "The app is quitting, so it cannot restart the service",
            )
            .to_string());
        }
        // A user-initiated restart also clears a previous "stopped" flag, so a
        // restart after a failed handshake genuinely retries.
        //
        // Retire the current supervisor thread *first*: otherwise it sees the
        // launcher we are about to kill as a crash and auto-restarts as well.
        let generation = self.generation.fetch_add(1, Ordering::SeqCst) + 1;
        self.stopping.store(false, Ordering::SeqCst);
        self.terminate_child();
        let _ = fs::remove_file(&self.config.state_path);
        self.set_status(&tr(
            locale,
            "正在重新启动本地服务 ...",
            "Restarting the local service ...",
        ));
        self.append_shell_log("manual restart requested");
        self.spawn_thread(generation);
        Ok(())
    }
}

impl DesktopBackend for Supervisor {
    fn status(&self) -> DesktopStatus {
        let runtime = RuntimeInfo::read(&self.config.state_path).map(|info| RuntimeSnapshot {
            schema_version: info.schema_version,
            status: info.status,
            frontend_url: info.frontend_url,
            backend_url: info.backend_url,
            backend_port: info.backend_port,
            frontend_port: info.frontend_port,
            token_present: info.token.is_some(),
        });
        DesktopStatus {
            launch_count: self.launch_count.load(Ordering::SeqCst),
            restarts: self.restarts.load(Ordering::SeqCst),
            launcher_running: self.child_running(),
            launcher_pid: self.launcher_pid(),
            message: self
                .last_status
                .lock()
                .map(|value| value.clone())
                .unwrap_or_default(),
            home: self.config.home.to_string_lossy().into_owned(),
            workdir: self.config.workdir.to_string_lossy().into_owned(),
            python: self.interpreter_for_display(),
            pack: self.config.active_pack().map(|pack| pack.pack_id),
            logs_dir: self.config.logs_dir.to_string_lossy().into_owned(),
            notifications_posted: self.notifications.posted(),
            startup: self.startup_timings(),
            window: self.window_geometry(),
            runtime,
        }
    }

    fn restart(&self) -> Result<(), String> {
        Supervisor::restart(self)
    }

    fn note_caller(&self, origin: &str) {
        self.append_shell_log(&format!("webview-ipc ok: invoke received from {origin}"));
    }

    fn settings(&self) -> ShellSettingsSnapshot {
        Supervisor::shell_settings(self)
    }

    fn update_settings(&self, patch: SettingsPatch) -> Result<ShellSettingsSnapshot, String> {
        Supervisor::apply_settings_patch(self, patch)
    }

    fn note_ui_ready(&self, elapsed_ms: u64) {
        // `performance.now()` in the app page is measured from that document's
        // navigation start, which is the moment the shell handed the window over
        // (`ready_ms`). Adding the two puts the UI's number on the shell's axis.
        let total = self
            .ready_ms
            .load(Ordering::SeqCst)
            .saturating_add(elapsed_ms);
        if self.ui_ms.swap(total, Ordering::SeqCst) == 0 {
            let timings = self.startup_timings();
            self.append_shell_log(&format!(
                "startup: spawn {} ms, ready {} ms, first paint {} ms ({} ms after ready)",
                timings
                    .as_ref()
                    .map(|value| value.spawn_ms)
                    .unwrap_or_default(),
                timings
                    .as_ref()
                    .map(|value| value.ready_ms)
                    .unwrap_or_default(),
                timings
                    .as_ref()
                    .map(|value| value.ui_ms)
                    .unwrap_or_default(),
                timings
                    .as_ref()
                    .map(|value| value.ready_to_ui_ms)
                    .unwrap_or_default(),
            ));
        }
    }

    fn notify(&self, request: NotificationRequest) -> Result<NotificationOutcome, String> {
        Supervisor::notify_round(self, request)
    }

    fn take_notification_target(&self) -> Option<NotificationTarget> {
        self.notifications.take()
    }

    fn take_open_request(&self) -> Option<OpenRequestPayload> {
        self.handoffs.take()
    }

    fn locale(&self) -> String {
        Supervisor::locale(self).code().to_string()
    }

    fn allow_local_read(&self, path: &Path) {
        self.handoffs.grant_read(path);
    }

    fn take_local_read_permission(&self, path: &Path) -> bool {
        self.handoffs.take_read_grant(path)
    }

    fn first_run(&self) -> FirstRunState {
        Supervisor::first_run_state(self)
    }

    fn apply_first_run(&self, choices: FirstRunChoices) -> Result<FirstRunOutcome, String> {
        Supervisor::apply_first_run(self, choices)
    }

    fn preview_updates(&self) -> RuntimeUpdateReport {
        Supervisor::preview_runtime_updates(self, None)
    }

    fn confirm_and_install_runtime_update(&self) -> RuntimeUpdateReport {
        Supervisor::confirm_and_install_runtime_update(self)
    }
}

/// Phase 3 shell behaviour: preferences, notifications, OS hand-offs and the
/// "check updates" report. Kept in its own block so the launch/monitor state
/// machine above stays readable.
impl Supervisor {
    pub fn shell_settings(&self) -> ShellSettingsSnapshot {
        let settings = self
            .settings
            .lock()
            .map(|settings| settings.clone())
            .unwrap_or_default();
        ShellSettingsSnapshot {
            close_to_tray: settings.close_to_tray,
            notifications: settings.notifications,
            locale: settings.locale,
            first_run_completed: settings.first_run_completed,
            pack_catalog: settings.pack_catalog,
            home: self.config.home.to_string_lossy().into_owned(),
            default_home: self.config.default_home.to_string_lossy().into_owned(),
            restart_required: self.restart_required.load(Ordering::SeqCst),
        }
    }

    /// Apply a partial preference update and persist it.
    pub fn apply_settings_patch(
        &self,
        patch: SettingsPatch,
    ) -> Result<ShellSettingsSnapshot, String> {
        let locale = self.locale();
        let mut guard = self.settings.lock().map_err(|_| {
            tr(
                locale,
                "设置不可用（锁已损坏）",
                "Settings are unavailable (the lock is poisoned)",
            )
            .to_string()
        })?;
        if let Some(value) = patch.close_to_tray {
            guard.close_to_tray = value;
        }
        if let Some(value) = patch.notifications {
            guard.notifications = value;
        }
        if let Some(value) = patch.locale {
            let value = value.trim().to_string();
            if !value.is_empty() && value != "zh-CN" && value != "en" {
                return Err(tr(
                    locale,
                    format!("不支持的语言：{value}"),
                    format!("Unsupported language: {value}"),
                ));
            }
            guard.locale = value;
        }
        if let Some(value) = patch.first_run_completed {
            guard.first_run_completed = value;
        }
        if let Some(value) = patch.pack_catalog {
            let value = value.trim().to_string();
            guard.pack_catalog = if value.is_empty() {
                None
            } else {
                Some(validate_update_source(&value, locale)?)
            };
        }
        guard.save(&self.config.home)?;
        // The notification preference is read on the hot path, so mirror it
        // instead of taking the settings lock for every round that finishes.
        self.notifications.set_enabled(guard.notifications);
        let language_changed = Locale::resolve(&guard.locale, &default_locale()) != locale;
        drop(guard);
        // The menu bar and the tray are native chrome built once at startup;
        // without this a language change would only take effect on relaunch.
        if language_changed {
            if let Some(app) = self.app.get() {
                let _ = crate::app::refresh_chrome(app);
            }
        }
        Ok(self.shell_settings())
    }

    /// Post the "round finished" notification and remember where it points.
    pub fn notify_round(
        &self,
        request: NotificationRequest,
    ) -> Result<NotificationOutcome, String> {
        let locale = self.locale();
        validate_notification(&request, locale)?;
        if !self.notifications.is_enabled() {
            // A preference flipped off must not leave an old "come back to this
            // session" pointer armed for the next focus change.
            self.notifications.clear();
            return Ok(NotificationOutcome {
                delivered: false,
                permission: "disabled".to_string(),
                detail: Some(
                    tr(
                        locale,
                        "桌面通知已在设置中关闭",
                        "Desktop notifications are switched off in settings",
                    )
                    .to_string(),
                ),
            });
        }
        let app = self.app.get().cloned().ok_or_else(|| {
            tr(
                locale,
                "应用句柄尚未就绪",
                "The app handle is not ready yet",
            )
            .to_string()
        })?;
        match app
            .notification()
            .builder()
            .title(request.title.clone())
            .body(request.body.clone())
            .show()
        {
            Ok(()) => {
                self.append_shell_log(&format!(
                    "notification posted: kind={} route={}",
                    request.kind.as_deref().unwrap_or("unknown"),
                    request.route
                ));
                self.notifications.record(&request);
                Ok(NotificationOutcome {
                    delivered: true,
                    permission: "granted".to_string(),
                    detail: None,
                })
            }
            Err(error) => {
                self.append_shell_log(&format!("notification failed: {error}"));
                Err(format!("无法发送系统通知：{error}"))
            }
        }
    }

    pub fn first_run_state(&self) -> FirstRunState {
        let snapshot = self.shell_settings();
        FirstRunState {
            completed: snapshot.first_run_completed,
            locale: snapshot.locale,
            default_locale: default_locale(),
            close_to_tray: snapshot.close_to_tray,
            notifications: snapshot.notifications,
            home: snapshot.home,
            default_home: snapshot.default_home,
            // Changing the data directory is a first-run decision: doing it
            // later would orphan the profile the user already has.
            can_change_data_dir: !snapshot.first_run_completed,
        }
    }

    /// Persist the wizard's answers; the waiting supervisor thread picks the
    /// `first_run_completed` flag up on its next poll and launches.
    pub fn apply_first_run(&self, choices: FirstRunChoices) -> Result<FirstRunOutcome, String> {
        let ui_locale = self.locale();
        let locale = match choices.locale.trim() {
            "" => self.shell_settings().locale,
            "en" => "en".to_string(),
            "zh" | "zh-CN" | "zh-Hans" => "zh-CN".to_string(),
            other => {
                return Err(tr_code(
                    other,
                    format!("不支持的语言：{other}"),
                    format!("Unsupported language: {other}"),
                ))
            }
        };

        let requested = choices
            .data_dir
            .as_deref()
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(PathBuf::from);
        let mut restart_required = false;
        let mut settings_home: Option<PathBuf> = None;
        match requested {
            Some(target) => {
                if !target.is_absolute() {
                    return Err(tr(
                        ui_locale,
                        "数据目录必须是绝对路径",
                        "The data directory must be an absolute path",
                    )
                    .to_string());
                }
                fs::create_dir_all(&target).map_err(|error| {
                    tr(
                        ui_locale,
                        format!("无法创建数据目录 {}：{error}", target.display()),
                        format!(
                            "Could not create the data directory {}: {error}",
                            target.display()
                        ),
                    )
                })?;
                if target != self.config.home {
                    Bootstrap::write_home(&self.config.default_home, &target)?;
                    restart_required = true;
                    settings_home = Some(target);
                } else {
                    // "Keep the default" must also undo an earlier pointer.
                    Bootstrap::clear(&self.config.default_home)?;
                }
            }
            None => {
                if self.config.home != self.config.default_home {
                    Bootstrap::clear(&self.config.default_home)?;
                    restart_required = true;
                }
            }
        }

        let snapshot = self.apply_settings_patch(SettingsPatch {
            close_to_tray: Some(choices.close_to_tray),
            notifications: Some(choices.notifications),
            locale: Some(locale),
            first_run_completed: Some(true),
            pack_catalog: None,
        })?;
        // A relaunch will read settings from the *new* home; write the same
        // answers there so the wizard does not reappear after the restart.
        if let Some(home) = settings_home {
            let settings = self
                .settings
                .lock()
                .map_err(|_| {
                    tr(
                        ui_locale,
                        "设置不可用（锁已损坏）",
                        "Settings are unavailable (the lock is poisoned)",
                    )
                    .to_string()
                })?
                .clone();
            settings.save(&home)?;
        }
        if restart_required {
            self.restart_required.store(true, Ordering::SeqCst);
        }
        self.append_shell_log(&format!(
            "first-run wizard completed (home={}, restart_required={restart_required})",
            self.config.home.display()
        ));
        Ok(FirstRunOutcome {
            restart_required,
            settings: snapshot,
        })
    }

    /// Queue a URL the OS asked us to open and bring the window forward.
    pub fn push_open_urls<'a, I: IntoIterator<Item = &'a tauri::Url>>(
        &self,
        urls: I,
        source: &'static str,
    ) -> usize {
        let accepted = self.handoffs.push_urls(urls, source);
        if accepted > 0 {
            self.append_shell_log(&format!("queued {accepted} open request(s) from {source}"));
            self.notify_ui_of_handoff();
        }
        accepted
    }

    pub fn push_open_args<I: IntoIterator<Item = String>>(
        &self,
        args: I,
        source: &'static str,
    ) -> usize {
        let accepted = self.handoffs.push_args(args, source);
        if accepted > 0 {
            self.append_shell_log(&format!("queued {accepted} open request(s) from {source}"));
            self.notify_ui_of_handoff();
        }
        accepted
    }

    /// Tell the UI there is something waiting, and make sure it is visible.
    fn notify_ui_of_handoff(&self) {
        if self.handoffs.is_empty() {
            return;
        }
        self.emit_to_ui("deeptutor://open-request", serde_json::json!({}));
    }

    /// Deliver the session a notification pointed at, now that the user is back.
    pub fn flush_notification_target(&self) -> Option<NotificationTarget> {
        let target = self.notifications.take()?;
        self.emit_to_ui(
            "deeptutor://notification-target",
            serde_json::to_value(&target).unwrap_or(serde_json::Value::Null),
        );
        Some(target)
    }

    fn emit_to_ui(&self, event: &str, payload: serde_json::Value) {
        let Some(app) = self.app.get().cloned() else {
            return;
        };
        use tauri::Emitter as _;
        if let Err(error) = app.emit(event, payload) {
            self.append_shell_log(&format!("emit {event} failed: {error}"));
        }
    }

    /// Runtime-pack update check. Installs when the catalog has something newer.
    ///
    /// The shell plane is deliberately absent here: it lives in
    /// `tauri-plugin-deeptutor`, which owns the updater plugin, and the caller
    /// combines both into one [`UpdateReport`].
    pub fn check_runtime_updates(&self) -> RuntimeUpdateReport {
        let locale = self.locale();
        let installer = self.installer();
        let source = self.update_source();

        match source {
            None => {
                let state = installer.state();
                RuntimeUpdateReport {
                    checked: false,
                    source: None,
                    updated: false,
                    error: None,
                    app_version: state
                        .active_pack
                        .as_ref()
                        .and_then(|pack_id| installer.load(pack_id).ok())
                        .map(|pack| pack.manifest.app_version),
                    active_pack: state.active_pack,
                    previous_pack: state.previous_pack,
                    detail: tr(locale, "未配置运行时更新源：在 desktop/shell.json 写入 pack_catalog，或设置 DEEPTUTOR_DESKTOP_PACK_CATALOG。", "No runtime update source configured: set pack_catalog in desktop/shell.json, or DEEPTUTOR_DESKTOP_PACK_CATALOG.").to_string(),
                }
            }
            Some(source) => match installer.update_from_catalog(&source) {
                Ok(Some(pack)) => {
                    let state = installer.state();
                    self.append_shell_log(&format!(
                        "runtime pack updated to {} from {source}",
                        pack.pack_id
                    ));
                    let report = RuntimeUpdateReport {
                        checked: true,
                        source: Some(source),
                        updated: true,
                        error: None,
                        app_version: Some(pack.manifest.app_version.clone()),
                        active_pack: state.active_pack,
                        previous_pack: state.previous_pack,
                        detail: format!("已安装运行时包 {}", pack.pack_id),
                    };
                    // A new pack only takes effect on the next launch of the
                    // backend, so do that now instead of leaving the user on a
                    // version the UI just said was replaced.
                    if let Err(error) = self.restart() {
                        self.append_shell_log(&format!(
                            "restart after pack update failed: {error}"
                        ));
                    }
                    report
                }
                Ok(None) => {
                    let state = installer.state();
                    RuntimeUpdateReport {
                        checked: true,
                        source: Some(source),
                        updated: false,
                        error: None,
                        app_version: state
                            .active_pack
                            .as_ref()
                            .and_then(|pack_id| installer.load(pack_id).ok())
                            .map(|pack| pack.manifest.app_version),
                        active_pack: state.active_pack,
                        previous_pack: state.previous_pack,
                        detail: tr(locale, "运行时包已是最新", "The runtime pack is up to date")
                            .to_string(),
                    }
                }
                Err(error) => {
                    let state = installer.state();
                    RuntimeUpdateReport {
                        checked: true,
                        source: Some(source),
                        updated: false,
                        app_version: None,
                        active_pack: state.active_pack,
                        previous_pack: state.previous_pack,
                        error: Some(error.to_string()),
                        detail: tr(
                            locale,
                            format!("检查运行时包失败：{error}"),
                            format!("Could not read the runtime pack catalog: {error}"),
                        ),
                    }
                }
            },
        }
    }

    /// Where the runtime-pack check looks for its catalog, if anywhere.
    fn update_source(&self) -> Option<String> {
        self.shell_settings()
            .pack_catalog
            .or_else(|| std::env::var("DEEPTUTOR_DESKTOP_PACK_CATALOG").ok())
            .map(|value| value.trim().to_string())
            .filter(|value| !value.is_empty())
    }

    /// Read-only variant of [`Supervisor::check_runtime_updates`].
    ///
    /// Answers "is there something newer" without downloading a pack and
    /// without restarting the local service — what a headless gate
    /// (`--check-updates`) must do, and what the tray dialog could report
    /// before spending 250 MB of somebody's bandwidth.
    pub fn preview_runtime_updates(&self, source: Option<String>) -> RuntimeUpdateReport {
        self.runtime_update_plan(source).0
    }

    /// The read-only answer plus the release it is about, when there is one.
    ///
    /// The installing path needs the release itself (to name the version and the
    /// download size in the confirmation), and "is there an update" is not
    /// something the report carries: its `detail` is prose.
    fn runtime_update_plan(
        &self,
        source: Option<String>,
    ) -> (RuntimeUpdateReport, Option<PackRelease>) {
        let locale = self.locale();
        let installer = self.installer();
        let source = source.or_else(|| self.update_source());
        let state = installer.state();
        let active_version = state
            .active_pack
            .as_ref()
            .and_then(|pack_id| installer.load(pack_id).ok())
            .map(|pack| pack.manifest.app_version);
        match source {
            None => (
                RuntimeUpdateReport {
                    checked: false,
                    source: None,
                    updated: false,
                    error: None,
                    app_version: active_version,
                    active_pack: state.active_pack,
                    previous_pack: state.previous_pack,
                    detail: tr(locale, "未配置运行时更新源：在 desktop/shell.json 写入 pack_catalog，或设置 DEEPTUTOR_DESKTOP_PACK_CATALOG。", "No runtime update source configured: set pack_catalog in desktop/shell.json, or DEEPTUTOR_DESKTOP_PACK_CATALOG.").to_string(),
                },
                None,
            ),
            Some(source) => match installer.outdated_from_catalog(&source) {
                Ok(Some(release)) => {
                    // Say which download the user is actually signing up for.
                    let incremental = installer.delta_applies(&release);
                    let report = RuntimeUpdateReport {
                        checked: true,
                        source: Some(source),
                        updated: false,
                        error: None,
                        app_version: active_version,
                        active_pack: state.active_pack,
                        previous_pack: state.previous_pack,
                        detail: format!(
                            "有新版本 {} 可用（{} MB{}）",
                            release.app_version,
                            download_size(&release, incremental) / (1024 * 1024),
                            if incremental {
                                "，增量更新"
                            } else {
                                "，完整包"
                            }
                        ),
                    };
                    (report, Some(release))
                }
                Ok(None) => (
                    RuntimeUpdateReport {
                        checked: true,
                        source: Some(source),
                        updated: false,
                        error: None,
                        app_version: active_version,
                        active_pack: state.active_pack,
                        previous_pack: state.previous_pack,
                        detail: tr(locale, "运行时包已是最新", "The runtime pack is up to date").to_string(),
                    },
                    None,
                ),
                Err(error) => (
                    RuntimeUpdateReport {
                        checked: true,
                        source: Some(source),
                        updated: false,
                        app_version: None,
                        active_pack: state.active_pack,
                        previous_pack: state.previous_pack,
                        error: Some(error.to_string()),
                        detail: tr(locale, format!("检查运行时包失败：{error}"), format!("Could not read the runtime pack catalog: {error}")),
                    },
                    None,
                ),
            },
        }
    }

    /// Preview, ask the user, and only then install.
    ///
    /// The command is reachable from the loopback-served UI, so downloading and
    /// executing a pack needs an explicit yes from a native dialog rather than
    /// an IPC call. A declined prompt reports "nothing happened", not an error.
    pub fn confirm_and_install_runtime_update(&self) -> RuntimeUpdateReport {
        let locale = self.locale();
        let (report, release) = self.runtime_update_plan(None);
        let Some(release) = release else {
            return report;
        };
        if !self.confirm_pack_install(&release) {
            self.append_shell_log(&format!(
                "runtime pack update to {} declined by the user",
                release.app_version
            ));
            return RuntimeUpdateReport {
                detail: tr(
                    locale,
                    "已取消运行时包更新",
                    "Runtime pack update cancelled",
                )
                .to_string(),
                ..report
            };
        }
        self.check_runtime_updates()
    }

    /// The authorization boundary for a runtime-pack install.
    ///
    /// Runs on a worker thread (the update-check thread or the command's
    /// blocking pool), never on the window's own thread, which is what makes a
    /// blocking native dialog safe here.
    fn confirm_pack_install(&self, release: &PackRelease) -> bool {
        let locale = self.locale();
        let Some(app) = self.app.get() else {
            return false;
        };
        let incremental = self.installer().delta_applies(release);
        app.dialog()
            .message(format!(
                "运行时包有新版本 {}（约 {} MB{}）。\n\n下载并安装后本地服务会重启，期间界面会短暂断开。",
                release.app_version,
                download_size(release, incremental) / (1024 * 1024),
                if incremental {
                    "，增量更新"
                } else {
                    "，完整包"
                }
            ))
            .title(tr(locale, "DeepTutor 运行时更新", "DeepTutor runtime update"))
            .buttons(MessageDialogButtons::OkCancelCustom(
                tr(locale, "下载并安装", "Download and install").to_string(),
                tr(locale, "稍后", "Later").to_string(),
            ))
            .blocking_show()
    }
}

/// How many bytes an update to `release` would download.
fn download_size(release: &PackRelease, incremental: bool) -> u64 {
    if incremental {
        release.delta.as_ref().map(|delta| delta.size).unwrap_or(0)
    } else {
        release.size
    }
}

/// A configured runtime-pack source must not be plaintext.
///
/// The catalog names the archive *and* the sha256 that authenticates it, so an
/// http catalog is a man-in-the-middle away from handing this shell a pack it
/// will execute. A local path is fine: only the machine's owner can write the
/// settings (and CI/headless runs pass their own catalogs explicitly).
fn validate_update_source(value: &str, locale: Locale) -> Result<String, String> {
    if value.starts_with("http://") {
        return Err(tr(
            locale,
            "运行时更新源必须是 https（或本地路径）",
            "The runtime update source must be https (or a local path)",
        )
        .to_string());
    }
    Ok(value.to_string())
}

/// Bounds for what the webview may ask the shell to display.
///
/// A system notification is drawn outside the app and its route is handed back
/// to the UI to navigate to, so neither is an unbounded string a page gets to
/// choose. The web app's own limits (60/180 characters) sit well inside these.
const MAX_NOTIFICATION_TITLE: usize = 200;
const MAX_NOTIFICATION_BODY: usize = 500;
const MAX_NOTIFICATION_ROUTE: usize = 512;

fn validate_notification(request: &NotificationRequest, locale: Locale) -> Result<(), String> {
    let route = request.route.trim();
    if route.is_empty()
        || !route.starts_with('/')
        || route.starts_with("//")
        || route.chars().count() > MAX_NOTIFICATION_ROUTE
    {
        return Err(tr(
            locale,
            format!("通知的路由必须是应用内路径：{}", request.route),
            format!(
                "A notification route must be an in-app path: {}",
                request.route
            ),
        ));
    }
    if request.title.chars().count() > MAX_NOTIFICATION_TITLE {
        return Err(tr(
            locale,
            format!("通知标题过长（上限 {MAX_NOTIFICATION_TITLE} 字符）"),
            format!(
                "The notification title is too long (limit {MAX_NOTIFICATION_TITLE} characters)"
            ),
        ));
    }
    if request.body.chars().count() > MAX_NOTIFICATION_BODY {
        return Err(tr(
            locale,
            format!("通知正文过长（上限 {MAX_NOTIFICATION_BODY} 字符）"),
            format!("The notification body is too long (limit {MAX_NOTIFICATION_BODY} characters)"),
        ));
    }
    Ok(())
}

/// Language the wizard preselects, from the OS locale.
pub fn default_locale() -> String {
    for key in ["LANG", "LC_ALL", "LC_MESSAGES"] {
        if let Ok(value) = std::env::var(key) {
            if value.to_ascii_lowercase().starts_with("zh") {
                return "zh-CN".to_string();
            }
            if !value.trim().is_empty() {
                return "en".to_string();
            }
        }
    }
    "zh-CN".to_string()
}

impl Supervisor {
    /// Launch timings, once the UI has reported its first paint.
    fn startup_timings(&self) -> Option<StartupTimings> {
        let ui = self.ui_ms.load(Ordering::SeqCst);
        if ui == 0 {
            return None;
        }
        let ready = self.ready_ms.load(Ordering::SeqCst);
        Some(StartupTimings {
            spawn_ms: self.spawn_ms.load(Ordering::SeqCst),
            ready_ms: ready,
            ui_ms: ui,
            // Saturating: a UI that reports before `ready` (a warm reload, say)
            // is not a reason to wrap around.
            ready_to_ui_ms: ui.saturating_sub(ready),
        })
    }

    /// Current main-window geometry, when the window exists.
    ///
    /// Reported because "the window forgot its size" is otherwise invisible in
    /// a log, and because the restore path is hand-rolled (see `window.rs`).
    fn window_geometry(&self) -> Option<WindowGeometry> {
        let guard = self.window.lock().ok()?;
        let window = guard.as_ref()?;
        let size = window.outer_size().ok()?;
        let position = window.outer_position().unwrap_or_default();
        Some(WindowGeometry {
            width: size.width,
            height: size.height,
            x: position.x,
            y: position.y,
            maximized: window.is_maximized().unwrap_or(false),
            fullscreen: window.is_fullscreen().unwrap_or(false),
            visible: window.is_visible().unwrap_or(false),
        })
    }

    /// Cached resolution when known, otherwise the most specific candidate.
    /// Never probes: the status command is polled by the UI.
    fn interpreter_for_display(&self) -> String {
        if let Ok(cache) = self.interpreter.lock() {
            if let Some(candidate) = cache.as_ref() {
                return candidate.path.to_string_lossy().into_owned();
            }
        }
        self.config
            .interpreter_candidates()
            .first()
            .map(|candidate| candidate.path.to_string_lossy().into_owned())
            .unwrap_or_default()
    }
}

#[cfg(unix)]
fn signal_group(child: &Child, terminate: bool) {
    let signal = if terminate {
        libc::SIGTERM
    } else {
        libc::SIGKILL
    };
    // The launcher was spawned with process_group(0), so its pid is the pgid.
    unsafe {
        libc::kill(-(child.id() as i32), signal);
    }
}

#[cfg(windows)]
fn signal_group(child: &Child, _terminate: bool) {
    // taskkill /T is the only portable way to reach the launcher's own children
    // (uvicorn + Node); console processes get no CTRL_BREAK from here, so both
    // the graceful and the forced path use /F.
    let _ = Command::new("taskkill")
        .arg("/PID")
        .arg(child.id().to_string())
        .arg("/T")
        .arg("/F")
        .status();
}

fn json_string(value: &str) -> String {
    serde_json::to_string(value).unwrap_or_else(|_| "\"\"".to_string())
}

/// Self-test evaluated inside the loopback page, on demand.
///
/// Reports through `location.hash` because the interesting failure is "the
/// bridge is missing or the permission was refused", which IPC itself cannot
/// describe. It only *reads*: an earlier version also invoked `restart_service`
/// to prove the command was reachable, which meant every launch restarted the
/// local service a few seconds after the window appeared.
const PROBE_SCRIPT: &str = concat!(
    "(function () {",
    " var report = function (text) {",
    "  try { location.hash = 'deeptutorProbe=' + String(text).replace(/[^A-Za-z0-9_.:;=\\-]/g, '_'); } catch (e) {}",
    " };",
    " if (!window.__TAURI__ || !window.__TAURI__.core) { report('no-bridge'); return; }",
    " var parts = [];",
    " var expect = 3;",
    " var done = function () { if (parts.length >= expect) { report(parts.join(' ; ')); } };",
    " var push = function (label, value) { parts.push(label + '=' + value); done(); };",
    " var invoke = window.__TAURI__.core.invoke;",
    " invoke('plugin:app|version').then(",
    "  function (value) { push('core-app-ok', value); },",
    "  function (error) { push('core-app-error', error); });",
    " invoke('plugin:deeptutor|desktop_status').then(",
    "  function (value) { push('shell-cmd-ok', value && (value.launcher_running + ' launch=' + value.launch_count + ' restarts=' + value.restarts + ' win=' + (value.window ? value.window.width + 'x' + value.window.height : '-'))); },",
    "  function (error) { push('shell-cmd-error', error); });",
    // Phase 3 commands, called from the *loopback* document: Tauri's ACL only
    // covers plugin commands, so this is the check that the new permissions are
    // granted to the origin the real UI actually runs on.
    " invoke('plugin:deeptutor|shell_settings').then(",
    "  function (value) { push('shell-settings-ok', value && (value.close_to_tray + '/' + value.notifications + '/' + (value.locale || 'auto'))); },",
    "  function (error) { push('shell-settings-error', error); });",
    "})();"
);

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn env_map(pairs: &[(&str, &str)]) -> HashMap<String, String> {
        pairs
            .iter()
            .map(|(key, value)| ((*key).to_string(), (*value).to_string()))
            .collect()
    }

    fn config_with(pairs: &[(&str, &str)]) -> ShellConfig {
        let map = env_map(pairs);
        ShellConfig::resolve_with(&|key| map.get(key).cloned())
    }

    #[test]
    fn explicit_home_wins_and_owns_the_state_layout() {
        let config = config_with(&[
            ("DEEPTUTOR_HOME", "/tmp/deeptutor"),
            ("HOME", "/Users/example"),
        ]);
        assert_eq!(config.home, PathBuf::from("/tmp/deeptutor"));
        assert_eq!(
            config.state_path,
            PathBuf::from("/tmp/deeptutor/desktop/runtime.json")
        );
        assert_eq!(
            config.logs_dir,
            PathBuf::from("/tmp/deeptutor/desktop/logs")
        );
        // Workdir follows home unless the shell is pointed at a checkout.
        assert_eq!(config.workdir, PathBuf::from("/tmp/deeptutor"));
    }

    #[test]
    fn workdir_override_is_honoured() {
        let config = config_with(&[
            ("DEEPTUTOR_HOME", "/tmp/deeptutor"),
            ("DEEPTUTOR_DESKTOP_WORKDIR", "/src/DeepTutor"),
        ]);
        assert_eq!(config.workdir, PathBuf::from("/src/DeepTutor"));
        assert_eq!(config.home, PathBuf::from("/tmp/deeptutor"));
    }

    #[test]
    fn blank_environment_values_fall_through() {
        let config = config_with(&[("DEEPTUTOR_HOME", "   "), ("HOME", "/Users/example")]);
        assert!(config.home.ends_with("DeepTutor"));
    }

    #[test]
    fn platform_default_home_matches_documented_location() {
        let config = config_with(&[("HOME", "/Users/example")]);
        if cfg!(target_os = "macos") {
            assert_eq!(
                config.home,
                PathBuf::from("/Users/example/Library/Application Support/DeepTutor")
            );
        } else if !cfg!(windows) {
            assert_eq!(
                config.home,
                PathBuf::from("/Users/example/.local/share/DeepTutor")
            );
        }
    }

    #[test]
    fn bundled_venv_is_preferred_over_path_lookup() {
        let config = config_with(&[("DEEPTUTOR_HOME", "/tmp/deeptutor")]);
        let candidates = config.interpreter_candidates();
        assert!(candidates[0].path.to_string_lossy().contains(".venv"));
        assert_eq!(candidates[0].source, "<home>/.venv");
        // The last resort is whatever is on PATH; `resolve_interpreter` probes
        // it before it is ever used.
        assert_eq!(candidates.last().unwrap().source, "PATH");
    }

    #[test]
    fn workdir_venv_is_tried_after_the_app_data_venv() {
        let config = config_with(&[
            ("DEEPTUTOR_HOME", "/tmp/deeptutor"),
            ("DEEPTUTOR_DESKTOP_WORKDIR", "/src/DeepTutor"),
        ]);
        let sources: Vec<&str> = config
            .interpreter_candidates()
            .iter()
            .map(|candidate| candidate.source)
            .collect();
        assert_eq!(sources[0], "<home>/.venv");
        assert_eq!(sources[1], "<workdir>/.venv");
        assert_eq!(sources[2], "PATH");
    }

    #[test]
    fn workdir_equal_to_home_does_not_duplicate_candidates() {
        let config = config_with(&[("DEEPTUTOR_HOME", "/tmp/deeptutor")]);
        let sources: Vec<&str> = config
            .interpreter_candidates()
            .iter()
            .map(|candidate| candidate.source)
            .collect();
        assert_eq!(sources, vec!["<home>/.venv", "PATH", "PATH"]);
    }

    #[test]
    fn explicit_interpreter_is_the_first_candidate() {
        let config = config_with(&[
            ("DEEPTUTOR_HOME", "/tmp/deeptutor"),
            ("DEEPTUTOR_DESKTOP_PYTHON", "/opt/py/bin/python3"),
        ]);
        let candidates = config.interpreter_candidates();
        assert_eq!(candidates[0].source, "DEEPTUTOR_DESKTOP_PYTHON");
        assert_eq!(candidates[0].path, PathBuf::from("/opt/py/bin/python3"));
        assert!(candidates[0].must_exist);
    }

    /// The loopback IPC self-test evals into the live UI, so it must never run
    /// unless a diagnostic run asked for it.
    #[test]
    fn the_remote_ipc_probe_is_off_unless_asked_for() {
        assert!(!config_with(&[("DEEPTUTOR_HOME", "/tmp/deeptutor")]).probe_remote_ipc);
        for value in ["0", "false", "off", "", "  "] {
            let config = config_with(&[
                ("DEEPTUTOR_HOME", "/tmp/deeptutor"),
                ("DEEPTUTOR_DESKTOP_PROBE", value),
            ]);
            assert!(!config.probe_remote_ipc, "{value:?} must not enable it");
        }
        for value in ["1", "true", "yes", "on", " 1 "] {
            let config = config_with(&[
                ("DEEPTUTOR_HOME", "/tmp/deeptutor"),
                ("DEEPTUTOR_DESKTOP_PROBE", value),
            ]);
            assert!(config.probe_remote_ipc, "{value:?} must enable it");
        }
    }

    /// The navigation policy trusts exactly one loopback port, and learns it
    /// from the launcher's state file until the window has been handed over.
    #[test]
    fn the_expected_frontend_port_comes_from_the_launcher_state_file() {
        let home = temp_home("frontend-port");
        let config = ShellConfig::resolve_full(
            &|key| (key == "DEEPTUTOR_HOME").then(|| home.to_string_lossy().into_owned()),
            &|_| None,
        );
        let supervisor = Supervisor::new_shared(config);
        assert_eq!(supervisor.frontend_port(), None);

        fs::create_dir_all(home.join("desktop")).unwrap();
        fs::write(
            home.join("desktop").join("runtime.json"),
            r#"{"schema_version":1,"status":"ready","frontend_url":"http://127.0.0.1:4123"}"#,
        )
        .unwrap();
        assert_eq!(supervisor.frontend_port(), Some(4123));

        // Half-written or absent state stays "unknown" instead of guessing.
        fs::write(home.join("desktop").join("runtime.json"), "{ not json").unwrap();
        assert_eq!(supervisor.frontend_port(), None);
        let _ = fs::remove_dir_all(&home);
    }

    fn temp_home(name: &str) -> PathBuf {
        let home = std::env::temp_dir().join(format!(
            "deeptutor-supervisor-test-{name}-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&home);
        fs::create_dir_all(&home).expect("temp home");
        home
    }

    #[test]
    fn a_bootstrap_pointer_moves_the_data_directory() {
        let default = PathBuf::from("/Users/example/Library/Application Support/DeepTutor");
        let chosen = PathBuf::from("/Volumes/Data/DeepTutor");
        let map = env_map(&[("HOME", "/Users/example")]);
        let config = ShellConfig::resolve_full(&|key| map.get(key).cloned(), &|home: &Path| {
            (home == default).then(|| chosen.clone())
        });
        assert_eq!(config.home, chosen);
        // The pointer's own location never follows the pointer.
        assert_eq!(config.default_home, default);
        assert_eq!(
            config.state_path,
            chosen.join("desktop").join("runtime.json")
        );
        assert_eq!(config.workdir, chosen);
    }

    #[test]
    fn a_bootstrap_pointer_at_another_home_is_ignored_for_dev_overrides() {
        // `DEEPTUTOR_HOME` stays the search root for the pointer, so a checkout
        // run cannot be hijacked by a pointer in the real app-data home.
        let map = env_map(&[
            ("DEEPTUTOR_HOME", "/tmp/deeptutor"),
            ("HOME", "/Users/example"),
        ]);
        let config = ShellConfig::resolve_full(&|key| map.get(key).cloned(), &|home: &Path| {
            (home == Path::new("/Users/example")).then(|| PathBuf::from("/Volumes/Data/DeepTutor"))
        });
        assert_eq!(config.home, PathBuf::from("/tmp/deeptutor"));
        assert_eq!(config.default_home, PathBuf::from("/tmp/deeptutor"));
    }

    #[test]
    fn settings_patch_persists_and_gates_notifications() {
        let home = temp_home("patch");
        let config = ShellConfig::resolve_full(
            &|key| (key == "DEEPTUTOR_HOME").then(|| home.to_string_lossy().into_owned()),
            &|_| None,
        );
        let supervisor = Supervisor::new_shared(config);
        assert!(supervisor.shell_settings().notifications);

        let snapshot = supervisor
            .apply_settings_patch(SettingsPatch {
                notifications: Some(false),
                close_to_tray: Some(false),
                locale: Some("en".to_string()),
                ..SettingsPatch::default()
            })
            .expect("patch");
        assert!(!snapshot.notifications);
        assert!(!snapshot.close_to_tray);
        assert_eq!(snapshot.locale, "en");
        assert!(!supervisor.notifications.is_enabled());
        // Persisted, not just in memory.
        let reloaded = ShellSettings::load(&home);
        assert!(!reloaded.notifications);
        assert_eq!(reloaded.locale, "en");

        assert!(supervisor
            .apply_settings_patch(SettingsPatch {
                locale: Some("fr".to_string()),
                ..SettingsPatch::default()
            })
            .is_err());
        let _ = fs::remove_dir_all(&home);
    }

    /// The shell's own surfaces (dialogs, menu bar, the `detail` lines the
    /// settings page prints) follow the saved preference, so an English UI no
    /// longer gets Chinese dialogs.
    #[test]
    fn the_shell_language_follows_the_saved_preference() {
        let home = temp_home("locale");
        let config = ShellConfig::resolve_full(
            &|key| (key == "DEEPTUTOR_HOME").then(|| home.to_string_lossy().into_owned()),
            &|_| None,
        );
        let supervisor = Supervisor::new_shared(config);

        supervisor
            .apply_settings_patch(SettingsPatch {
                locale: Some("en".to_string()),
                ..SettingsPatch::default()
            })
            .expect("english");
        assert_eq!(supervisor.locale(), Locale::En);
        assert_eq!(supervisor.shell_settings().locale, "en");

        supervisor
            .apply_settings_patch(SettingsPatch {
                locale: Some("zh-CN".to_string()),
                ..SettingsPatch::default()
            })
            .expect("chinese");
        assert_eq!(supervisor.locale(), Locale::Zh);

        assert!(supervisor
            .apply_settings_patch(SettingsPatch {
                locale: Some("fr".to_string()),
                ..SettingsPatch::default()
            })
            .is_err());
        assert_eq!(
            supervisor.locale(),
            Locale::Zh,
            "a rejected value changes nothing"
        );
        let _ = fs::remove_dir_all(&home);
    }

    /// The notification command is reachable from the loopback page, so the
    /// shell bounds what it will draw and where it will navigate to.
    #[test]
    fn a_notification_request_is_validated_before_anything_is_posted() {
        let home = temp_home("notification");
        let config = ShellConfig::resolve_full(
            &|key| (key == "DEEPTUTOR_HOME").then(|| home.to_string_lossy().into_owned()),
            &|_| None,
        );
        let supervisor = Supervisor::new_shared(config);
        let request = |route: &str, title: &str, body: &str| NotificationRequest {
            title: title.to_string(),
            body: body.to_string(),
            route: route.to_string(),
            session_id: Some("s-1".to_string()),
            kind: Some("round_complete".to_string()),
        };

        for route in ["//evil.example", "https://evil.example", "chat/1", ""] {
            let error = supervisor
                .notify_round(request(route, "title", "body"))
                .expect_err(route);
            assert!(error.contains("应用内路径"), "{route}: {error}");
        }
        let long_title = "x".repeat(MAX_NOTIFICATION_TITLE + 1);
        assert!(supervisor
            .notify_round(request("/chat/1", &long_title, "body"))
            .is_err());
        assert!(supervisor
            .notify_round(request(
                "/chat/1",
                "title",
                &"y".repeat(MAX_NOTIFICATION_BODY + 1)
            ))
            .is_err());

        // A valid request gets past validation and only then fails for the
        // reason that matters here: there is no window in a unit test.
        let error = supervisor
            .notify_round(request("/chat/1", "title", "body"))
            .expect_err("no app handle");
        assert!(error.contains("应用句柄"), "{error}");
        let _ = fs::remove_dir_all(&home);
    }

    #[test]
    fn the_first_run_wizard_gates_and_then_releases_the_launcher() {
        let home = temp_home("first-run");
        let config = ShellConfig::resolve_full(
            &|key| (key == "DEEPTUTOR_HOME").then(|| home.to_string_lossy().into_owned()),
            &|_| None,
        );
        let supervisor = Supervisor::new_shared(config);

        let state = supervisor.first_run_state();
        assert!(!state.completed);
        assert!(state.can_change_data_dir);
        assert_eq!(state.home, home.to_string_lossy());
        assert!(supervisor.needs_first_run());

        let outcome = supervisor
            .apply_first_run(FirstRunChoices {
                locale: "en".to_string(),
                data_dir: None,
                close_to_tray: true,
                notifications: false,
            })
            .expect("apply");
        assert!(!outcome.restart_required);
        assert!(outcome.settings.first_run_completed);
        assert!(!outcome.settings.notifications);
        assert!(!supervisor.needs_first_run());
        let _ = fs::remove_dir_all(&home);
    }

    #[test]
    fn choosing_another_data_directory_asks_for_a_restart_and_keeps_the_answers() {
        let home = temp_home("data-dir");
        let target = home.join("elsewhere");
        let config = ShellConfig::resolve_full(
            &|key| (key == "DEEPTUTOR_HOME").then(|| home.to_string_lossy().into_owned()),
            &|_| None,
        );
        let supervisor = Supervisor::new_shared(config);
        let outcome = supervisor
            .apply_first_run(FirstRunChoices {
                locale: "zh-CN".to_string(),
                data_dir: Some(target.to_string_lossy().into_owned()),
                close_to_tray: false,
                notifications: true,
            })
            .expect("apply");
        assert!(outcome.restart_required);
        assert!(supervisor.shell_settings().restart_required);
        // The pointer lives in the default home; the answers travel with it, so
        // the relaunched shell does not ask again.
        assert_eq!(Bootstrap::read_home(&home), Some(target.clone()));
        let reloaded = ShellSettings::load(&target);
        assert!(reloaded.first_run_completed);
        assert!(!reloaded.close_to_tray);
        assert_eq!(reloaded.locale, "zh-CN");
        let _ = fs::remove_dir_all(&home);
    }

    #[test]
    fn a_relative_data_directory_is_refused() {
        let home = temp_home("relative");
        let config = ShellConfig::resolve_full(
            &|key| (key == "DEEPTUTOR_HOME").then(|| home.to_string_lossy().into_owned()),
            &|_| None,
        );
        let supervisor = Supervisor::new_shared(config);
        assert!(supervisor
            .apply_first_run(FirstRunChoices {
                locale: "en".to_string(),
                data_dir: Some("relative/path".to_string()),
                close_to_tray: true,
                notifications: true,
            })
            .is_err());
        // A refused answer must not mark the wizard as done.
        assert!(supervisor.needs_first_run());
        let _ = fs::remove_dir_all(&home);
    }
}
