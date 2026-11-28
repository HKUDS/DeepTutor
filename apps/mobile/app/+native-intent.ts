const nativeRoutes = new Set([
  '',
  '/',
  '/server',
  '/login',
  '/chat',
  '/settings',
]);
const scheme = 'deeptutor-mobile://';

// This version has no route parameters. Only hand known static routes to
// Expo Router; native intents may come from another app.
export function redirectSystemPath({ path }: { path: string }) {
  if (path.length > scheme.length + 12) return '/';
  const route = path.startsWith(scheme)
    ? '/' + path.slice(scheme.length).replace(/^\//, '')
    : path;
  return nativeRoutes.has(route) && route ? route : '/';
}
