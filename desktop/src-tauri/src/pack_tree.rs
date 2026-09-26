//! Pack-tree utilities: fingerprinting, cheap cloning and safe path handling.
//!
//! Incremental runtime updates (Phase 4, Spike B) rest on one question: "is the
//! pack I am about to patch the pack this patch was built from?" Answering it
//! correctly is subtler than hashing a directory, because a pack changes shape
//! the moment it is installed — `rehydrate` rewrites the interpreter links and
//! every small text file that mentions the build machine's pack path. Raw bytes
//! therefore differ between the staged tree the builder hashed and the installed
//! tree the user has, so a naive fingerprint would reject every honest delta.
//!
//! [`tree_digest`] hashes a *rehydration-normalised* view instead; the rules are
//! mirrored exactly by `desktop/pack/build_delta.py`, and a mismatch on either
//! side refuses the update rather than producing a subtly mixed pack.

use std::fs::{self, File};
use std::io::Read;
use std::path::{Component, Path, PathBuf};

use sha2::{Digest, Sha256};

/// Mirrors `rewrite_prefix`'s size gate: larger files are never rewritten during
/// rehydration, so they are compared byte for byte.
const MAX_REWRITE_BYTES: u64 = 256 * 1024;

/// What a file's own pack-root path collapses to when it is fingerprinted.
/// `build_delta.py` uses the same token.
const PACK_ROOT_TOKEN: &str = "<PACK_ROOT>";

/// A pack tree's identity: one digest over every file, its size and its hash.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TreeDigest {
    pub sha256: String,
    pub files: u64,
    pub bytes: u64,
}

/// Fingerprint a pack tree so the builder and the installer agree on it.
///
/// Entries are hashed in a rehydration-normalised form:
///
/// * regular files larger than [`MAX_REWRITE_BYTES`] are hashed verbatim —
///   rehydration skips them too;
/// * a file whose text mentions its own pack root is hashed with that path
///   replaced by [`PACK_ROOT_TOKEN`], which is precisely what rehydration does;
/// * the interpreter links (`venv/bin/python*`) are skipped: rehydration changes
///   their *form* (absolute → `../../python/bin/python3`), not just their path,
///   and `rehydrate` plus the smoke test cover them;
/// * runtime by-products (`__pycache__`, `*.pyc`, `.DS_Store`) are skipped, so a
///   pack that has actually run still matches the tree it was built from.
///
/// Everything else — CPython, Node, every wheel, the web bundle — is compared
/// byte for byte, which is what makes "apply this patch to *that* pack" a
/// checkable claim rather than a hope.
pub fn tree_digest(root: &Path, stale_roots: &[String]) -> Result<TreeDigest, String> {
    let mut rows: Vec<(String, char, u64, String)> = Vec::new();
    collect_rows(root, root, stale_roots, &mut rows)?;
    rows.sort_by(|left, right| left.0.cmp(&right.0));
    let mut hasher = Sha256::new();
    let mut bytes = 0u64;
    for (path, kind, size, digest) in &rows {
        hasher.update(format!("{path}\t{kind}\t{size}\t{digest}\n").as_bytes());
        bytes += size;
    }
    Ok(TreeDigest {
        sha256: format!("{:x}", hasher.finalize()),
        files: rows.len() as u64,
        bytes,
    })
}

fn collect_rows(
    root: &Path,
    directory: &Path,
    stale_roots: &[String],
    rows: &mut Vec<(String, char, u64, String)>,
) -> Result<(), String> {
    let entries = fs::read_dir(directory)
        .map_err(|error| format!("无法遍历 {}: {error}", directory.display()))?;
    for entry in entries.flatten() {
        let path = entry.path();
        let name = entry.file_name().to_string_lossy().into_owned();
        let Ok(relative) = path.strip_prefix(root) else {
            continue;
        };
        let relative = relative.to_string_lossy().replace('\\', "/");
        let Ok(metadata) = fs::symlink_metadata(&path) else {
            continue;
        };
        if metadata.is_dir() {
            if name == "__pycache__" {
                continue;
            }
            collect_rows(root, &path, stale_roots, rows)?;
            continue;
        }
        if metadata.file_type().is_symlink() {
            if is_rehydrated_link(&relative) {
                continue;
            }
            let target = fs::read_link(&path).map_err(|error| error.to_string())?;
            let target = normalise(&target.to_string_lossy(), root, stale_roots);
            rows.push((relative, 'l', 0, sha256_bytes(target.as_bytes())));
            continue;
        }
        if is_pack_noise(&name) {
            continue;
        }
        // The size that counts is the size of whatever was *hashed*: a file
        // whose text mentions its own pack root shrinks when that root is
        // tokenised, and rehydration shrinks it the same way on the other side.
        let (digest, size) = if metadata.len() > MAX_REWRITE_BYTES {
            (sha256_file(&path)?, metadata.len())
        } else {
            let content =
                fs::read(&path).map_err(|error| format!("无法读取 {}: {error}", path.display()))?;
            match String::from_utf8(content) {
                // The same gate `rewrite_prefix` applies: only valid UTF-8 is rewritten.
                Ok(text) => {
                    let normalised = normalise(&text, root, stale_roots);
                    let size = normalised.len() as u64;
                    (sha256_bytes(normalised.as_bytes()), size)
                }
                Err(error) => {
                    let raw = error.into_bytes();
                    let size = raw.len() as u64;
                    (sha256_bytes(&raw), size)
                }
            }
        };
        rows.push((relative, 'f', size, digest));
    }
    Ok(())
}

/// Replace every pack-root spelling a file might carry with one token.
///
/// Two roots can appear in an installed pack:
///
/// * its **own** path — what `rehydrate` writes into `pyvenv.cfg`, the
///   interpreter links, entry-point shebangs and venv metadata;
/// * the path the base was **staged** at on the build machine — still present in
///   everything rehydration does not touch (the CPython tree, `manifest.json`,
///   wheels' own metadata), because rehydration only walks the venv.
///
/// `stale_roots` carries the second kind, straight from the delta manifest. This
/// is not theoretical: without it an installed pack's fingerprint differed from
/// the build machine's by 108 bytes, and the delta was refused.
fn normalise(text: &str, root: &Path, stale_roots: &[String]) -> String {
    let mut normalised = text.to_string();
    let own = root.to_string_lossy().to_string();
    if !own.is_empty() && normalised.contains(&own) {
        normalised = normalised.replace(&own, PACK_ROOT_TOKEN);
    }
    for stale in stale_roots {
        if !stale.is_empty() && normalised.contains(stale.as_str()) {
            normalised = normalised.replace(stale.as_str(), PACK_ROOT_TOKEN);
        }
    }
    normalised
}

/// The links `rehydrate` rewrites from absolute to relative form.
fn is_rehydrated_link(relative: &str) -> bool {
    matches!(
        relative,
        "venv/bin/python" | "venv/bin/python3" | "venv/bin/python3.12"
    )
}

/// Runtime by-products, never pack content.
fn is_pack_noise(name: &str) -> bool {
    let lower = name.to_ascii_lowercase();
    name == ".DS_Store" || lower.ends_with(".pyc") || lower.ends_with(".pyo")
}

fn sha256_bytes(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}

fn sha256_file(path: &Path) -> Result<String, String> {
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

/// Copy a tree without duplicating bytes where the filesystem can avoid it.
///
/// Hard links make the base half of an incremental update free: no copy, no
/// extra space. Two rules keep the base pack safe from its own clone:
///
/// * every path the delta replaces is unlinked first, which breaks the link for
///   that entry only;
/// * every write the installer makes into a cloned tree goes through a
///   temporary file and a rename (`runtime_pack::replace_file_contents`), so
///   rehydration replaces the entry instead of editing the shared inode.
///
/// Without the second rule a failed delta could damage the pack that is
/// currently in use — the staging directory is deleted on the error path, and
/// `pyvenv.cfg` would already have been rewritten to point into it.
pub fn clone_tree(source: &Path, destination: &Path) -> Result<(), String> {
    fs::create_dir_all(destination).map_err(|error| error.to_string())?;
    for entry in fs::read_dir(source)
        .map_err(|error| format!("无法遍历 {}: {error}", source.display()))?
        .flatten()
    {
        let from = entry.path();
        let to = destination.join(entry.file_name());
        let metadata = fs::symlink_metadata(&from)
            .map_err(|error| format!("无法读取 {}: {error}", from.display()))?;
        if metadata.file_type().is_symlink() {
            let target = fs::read_link(&from).map_err(|error| error.to_string())?;
            create_symlink(&target.to_string_lossy(), &to)?;
        } else if metadata.is_dir() {
            clone_tree(&from, &to)?;
        } else if fs::hard_link(&from, &to).is_err() {
            fs::copy(&from, &to).map_err(|error| {
                format!("无法复制 {} -> {}: {error}", from.display(), to.display())
            })?;
        }
    }
    Ok(())
}

/// A delta path must stay inside the tree it patches.
pub fn safe_relative_path(raw: &str) -> Result<PathBuf, String> {
    let candidate = Path::new(raw);
    if candidate.is_absolute() {
        return Err(format!("增量包包含绝对路径：{raw}"));
    }
    let mut safe = PathBuf::new();
    for component in candidate.components() {
        match component {
            Component::Normal(part) => safe.push(part),
            Component::CurDir => {}
            _ => return Err(format!("增量包包含不安全的路径：{raw}")),
        }
    }
    if safe.as_os_str().is_empty() {
        return Err(format!("增量包包含空路径：{raw}"));
    }
    Ok(safe)
}

pub fn remove_entry(path: &Path) -> Result<(), String> {
    let metadata = fs::symlink_metadata(path).map_err(|error| error.to_string())?;
    if metadata.is_dir() {
        fs::remove_dir_all(path).map_err(|error| format!("无法删除 {}: {error}", path.display()))
    } else {
        fs::remove_file(path).map_err(|error| format!("无法删除 {}: {error}", path.display()))
    }
}

pub fn move_file(source: &Path, destination: &Path) -> Result<(), String> {
    match fs::rename(source, destination) {
        Ok(()) => Ok(()),
        // Different volumes (a delta staged on another disk) still work.
        Err(_) => {
            fs::copy(source, destination)
                .map_err(|error| format!("无法写入 {}: {error}", destination.display()))?;
            let _ = fs::remove_file(source);
            Ok(())
        }
    }
}

#[cfg(unix)]
pub fn create_symlink(target: &str, link: &Path) -> Result<(), String> {
    std::os::unix::fs::symlink(target, link)
        .map_err(|error| format!("无法创建符号链接 {}: {error}", link.display()))
}

#[cfg(windows)]
pub fn create_symlink(target: &str, link: &Path) -> Result<(), String> {
    // Windows packs carry no symlinks today; if one appears, a copy keeps the
    // update working instead of failing on a privilege requirement.
    match link.parent().map(|parent| parent.join(target)) {
        Some(source) if source.exists() => fs::copy(&source, link)
            .map(|_| ())
            .map_err(|error| format!("无法复制 {}: {error}", link.display())),
        _ => Err(format!("无法创建符号链接 {}", link.display())),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(name: &str) -> PathBuf {
        let path =
            std::env::temp_dir().join(format!("deeptutor-pack-tree-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&path);
        fs::create_dir_all(&path).expect("scratch dir");
        path
    }

    #[test]
    fn a_tree_digest_survives_rehydration() {
        // The staged form: interpreter links point into the build directory, and
        // a shebang carries the build path.
        let staged = scratch("staged");
        fs::create_dir_all(staged.join("venv/bin")).unwrap();
        fs::write(
            staged.join("venv/pyvenv.cfg"),
            format!("home = {}/python/bin\n", staged.display()),
        )
        .unwrap();
        fs::write(
            staged.join("venv/bin/deeptutor"),
            format!("#!{}/venv/bin/python\n", staged.display()),
        )
        .unwrap();
        create_symlink(
            &format!("{}/python/bin/python3", staged.display()),
            &staged.join("venv/bin/python"),
        )
        .unwrap();
        fs::write(staged.join("manifest.json"), "{\"pack_id\":\"x\"}").unwrap();

        // The installed form: same files, root path rewritten, links relative.
        let installed = scratch("installed");
        fs::create_dir_all(installed.join("venv/bin")).unwrap();
        fs::write(
            installed.join("venv/pyvenv.cfg"),
            format!("home = {}/python/bin\n", installed.display()),
        )
        .unwrap();
        fs::write(
            installed.join("venv/bin/deeptutor"),
            format!("#!{}/venv/bin/python\n", installed.display()),
        )
        .unwrap();
        create_symlink(
            "../../python/bin/python3",
            &installed.join("venv/bin/python"),
        )
        .unwrap();
        fs::write(installed.join("manifest.json"), "{\"pack_id\":\"x\"}").unwrap();

        // Content *outside* the venv keeps the build directory forever: only
        // `rewrite_prefix` (venv-scoped) ever rewrites paths, and it never looks
        // at `python/`. The installer therefore has to tokenise the delta's
        // recorded base root too — this is the 108-byte mismatch found against a
        // real pack on 2026-09-24.
        for tree in [&staged, &installed] {
            fs::create_dir_all(tree.join("python/bin")).unwrap();
            fs::write(
                tree.join("python/bin/version.txt"),
                format!("built in {}\n", staged.display()),
            )
            .unwrap();
        }
        let stale = vec![staged.to_string_lossy().into_owned()];

        assert_eq!(
            tree_digest(&staged, &[]).unwrap(),
            tree_digest(&installed, &stale).unwrap(),
            "a fingerprint that changes when a pack is installed would reject every delta"
        );

        // ...and a real content change still moves the fingerprint.
        fs::write(installed.join("manifest.json"), "{\"pack_id\":\"y\"}").unwrap();
        assert_ne!(
            tree_digest(&staged, &[]).unwrap(),
            tree_digest(&installed, &stale).unwrap()
        );
        let _ = fs::remove_dir_all(&staged);
        let _ = fs::remove_dir_all(&installed);
    }

    #[test]
    fn runtime_by_products_do_not_disturb_the_fingerprint() {
        let tree = scratch("noise");
        fs::write(tree.join("module.py"), "x = 1\n").unwrap();
        let before = tree_digest(&tree, &[]).unwrap();
        fs::write(tree.join("module.pyc"), "bytecode").unwrap();
        fs::create_dir_all(tree.join("pkg/__pycache__")).unwrap();
        fs::write(tree.join("pkg/__pycache__/m.cpython-312.pyc"), "cache").unwrap();
        fs::write(tree.join(".DS_Store"), "junk").unwrap();
        assert_eq!(before, tree_digest(&tree, &[]).unwrap());
        let _ = fs::remove_dir_all(&tree);
    }

    #[test]
    fn cloning_links_unchanged_files_and_keeps_symlinks() {
        let source = scratch("clone-source");
        let destination = scratch("clone-destination");
        fs::write(source.join("big.bin"), vec![7u8; 4096]).unwrap();
        fs::create_dir_all(source.join("venv/bin")).unwrap();
        create_symlink("../../python/bin/python3", &source.join("venv/bin/python")).unwrap();

        clone_tree(&source, &destination).unwrap();
        assert_eq!(
            fs::read(destination.join("big.bin")).unwrap(),
            vec![7u8; 4096]
        );
        assert_eq!(
            fs::read_link(destination.join("venv/bin/python")).unwrap(),
            PathBuf::from("../../python/bin/python3")
        );
        let _ = fs::remove_dir_all(&source);
        let _ = fs::remove_dir_all(&destination);
    }

    #[test]
    fn delta_paths_cannot_escape_the_tree() {
        assert!(safe_relative_path("venv/lib/python3.12/site-packages/x.py").is_ok());
        assert!(safe_relative_path(".").is_err());
        assert!(safe_relative_path("").is_err());
        assert!(safe_relative_path("/etc/passwd").is_err());
        assert!(safe_relative_path("../outside").is_err());
        assert!(safe_relative_path("venv/../../outside").is_err());
    }
}
