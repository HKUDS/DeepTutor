import { createPublicKey } from 'node:crypto';

/** Compare key material, independent of PEM whitespace and checkout line endings. */
export function assertSigningKey(privateKey, publicKey) {
  const derived = createPublicKey(privateKey).export({ type: 'spki', format: 'der' });
  const expected = createPublicKey(publicKey).export({ type: 'spki', format: 'der' });
  if (!derived.equals(expected)) {
    throw new Error('The signing key does not match assets/runtime-public.pem; the shipped app would reject this core.');
  }
}
