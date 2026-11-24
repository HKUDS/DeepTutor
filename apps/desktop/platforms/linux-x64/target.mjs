// Open DeepTutor for Linux (x64). Builds on Linux only.
export default {
  id: 'linux-x64', platform: 'linux', arch: 'x64',
  python: { version: '3.12.13', build: 'cpython-3.12.13-linux-x86_64-none' },
  node: { version: '22.23.4', file: 'node-v22.23.4-linux-x64.tar.gz', sha256: 'b8492284c76a54baf58d61668dd0e41ee0fc98adabf9503d30f05d08f55b4406' },
  // Wheels only: the build machine needs no C/C++ or Rust toolchain.
  pip: ['--only-binary', ':all:'],
  artifact: 'Open-DeepTutor-Linux',
};
