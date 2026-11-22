import assert from 'node:assert/strict';
import { access, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { prepareChatGPTPlanVault } from '../src/chatgpt-plan-vault.mjs';

test('moves the current vault out of the workspace and removes rollback copies', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'deeptutor-vault-'));
  try {
    const paths = ['workspace', 'backups/before-fixture', 'workspace.interrupted-fixture'];
    const files = [];
    for (const location of paths) {
      const directory = path.join(root, location, 'data', 'system');
      await mkdir(directory, { recursive: true });
      const file = path.join(directory, 'chatgpt-plan.enc');
      await writeFile(file, location);
      await writeFile(path.join(directory, 'other-data'), location);
      files.push(file);
    }
    await prepareChatGPTPlanVault(root);
    await prepareChatGPTPlanVault(root);
    assert.equal(await readFile(path.join(root, 'chatgpt-plan-vault.enc'), 'utf8'), 'workspace');
    for (const file of files) {
      await assert.rejects(access(file), { code: 'ENOENT' });
      await access(path.join(path.dirname(file), 'other-data'));
    }
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
