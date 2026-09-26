/**
 * A v4 UUID minted in the browser, on any origin.
 *
 * ``crypto.randomUUID`` is defined only in a secure context, so a deployment
 * reached over plain HTTP — a LAN box, a VPS without TLS — has none, and every
 * caller that reached for it *threw*. On the provider settings page that
 * exception landed inside the "Continue" click handler, before the connection
 * was staged: the button appeared dead, with nothing on screen to explain it.
 *
 * ``crypto.getRandomValues`` carries no such gate, which is why it is the
 * fallback rather than ``Math.random``: same shape, still unguessable. The
 * ``Math.random`` tail is only for a runtime with no Web Crypto at all.
 *
 * ``contracts/parse/turn-command.ts`` states the same decision a second time
 * for ``command_id``, and has to: the architecture keeps ``contracts/`` a leaf
 * (``contracts-are-leaves`` in ``.dependency-cruiser.cjs``), so it cannot
 * import this. Everything outside that layer mints ids here.
 */
export function randomUuid(): string {
  const webCrypto = globalThis.crypto;
  if (typeof webCrypto?.randomUUID === "function") return webCrypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (typeof webCrypto?.getRandomValues === "function") {
    webCrypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < bytes.length; i += 1) {
      bytes[i] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
  return [
    hex.slice(0, 4).join(""),
    hex.slice(4, 6).join(""),
    hex.slice(6, 8).join(""),
    hex.slice(8, 10).join(""),
    hex.slice(10, 16).join(""),
  ].join("-");
}
