// Electron renderer type declarations
interface DeeptutorAppAPI {
  start():     Promise<{ ok: boolean; error?: string }>;
  stop():      Promise<{ ok: boolean }>;
  restart():   Promise<{ ok: boolean }>;
  getStatus(): Promise<{ running: boolean; frontendUrl: string | null; error: string | null }>;
  getConfig(): Promise<{ backendPort: number; frontendPort: number; home: string }>;
  onError(cb: (msg: string) => void): () => void;
}

declare global {
  interface Window {
    deeptutorApp: DeeptutorAppAPI;
  }
}
