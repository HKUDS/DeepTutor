import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, symlink, rm } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { findMachOBinaries } from '../scripts/lib/macos-runtime-signing.mjs';

test('Mac signing finds extensionless code and hidden libraries without following symlinks', { skip: process.platform !== 'darwin' }, async () => {
  const temp = await mkdtemp(path.join(os.tmpdir(), 'native-signing-'));
  try {
    const root = path.join(temp, 'runtime');
    await mkdir(path.join(root, '.libs'), { recursive: true });
    const source = path.join(temp, 'fixture.c');
    await writeFile(source, 'int main(void) { return 0; }\n');
    execFileSync('cc', [source, '-o', path.join(root, 'interpreter')]);
    execFileSync('cc', ['-dynamiclib', source, '-o', path.join(root, '.libs', 'dependency')]);
    execFileSync('cc', ['-c', source, '-o', path.join(root, 'static.o')]);
    await writeFile(path.join(root, 'fake.dylib'), '#!/bin/sh\n');
    await symlink(process.execPath, path.join(root, 'outside'));
    await symlink(path.join(root, 'interpreter'), path.join(root, 'alias'));
    const files = await findMachOBinaries(root);
    assert.deepEqual(files.map(({ file, executable }) => [path.relative(root, file), executable]).sort(), [
      ['.libs/dependency', false], ['interpreter', true],
    ]);
  } finally { await rm(temp, { recursive: true, force: true }); }
});
