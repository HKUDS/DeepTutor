import { packager } from '@electron/packager';
import { cp, mkdir, rm, symlink } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { appRoot } from './target.mjs';
import { PACKAGER, stageApp } from './stage.mjs';

/** Shared by platforms/macos-arm64 and platforms/macos-x64: a signed .app inside a DMG. */
export async function packageMac(target) {
  const { stage, version, pkg, out } = await stageApp(target);
  // With APPLE_SIGNING_IDENTITY ("Developer ID Application: …") the app gets a
  // hardened-runtime Developer ID signature; otherwise it is signed ad hoc.
  const identity = process.env.APPLE_SIGNING_IDENTITY;
  const entitlements = path.join(appRoot, 'assets/entitlements.mac.plist');
  const [built] = await packager({
    ...PACKAGER, dir: stage, out,
    appVersion: version, buildVersion: version, electronVersion: pkg.devDependencies.electron,
    platform: 'darwin', arch: target.arch, icon: path.join(appRoot, 'assets/icon.icns'),
    extraResource: [target.seed],
    appCategoryType: 'public.app-category.education',
    extendInfo: {
      NSMicrophoneUsageDescription: 'Open DeepTutor uses the microphone when you speak to your tutor.',
      NSCameraUsageDescription: 'Open DeepTutor uses the camera when you capture learning material.',
      NSLocalNetworkUsageDescription: 'Open DeepTutor runs its learning services on this Mac.',
    },
    ...(identity ? { osxSign: { identity, optionsForFile: () => ({ hardenedRuntime: true, entitlements }) } } : {}),
  });
  const bundle = path.join(built, 'Open DeepTutor.app');
  if (!identity) execFileSync('/usr/bin/codesign', ['--force', '--deep', '--sign', '-', bundle], { stdio: 'inherit' });
  execFileSync('/usr/bin/codesign', ['--verify', '--deep', '--strict', bundle], { stdio: 'inherit' });

  const dmgStage = path.join(target.local, 'dmg');
  const dmg = path.join(out, `${target.artifact}-v${version}.dmg`);
  await rm(dmgStage, { recursive: true, force: true });
  await mkdir(dmgStage, { recursive: true });
  await cp(bundle, path.join(dmgStage, 'Open DeepTutor.app'), { recursive: true, verbatimSymlinks: true });
  await cp(path.join(built, 'LICENSES.chromium.html'), path.join(dmgStage, 'LICENSES.chromium.html'));
  await symlink('/Applications', path.join(dmgStage, 'Applications'));
  await rm(dmg, { force: true });
  execFileSync('/usr/bin/hdiutil', ['create', '-volname', 'Open DeepTutor', '-srcfolder', dmgStage, '-fs', 'APFS', '-format', 'ULFO', dmg], { stdio: 'inherit' });
  await rm(dmgStage, { recursive: true, force: true });
  return [bundle, dmg];
}
