import { Platform } from 'react-native';

const ORIGIN_PATTERN =
  /^(https?):\/\/(\[[0-9a-f:.]+\]|[a-z0-9.-]+)(?::([0-9]{1,5}))?\/?$/i;
const DEV_HTTP_HOSTS = new Set(['localhost', '127.0.0.1', '10.0.2.2', '[::1]']);

export function serverOrigin(
  address: string,
  allowLocalHttp = __DEV__,
): string {
  const match = ORIGIN_PATTERN.exec(address.trim());
  const invalid = 'Enter a server address like https://tutor.example.com.';
  if (!match) {
    throw new Error(invalid);
  }
  const protocol = match[1].toLowerCase();
  const host = match[2].toLowerCase();
  const port = match[3] ? Number(match[3]) : undefined;
  if (port !== undefined && (port < 1 || port > 65535)) {
    throw new Error(invalid);
  }
  if (
    !host.startsWith('[') &&
    (host.length > 253 ||
      host
        .split('.')
        .some(label => !/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label)))
  ) {
    throw new Error(invalid);
  }

  const origin = `${protocol}://${host}${port === undefined ? '' : `:${port}`}`;
  let parsed: URL;
  try {
    parsed = new URL(origin);
  } catch {
    throw new Error(invalid);
  }
  // Reject noncanonical numeric hosts that URL parsers could interpret as IPv4.
  if (!host.startsWith('[') && parsed.hostname.toLowerCase() !== host) {
    throw new Error(invalid);
  }
  if (protocol === 'http' && !(allowLocalHttp && DEV_HTTP_HOSTS.has(host))) {
    throw new Error('Use HTTPS to connect to this server.');
  }
  const defaultPort = protocol === 'https' ? 443 : 80;
  return `${protocol}://${parsed.hostname.toLowerCase()}${
    port === undefined || port === defaultPort ? '' : `:${port}`
  }`;
}

export function devSuggestedServerAddress(): string {
  if (!__DEV__) {
    return '';
  }
  return Platform.OS === 'android'
    ? 'http://10.0.2.2:18001'
    : 'http://localhost:18001';
}
