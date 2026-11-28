import { serverOrigin } from '../src/features/server/serverAddress';

describe('serverOrigin', () => {
  test.each([
    [' HTTPS://Tutor.Example.com:443/ ', 'https://tutor.example.com'],
    ['https://localhost:8443', 'https://localhost:8443'],
    ['https://192.168.1.42:8080', 'https://192.168.1.42:8080'],
    ['https://[2001:db8::5]:8443', 'https://[2001:db8::5]:8443'],
  ])('normalizes the self-hosted origin %s', (address, expected) => {
    expect(serverOrigin(address, false)).toBe(expected);
  });

  test.each([
    'http://10.0.2.2:18001',
    'http://localhost:18001',
    'http://127.0.0.1:18001',
    'http://[::1]:18001',
  ])('accepts %s only in local development', address => {
    expect(serverOrigin(address, true)).toBe(address);
    expect(() => serverOrigin(address, false)).toThrow('Use HTTPS');
  });

  test.each([
    'http://192.168.1.42:80',
    'http://localhost.evil.example',
    'http://127.1:8001',
    'http://0x7f000001:8001',
    'https://tutor.example.com:0',
    'https://tutor.example.com:65536',
    'https://tutor.example.com:-1',
    'https://tutor.example.com/path',
    'https://tutor.example.com/?token=x',
    'https://tutor.example.com#',
    'https://tutor.example.com@evil.example',
    'https://user:pass@tutor.example.com',
    'https://tutor.example.com\\evil.example',
    'https://tutor.example.com%2f.evil.example',
    'https://[fe80:::1]',
    'file:///tmp',
    ['javascript', 'alert(1)'].join(':'),
  ])('rejects invalid or unsafe address %s', address => {
    expect(() => serverOrigin(address, true)).toThrow();
  });
});
