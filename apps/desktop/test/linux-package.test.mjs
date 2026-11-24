import test from 'node:test';
import assert from 'node:assert/strict';

test('Linux downloads are named with the version and both formats', () => {
  const stem = `Open-DeepTutor-Linux-v1.7.4`;
  assert.equal(`${stem}.AppImage`, 'Open-DeepTutor-Linux-v1.7.4.AppImage');
  assert.equal(`${stem}.deb`, 'Open-DeepTutor-Linux-v1.7.4.deb');
});

test('the Linux target names its toolchain and artifact', async () => {
  const { default: target } = await import('../platforms/linux-x64/target.mjs');
  assert.equal(target.id, 'linux-x64');
  assert.equal(target.platform, 'linux');
  assert.equal(target.arch, 'x64');
  assert.equal(target.python.version, '3.12.13');
  assert.equal(target.node.version, '22.23.4');
  assert.match(target.node.sha256, /^[a-f0-9]{64}$/);
  assert.deepEqual(target.pip, ['--only-binary', ':all:']);
  assert.equal(target.artifact, 'Open-DeepTutor-Linux');
});
