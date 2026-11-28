import { TurboModuleRegistry, type TurboModule } from 'react-native';

interface NetworkingCookies extends TurboModule {
  clearCookies(callback: (removedCookies: boolean) => void): void;
}

/**
 * Native networking and WebSocket share the OS cookie store. Cookies are not
 * scoped by port, so switching origins must clear the jar before probing the
 * next origin. Never read HttpOnly values into JavaScript.
 */
export async function clearNativeCookies(): Promise<void> {
  const networking = TurboModuleRegistry.get<NetworkingCookies>('Networking');
  if (!networking || typeof networking.clearCookies !== 'function') {
    throw new Error('This build cannot clear the saved server session.');
  }
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error('The saved server session could not be cleared.')),
      5000,
    );
    // False means the store was already empty on either supported platform.
    networking.clearCookies(() => {
      clearTimeout(timer);
      resolve();
    });
  });
}
