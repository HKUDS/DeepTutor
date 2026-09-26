//! Runtime packs: the "no Python, no Node" install.
//!
//! A pack is a tarball containing a CPython, a virtualenv with DeepTutor in it,
//! the Node runtime and a manifest. Installing one is: verify the digest,
//! extract, rehydrate the venv for this machine, smoke test, then switch
//! atomically and keep the previous pack for rollback.
//!
//! Why rehydrate: a virtualenv written for one path does not survive being
//! moved. `uv venv --relocatable` marks `pyvenv.cfg`, but the interpreter link
//! and the `home` line are still absolute (measured on 2026-09-24). The
//! installer repairs exactly those self-references, so the build machine's
//! paths never have to match the user's.

use std::fs::{self, File};
use std::io::{Read, Write};
use std::path::{Component, Path, PathBuf};
use std::time::Duration;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::pack_tree::{
    clone_tree, create_symlink, move_file, remove_entry, safe_relative_path, tree_digest,
};

pub const MANIFEST_FILE: &str = "manifest.json";
pub const DELTA_FILE: &str = "delta.json";
pub const STATE_FILE: &str = "state.json";
pub const SCHEMA_VERSION: u32 = 1;
pub const DELTA_SCHEMA_VERSION: u32 = 1;
/// Guards against a pack that would unpack into an unrelated corner of the disk.
const MAX_ENTRY_COUNT: usize = 400_000;
/// Hard ceiling for one runtime archive; real packs are ~250 MB.
const MAX_DOWNLOAD_BYTES: u64 = 2 * 1024 * 1024 * 1024;
/// A wedged mirror must not leave a check or an install hanging forever.
const TEXT_TIMEOUT: Duration = Duration::from_secs(30);
const ARCHIVE_TIMEOUT: Duration = Duration::from_secs(30 * 60);

/// `manifest.json` inside a pack, written by `desktop/pack/build_pack.py`.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct PackManifest {
    pub schema_version: u32,
    pub pack_id: String,
    pub app_version: String,
    pub platform: String,
    #[serde(default)]
    pub created_at: Option<String>,
    #[serde(default)]
    pub python: Option<PackComponent>,
    #[serde(default)]
    pub node: Option<PackComponent>,
    pub paths: PackPaths,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct PackComponent {
    #[serde(default)]
    pub version: Option<String>,
    #[serde(default)]
    pub source: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct PackPaths {
    /// Interpreter relative to the pack root, e.g. `venv/bin/python`.
    pub python: String,
    /// Directory prepended to `PATH` so the launcher finds `node`.
    pub node_dir: String,
}

impl PackManifest {
    pub fn read(pack_dir: &Path) -> Result<Self, String> {
        let path = pack_dir.join(MANIFEST_FILE);
        let text = fs::read_to_string(&path)
            .map_err(|error| format!("无法读取 {}: {error}", path.display()))?;
        let manifest: Self = serde_json::from_str(&text)
            .map_err(|error| format!("{} 不是合法的 pack 清单: {error}", path.display()))?;
        if manifest.schema_version != SCHEMA_VERSION {
            return Err(format!(
                "pack 清单版本 {} 不受支持（期望 {SCHEMA_VERSION}）",
                manifest.schema_version
            ));
        }
        manifest.validate()?;
        Ok(manifest)
    }

    /// Everything a manifest claims must stay inside the pack it came with.
    ///
    /// `pack_id` becomes a directory name under `runtimes/` (and the target of a
    /// `remove_dir_all` + `rename`), while the two component paths are joined
    /// onto the pack root and then executed. `Path::join` silently *replaces*
    /// its base when handed an absolute path, so an unvalidated manifest could
    /// name any directory on the disk or any binary on it.
    fn validate(&self) -> Result<(), String> {
        safe_pack_id(&self.pack_id)?;
        safe_relative_path(&self.paths.python)
            .map_err(|error| format!("pack 清单里的解释器路径不合法：{error}"))?;
        safe_relative_path(&self.paths.node_dir)
            .map_err(|error| format!("pack 清单里的 Node 路径不合法：{error}"))?;
        Ok(())
    }

    pub fn python_path(&self, pack_dir: &Path) -> PathBuf {
        pack_dir.join(&self.paths.python)
    }

    pub fn node_dir(&self, pack_dir: &Path) -> PathBuf {
        pack_dir.join(&self.paths.node_dir)
    }
}

/// A pack id names exactly one directory directly under `runtimes/`.
///
/// Anything else — absolute, dotted, nested, padded with whitespace — would let
/// an archive choose a directory outside the runtime tree to replace.
fn safe_pack_id(pack_id: &str) -> Result<(), String> {
    let invalid = || format!("运行时包 ID 不合法：{pack_id:?}（必须是单个目录名）");
    if pack_id.is_empty() || pack_id.trim() != pack_id || pack_id.contains('\0') {
        return Err(invalid());
    }
    let mut components = Path::new(pack_id).components();
    match (components.next(), components.next()) {
        (Some(Component::Normal(_)), None) => Ok(()),
        _ => Err(invalid()),
    }
}

/// Parses a minisign public key in any of the shapes a user might paste.
///
/// The shell plane's key lives in `tauri.conf.json` as base64 of the whole
/// `.pub` file, the file itself is two lines of text, and the second line is the
/// key on its own. All three are accepted so provisioning is copy-paste.
pub fn parse_minisign_public_key(text: &str) -> Result<minisign_verify::PublicKey, String> {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return Err("minisign 公钥为空".to_string());
    }
    if trimmed.contains("untrusted comment") {
        return minisign_verify::PublicKey::decode(trimmed)
            .map_err(|error| format!("minisign 公钥无法解析: {error}"));
    }
    if let Ok(key) = minisign_verify::PublicKey::from_base64(trimmed) {
        return Ok(key);
    }
    // Tauri stores the base64 of the *file*, not of the key line.
    let decoded =
        base64_decode(trimmed).ok_or_else(|| "minisign 公钥不是合法 base64".to_string())?;
    let decoded = String::from_utf8(decoded)
        .map_err(|_| "minisign 公钥既不是 key，也不是 .pub 文件内容".to_string())?;
    minisign_verify::PublicKey::decode(decoded.trim())
        .map_err(|error| format!("minisign 公钥无法解析: {error}"))
}

fn base64_decode(text: &str) -> Option<Vec<u8>> {
    use base64::Engine as _;
    base64::engine::general_purpose::STANDARD
        .decode(text.as_bytes())
        .ok()
}

/// Verify a detached minisign signature over `message`.
pub fn verify_minisign(
    public_key: &str,
    message: &[u8],
    signature_text: &str,
) -> Result<(), String> {
    let key = parse_minisign_public_key(public_key)?;
    let signature = minisign_verify::Signature::decode(signature_text)
        .map_err(|error| format!("签名文件无法解析: {error}"))?;
    // `true` accepts the classic (non-prehashed) form, which is what minisign
    // and `tauri signer sign` produce for a file this size.
    key.verify(message, &signature, true)
        .map_err(|error| format!("签名校验不通过: {error}"))
}

/// Which pack is active, and what to fall back to.
#[derive(Debug, Clone, Default, PartialEq, Eq, Deserialize, Serialize)]
pub struct PackState {
    #[serde(default = "default_schema_version")]
    pub schema_version: u32,
    #[serde(default)]
    pub active_pack: Option<String>,
    #[serde(default)]
    pub previous_pack: Option<String>,
}

fn default_schema_version() -> u32 {
    SCHEMA_VERSION
}

/// One entry of `runtime-packs.json`, the release catalog.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct PackRelease {
    pub pack_id: String,
    #[serde(default)]
    pub app_version: String,
    pub platform: String,
    pub url: String,
    pub sha256: String,
    #[serde(default)]
    pub size: u64,
    #[serde(default)]
    pub requires_shell: Option<String>,
    /// Incremental path from one specific base pack, when the release ships one.
    #[serde(default)]
    pub delta: Option<PackDeltaRelease>,
}

/// The delta half of a catalog entry: how to get here from a pack you already have.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct PackDeltaRelease {
    /// The exact pack this delta was built against. A different base means the
    /// full archive is used instead.
    pub base_pack_id: String,
    pub url: String,
    pub sha256: String,
    #[serde(default)]
    pub size: u64,
}

/// One file a delta adds or replaces.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct PackDeltaEntry {
    /// Relative to the pack root, `/`-separated.
    pub path: String,
    #[serde(default)]
    pub size: u64,
    /// sha256 of the file's bytes *as shipped* (not path-normalised).
    pub sha256: String,
}

/// A symlink the target tree has and the base did not (or had differently).
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct PackDeltaLink {
    pub path: String,
    pub target: String,
}

/// `delta.json` inside a delta archive, written by `desktop/pack/build_delta.py`.
///
/// Everything here is a cross-check: the file hashes prove the payload, and the
/// tree fingerprints prove the base. A delta that describes a *different* pack
/// than the one installed is refused, never merged.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct PackDelta {
    pub schema_version: u32,
    pub base_pack_id: String,
    pub target_pack_id: String,
    pub platform: String,
    #[serde(default)]
    pub app_version: String,
    /// Absolute paths the two trees were staged at on the build machine.
    /// Everything outside `venv/` keeps these forever, so the fingerprint has to
    /// tokenise them on the installed copy too.
    #[serde(default)]
    pub base_root: String,
    #[serde(default)]
    pub target_root: String,
    /// Fingerprint of the base tree, computed with rehydration-normalised
    /// content so it matches the pack as *installed* (see [`tree_digest`]).
    pub base_tree_sha256: String,
    #[serde(default)]
    pub base_file_count: u64,
    #[serde(default)]
    pub base_total_size: u64,
    /// Fingerprint the tree must have once the delta has been applied.
    pub target_tree_sha256: String,
    #[serde(default)]
    pub added: Vec<PackDeltaEntry>,
    #[serde(default)]
    pub changed: Vec<PackDeltaEntry>,
    #[serde(default)]
    pub removed: Vec<String>,
    #[serde(default)]
    pub links: Vec<PackDeltaLink>,
}

impl PackDelta {
    pub fn read(directory: &Path) -> Result<Self, String> {
        let path = directory.join(DELTA_FILE);
        let text = fs::read_to_string(&path)
            .map_err(|error| format!("无法读取 {}: {error}", path.display()))?;
        let delta: Self = serde_json::from_str(&text)
            .map_err(|error| format!("{} 不是合法的增量清单: {error}", path.display()))?;
        if delta.schema_version != DELTA_SCHEMA_VERSION {
            return Err(format!(
                "增量清单版本 {} 不受支持（期望 {DELTA_SCHEMA_VERSION}）",
                delta.schema_version
            ));
        }
        Ok(delta)
    }

    /// Every path the delta may write or delete.
    pub fn touched_paths(&self) -> impl Iterator<Item = &str> {
        self.added
            .iter()
            .chain(self.changed.iter())
            .map(|entry| entry.path.as_str())
            .chain(self.links.iter().map(|link| link.path.as_str()))
            .chain(self.removed.iter().map(String::as_str))
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
pub struct PackCatalog {
    #[serde(default = "default_schema_version")]
    pub schema_version: u32,
    pub packs: Vec<PackRelease>,
}

/// Ordering key for a version string: `(dotted numbers, is a release)`.
///
/// The second element is what makes `1.6.11-rc1` sort *below* `1.6.11`. Splitting
/// on `-` and parsing the suffix as a number gave the candidate a trailing `0`,
/// so it compared as newer than the release it precedes — a catalog carrying both
/// would have offered the release candidate to everyone already on the release.
///
/// Build metadata (`+build`) is ignored, as SemVer requires: it does not affect
/// precedence.
fn version_key(version: &str) -> (Vec<u64>, bool) {
    let trimmed = version.trim_start_matches('v');
    let core = trimmed.split(['-', '+']).next().unwrap_or(trimmed);
    let numbers = core
        .split('.')
        .map(|part| part.parse::<u64>().unwrap_or(0))
        .collect();
    (numbers, !trimmed.contains('-'))
}

/// The newest catalog entry for this host, when it beats what is active.
///
/// Shared by the installing path and the read-only one so "check" and "update"
/// can never disagree about which release they mean.
fn newest_for_host(
    catalog: &PackCatalog,
    active_version: &str,
) -> Result<Option<PackRelease>, String> {
    let host = host_platform();
    let mut candidates: Vec<&PackRelease> = catalog
        .packs
        .iter()
        .filter(|release| release.platform == host)
        .collect();
    candidates.sort_by_key(|release| version_key(&release.app_version));
    let Some(best) = candidates.last() else {
        return Err(format!("清单里没有适用于 {host} 的运行时包"));
    };
    if version_key(&best.app_version) <= version_key(active_version) {
        log(&format!(
            "active pack {active_version} is already the newest for {host}"
        ));
        return Ok(None);
    }
    Ok(Some((*best).clone()))
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InstalledPack {
    pub pack_id: String,
    pub dir: PathBuf,
    pub manifest: PackManifest,
}

/// Installs and switches packs under `<home>/runtimes`.
pub struct PackInstaller {
    runtimes_dir: PathBuf,
    state_path: PathBuf,
    /// minisign public key the runtime catalog must be signed with.
    ///
    /// `None` means "not configured": the catalog is still read, but the shell
    /// logs that it is unverified. See [`PackInstaller::with_catalog_pubkey`].
    catalog_pubkey: Option<String>,
}

impl PackInstaller {
    pub fn new(home: &Path) -> Self {
        Self {
            runtimes_dir: home.join("runtimes"),
            state_path: home.join("desktop").join(STATE_FILE),
            catalog_pubkey: None,
        }
    }

    /// Require every catalog read to carry a valid minisign signature.
    ///
    /// The catalog names both the archive and the sha256 that authenticates it,
    /// so signing the catalog is what turns "TLS to some host" into "the release
    /// key approved these bytes". The archive URLs do not need their own
    /// signatures: their digests travel inside the signed document.
    pub fn with_catalog_pubkey(mut self, public_key: Option<String>) -> Self {
        self.catalog_pubkey = public_key.filter(|key| !key.trim().is_empty());
        self
    }

    pub fn state(&self) -> PackState {
        fs::read_to_string(&self.state_path)
            .ok()
            .and_then(|text| serde_json::from_str(&text).ok())
            .unwrap_or_default()
    }

    fn write_state(&self, state: &PackState) -> Result<(), String> {
        if let Some(parent) = self.state_path.parent() {
            fs::create_dir_all(parent).map_err(|error| format!("无法创建状态目录: {error}"))?;
        }
        let text = serde_json::to_string_pretty(state).map_err(|error| error.to_string())?;
        fs::write(&self.state_path, text + "\n")
            .map_err(|error| format!("无法写入 {}: {error}", self.state_path.display()))
    }

    pub fn active(&self) -> Option<InstalledPack> {
        self.state().active_pack.and_then(|id| self.load(&id).ok())
    }

    /// The directory one pack id names. Validated here as well as in
    /// [`PackManifest::read`], because the id can also arrive from
    /// `desktop/state.json` rather than from an archive.
    fn pack_dir(&self, pack_id: &str) -> Result<PathBuf, String> {
        safe_pack_id(pack_id)?;
        Ok(self.runtimes_dir.join(pack_id))
    }

    pub fn load(&self, pack_id: &str) -> Result<InstalledPack, String> {
        let dir = self.pack_dir(pack_id)?;
        let manifest = PackManifest::read(&dir)?;
        Ok(InstalledPack {
            pack_id: manifest.pack_id.clone(),
            dir,
            manifest,
        })
    }

    /// Pack ids present under `<home>/runtimes`, oldest name first.
    pub fn installed(&self) -> Vec<String> {
        let Ok(entries) = fs::read_dir(&self.runtimes_dir) else {
            return Vec::new();
        };
        let mut packs: Vec<String> = entries
            .flatten()
            .filter(|entry| entry.path().is_dir())
            .filter_map(|entry| entry.file_name().to_str().map(str::to_string))
            .filter(|name| !name.starts_with('.'))
            .collect();
        packs.sort();
        packs
    }

    /// Read the release catalog from a URL or a local path.
    ///
    /// Verifies the detached minisign signature first when a public key is
    /// configured; a catalog that is unsigned, signed by another key, or edited
    /// after signing is refused before any of its URLs are trusted.
    pub fn catalog(&self, source: &str) -> Result<PackCatalog, String> {
        let text = fetch_text(source)?;
        self.verify_catalog(source, &text)?;
        let catalog: PackCatalog =
            serde_json::from_str(&text).map_err(|error| format!("清单解析失败: {error}"))?;
        if catalog.schema_version != SCHEMA_VERSION {
            return Err(format!(
                "清单版本 {} 不受支持（期望 {SCHEMA_VERSION}）",
                catalog.schema_version
            ));
        }
        Ok(catalog)
    }

    fn verify_catalog(&self, source: &str, text: &str) -> Result<(), String> {
        let Some(public_key) = self.catalog_pubkey.as_deref() else {
            log("runtime catalog is not signature-verified (no minisign public key configured)");
            return Ok(());
        };
        let (signature_source, signature) = fetch_catalog_signature(source)?;
        verify_minisign(public_key, text.as_bytes(), &signature).map_err(|error| {
            format!("运行时包清单验签失败（{source} 的签名取自 {signature_source}）：{error}")
        })?;
        log(&format!(
            "runtime catalog signature ok ({signature_source})"
        ));
        Ok(())
    }

    /// Install the newest catalog pack for this platform, if it is newer than
    /// what is active. Returns `None` when already up to date.
    ///
    /// When the catalog offers a delta against the pack that is *currently*
    /// active, that is used instead of the full archive: the delta is a few
    /// percent of the download, and it is refused (falling back to the full
    /// pack) whenever the base is not exactly what it was cut against.
    pub fn update_from_catalog(&self, source: &str) -> Result<Option<InstalledPack>, String> {
        let catalog = self.catalog(source)?;
        let Some(best) = newest_for_host(&catalog, self.active_version().as_str())? else {
            return Ok(None);
        };
        if let Some(delta) = &best.delta {
            if self.active().map(|pack| pack.pack_id) == Some(delta.base_pack_id.clone()) {
                let url = resolve_relative(source, &delta.url);
                log(&format!(
                    "updating {} -> {} with a delta ({} MB instead of a full pack)",
                    delta.base_pack_id,
                    best.pack_id,
                    delta.size / (1024 * 1024)
                ));
                match self.install_delta_from_url(&url, &delta.sha256, Some(delta.size)) {
                    Ok(pack) => return Ok(Some(pack)),
                    Err(error) => {
                        // An unusable delta must not cost the user the update:
                        // log it and take the long way round.
                        log(&format!(
                            "delta update failed ({error}); falling back to the full pack"
                        ));
                    }
                }
            }
        }
        let url = resolve_relative(source, &best.url);
        let pack = self.install_from_url(&url, &best.sha256, Some(best.size))?;
        Ok(Some(pack))
    }

    /// The catalog entry a user would be offered, without downloading anything.
    ///
    /// "Check for updates" has to be able to answer before it acts, and the
    /// headless `--check-updates` gate must never install.
    pub fn outdated_from_catalog(&self, source: &str) -> Result<Option<PackRelease>, String> {
        let catalog = self.catalog(source)?;
        newest_for_host(&catalog, self.active_version().as_str())
    }

    /// Whether `release`'s delta can be applied to the pack that is active now.
    ///
    /// The check reports the download the user would actually take: an
    /// applicable delta is a fraction of the full pack, and announcing 250 MB
    /// when the update is 20 MB would make the check look worse than it is.
    pub fn delta_applies(&self, release: &PackRelease) -> bool {
        let Some(delta) = &release.delta else {
            return false;
        };
        self.active().map(|pack| pack.pack_id) == Some(delta.base_pack_id.clone())
    }

    fn active_version(&self) -> String {
        self.active()
            .map(|pack| pack.manifest.app_version)
            .unwrap_or_default()
    }

    /// Install an archive that is already on disk (the "fat installer" path).
    /// `expected_sha256` comes from the release catalog; a mismatch aborts
    /// before anything is written.
    pub fn install_archive(
        &self,
        archive: &Path,
        expected_sha256: Option<&str>,
    ) -> Result<InstalledPack, String> {
        if let Some(expected) = expected_sha256 {
            let actual = sha256_file(archive)?;
            if !actual.eq_ignore_ascii_case(expected) {
                return Err(format!(
                    "运行时包校验失败：期望 {expected}，实际 {actual}（已拒绝安装）"
                ));
            }
        }
        sweep_stale_staging(&self.runtimes_dir);
        let staging = self
            .runtimes_dir
            .join(format!(".incoming-{}", std::process::id()));
        if staging.exists() {
            fs::remove_dir_all(&staging).map_err(|error| error.to_string())?;
        }
        fs::create_dir_all(&staging).map_err(|error| format!("无法创建暂存目录: {error}"))?;
        // Everything below can fail on a pack that is merely unusual, and a
        // staging tree is most of a gigabyte: it must not survive the failure.
        let outcome = self.install_into(&staging, archive);
        if outcome.is_err() {
            let _ = fs::remove_dir_all(&staging);
        }
        outcome
    }

    fn install_into(&self, staging: &Path, archive: &Path) -> Result<InstalledPack, String> {
        extract_tar_gz(archive, staging)?;
        let manifest = PackManifest::read(staging)?;
        let host = host_platform();
        if manifest.platform != host {
            return Err(format!(
                "这个运行时包是为 {} 构建的，本机是 {host}",
                manifest.platform
            ));
        }
        // Where the archive was staged on the build machine, captured before
        // rehydration overwrites the only record of it.
        let build_root = pack_root_from_cfg(staging);
        rehydrate(staging)?;
        smoke_test(staging, &manifest)?;

        let target = self.pack_dir(&manifest.pack_id)?;
        if target.exists() {
            fs::remove_dir_all(&target).map_err(|error| error.to_string())?;
        }
        fs::rename(staging, &target)
            .map_err(|error| format!("无法就位 {}: {error}", target.display()))?;
        // The tree just moved, and a pack's self-references are absolute:
        // `pyvenv.cfg`'s `home`, entry-point shebangs and the `.dist-info`
        // metadata all name the pack's own directory. Rehydrating only before
        // the rename left every installed pack pointing at its staging path
        // (found on 2026-09-24 while fingerprinting a pack for an incremental
        // update). Do it again here, where the pack actually lives, and smoke
        // test the result rather than trusting the pre-move one.
        rehydrate(&target)?;
        // Everything rehydration does not touch (the CPython tree, wheel
        // metadata) still names the build machine; canonicalising it here is
        // what lets this install be the base of *another* delta later.
        let mut stale = Vec::new();
        if let Some(build_root) = build_root {
            stale.push(build_root);
        }
        stale.push(staging.to_path_buf());
        canonicalise(&target, &stale)?;
        smoke_test(&target, &manifest)?;
        self.activate(&manifest.pack_id)?;
        log(&format!("runtime pack {} installed", manifest.pack_id));
        self.load(&manifest.pack_id)
    }

    /// Download then install: the "slim installer + fetch on first run" path,
    /// and how runtime-only updates arrive.
    pub fn install_from_url(
        &self,
        url: &str,
        expected_sha256: &str,
        expected_size: Option<u64>,
    ) -> Result<InstalledPack, String> {
        let downloads = self.runtimes_dir.join(".downloads");
        fs::create_dir_all(&downloads).map_err(|error| error.to_string())?;
        let target = download_target(&downloads, "runtime-pack");
        log(&format!("fetching runtime pack from {url}"));
        let outcome = fetch_archive(url, &target, expected_size)
            .and_then(|()| self.install_archive(&target, Some(expected_sha256)));
        // The archive is only useful for this install. Deleting it here (rather
        // than on the happy path) is what keeps a failed 250 MB download from
        // sitting in `.downloads` forever.
        let _ = fs::remove_file(&target);
        outcome
    }

    /// Point the shell at `pack_id`, remembering the outgoing pack for rollback.
    pub fn activate(&self, pack_id: &str) -> Result<(), String> {
        self.load(pack_id)?;
        let mut state = self.state();
        if state.active_pack.as_deref() != Some(pack_id) {
            state.previous_pack = state.active_pack.take();
            state.active_pack = Some(pack_id.to_string());
            state.schema_version = SCHEMA_VERSION;
        }
        self.write_state(&state)
    }

    /// Return to the pack that was active before the last switch.
    pub fn rollback(&self) -> Result<InstalledPack, String> {
        let mut state = self.state();
        let Some(previous) = state.previous_pack.clone() else {
            return Err("没有可回滚的运行时包".to_string());
        };
        let pack = self.load(&previous)?;
        std::mem::swap(&mut state.active_pack, &mut state.previous_pack);
        self.write_state(&state)?;
        log(&format!("rolled back to runtime pack {previous}"));
        Ok(pack)
    }

    /// Install an incremental update on top of the pack that is active.
    ///
    /// Unlike [`PackInstaller::install_archive`], the payload is a *patch*: the
    /// new tree is the installed pack plus the delta's files. That is why the
    /// base is fingerprinted first and the result is fingerprinted again — an
    /// incremental update is only safe if both ends are the ones the builder
    /// signed off on.
    pub fn install_delta_archive(
        &self,
        archive: &Path,
        expected_sha256: Option<&str>,
    ) -> Result<InstalledPack, String> {
        if let Some(expected) = expected_sha256 {
            let actual = sha256_file(archive)?;
            if !actual.eq_ignore_ascii_case(expected) {
                return Err(format!(
                    "增量包校验失败：期望 {expected}，实际 {actual}（已拒绝安装）"
                ));
            }
        }
        sweep_stale_staging(&self.runtimes_dir);
        let staging = self
            .runtimes_dir
            .join(format!(".delta-incoming-{}", std::process::id()));
        if staging.exists() {
            fs::remove_dir_all(&staging).map_err(|error| error.to_string())?;
        }
        fs::create_dir_all(&staging).map_err(|error| format!("无法创建暂存目录: {error}"))?;
        match self.apply_delta(archive, &staging) {
            Ok(pack) => {
                let _ = fs::remove_dir_all(&staging);
                Ok(pack)
            }
            Err(error) => {
                // The live pack is untouched: everything happened in staging.
                let _ = fs::remove_dir_all(&staging);
                Err(error)
            }
        }
    }

    /// Download then apply: how an incremental runtime update arrives.
    pub fn install_delta_from_url(
        &self,
        url: &str,
        expected_sha256: &str,
        expected_size: Option<u64>,
    ) -> Result<InstalledPack, String> {
        let downloads = self.runtimes_dir.join(".downloads");
        fs::create_dir_all(&downloads).map_err(|error| error.to_string())?;
        let target = download_target(&downloads, "runtime-delta");
        log(&format!("fetching runtime delta from {url}"));
        let outcome = fetch_archive(url, &target, expected_size)
            .and_then(|()| self.install_delta_archive(&target, Some(expected_sha256)));
        let _ = fs::remove_file(&target);
        outcome
    }

    fn apply_delta(&self, archive: &Path, staging: &Path) -> Result<InstalledPack, String> {
        let started = std::time::Instant::now();
        extract_tar_gz(archive, staging)?;
        let delta = PackDelta::read(staging)?;
        log(&format!(
            "delta {} -> {}: {} added, {} changed, {} removed (unpacked in {:.1}s)",
            delta.base_pack_id,
            delta.target_pack_id,
            delta.added.len(),
            delta.changed.len(),
            delta.removed.len(),
            started.elapsed().as_secs_f32()
        ));

        // Every path is checked before anything is written: a delta that names
        // one unsafe path must not leave a half-patched tree behind.
        for path in delta.touched_paths() {
            safe_relative_path(path)?;
        }

        let active = self
            .active()
            .ok_or_else(|| "没有已安装的运行时包可以作为增量更新的基线".to_string())?;
        if delta.base_pack_id != active.pack_id {
            return Err(format!(
                "这个增量包是为 {} 准备的，本机当前是 {}；请下载完整运行时包",
                delta.base_pack_id, active.pack_id
            ));
        }
        if delta.platform != host_platform() {
            return Err(format!(
                "这个增量包是为 {} 构建的，本机是 {}",
                delta.platform,
                host_platform()
            ));
        }

        // The base must be the build the delta was cut against, not merely a
        // pack with the same name: a half-written or hand-edited pack would
        // otherwise be patched into something that only looks right.
        // The installed base still carries the *build* directory in everything
        // rehydration does not touch (the delta names it for exactly this
        // reason), so both spellings are tokenised before comparing.
        let stale = [delta.base_root.clone()];
        let base = tree_digest(&active.dir, &stale)?;
        log(&format!(
            "delta: base fingerprint {} files / {} MB in {:.1}s",
            base.files,
            base.bytes / (1024 * 1024),
            started.elapsed().as_secs_f32()
        ));
        if base.files != delta.base_file_count || base.bytes != delta.base_total_size {
            return Err(format!(
                "基线包内容与增量不匹配（文件数 {}/{}，大小 {}/{}）",
                base.files, delta.base_file_count, base.bytes, delta.base_total_size
            ));
        }
        if base.sha256 != delta.base_tree_sha256 {
            return Err("基线包指纹与增量不匹配（基线可能已损坏或来自别的构建）".to_string());
        }

        // Everything below happens inside `staging`; the live pack stays as it is
        // until the very last rename.
        let tree = staging.join("tree");
        clone_tree(&active.dir, &tree)?;
        log(&format!(
            "delta: base cloned (hard links) in {:.1}s",
            started.elapsed().as_secs_f32()
        ));

        let payload = staging.join("files");
        for entry in delta.added.iter().chain(delta.changed.iter()) {
            let relative = safe_relative_path(&entry.path)?;
            let source = payload.join(&relative);
            let actual =
                sha256_file(&source).map_err(|_| format!("增量包缺少文件 {}", entry.path))?;
            if !actual.eq_ignore_ascii_case(&entry.sha256) {
                return Err(format!(
                    "增量文件校验失败：{}（期望 {}，实际 {actual}）",
                    entry.path, entry.sha256
                ));
            }
            let destination = tree.join(&relative);
            if let Some(parent) = destination.parent() {
                fs::create_dir_all(parent).map_err(|error| error.to_string())?;
            }
            if destination.symlink_metadata().is_ok() {
                remove_entry(&destination)?;
            }
            move_file(&source, &destination)?;
        }

        for link in &delta.links {
            let relative = safe_relative_path(&link.path)?;
            let destination = tree.join(&relative);
            if let Some(parent) = destination.parent() {
                fs::create_dir_all(parent).map_err(|error| error.to_string())?;
            }
            if destination.symlink_metadata().is_ok() {
                remove_entry(&destination)?;
            }
            create_symlink(&link.target, &destination)?;
        }

        for path in &delta.removed {
            let relative = safe_relative_path(path)?;
            let victim = tree.join(&relative);
            if victim.symlink_metadata().is_ok() {
                remove_entry(&victim)?;
            }
        }

        // The applied tree is a mix of three spellings: files that were already
        // in the installed base still say *their* directory (rehydration
        // rewrote the venv when that pack was installed), everything rehydration
        // never touched says the base's build directory, and the delta's own
        // files say the target's build directory.
        let applied_roots = [
            delta.base_root.clone(),
            delta.target_root.clone(),
            active.dir.to_string_lossy().into_owned(),
        ];
        let applied = tree_digest(&tree, &applied_roots)?;
        log(&format!(
            "delta: applied and re-fingerprinted in {:.1}s",
            started.elapsed().as_secs_f32()
        ));
        if applied.sha256 != delta.target_tree_sha256 {
            return Err(format!(
                "应用增量后的目录树与目标不一致（{} 个文件，{} 字节）",
                applied.files, applied.bytes
            ));
        }

        let manifest = PackManifest::read(&tree)?;
        if manifest.pack_id != delta.target_pack_id {
            return Err(format!(
                "增量包声明的目标是 {}，清单里却是 {}",
                delta.target_pack_id, manifest.pack_id
            ));
        }
        rehydrate(&tree)?;
        smoke_test(&tree, &manifest)?;

        let target = self.pack_dir(&manifest.pack_id)?;
        if target.exists() {
            fs::remove_dir_all(&target).map_err(|error| error.to_string())?;
        }
        fs::rename(&tree, &target)
            .map_err(|error| format!("无法就位 {}: {error}", target.display()))?;
        // Same lesson as `install_archive`: the pack's self-references must name
        // where it ended up, not where it was assembled.
        rehydrate(&target)?;
        // The applied tree is a mix of spellings: unchanged files still name the
        // pack this one descends from (or *its* build machine), and the delta's
        // own files name the build machine of this release. Canonicalising turns
        // all of them into this pack's directory, so this install can itself be
        // the base of the next delta instead of being refused by the fingerprint
        // check (`stale_roots` only ever knows one build root).
        canonicalise(
            &target,
            &[
                PathBuf::from(&delta.base_root),
                PathBuf::from(&delta.target_root),
                active.dir.clone(),
            ],
        )?;
        smoke_test(&target, &manifest)?;
        self.activate(&manifest.pack_id)?;
        log(&format!(
            "runtime pack {} installed from delta off {}",
            manifest.pack_id, delta.base_pack_id
        ));
        self.load(&manifest.pack_id)
    }
}

/// Remove staging trees a crashed run left behind.
///
/// They are ours by name (`.incoming-<pid>` / `.delta-incoming-<pid>`), so a
/// different pid than this process means a previous run died mid-install. The
/// current process's own staging is left alone.
fn sweep_stale_staging(runtimes_dir: &Path) {
    let current = std::process::id().to_string();
    let Ok(entries) = fs::read_dir(runtimes_dir) else {
        return;
    };
    for entry in entries.flatten() {
        let name = entry.file_name().to_string_lossy().into_owned();
        let stale = [".incoming-", ".delta-incoming-"]
            .iter()
            .any(|prefix| name.starts_with(prefix) && !name.ends_with(&current));
        if stale {
            let _ = fs::remove_dir_all(entry.path());
        }
    }
}

/// Where a downloaded archive is staged before it is verified and unpacked.
///
/// Deliberately *not* the URL's last segment: a catalog chooses that string, and
/// on Windows `..\..\AppData\Roaming\...\evil.bat` is a legal file *name* that
/// `Path::join` would happily resolve into a write outside the download
/// directory. The archive's own name never matters — only its bytes do.
fn download_target(downloads: &Path, kind: &str) -> PathBuf {
    downloads.join(format!("{kind}-{}.tar.gz", std::process::id()))
}

/// Download the catalog's detached signature.
///
/// `<catalog>.sig` is what `tauri signer sign` and minisign write, and
/// `<catalog>.minisig` is the spelling this repository's docs use; both are
/// looked up so the release job can produce either.
fn fetch_catalog_signature(source: &str) -> Result<(String, String), String> {
    let mut tried = Vec::new();
    for suffix in [".sig", ".minisig"] {
        let candidate = format!("{source}{suffix}");
        match fetch_text(&candidate) {
            Ok(text) => return Ok((candidate, text)),
            Err(error) => tried.push(format!("{candidate}: {error}")),
        }
    }
    Err(format!(
        "清单没有签名，已拒绝使用（找过 {}）",
        tried.join("；")
    ))
}

/// Read a catalog/archive location: `http(s)` goes over the network, anything
/// else is a path on disk (which is what a local test or an offline install
/// uses).
fn fetch_text(source: &str) -> Result<String, String> {
    if source.starts_with("http://") || source.starts_with("https://") {
        let response = ureq::get(source)
            .timeout(TEXT_TIMEOUT)
            .call()
            .map_err(|error| format!("读取 {source} 失败: {error}"))?;
        return response
            .into_string()
            .map_err(|error| format!("读取 {source} 失败: {error}"));
    }
    fs::read_to_string(source).map_err(|error| format!("无法读取 {source}: {error}"))
}

/// Bring an archive (full pack or delta) into `target`, from the network or
/// from disk.
///
/// A catalog's URLs are resolved against the catalog's own location, so an
/// offline mirror — or a local test catalog — yields plain paths. Those used to
/// fail inside the HTTP client ("relative URL without a base"), which meant a
/// file-based catalog could be *read* but never *used*.
fn fetch_archive(source: &str, target: &Path, expected_size: Option<u64>) -> Result<(), String> {
    let written = if source.starts_with("http://") || source.starts_with("https://") {
        let response = ureq::get(source)
            .timeout(ARCHIVE_TIMEOUT)
            .call()
            .map_err(|error| format!("下载 {source} 失败: {error}"))?;
        let mut reader = response.into_reader();
        let mut file = File::create(target).map_err(|error| error.to_string())?;
        let mut written = 0u64;
        let mut buffer = [0u8; 256 * 1024];
        loop {
            let read = reader
                .read(&mut buffer)
                .map_err(|error| format!("下载 {source} 失败: {error}"))?;
            if read == 0 {
                break;
            }
            written += read as u64;
            // Checked while streaming: a mirror that keeps sending must not be
            // able to fill the disk before the digest can reject the file.
            check_download_size(written, expected_size, source)?;
            file.write_all(&buffer[..read])
                .map_err(|error| format!("写入下载失败: {error}"))?;
        }
        file.flush().map_err(|error| error.to_string())?;
        written
    } else {
        let from = Path::new(source);
        let size = fs::metadata(from)
            .map_err(|error| format!("无法读取 {}: {error}", from.display()))?
            .len();
        check_download_size(size, expected_size, source)?;
        if from != target {
            fs::copy(from, target)
                .map_err(|error| format!("无法复制 {}: {error}", from.display()))?;
        }
        size
    };
    // A catalog's `size` is a promise about the bytes: a short read is a
    // truncated archive, and a long one is not the release that was announced.
    if let Some(expected) = expected_size.filter(|size| *size > 0) {
        if written != expected {
            // A refused archive must not be left behind for the next step (or
            // the next run) to trip over.
            let _ = fs::remove_file(target);
            return Err(format!(
                "归档大小与清单不符（清单 {expected} 字节，实际 {written} 字节）"
            ));
        }
    }
    Ok(())
}

/// Refuse a download that already exceeds what it claims, or the hard ceiling.
fn check_download_size(
    written: u64,
    expected_size: Option<u64>,
    source: &str,
) -> Result<(), String> {
    if written > MAX_DOWNLOAD_BYTES {
        return Err(format!(
            "{source} 超过运行时包大小上限（{} MB），已中止下载",
            MAX_DOWNLOAD_BYTES / (1024 * 1024)
        ));
    }
    if let Some(expected) = expected_size.filter(|size| *size > 0) {
        if written > expected {
            return Err(format!(
                "{source} 超过清单声明的大小（{expected} 字节），已中止下载"
            ));
        }
    }
    Ok(())
}

/// Resolve a catalog-relative URL against the catalog's own location, so a
/// catalog can list plain file names next to itself.
fn resolve_relative(base: &str, target: &str) -> String {
    if target.starts_with("http://") || target.starts_with("https://") || target.starts_with('/') {
        return target.to_string();
    }
    if base.starts_with("http://") || base.starts_with("https://") {
        let directory = base.rsplit_once('/').map(|(head, _)| head).unwrap_or(base);
        return format!("{directory}/{target}");
    }
    Path::new(base)
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join(target)
        .to_string_lossy()
        .to_string()
}

pub fn sha256_file(path: &Path) -> Result<String, String> {
    let mut file =
        File::open(path).map_err(|error| format!("无法读取 {}: {error}", path.display()))?;
    let mut hasher = Sha256::new();
    let mut buffer = [0u8; 1024 * 256];
    loop {
        let read = file.read(&mut buffer).map_err(|error| error.to_string())?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}

/// Extract a `.tar.gz`, refusing entries that would escape the destination.
pub fn extract_tar_gz(archive: &Path, destination: &Path) -> Result<(), String> {
    let file =
        File::open(archive).map_err(|error| format!("无法打开 {}: {error}", archive.display()))?;
    let mut tar = tar::Archive::new(flate2::read::GzDecoder::new(file));
    let mut count = 0usize;
    for entry in tar.entries().map_err(|error| error.to_string())? {
        let mut entry = entry.map_err(|error| error.to_string())?;
        let path = entry
            .path()
            .map_err(|error| error.to_string())?
            .into_owned();
        if !is_safe_entry_path(&path) {
            return Err(format!("运行时包包含非法路径: {}", path.display()));
        }
        count += 1;
        if count > MAX_ENTRY_COUNT {
            return Err("运行时包条目数异常，已中止安装".to_string());
        }
        entry
            .unpack_in(destination)
            .map_err(|error| format!("解包 {} 失败: {error}", path.display()))?;
    }
    Ok(())
}

/// Reject absolute paths and any `..` segment: a pack must only ever write
/// inside the directory it is being unpacked into.
pub(crate) fn is_safe_entry_path(path: &Path) -> bool {
    !path.is_absolute()
        && !path.components().any(|part| {
            matches!(
                part,
                Component::ParentDir | Component::RootDir | Component::Prefix(_)
            )
        })
}

/// Replace a file's contents *without* writing through its inode.
///
/// An incremental update clones the base pack with hard links
/// (`pack_tree::clone_tree`), so an in-place `fs::write` on a cloned path would
/// rewrite the base pack too: rehydration always rewrites `pyvenv.cfg`, and one
/// failed apply would leave the *live* pack pointing at a staging directory that
/// is deleted seconds later. Writing a sibling temporary and renaming over the
/// destination replaces the directory entry, which breaks the link for this path
/// only — the invariant `clone_tree` documents, and the one the delta path needs.
///
/// Permissions travel with the replacement because a console script's execute
/// bit is what makes it runnable at all.
fn replace_file_contents(path: &Path, contents: &[u8]) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or_else(|| format!("{} 没有父目录", path.display()))?;
    let name = path
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_else(|| "file".to_string());
    let temporary = parent.join(format!(".{name}.deeptutor-{}", std::process::id()));
    let permissions = fs::metadata(path)
        .ok()
        .map(|metadata| metadata.permissions());
    {
        let mut handle = File::create(&temporary)
            .map_err(|error| format!("无法写入 {}: {error}", temporary.display()))?;
        handle
            .write_all(contents)
            .map_err(|error| format!("无法写入 {}: {error}", temporary.display()))?;
        let _ = handle.sync_all();
    }
    if let Some(permissions) = permissions {
        let _ = fs::set_permissions(&temporary, permissions);
    }
    fs::rename(&temporary, path).map_err(|error| {
        let _ = fs::remove_file(&temporary);
        format!("无法替换 {}: {error}", path.display())
    })
}

/// Repair the self-references a moved virtualenv carries.
///
/// Two things are path-bound: `pyvenv.cfg`'s `home` (python uses it to find its
/// stdlib) and the interpreter link in `bin/`. Both are rewritten for this
/// machine; the build machine's prefix is replaced in the small text files that
/// embed it (entry-point shebangs, `activate`, `.pth`).
/// The directory a pack was *built* in, as its own `pyvenv.cfg` still records it.
///
/// `home = <build root>/python/bin`, which is the derivation `rehydrate` uses to
/// decide what to rewrite and the one `desktop/pack/build_delta.py::build_root`
/// mirrors. `None` when the file is missing or has no `home` line.
pub fn pack_root_from_cfg(pack_dir: &Path) -> Option<PathBuf> {
    let text = fs::read_to_string(pack_dir.join("venv").join("pyvenv.cfg")).ok()?;
    let home = text
        .lines()
        .find_map(|line| line.strip_prefix("home =").map(|value| value.trim()))?;
    if home.is_empty() {
        return None;
    }
    Path::new(home)
        .parent()
        .and_then(Path::parent)
        .map(Path::to_path_buf)
}

pub fn rehydrate(pack_dir: &Path) -> Result<(), String> {
    let venv = pack_dir.join("venv");
    let cfg = venv.join("pyvenv.cfg");
    let bin_dir = pack_dir.join("python").join("bin");
    let old_root = pack_root_from_cfg(pack_dir);

    let text =
        fs::read_to_string(&cfg).map_err(|error| format!("无法读取 {}: {error}", cfg.display()))?;
    let mut updated = String::with_capacity(text.len());
    for line in text.lines() {
        if line.starts_with("home =") {
            updated.push_str(&format!("home = {}\n", bin_dir.display()));
        } else {
            updated.push_str(line);
            updated.push('\n');
        }
    }
    replace_file_contents(&cfg, updated.as_bytes())?;

    // Relative interpreter links: the pack moves as one unit, so `../../python`
    // stays correct wherever it is unpacked.
    #[cfg(unix)]
    {
        for name in ["python", "python3", "python3.12"] {
            let link = venv.join("bin").join(name);
            if link.symlink_metadata().is_err() {
                continue;
            }
            let _ = fs::remove_file(&link);
            std::os::unix::fs::symlink("../../python/bin/python3", &link)
                .map_err(|error| format!("无法重建 {}: {error}", link.display()))?;
        }
    }

    if let Some(old_root) = old_root {
        if old_root != pack_dir {
            rewrite_prefixes(&venv, &[(old_root, pack_dir.to_path_buf())])?;
        }
    }
    Ok(())
}

/// Make an installed pack self-describing: no path inside it names a directory
/// the pack no longer lives in.
///
/// A pack only *rehydrates* its venv, so everything outside it (the CPython
/// tree, wheel metadata, the manifest) keeps the build directory it was staged
/// at — and an incremental update copies those files from the base rather than
/// shipping them again. The result is a pack whose identity depends on which
/// full release it descends from, which is exactly what the next delta's base
/// fingerprint refuses. Rewriting the residuals to where the pack actually is
/// makes every installed pack canonical, so the chain keeps working.
///
/// Only small text files are visited (the same gate as `rehydrate`), and writes
/// go through the temp-file path, so a hard-linked base is never touched.
pub fn canonicalise(pack_dir: &Path, stale_roots: &[PathBuf]) -> Result<(), String> {
    let mut pairs: Vec<(PathBuf, PathBuf)> = stale_roots
        .iter()
        .filter(|root| !root.as_os_str().is_empty() && root.as_path() != pack_dir)
        .map(|root| (root.clone(), pack_dir.to_path_buf()))
        .collect();
    // Longest first: a shorter root that happens to be a prefix of a longer one
    // must not rewrite the longer one's text into something else.
    pairs.sort_by_key(|(from, _)| std::cmp::Reverse(from.as_os_str().len()));
    pairs.dedup();
    if pairs.is_empty() {
        return Ok(());
    }
    rewrite_prefixes(pack_dir, &pairs)?;
    // Symlinks are content to the fingerprint (`tree_digest` hashes the target
    // text), so a link left pointing at the build machine would break the chain
    // exactly like a file would.
    rewrite_link_targets(pack_dir, &pairs)
}

/// Repoint every symlink whose target names one of `pairs`.
fn rewrite_link_targets(root: &Path, pairs: &[(PathBuf, PathBuf)]) -> Result<(), String> {
    let replacements: Vec<(String, String)> = pairs
        .iter()
        .map(|(from, to)| {
            (
                from.to_string_lossy().to_string(),
                to.to_string_lossy().to_string(),
            )
        })
        .collect();
    let mut stack = vec![root.to_path_buf()];
    while let Some(directory) = stack.pop() {
        let Ok(entries) = fs::read_dir(&directory) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            let Ok(metadata) = entry.metadata() else {
                continue;
            };
            if metadata.is_dir() {
                stack.push(path);
                continue;
            }
            if !metadata.file_type().is_symlink() {
                continue;
            }
            let Ok(target) = fs::read_link(&path) else {
                continue;
            };
            let original = target.to_string_lossy().to_string();
            let mut updated = original.clone();
            for (from, to) in &replacements {
                if updated.contains(from.as_str()) {
                    updated = updated.replace(from.as_str(), to.as_str());
                }
            }
            if updated == original {
                continue;
            }
            fs::remove_file(&path)
                .map_err(|error| format!("无法更新符号链接 {}: {error}", path.display()))?;
            create_symlink(&updated, &path)?;
        }
    }
    Ok(())
}

/// Replace each `from` with its `to` inside the small text files under `root`.
///
/// One pass over the tree, whatever the number of replacements, and every write
/// goes through [`replace_file_contents`] — so a hard-linked clone of this tree
/// never carries a rewrite back into the pack it was cloned from.
fn rewrite_prefixes(root: &Path, pairs: &[(PathBuf, PathBuf)]) -> Result<(), String> {
    let rewritten: Vec<(String, String)> = pairs
        .iter()
        .map(|(from, to)| {
            (
                from.to_string_lossy().to_string(),
                to.to_string_lossy().to_string(),
            )
        })
        .collect();
    let mut stack = vec![root.to_path_buf()];
    while let Some(directory) = stack.pop() {
        let Ok(entries) = fs::read_dir(&directory) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            let Ok(metadata) = entry.metadata() else {
                continue;
            };
            if metadata.is_dir() {
                stack.push(path);
                continue;
            }
            // A symlink is structure, not content: `read_to_string` would follow
            // it out of the pack and `fs::write` would edit whatever it points
            // at. The interpreter links are rebuilt explicitly in `rehydrate`.
            if metadata.file_type().is_symlink() {
                continue;
            }
            // Only small text files can carry a prefix; binaries and RECORDs are
            // skipped to keep install time bounded.
            if metadata.len() > 256 * 1024 {
                continue;
            }
            let Ok(content) = fs::read_to_string(&path) else {
                continue;
            };
            if !rewritten
                .iter()
                .any(|(old_text, _)| content.contains(old_text.as_str()))
            {
                continue;
            }
            let mut updated = content;
            for (old_text, new_text) in &rewritten {
                if updated.contains(old_text.as_str()) {
                    updated = updated.replace(old_text.as_str(), new_text.as_str());
                }
            }
            let _ = replace_file_contents(&path, updated.as_bytes());
        }
    }
    Ok(())
}

/// Can this pack actually run the launcher on this machine?
fn smoke_test(pack_dir: &Path, manifest: &PackManifest) -> Result<(), String> {
    let python = manifest.python_path(pack_dir);
    let output = std::process::Command::new(&python)
        .arg("-c")
        .arg("import deeptutor_cli.main, deeptutor_web")
        .stdin(std::process::Stdio::null())
        .output()
        .map_err(|error| format!("无法运行 {}: {error}", python.display()))?;
    if !output.status.success() {
        return Err(format!(
            "运行时包冒烟失败：{} 无法导入 DeepTutor（{}）",
            python.display(),
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    Ok(())
}

/// Mirrors `host_platform()` in `desktop/pack/build_pack.py`.
pub fn host_platform() -> String {
    if cfg!(target_os = "macos") {
        if cfg!(target_arch = "aarch64") {
            "macos-aarch64".to_string()
        } else {
            "macos-x86_64".to_string()
        }
    } else if cfg!(windows) {
        "windows-x86_64".to_string()
    } else {
        "linux-x86_64".to_string()
    }
}

fn log(message: &str) {
    eprintln!("[runtime-pack] {message}");
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(name: &str) -> PathBuf {
        let dir =
            std::env::temp_dir().join(format!("deeptutor-pack-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn write_manifest(dir: &Path, pack_id: &str) {
        let manifest = serde_json::json!({
            "schema_version": SCHEMA_VERSION,
            "pack_id": pack_id,
            "app_version": "1.6.10",
            "platform": host_platform(),
            "paths": {"python": "venv/bin/python", "node_dir": "node/bin"},
        });
        fs::write(
            dir.join(MANIFEST_FILE),
            serde_json::to_string_pretty(&manifest).unwrap(),
        )
        .unwrap();
    }

    /// A stand-in for a real pack: the files rehydration has to repair.
    fn fake_pack(root: &Path, old_prefix: &Path) -> PathBuf {
        let pack = root.join("pack");
        fs::create_dir_all(pack.join("python/bin")).unwrap();
        fs::create_dir_all(pack.join("venv/bin")).unwrap();
        fs::write(pack.join("python/bin/python3"), b"#!/bin/sh\n").unwrap();
        fs::write(
            pack.join("venv/pyvenv.cfg"),
            format!(
                "home = {}/python/bin\nversion_info = 3.12.14\n",
                old_prefix.display()
            ),
        )
        .unwrap();
        let mut handle = File::create(pack.join("venv/bin/deeptutor")).unwrap();
        writeln!(handle, "#!{}/python/bin/python3", old_prefix.display()).unwrap();
        // A real pack ships an absolute interpreter link; that is exactly what
        // rehydration has to make relative.
        #[cfg(unix)]
        std::os::unix::fs::symlink(
            old_prefix.join("python/bin/python3"),
            pack.join("venv/bin/python"),
        )
        .unwrap();
        write_manifest(&pack, "1.6.10-macos-aarch64");
        pack
    }

    #[test]
    fn rehydrate_rewrites_home_prefix_and_links() {
        let tmp = scratch("rehydrate");
        let old_prefix = PathBuf::from("/build/machine/stage");
        let pack = fake_pack(&tmp, &old_prefix);

        rehydrate(&pack).unwrap();

        let cfg = fs::read_to_string(pack.join("venv/pyvenv.cfg")).unwrap();
        assert!(cfg.contains(&format!("home = {}/python/bin", pack.display())));
        assert!(!cfg.contains("/build/machine"));

        let script = fs::read_to_string(pack.join("venv/bin/deeptutor")).unwrap();
        assert!(script.contains(&pack.to_string_lossy().to_string()));
        assert!(!script.contains("/build/machine"));

        #[cfg(unix)]
        {
            let target = fs::read_link(pack.join("venv/bin/python")).unwrap();
            assert_eq!(target, PathBuf::from("../../python/bin/python3"));
        }
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn manifest_rejects_an_unknown_schema() {
        let tmp = scratch("schema");
        fs::write(
            tmp.join(MANIFEST_FILE),
            r#"{"schema_version":99,"pack_id":"x","app_version":"1",
                "platform":"macos-aarch64",
                "paths":{"python":"venv/bin/python","node_dir":"node/bin"}}"#,
        )
        .unwrap();
        let error = PackManifest::read(&tmp).unwrap_err();
        assert!(error.contains("不受支持"), "{error}");
        let _ = fs::remove_dir_all(&tmp);
    }

    /// A pack's own manifest is untrusted input: `pack_id` names a directory
    /// under `runtimes/` that gets `remove_dir_all`ed and replaced, and the two
    /// component paths are joined onto the pack root (an absolute value would
    /// replace it) and then executed.
    #[test]
    fn manifest_rejects_ids_and_paths_that_escape_the_pack() {
        let tmp = scratch("manifest-escape");
        write_manifest(&tmp, "1.6.10-macos-aarch64");
        assert!(PackManifest::read(&tmp).is_ok());

        for pack_id in [
            "../outside",
            "venv/../../outside",
            "/tmp/outside",
            ".",
            "..",
            "",
            "  padded",
            "nested/name",
        ] {
            write_manifest(&tmp, pack_id);
            let error = PackManifest::read(&tmp).unwrap_err();
            assert!(error.contains("ID 不合法"), "{pack_id:?} -> {error}");
        }

        // The catalog's own id is fine, but the paths must stay relative.
        for paths in [
            r#"{"python":"/bin/sh","node_dir":"node/bin"}"#,
            r#"{"python":"../python/bin/python","node_dir":"node/bin"}"#,
            r#"{"python":"venv/bin/python","node_dir":"/tmp"}"#,
            r#"{"python":"venv/bin/python","node_dir":".."}"#,
        ] {
            fs::write(
                tmp.join(MANIFEST_FILE),
                format!(
                    r#"{{"schema_version":{SCHEMA_VERSION},"pack_id":"1.6.10-macos-aarch64",
                        "app_version":"1.6.10","platform":"macos-aarch64","paths":{paths}}}"#
                ),
            )
            .unwrap();
            let error = PackManifest::read(&tmp).unwrap_err();
            assert!(error.contains("不合法"), "{paths} -> {error}");
        }
        let _ = fs::remove_dir_all(&tmp);
    }

    /// `state.json` is machine-local, but the id it names still has to resolve
    /// inside the runtime tree instead of anywhere on the disk.
    #[test]
    fn a_state_file_cannot_point_the_installer_outside_the_runtime_tree() {
        let tmp = scratch("state-escape");
        fs::create_dir_all(tmp.join("desktop")).unwrap();
        fs::write(
            tmp.join("desktop").join(STATE_FILE),
            r#"{"schema_version":1,"active_pack":"../../etc"}"#,
        )
        .unwrap();
        let installer = PackInstaller::new(&tmp);
        assert!(installer.active().is_none());
        assert!(installer.load("../outside").is_err());
        assert!(installer.load("/tmp/outside").is_err());
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn install_refuses_a_digest_mismatch_before_writing() {
        let tmp = scratch("digest");
        let archive = tmp.join("runtime.tar.gz");
        fs::write(&archive, b"not really a tarball").unwrap();
        let installer = PackInstaller::new(&tmp);

        let error = installer
            .install_archive(&archive, Some(&"0".repeat(64)))
            .unwrap_err();

        assert!(error.contains("校验失败"), "{error}");
        assert!(!tmp.join("runtimes").join("1.6.10-macos-aarch64").exists());
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn entry_paths_must_stay_inside_the_pack() {
        // The `tar` crate refuses to *write* these paths, so the guard is tested
        // where extraction consults it: an archive from anywhere is untrusted.
        assert!(is_safe_entry_path(Path::new("venv/bin/python")));
        assert!(is_safe_entry_path(Path::new("manifest.json")));
        assert!(!is_safe_entry_path(Path::new("../escaped.txt")));
        assert!(!is_safe_entry_path(Path::new("venv/../../escaped.txt")));
        assert!(!is_safe_entry_path(Path::new("/etc/passwd")));
    }

    #[test]
    fn extract_accepts_a_well_formed_archive() {
        let tmp = scratch("extract-ok");
        let archive = tmp.join("good.tar.gz");
        let file = File::create(&archive).unwrap();
        let mut builder = tar::Builder::new(flate2::write::GzEncoder::new(
            file,
            flate2::Compression::fast(),
        ));
        let mut header = tar::Header::new_gnu();
        header.set_size(2);
        header.set_mode(0o644);
        header.set_cksum();
        builder
            .append_data(&mut header, "manifest.json", &b"{}"[..])
            .unwrap();
        builder.into_inner().unwrap().finish().unwrap();

        let destination = tmp.join("out");
        fs::create_dir_all(&destination).unwrap();
        extract_tar_gz(&archive, &destination).unwrap();

        assert!(destination.join("manifest.json").exists());
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn activate_then_rollback_swaps_the_active_pack() {
        let tmp = scratch("state");
        for pack_id in ["1.6.10-macos-aarch64", "1.6.11-macos-aarch64"] {
            let dir = tmp.join("runtimes").join(pack_id);
            fs::create_dir_all(&dir).unwrap();
            write_manifest(&dir, pack_id);
        }
        let installer = PackInstaller::new(&tmp);

        installer.activate("1.6.10-macos-aarch64").unwrap();
        installer.activate("1.6.11-macos-aarch64").unwrap();
        assert_eq!(
            installer.state().active_pack.as_deref(),
            Some("1.6.11-macos-aarch64")
        );
        assert_eq!(
            installer.state().previous_pack.as_deref(),
            Some("1.6.10-macos-aarch64")
        );

        let pack = installer.rollback().unwrap();
        assert_eq!(pack.pack_id, "1.6.10-macos-aarch64");
        assert_eq!(
            installer.state().active_pack.as_deref(),
            Some("1.6.10-macos-aarch64")
        );
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn rollback_without_history_reports_clearly() {
        let tmp = scratch("rollback-empty");
        let installer = PackInstaller::new(&tmp);
        let error = installer.rollback().unwrap_err();
        assert!(error.contains("没有可回滚"), "{error}");
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn the_download_target_cannot_come_from_the_url() {
        // A catalog-controlled last segment must not be able to name the file
        // (on Windows `..\..\Startup\x.bat` is a single path component).
        for kind in ["runtime-pack", "runtime-delta"] {
            let target = download_target(Path::new("/tmp/downloads"), kind);
            assert_eq!(
                target.parent(),
                Some(Path::new("/tmp/downloads")),
                "{target:?}"
            );
            let name = target.file_name().unwrap().to_string_lossy().into_owned();
            assert!(name.starts_with(kind), "{name}");
            assert!(!name.contains('/') && !name.contains('\\') && !name.contains(".."));
        }
    }

    #[test]
    fn version_key_orders_stable_releases() {
        assert!(version_key("1.6.11") > version_key("1.6.10"));
        assert!(version_key("1.6.10") > version_key("1.5.99"));
        assert_eq!(version_key("v1.6.10"), version_key("1.6.10"));
        // A newer core still wins, even as a pre-release.
        assert!(version_key("1.7.0") > version_key("1.6.10-rc1"));
        // ...but a release candidate never beats the release it precedes.
        assert!(version_key("1.6.11") > version_key("1.6.11-rc1"));
        // Two candidates of the same core are equal here on purpose: the product
        // ships stable releases, and the only decision that matters is that
        // neither of them outranks the release itself.
        assert_eq!(version_key("1.6.11-rc1"), version_key("1.6.11-rc2"));
        // Build metadata does not affect precedence.
        assert_eq!(version_key("1.6.11+build.7"), version_key("1.6.11"));
    }

    fn release(app_version: &str, platform: &str) -> PackRelease {
        PackRelease {
            pack_id: format!("{app_version}-{platform}"),
            app_version: app_version.to_string(),
            platform: platform.to_string(),
            url: format!("{app_version}-{platform}.tar.gz"),
            sha256: "0".repeat(64),
            size: 1024,
            requires_shell: None,
            delta: None,
        }
    }

    /// The real selector, not a copy of its sort: a catalog carrying both a
    /// release and its candidate must never "update" a stable install to the
    /// candidate.
    #[test]
    fn a_release_candidate_does_not_beat_its_release() {
        let host = host_platform();
        let catalog = PackCatalog {
            schema_version: SCHEMA_VERSION,
            packs: vec![release("1.6.11", &host), release("1.6.11-rc1", &host)],
        };

        assert!(
            newest_for_host(&catalog, "1.6.11").unwrap().is_none(),
            "a stable install must not be offered its own release candidate"
        );
        assert_eq!(
            newest_for_host(&catalog, "1.6.10")
                .unwrap()
                .expect("1.6.11 is newer than 1.6.10")
                .app_version,
            "1.6.11"
        );
    }

    #[test]
    fn catalog_prefers_the_newest_pack_for_this_platform() {
        let tmp = scratch("catalog");
        let installer = PackInstaller::new(&tmp);
        let host = host_platform();
        fs::write(
            tmp.join("runtime-packs.json"),
            serde_json::json!({
                "schema_version": SCHEMA_VERSION,
                "packs": [
                    {"pack_id": "1.6.10", "app_version": "1.6.10", "platform": host,
                     "url": "a.tar.gz", "sha256": "aa"},
                    {"pack_id": "1.6.11", "app_version": "1.6.11", "platform": host,
                     "url": "b.tar.gz", "sha256": "bb"},
                    {"pack_id": "9.9.9-other", "app_version": "9.9.9", "platform": "windows-x86_64",
                     "url": "c.tar.gz", "sha256": "cc"}
                ]
            })
            .to_string(),
        )
        .unwrap();

        let catalog = installer
            .catalog(&tmp.join("runtime-packs.json").to_string_lossy())
            .unwrap();

        assert_eq!(
            catalog.packs.len(),
            3,
            "another platform is listed, not used"
        );
        assert_eq!(
            newest_for_host(&catalog, "1.6.9")
                .unwrap()
                .expect("1.6.11 is newer")
                .app_version,
            "1.6.11"
        );
        assert!(newest_for_host(&catalog, "1.6.11").unwrap().is_none());
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn relative_catalog_urls_resolve_next_to_the_catalog() {
        assert_eq!(
            resolve_relative("https://example.com/dl/packs.json", "a.tar.gz"),
            "https://example.com/dl/a.tar.gz"
        );
        assert_eq!(
            resolve_relative("/tmp/packs.json", "a.tar.gz"),
            "/tmp/a.tar.gz"
        );
        assert_eq!(
            resolve_relative("https://example.com/dl/packs.json", "https://cdn/a.tar.gz"),
            "https://cdn/a.tar.gz"
        );
    }

    /// The delta path clones the base pack with hard links, then rehydrates the
    /// clone. An in-place write would edit the base through the shared inode:
    /// on the error path the staging directory is deleted right afterwards, so
    /// the pack the user is running would be left pointing at nothing.
    #[test]
    fn rehydrating_a_hard_linked_clone_leaves_the_base_pack_alone() {
        let tmp = scratch("clone-rehydrate");
        let build_root = tmp.join("build");
        let base = fake_pack(&tmp, &build_root);
        let clone = tmp.join("clone");
        clone_tree(&base, &clone).unwrap();

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt as _;
            fs::set_permissions(
                base.join("venv/bin/deeptutor"),
                fs::Permissions::from_mode(0o755),
            )
            .unwrap();
        }

        rehydrate(&clone).unwrap();

        let base_cfg = fs::read_to_string(base.join("venv/pyvenv.cfg")).unwrap();
        assert!(
            base_cfg.contains(&format!("home = {}/python/bin", build_root.display())),
            "the base pack's pyvenv.cfg was rewritten by the clone: {base_cfg}"
        );
        let base_script = fs::read_to_string(base.join("venv/bin/deeptutor")).unwrap();
        assert!(
            base_script.contains(&build_root.to_string_lossy().to_string()),
            "the base pack's console script was rewritten by the clone: {base_script}"
        );

        let clone_cfg = fs::read_to_string(clone.join("venv/pyvenv.cfg")).unwrap();
        assert!(clone_cfg.contains(&format!("home = {}/python/bin", clone.display())));

        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt as _;
            let mode = fs::metadata(clone.join("venv/bin/deeptutor"))
                .unwrap()
                .permissions()
                .mode();
            assert_eq!(
                mode & 0o111,
                0o111,
                "replacing the file dropped the execute bit"
            );
        }
        let _ = fs::remove_dir_all(&tmp);
    }

    /// A pack is untrusted input: `rewrite_prefix` must never read or write
    /// through a symlink that points out of the tree it was handed.
    #[cfg(unix)]
    #[test]
    fn rehydration_does_not_write_through_a_symlink() {
        let tmp = scratch("rehydrate-symlink");
        let build_root = tmp.join("build");
        let base = fake_pack(&tmp, &build_root);
        let outside = tmp.join("outside.txt");
        fs::write(&outside, format!("prefix {}\n", build_root.display())).unwrap();
        std::os::unix::fs::symlink(&outside, base.join("venv/aliased.txt")).unwrap();

        let clone = tmp.join("clone");
        clone_tree(&base, &clone).unwrap();
        rehydrate(&clone).unwrap();

        let text = fs::read_to_string(&outside).unwrap();
        assert!(
            text.contains(&build_root.to_string_lossy().to_string()),
            "rehydration followed a symlink out of the pack: {text}"
        );
        assert!(
            clone.join("venv/aliased.txt").is_symlink(),
            "rehydration replaced the symlink instead of leaving it alone"
        );
        let _ = fs::remove_dir_all(&tmp);
    }

    /// The chain invariant: a pack installed by this shell must fingerprint as
    /// the tree its delta was built from.
    ///
    /// Rehydration only rewrites the venv, so everything else keeps the build
    /// path of whichever *full* release it descends from. Without
    /// canonicalisation an installed pack therefore carried a root that the next
    /// delta's single `base_root` could never name, every second incremental
    /// update was refused, and the user silently downloaded a full archive.
    #[test]
    fn an_installed_pack_fingerprints_as_its_staged_self() {
        let tmp = scratch("chain");
        let build_root = tmp.join("stage-1.0.0");
        let staged = fake_pack(&tmp, &build_root);
        // Outside the venv: the CPython tree and wheel metadata look like this.
        fs::write(
            staged.join("python/bin/sysconfigdata.txt"),
            format!("prefix={}/python\n", build_root.display()),
        )
        .unwrap();
        let stale = vec![build_root.to_string_lossy().into_owned()];
        // What `build_delta.py` records for the base it stages.
        let staged_digest = tree_digest(&staged, &stale).unwrap();

        let installed = tmp.join("runtimes/1.0.0");
        clone_tree(&staged, &installed).unwrap();
        rehydrate(&installed).unwrap();
        canonicalise(&installed, std::slice::from_ref(&build_root)).unwrap();

        // What the applier computes for a delta whose base is this install.
        assert_eq!(tree_digest(&installed, &stale).unwrap(), staged_digest);

        // And nothing is left naming the build machine.
        let text = fs::read_to_string(installed.join("python/bin/sysconfigdata.txt")).unwrap();
        assert!(
            text.contains(&installed.to_string_lossy().to_string()),
            "{text}"
        );
        assert!(
            !text.contains(&build_root.to_string_lossy().to_string()),
            "{text}"
        );
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn canonicalising_rewrites_residual_roots_and_leaves_structure_alone() {
        let tmp = scratch("canonicalise");
        let build_root = tmp.join("stage");
        let pack = fake_pack(&tmp, &build_root);
        let residual = pack.join("python/bin/sysconfigdata.txt");
        fs::write(
            &residual,
            format!("prefix={}/python\n", build_root.display()),
        )
        .unwrap();
        // Past `MAX_REWRITE_BYTES`: rehydration skips it, so canonicalisation
        // must too (it is a binary/payload, not a prefix carrier).
        let big = pack.join("python/bin/big.txt");
        fs::write(
            &big,
            format!("{}\n{}", build_root.display(), "x".repeat(300 * 1024)),
        )
        .unwrap();
        #[cfg(unix)]
        let linked = {
            let link = pack.join("venv/elsewhere");
            std::os::unix::fs::symlink(build_root.join("python/bin/python3"), &link).unwrap();
            link
        };

        // An empty root is ignored rather than turning into a whole-tree replace.
        canonicalise(&pack, &[PathBuf::new(), build_root.clone()]).unwrap();

        let rewritten = fs::read_to_string(&residual).unwrap();
        assert!(
            rewritten.contains(&pack.to_string_lossy().to_string()),
            "{rewritten}"
        );
        assert!(
            !rewritten.contains(&build_root.to_string_lossy().to_string()),
            "{rewritten}"
        );
        assert!(
            fs::read_to_string(&big)
                .unwrap()
                .contains(&build_root.to_string_lossy().to_string()),
            "a file past the rewrite gate must be left alone"
        );
        #[cfg(unix)]
        assert_eq!(
            fs::read_link(&linked).unwrap(),
            pack.join("python/bin/python3"),
            "a symlink target naming the build machine must be repointed"
        );
        let _ = fs::remove_dir_all(&tmp);
    }

    // --- Runtime-catalog signing -------------------------------------------
    //
    // A throwaway minisign keypair, generated once for these tests. A catalog is
    // the document that names both the archive and the sha256 authenticating it,
    // so its signature is the only thing standing between "some https host" and
    // code the shell will execute.

    /// A throwaway keypair generated once for these tests: the public key is
    /// `RWQAESIzRFVmdwOhB7/zzhC+HXDdGOdLwJln5NYwm6UNXx3chmQSVTG4`.
    ///
    /// The signature is legacy (`Ed`) so the fixture also covers the form a
    /// plain `minisign` produces; its *global* signature covers the trusted
    /// comment's **text without** the `trusted comment: ` label, which is what
    /// the verifier reconstructs.
    const TEST_PUBKEY_FILE: &str = "untrusted comment: minisign public key: 0011223344556677\n\
         RWQAESIzRFVmdwOhB7/zzhC+HXDdGOdLwJln5NYwm6UNXx3chmQSVTG4\n";
    const TEST_PUBKEY_BARE: &str = "RWQAESIzRFVmdwOhB7/zzhC+HXDdGOdLwJln5NYwm6UNXx3chmQSVTG4";
    /// The same key as `tauri.conf.json` stores it: base64 of the *file*.
    const TEST_PUBKEY_TAURI: &str = "dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk6IDAwMTEyMjMzNDQ1NTY2NzcKUldRQUVTSXpSRlZtZHdPaEI3L3p6aEMrSFhEZEdPZEx3SmxuNU5Zd202VU5YeDNjaG1RU1ZURzQK";
    /// A different key with the same key id.
    const TEST_OTHER_PUBKEY: &str = "RWQAESIzRFVmd0y1q/atefv1q7zK/MJp2FzSZR7UuIW1hp8kGu3wpbop";
    const TEST_CATALOG: &str = "{\n  \"schema_version\": 1,\n  \"packs\": []\n}\n";
    const TEST_SIGNATURE: &str = "untrusted comment: signature from minisign secret key\n\
         RWQAESIzRFVmd+jBMpvXAvjDgDWsNDB+T5l9VkXS9h8whDUCst4MB6PGsGSr09cqMvKkGURdYrVomxi2BIvhGIUJJfHORj623gI=\n\
         trusted comment: timestamp:1790386087\tfile:runtime-packs.json\n\
         pAoyelmPpjlSR4cPz/CwPjU2eO4gC7xxaRnkG5n/CRw34lUfwXw9HiCOm/MeGL1zykt1iTM0ECu/XDl2ayHuBg==\n";

    #[test]
    fn every_shape_of_minisign_public_key_is_accepted() {
        for key in [TEST_PUBKEY_FILE, TEST_PUBKEY_BARE, TEST_PUBKEY_TAURI] {
            assert!(
                parse_minisign_public_key(key).is_ok(),
                "failed to parse: {key}"
            );
        }
        for broken in ["", "   ", "not base64 at all!!", "AAAA"] {
            assert!(parse_minisign_public_key(broken).is_err(), "{broken:?}");
        }
    }

    #[test]
    fn a_catalog_signature_verifies_or_is_refused() {
        if let Err(error) =
            verify_minisign(TEST_PUBKEY_FILE, TEST_CATALOG.as_bytes(), TEST_SIGNATURE)
        {
            panic!("the fixture signature must verify: {error}");
        }

        // One byte of the document moved: the signature no longer covers it.
        let tampered = TEST_CATALOG.replace("\"packs\": []", "\"packs\": [1]");
        let error = verify_minisign(TEST_PUBKEY_BARE, tampered.as_bytes(), TEST_SIGNATURE)
            .expect_err("a tampered catalog must not verify");
        assert!(error.contains("签名校验不通过"), "{error}");

        // Right key id, wrong key material.
        assert!(
            verify_minisign(TEST_OTHER_PUBKEY, TEST_CATALOG.as_bytes(), TEST_SIGNATURE).is_err()
        );
    }

    fn write_catalog(directory: &Path, text: &str) {
        fs::create_dir_all(directory).unwrap();
        fs::write(directory.join("runtime-packs.json"), text).unwrap();
    }

    #[test]
    fn the_installer_requires_a_signature_only_when_a_key_is_configured() {
        let tmp = scratch("catalog-signature");
        write_catalog(&tmp, TEST_CATALOG);
        let catalog_path = tmp.join("runtime-packs.json");
        let source = catalog_path.to_string_lossy().into_owned();

        // No key configured: today's behaviour, with the source still readable.
        let unsigned = PackInstaller::new(&tmp).catalog(&source).unwrap();
        assert!(unsigned.packs.is_empty());

        // Key configured, no signature next to the catalog: refuse.
        let with_key = PackInstaller::new(&tmp).with_catalog_pubkey(Some(TEST_PUBKEY_BARE.into()));
        let error = with_key.catalog(&source).unwrap_err();
        assert!(error.contains("没有签名"), "{error}");

        // `<catalog>.sig` is what the signing tools write.
        fs::write(tmp.join("runtime-packs.json.sig"), TEST_SIGNATURE).unwrap();
        assert!(with_key.catalog(&source).is_ok());

        // `<catalog>.minisig` is the other spelling, and both are accepted.
        fs::remove_file(tmp.join("runtime-packs.json.sig")).unwrap();
        assert!(with_key.catalog(&source).is_err());
        fs::write(tmp.join("runtime-packs.json.minisig"), TEST_SIGNATURE).unwrap();
        assert!(with_key.catalog(&source).is_ok());

        // A catalog edited after signing is refused even with a signature file.
        write_catalog(
            &tmp,
            &TEST_CATALOG.replace("\"packs\": []", "\"packs\": [{}]"),
        );
        let error = with_key.catalog(&source).unwrap_err();
        assert!(error.contains("验签失败"), "{error}");
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn a_download_is_capped_and_checked_against_the_catalog() {
        // The hard ceiling, and a catalog that claims more than is arriving.
        assert!(check_download_size(1024, None, "x").is_ok());
        assert!(check_download_size(MAX_DOWNLOAD_BYTES + 1, None, "x").is_err());
        assert!(check_download_size(2048, Some(1024), "x").is_err());
        assert!(check_download_size(1024, Some(1024), "x").is_ok());
        // `size: 0` (a catalog that omits it) means "unknown", not "empty".
        assert!(check_download_size(1024, Some(0), "x").is_ok());
    }

    #[test]
    fn a_local_archive_must_match_the_declared_size() {
        let tmp = scratch("archive-size");
        let archive = tmp.join("pack.tar.gz");
        fs::write(&archive, vec![7u8; 512]).unwrap();
        let target = tmp.join("copy.tar.gz");

        // More arriving than the catalog promised is refused while streaming...
        let error = fetch_archive(&archive.to_string_lossy(), &target, Some(256))
            .expect_err("more bytes than announced must be refused");
        assert!(error.contains("超过清单声明的大小"), "{error}");
        assert!(
            !target.exists(),
            "nothing may be staged from a refused archive"
        );

        // ...and fewer than promised is refused by the final size check.
        let error = fetch_archive(&archive.to_string_lossy(), &target, Some(1024))
            .expect_err("a truncated archive must be refused");
        assert!(error.contains("归档大小与清单不符"), "{error}");
        assert!(!target.exists());

        fetch_archive(&archive.to_string_lossy(), &target, Some(512)).unwrap();
        assert_eq!(fs::metadata(&target).unwrap().len(), 512);
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn a_failed_install_leaves_no_staging_tree() {
        let tmp = scratch("staging-cleanup");
        // A well-formed tarball without a manifest: extraction succeeds, the
        // manifest read fails, and the staging copy must not survive.
        let archive = tmp.join("not-a-pack.tar.gz");
        let file = File::create(&archive).unwrap();
        let mut builder = tar::Builder::new(flate2::write::GzEncoder::new(
            file,
            flate2::Compression::fast(),
        ));
        let mut header = tar::Header::new_gnu();
        header.set_size(4);
        header.set_mode(0o644);
        header.set_cksum();
        builder
            .append_data(&mut header, "payload.txt", &b"data"[..])
            .unwrap();
        builder.into_inner().unwrap().finish().unwrap();

        let installer = PackInstaller::new(&tmp);
        let error = installer.install_archive(&archive, None).unwrap_err();
        assert!(error.contains("manifest.json"), "{error}");

        let leftovers: Vec<String> = fs::read_dir(tmp.join("runtimes"))
            .map(|entries| {
                entries
                    .flatten()
                    .map(|entry| entry.file_name().to_string_lossy().into_owned())
                    .collect()
            })
            .unwrap_or_default();
        assert!(leftovers.is_empty(), "left behind: {leftovers:?}");
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn a_failed_download_does_not_stay_in_the_download_directory() {
        let tmp = scratch("downloads-cleanup");
        let archive = tmp.join("pack.tar.gz");
        fs::write(&archive, b"not the archive we expected").unwrap();
        let installer = PackInstaller::new(&tmp);

        // A local path exercises the same fetch-then-install path as a URL, and
        // the digest mismatch fails after the copy.
        installer
            .install_from_url(&archive.to_string_lossy(), &"0".repeat(64), None)
            .expect_err("the digest cannot match");

        let downloads = tmp.join("runtimes").join(".downloads");
        let leftovers: Vec<String> = fs::read_dir(&downloads)
            .map(|entries| {
                entries
                    .flatten()
                    .map(|entry| entry.file_name().to_string_lossy().into_owned())
                    .collect()
            })
            .unwrap_or_default();
        assert!(leftovers.is_empty(), "left behind: {leftovers:?}");
        let _ = fs::remove_dir_all(&tmp);
    }

    #[test]
    fn staging_from_a_crashed_run_is_swept_but_the_current_one_is_not() {
        let tmp = scratch("staging-sweep");
        let runtimes = tmp.join("runtimes");
        let crashed = runtimes.join(".incoming-999999");
        let crashed_delta = runtimes.join(".delta-incoming-999999");
        let mine = runtimes.join(format!(".incoming-{}", std::process::id()));
        for directory in [&crashed, &crashed_delta, &mine] {
            fs::create_dir_all(directory).unwrap();
            fs::write(directory.join("file"), b"x").unwrap();
        }

        sweep_stale_staging(&runtimes);

        assert!(!crashed.exists(), "a crashed run's staging must go");
        assert!(!crashed_delta.exists());
        assert!(mine.exists(), "the current run's staging must stay");
        let _ = fs::remove_dir_all(&tmp);
    }
}
