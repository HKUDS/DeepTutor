import path from 'node:path';

// Everything that differs between macOS and Windows at run time lives here;
// build-time differences live in platforms/<target>/.

export const WINDOWS = process.platform === 'win32';

/** Build target folder name for a platform and architecture, e.g. macos-arm64. */
export function targetId(platform = process.platform, arch = process.arch) {
  return `${platform === 'win32' ? 'windows' : 'macos'}-${arch}`;
}

/** Where Python, Node and npm sit inside a core bundle or a downloaded toolchain. */
export function runtimeLayout(platform = process.platform) {
  return platform === 'win32'
    ? { python: 'python/python.exe', node: 'node/node.exe', npm: 'node/node_modules/npm/bin/npm-cli.js' }
    : { python: 'python/bin/python3', node: 'node/bin/node', npm: 'node/lib/node_modules/npm/bin/npm-cli.js' };
}

/**
 * The client's name, which always precedes the version. `full` is used on the
 * start screen and in About; `short` where space is tight. The web UI keeps
 * the same table in web/lib/version.ts.
 */
const EDITIONS = {
  'macos-arm64': { full: 'Open DeepTutor for MacOS with Apple Silicon', short: 'MacOS (Apple Silicon)' },
  'macos-x64': { full: 'Open DeepTutor for MacOS with Intel Silicon', short: 'MacOS (Intel)' },
  'windows-x64': { full: 'Open DeepTutor for Windows', short: 'Windows' },
};

export function edition(platform = process.platform, arch = process.arch) {
  return EDITIONS[targetId(platform, arch)]
    ?? (platform === 'win32' ? EDITIONS['windows-x64'] : { full: 'Open DeepTutor for MacOS', short: 'MacOS' });
}

/** The marker the web UI reads from the user agent: OpenDeepTutor/1.7.1 (macOS; arm64). */
export function agentMarker(version, platform = process.platform, arch = process.arch) {
  return `OpenDeepTutor/${version} (${platform === 'win32' ? 'Windows' : 'macOS'}; ${arch})`;
}

/** The system tar: bsdtar on both macOS and Windows 10+, which also reads zip. */
export function systemTar() {
  return WINDOWS ? path.join(process.env.SystemRoot ?? 'C:\\Windows', 'System32', 'tar.exe') : '/usr/bin/tar';
}

/** A PATH that holds only operating system tools, so tests prove no developer toolchain is used. */
export function systemPath() {
  if (!WINDOWS) return '/usr/bin:/bin:/usr/sbin:/sbin';
  const root = process.env.SystemRoot ?? 'C:\\Windows';
  return [path.join(root, 'System32'), root, path.join(root, 'System32', 'Wbem')].join(';');
}
