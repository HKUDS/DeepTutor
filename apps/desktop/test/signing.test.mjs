import assert from 'node:assert/strict';
import { generateKeyPairSync } from 'node:crypto';
import test from 'node:test';
import { assertSigningKey } from '../scripts/lib/signing.mjs';

test('release signing accepts the same public key checked out with Windows line endings', () => {
  const { privateKey, publicKey } = generateKeyPairSync('ed25519');
  const pem = publicKey.export({ type: 'spki', format: 'pem' });
  assert.doesNotThrow(() => assertSigningKey(privateKey, pem));
  assert.doesNotThrow(() => assertSigningKey(privateKey, pem.replaceAll('\n', '\r\n')));
});

test('release signing rejects a different public key', () => {
  const { privateKey } = generateKeyPairSync('ed25519');
  const { publicKey } = generateKeyPairSync('ed25519');
  assert.throws(() => assertSigningKey(privateKey, publicKey.export({ type: 'spki', format: 'pem' })), /signing key does not match/);
});
