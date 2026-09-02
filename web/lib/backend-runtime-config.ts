type BackendRuntimeEnvironment = Record<string, string | undefined>;

const DEFAULT_BACKEND_API_BASE = "http://127.0.0.1:8001";

function nonEmpty(value: string | undefined): string | undefined {
  const normalized = value?.trim();
  return normalized ? normalized : undefined;
}

/** Resolve the address used by the Next server to reach FastAPI. */
export function resolveBackendApiBase(
  env: BackendRuntimeEnvironment = process.env,
): string {
  const privateBase = nonEmpty(env.DEEPTUTOR_API_BASE_URL);
  if (privateBase) return privateBase;

  // `next dev` can isolate Proxy in a worker that keeps conventional and
  // Next-managed variables but drops arbitrary process variables. Rebuild the
  // launcher's loopback origin from the port before using its public fallback.
  const backendPort = nonEmpty(env.BACKEND_PORT);
  if (backendPort && /^\d+$/.test(backendPort)) {
    return `http://127.0.0.1:${backendPort}`;
  }

  return nonEmpty(env.NEXT_PUBLIC_API_BASE) ?? DEFAULT_BACKEND_API_BASE;
}
