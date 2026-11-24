import { packager } from '@electron/packager';
import { mkdir, rm, writeFile, cp, access } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { appRoot } from '../../scripts/lib/target.mjs';
import { PACKAGER, stageApp } from '../../scripts/lib/stage.mjs';

async function findTool(name) {
  const candidates = [path.join(process.env.OPEN_DEEPTUTOR_TOOLS ?? '', name), name];
  for (const candidate of candidates) {
    if (!path.isAbsolute(candidate)) return candidate;
    try { await access(candidate); return candidate; } catch { /* next */ }
  }
}

// Open-DeepTutor-Linux-v<version>.AppImage and Open-DeepTutor-Linux-v<version>.deb
export default async function packageLinux(target) {
  const { stage, version, pkg, out } = await stageApp(target);
  // The packager emits a directory (e.g. linux-unpacked) containing the Electron
  // binary, the app (asar) and the bundled seed resource.
  const [built] = await packager({
    ...PACKAGER, dir: stage, out,
    appVersion: version, electronVersion: pkg.devDependencies.electron,
    platform: 'linux', arch: target.arch,
    icon: path.join(appRoot, 'assets/mark.png'),
    executableName: 'open-deeptutor',
    extraResource: [target.seed],
    appCopyright: 'Copyright HKUDS. Licensed under Apache-2.0.',
  });

  const stem = `${target.artifact}-v${version}`;

  // AppImage: build an AppDir with an AppRun launcher, a .desktop entry and an icon.
  const appDir = path.join(target.local, 'appdir');
  await rm(appDir, { recursive: true, force: true });
  await mkdir(appDir, { recursive: true });
  await writeFile(path.join(appDir, 'AppRun'), [
    '#!/bin/sh',
    'set -e',
    'exec "$(dirname "$0")/open-deeptutor" "$@"',
    '',
  ].join('\n'), { mode: 0o755 });
  // The packager output is a directory; copy its whole tree into the AppDir.
  await cp(built, path.join(appDir, 'open-deeptutor'), { recursive: true });
  await cp(path.join(appRoot, 'assets/mark.png'), path.join(appDir, 'open-deeptutor.png'));
  await writeFile(path.join(appDir, 'open-deeptutor.desktop'), [
    '[Desktop Entry]',
    'Name=Open DeepTutor',
    'Comment=Open DeepTutor for Linux',
    'Exec=open-deeptutor',
    'Icon=open-deeptutor',
    'Terminal=false',
    'Type=Application',
    'Categories=Education;',
    '',
  ].join('\n'), { mode: 0o644 });

  const appImage = path.join(out, `${stem}.AppImage`);
  await rm(appImage, { force: true });
  const appimagetool = await findTool('appimagetool');
  // --appimage-extract-and-run runs the tool even when FUSE is unavailable in
  // a container; --no-appstream skips the AppStream catalog requirement.
  execFileSync(appimagetool, ['--appimage-extract-and-run', '--no-appstream', appDir, appImage], { stdio: 'inherit' });

  // .deb: build a Debian package tree under /opt with a menu entry and icon.
  const deb = path.join(out, `${stem}.deb`);
  await rm(deb, { force: true });
  const debRoot = path.join(target.local, 'deb');
  await rm(debRoot, { recursive: true, force: true });
  await mkdir(path.join(debRoot, 'DEBIAN'), { recursive: true });
  await mkdir(path.join(debRoot, 'opt', 'Open DeepTutor'), { recursive: true });
  await mkdir(path.join(debRoot, 'usr', 'share', 'applications'), { recursive: true });
  await mkdir(path.join(debRoot, 'usr', 'share', 'icons', 'hicolor', '512x512', 'apps'), { recursive: true });
  await cp(built, path.join(debRoot, 'opt', 'Open DeepTutor', 'open-deeptutor'), { recursive: true });
  await cp(path.join(appRoot, 'assets/mark.png'), path.join(debRoot, 'usr', 'share', 'icons', 'hicolor', '512x512', 'apps', 'open-deeptutor.png'));
  await writeFile(path.join(debRoot, 'usr', 'share', 'applications', 'open-deeptutor.desktop'), [
    '[Desktop Entry]',
    'Name=Open DeepTutor',
    'Comment=Open DeepTutor for Linux',
    'Exec=/opt/Open DeepTutor/open-deeptutor',
    'Icon=open-deeptutor',
    'Terminal=false',
    'Type=Application',
    'Categories=Education;',
    '',
  ].join('\n'), { mode: 0o644 });
  await writeFile(path.join(debRoot, 'DEBIAN', 'control'), [
    `Package: open-deeptutor`,
    `Version: ${version}`,
    `Architecture: amd64`,
    `Maintainer: HKUDS <bingxizhao39@gmail.com>`,
    `Description: Open DeepTutor for Linux`,
    ` DeepTutor's local runtime in a native window.`,
    '',
  ].join('\n'), { mode: 0o644 });

  execFileSync('dpkg-deb', ['--build', debRoot, deb], { stdio: 'inherit' });
  return [appImage, deb];
}
