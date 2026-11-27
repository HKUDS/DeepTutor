// Open DeepTutor for Windows (x64). Builds on Windows only.
export default {
  id: 'windows-x64', platform: 'win32', arch: 'x64',
  python: { version: '3.12.13', build: 'cpython-3.12.13-windows-x86_64-none' },
  node: { version: '22.23.4', file: 'node-v22.23.4-win-x64.zip', sha256: 'cbc74b5e0982c9dbb41525fd8fb5dcd32fbee237863f7829072f4639a1ce5f20' },
  // Wheels only: the build machine needs no C/C++ or Rust toolchain.
  pip: ['--only-binary', ':all:'],
  artifact: 'Open-DeepTutor-Windows',
};
