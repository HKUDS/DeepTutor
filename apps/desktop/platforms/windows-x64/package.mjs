import { packager } from '@electron/packager';
import { access, rm } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { systemTar } from '../../src/platform.mjs';
import { appRoot } from '../../scripts/lib/target.mjs';
import { PACKAGER, stageApp } from '../../scripts/lib/stage.mjs';

async function findMakensis() {
  const candidates = [path.join(process.env['ProgramFiles(x86)'] ?? 'C:\\Program Files (x86)', 'NSIS', 'makensis.exe'), 'makensis'];
  for (const candidate of candidates) {
    if (!path.isAbsolute(candidate)) return candidate;
    try { await access(candidate); return candidate; } catch { /* next */ }
  }
}

/** Windows file versions are four numbers; 1.7.1rc2 becomes 1.7.1.0. */
const fileVersion = version => [...(version.match(/^\d+\.\d+\.\d+/)?.[0] ?? '0.0.0').split('.'), '0'].join('.');

// Open-DeepTutor-Windows-v<version>-Setup.exe and Open-DeepTutor-Windows-v<version>-Portable.zip
export default async function packageWindows(target) {
  const { stage, version, pkg, out } = await stageApp(target);
  const [built] = await packager({
    ...PACKAGER, dir: stage, out,
    appVersion: version, buildVersion: fileVersion(version), electronVersion: pkg.devDependencies.electron,
    platform: 'win32', arch: target.arch, icon: path.join(appRoot, 'assets/icon.ico'),
    extraResource: [target.seed],
    appCopyright: 'Copyright HKUDS. Licensed under Apache-2.0.',
    win32metadata: {
      CompanyName: 'HKUDS', ProductName: 'Open DeepTutor',
      FileDescription: 'Open DeepTutor for Windows', InternalName: 'Open DeepTutor',
      OriginalFilename: 'Open DeepTutor.exe', 'requested-execution-level': 'asInvoker',
    },
  });

  const stem = `${target.artifact}-v${version}`;
  const portable = path.join(out, `${stem}-Portable.zip`);
  await rm(portable, { force: true });
  execFileSync(systemTar(), ['--format', 'zip', '-cf', portable, '-C', path.dirname(built), path.basename(built)], { stdio: 'inherit' });

  const installer = path.join(out, `${stem}-Setup.exe`);
  await rm(installer, { force: true });
  execFileSync(await findMakensis(), [
    `/DSOURCE=${built}`, `/DOUTFILE=${installer}`, `/DICON=${path.join(appRoot, 'assets/icon.ico')}`,
    `/DVERSION=${version}`, `/DFILEVERSION=${fileVersion(version)}`,
    path.join(target.folder, 'installer.nsi'),
  ], { stdio: 'inherit' });
  return [built, portable, installer];
}
