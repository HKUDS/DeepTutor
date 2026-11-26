import { copyFile, mkdir, readdir, realpath, rm, stat, unlink } from 'node:fs/promises';
import path from 'node:path';

// An in-place core switch copies the workspace aside first and puts it back if
// the new core does not start. Both directions have to survive a data folder
// that is a junction or a symlink, and neither may destroy a tree: that is how
// a workspace looked lost in #2721.

/**
 * Copy a workspace tree over an existing one.
 *
 * Reparse points are followed instead of re-created. `fs.cp` decides for itself
 * whether to copy a junction's contents or to recreate the link, and recreating
 * it needs SeCreateSymbolicLinkPrivilege on Windows, which a normal user does
 * not have: that is the EPERM that aborted the upgrade in #2721. Following the
 * link here is deterministic across Node versions, and it also keeps a backup
 * self-contained: it holds the files, not a pointer to the live tree.
 *
 * Writing through the existing paths rather than replacing them is what keeps a
 * user's linked data folder on the drive they chose: files are written into the
 * folder the link points at, and the link itself is never touched.
 */
export async function copyWorkspace(source, destination) {
  await copyTree(source, destination, []);
  return destination;
}

async function copyTree(source, destination, ancestors) {
  // realpath also resolves the links we are writing through, and throws for a
  // dangling one, so an incomplete tree fails the copy instead of succeeding.
  const resolved = await realpath(source);
  // A junction that points back up its own tree must not recurse forever.
  if (ancestors.includes(resolved)) return;
  const chain = [...ancestors, resolved];
  await mkdir(destination, { recursive: true, mode: 0o700 });
  for (const entry of await readdir(resolved, { withFileTypes: true })) {
    const from = path.join(resolved, entry.name);
    const to = path.join(destination, entry.name);
    if (entry.isFile()) {
      await copyFile(from, to);
    } else if (entry.isDirectory() && !entry.isSymbolicLink()) {
      await copyTree(from, to, chain);
    } else if (entry.isSymbolicLink()) {
      // The target, not the link: a backup has to stand on its own. A link may
      // point at a file or a directory, and recursing into a file target made
      // `readdir` throw ENOTDIR — which `snapshotWorkspace` swallows, so the
      // upgrade silently continued without a rollback point. Resolve first.
      const target = await stat(from);
      if (target.isFile()) await copyFile(from, to);
      else if (target.isDirectory()) await copyTree(from, to, chain);
      // Sockets, FIFOs and devices are not workspace content: skip them.
    }
  }
}

/**
 * Back the workspace up before a core switch.
 *
 * Returns the backup path, or `undefined` when there is nothing to back up yet
 * or the copy failed. A backup only protects a rollback; it is never a reason
 * to refuse to start, so the caller logs the failure and keeps going rather
 * than aborting every launch. A partial copy is removed so it can never be
 * restored over the user's own tree, and the path is returned only once the
 * copy finished, so a folder that is not a backup cannot become a restore
 * source.
 */
export async function snapshotWorkspace(source, destination, { warn = () => {} } = {}) {
  try {
    await stat(source);
  } catch (error) {
    // First launch: there is no workspace to roll back to.
    if (error.code === 'ENOENT') return undefined;
    throw error;
  }
  try {
    await copyWorkspace(source, destination);
    return destination;
  } catch (error) {
    // The destination only ever holds what this copy wrote, so it is safe to
    // drop as a whole; nothing in the workspace is touched by it.
    await rm(destination, { recursive: true, force: true, maxRetries: 3 }).catch(() => {});
    warn(error);
    return undefined;
  }
}

/**
 * Put a workspace backup back in place.
 *
 * The backup is written over the existing tree instead of replacing it. That is
 * what keeps a linked data folder on its own drive, and it means a restore that
 * fails partway can only leave files the backup itself wrote: the previous
 * implementation moved the whole workspace aside first, so a copy that failed
 * after the move left a partial tree where the user's data used to be.
 */
export async function restoreWorkspace(backup, destination) {
  await copyWorkspace(backup, destination);
  await pruneExtra(backup, destination, []);
}

/**
 * Remove destination entries the backup does not have.
 *
 * The walk descends the backup's shape, so an unreadable backup cannot cause a
 * broad delete, and a link is only descended when the backup describes a
 * directory there — pruning can never reach a user's linked drive through a
 * junction the backup knows nothing about.
 */
async function pruneExtra(backup, destination, ancestors) {
  const resolvedBackup = await realpath(backup);
  if (ancestors.includes(resolvedBackup)) return;
  const chain = [...ancestors, resolvedBackup];

  let destinationEntries;
  try {
    destinationEntries = new Map(
      (await readdir(destination, { withFileTypes: true })).map(e => [e.name, e]),
    );
  } catch (error) {
    if (error.code === 'ENOENT' || error.code === 'ENOTDIR') return;
    throw error;
  }

  const keep = new Set();
  for (const entry of await readdir(resolvedBackup, { withFileTypes: true })) {
    keep.add(entry.name);
    const from = path.join(resolvedBackup, entry.name);
    const to = path.join(destination, entry.name);
    if (entry.isDirectory() && !entry.isSymbolicLink()) {
      const target = await stat(to).catch(() => null);
      if (target?.isDirectory()) await pruneExtra(from, to, chain);
    }
  }

  for (const [name, entry] of destinationEntries) {
    if (keep.has(name)) continue;
    const stale = path.join(destination, name);
    if (entry.isDirectory() && !entry.isSymbolicLink()) {
      await rm(stale, { recursive: true, force: true, maxRetries: 3 });
    } else {
      // unlink never recurses, so a link's target is untouched.
      await unlink(stale).catch(error => {
        if (error.code !== 'ENOENT') throw error;
      });
    }
  }
}
