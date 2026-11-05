// Open DeepTutor for MacOS with Intel Silicon. Builds on an Intel Mac, or on
// Apple Silicon through Rosetta: every build tool runs from the x64 toolchain.
export default {
  id: 'macos-x64', platform: 'darwin', arch: 'x64',
  python: { version: '3.12.13', build: 'cpython-3.12.13-macos-x86_64-none' },
  node: { version: '22.23.4', file: 'node-v22.23.4-darwin-x64.tar.gz', sha256: 'efcc2b0db6f94bf53eddb038fe2b370277a042bd29e4f19b8f8e23598795b819' },
  // PyMuPDF 2 and cryptography 50 ship no Intel Mac wheels and their sources do not
  // build here; wheels only resolves to the newest releases that do (PyMuPDF 1.28).
  pip: ['--only-binary', ':all:'],
  artifact: 'Open-DeepTutor-MacOS-Intel',
};
