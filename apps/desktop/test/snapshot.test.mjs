import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdir, mkdtemp, readdir, readFile, rmdir, symlink, unlink, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { copyWorkspace, restoreWorkspace, snapshotWorkspace } from '../src/snapshot.mjs';

const WINDOWS = process.platform === 'win32';

/** A junction on Windows, a directory symlink elsewhere: the shape #2721 hit. */
async function link(target, at) {
  if (WINDOWS) {
    execFileSync(path.join(process.env.SystemRoot ?? 'C:\\Windows', 'System32', 'cmd.exe'),
      ['/c', 'mklink', '/J', at, target], { stdio: 'ignore', windowsHide: true });
  } else await symlink(target, at, 'dir');
}

/**
 * Delete a fixture without ever following a link into the folder it points at.
 * `fs.rm` walks a junction as a directory on Windows, so a cleanup that used it
 * could delete the folder a test linked to.
 */
async function removeTree(target) {
  let entries;
  try { entries = await readdir(target, { withFileTypes: true }); }
  catch (error) {
    if (error.code === 'ENOENT' || error.code === 'ENOTDIR') return;
    throw error;
  }
  for (const entry of entries) {
    const child = path.join(target, entry.name);
    if (entry.isSymbolicLink()) {
      try { await unlink(child); } catch { await rmdir(child).catch(() => {}); }
    } else if (entry.isDirectory()) await removeTree(child);
    else await unlink(child).catch(() => {});
  }
  await rmdir(target).catch(() => {});
}

async function workspace(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'deeptutor snapshot '));
  t.after(() => removeTree(root));
  const home = path.join(root, 'workspace');
  await mkdir(path.join(home, 'data/user/settings'), { recursive: true });
  await writeFile(path.join(home, 'data/user/settings/interface.json'), '{"language":"en"}');
  await writeFile(path.join(home, 'active.json'), '{"runtimeId":"1.7.2-x64"}');
  return { root, home };
}

test('a backup follows a linked data folder instead of recreating the link', async t => {
  const { root, home } = await workspace(t);
  // The user's real data lives on another disk, reached through a junction.
  const elsewhere = path.join(root, 'elsewhere/data');
  await mkdir(path.join(elsewhere, 'user/settings'), { recursive: true });
  await writeFile(path.join(elsewhere, 'sessions.json'), '{"turns":3}');
  await writeFile(path.join(elsewhere, 'user/settings/interface.json'), '{"language":"zh"}');
  await removeTree(path.join(home, 'data'));
  await link(elsewhere, path.join(home, 'data'));

  const backup = path.join(root, 'backups/before-1.7.3');
  assert.equal(await snapshotWorkspace(home, backup), backup);
  // fs.cp recreates the junction as a link here, which needs a privilege a
  // normal Windows account does not have and fails with EPERM.
  const copied = path.join(backup, 'data');
  assert.equal((await readdir(copied)).sort().join(','), 'sessions.json,user');
  assert.equal(await readFile(path.join(copied, 'user/settings/interface.json'), 'utf8'), '{"language":"zh"}');
  // The backup is self-contained: it holds the files, not a pointer to the live
  // tree, so it survives the other drive going away.
  await removeTree(elsewhere);
  assert.equal(await readFile(path.join(copied, 'sessions.json'), 'utf8'), '{"turns":3}');
});

test('a circular link does not make the backup recurse forever', async t => {
  const { root, home } = await workspace(t);
  await mkdir(path.join(home, 'data/loop'), { recursive: true });
  await link(home, path.join(home, 'data/loop/back'));
  const backup = path.join(root, 'backups/before-1.7.3');
  assert.equal(await snapshotWorkspace(home, backup), backup);
  assert.equal(await readFile(path.join(backup, 'data/user/settings/interface.json'), 'utf8'), '{"language":"en"}');
});

test('a failed backup is reported, cleaned up, and never becomes a restore source', async t => {
  const { root, home } = await workspace(t);
  // A link whose target is gone makes the copy fail partway through.
  const dangling = path.join(root, 'dangling-target');
  await mkdir(dangling, { recursive: true });
  await link(dangling, path.join(home, 'data/lost'));
  await removeTree(dangling);

  const backup = path.join(root, 'backups/before-1.7.3');
  const failures = [];
  assert.equal(await snapshotWorkspace(home, backup, { warn: error => failures.push(error) }), undefined);
  assert.equal(failures.length, 1);
  // The half-written destination is removed, so nothing can restore a stub.
  await assert.rejects(readdir(backup), { code: 'ENOENT' });
  // The user's own workspace is untouched.
  assert.equal(await readFile(path.join(home, 'active.json'), 'utf8'), '{"runtimeId":"1.7.2-x64"}');
});

test('the first launch has nothing to back up', async t => {
  const { root } = await workspace(t);
  assert.equal(await snapshotWorkspace(path.join(root, 'absent'), path.join(root, 'backups/x')), undefined);
});

test('a restore puts the backup back over the failed workspace', async t => {
  const { root, home } = await workspace(t);
  const backup = path.join(root, 'backups/before-1.7.3');
  await snapshotWorkspace(home, backup);
  await writeFile(path.join(home, 'active.json'), '{"runtimeId":"1.7.3-x64"}');
  await writeFile(path.join(home, 'data/user/settings/interface.json'), '{"language":"zh"}');

  await restoreWorkspace(backup, home);
  assert.equal(await readFile(path.join(home, 'active.json'), 'utf8'), '{"runtimeId":"1.7.2-x64"}');
  assert.equal(await readFile(path.join(home, 'data/user/settings/interface.json'), 'utf8'), '{"language":"en"}');
});

test('a restore keeps a linked data folder on its own drive', async t => {
  const { root, home } = await workspace(t);
  const elsewhere = path.join(root, 'elsewhere/data');
  await mkdir(elsewhere, { recursive: true });
  await writeFile(path.join(elsewhere, 'sessions.json'), '{"turns":3}');
  await removeTree(path.join(home, 'data'));
  await link(elsewhere, path.join(home, 'data'));

  const backup = path.join(root, 'backups/before-1.7.3');
  await snapshotWorkspace(home, backup);
  // The failed core wrote into the linked folder before it was rolled back.
  await writeFile(path.join(elsewhere, 'half-written.json'), '{}');
  await restoreWorkspace(backup, home);

  // The data is back on the original drive, and the workspace still links to it
  // instead of holding a silent copy on the system drive.
  assert.equal(await readFile(path.join(elsewhere, 'sessions.json'), 'utf8'), '{"turns":3}');
  await writeFile(path.join(home, 'data/probe.json'), '{"via":"link"}');
  assert.equal(await readFile(path.join(elsewhere, 'probe.json'), 'utf8'), '{"via":"link"}');
});

test('a restore that cannot read its backup still leaves the workspace intact', async t => {
  const { root, home } = await workspace(t);
  const broken = path.join(root, 'backups/before-1.7.3');
  const gone = path.join(root, 'gone-target');
  await mkdir(gone, { recursive: true });
  await mkdir(path.join(broken, 'data'), { recursive: true });
  await link(gone, path.join(broken, 'data/lost'));
  await removeTree(gone);

  await assert.rejects(restoreWorkspace(broken, home));
  // Nothing was moved aside first, so the user's own tree is still there.
  assert.equal(await readFile(path.join(home, 'active.json'), 'utf8'), '{"runtimeId":"1.7.2-x64"}');
  assert.equal(await readFile(path.join(home, 'data/user/settings/interface.json'), 'utf8'), '{"language":"en"}');
});

test('copying a workspace keeps files that sit next to a linked folder', async t => {
  const { root, home } = await workspace(t);
  const copy = path.join(root, 'copy');
  await copyWorkspace(home, copy);
  assert.equal((await readdir(copy)).sort().join(','), 'active.json,data');
  await removeTree(copy);
});
