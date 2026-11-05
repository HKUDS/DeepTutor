import { open, readdir } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import path from 'node:path';

const MACHO_MAGIC = new Set(['feedface', 'cefaedfe', 'feedfacf', 'cffaedfe', 'cafebabe', 'bebafeca', 'cafebabf', 'bfbafeca']);

// Inspect every regular file, including hidden wheel libraries and extensionless
// executables. Never follow symlinks outside the assembled runtime.
export async function findMachOBinaries(root) {
  const binaries = [];
  for (const entry of await readdir(root, { withFileTypes: true })) {
    const file = path.join(root, entry.name);
    if (entry.isDirectory()) binaries.push(...await findMachOBinaries(file));
    if (!entry.isFile()) continue;
    const handle = await open(file, 'r');
    const magic = Buffer.alloc(4);
    try { await handle.read(magic, 0, 4, 0); }
    finally { await handle.close(); }
    if (!MACHO_MAGIC.has(magic.toString('hex'))) continue;
    // file also distinguishes Java class files (CAFEBABE) and static objects
    // from loadable Mach-O code, and handles universal binaries.
    const description = execFileSync('/usr/bin/file', ['--brief', file], { encoding: 'utf8' });
    if (!description.includes('Mach-O') || !/executable|shared library|bundle/.test(description)) continue;
    binaries.push({ file, executable: description.includes('executable') });
  }
  return binaries;
}

export async function signMacRuntime(root, identity, entitlements) {
  if (!identity) return;
  if (process.platform !== 'darwin') throw new Error('Mac runtime signing requires macOS');
  const binaries = await findMachOBinaries(root);
  if (!binaries.length) throw new Error('No native code found in the Mac runtime');
  // Sign dependencies before the interpreters that load them. The seed archive
  // is inspected recursively by Apple, even though it is an app resource.
  binaries.sort((a, b) => Number(a.executable) - Number(b.executable));
  for (const { file, executable } of binaries) {
    execFileSync('/usr/bin/codesign', [
      '--force', '--sign', identity, '--timestamp', '--options', 'runtime',
      ...(executable ? ['--entitlements', entitlements] : []), file,
    ], { stdio: 'inherit' });
    execFileSync('/usr/bin/codesign', ['--verify', '--strict', file], { stdio: 'inherit' });
  }
  console.log(`Developer ID signed and verified ${binaries.length} runtime binaries`);
}
