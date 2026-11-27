import { lstat, readdir, realpath, rename, unlink } from 'node:fs/promises';
import path from 'node:path';

const isMissing = error => error.code === 'ENOENT';

async function legacyVault(directory) {
  try {
    const root = await realpath(directory);
    if (root !== directory) return undefined;
    const candidate = path.join(root, 'data', 'system', 'chatgpt-plan.enc');
    const stat = await lstat(candidate);
    if (stat.isFile() && await realpath(candidate) === candidate) return candidate;
  } catch (error) {
    if (!isMissing(error)) throw error;
  }
}

async function removeLegacyCopies(parent, prefix) {
  const entries = await readdir(parent, { withFileTypes: true }).catch(error => {
    if (isMissing(error)) return [];
    throw error;
  });
  for (const entry of entries) {
    if (!entry.isDirectory() || !entry.name.startsWith(prefix)) continue;
    const legacy = await legacyVault(path.join(parent, entry.name));
    if (legacy) await unlink(legacy);
  }
}

export async function prepareChatGPTPlanVault(userRoot) {
  userRoot = await realpath(userRoot).catch(error => {
    if (isMissing(error)) return null;
    throw error;
  });
  if (!userRoot) return;
  const legacy = await legacyVault(path.join(userRoot, 'workspace'));
  if (legacy) {
    const vault = path.join(userRoot, 'chatgpt-plan-vault.enc');
    const existing = await lstat(vault).catch(error => {
      if (isMissing(error)) return null;
      throw error;
    });
    if (existing) {
      if (!existing.isFile()) throw new Error('The ChatGPT Plan vault is not a regular file');
      await unlink(legacy);
    } else {
      await rename(legacy, vault);
    }
  }
  // Workspace rollbacks cannot restore an older token set.
  const backups = path.join(userRoot, 'backups');
  if (await realpath(backups).catch(error => {
    if (isMissing(error)) return null;
    throw error;
  }) === backups) await removeLegacyCopies(backups, 'before-');
  await removeLegacyCopies(userRoot, 'workspace.interrupted-');
}
