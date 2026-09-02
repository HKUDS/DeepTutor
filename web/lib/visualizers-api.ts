import { apiFetch, apiUrl } from "@/lib/api";

const BASE = "/api/visualizers";

export interface VisualizerCatalogItem {
  id: string;
  version: string;
  display_name: string;
  description: string;
  render_target: "native" | "iframe" | "artifact";
  native_renderer: string;
  origin: "core" | "bundled" | "user";
  installed: boolean;
  enabled: boolean;
  uninstallable: boolean;
  agentic: boolean;
}

async function json<T>(response: Response): Promise<T> {
  const payload = (await response.json().catch(() => ({}))) as Record<
    string,
    unknown
  >;
  if (!response.ok) {
    throw new Error(
      String(payload.detail ?? `Request failed (${response.status})`),
    );
  }
  return payload as T;
}

export async function listVisualizers(): Promise<VisualizerCatalogItem[]> {
  const result = await json<{ visualizers: VisualizerCatalogItem[] }>(
    await apiFetch(apiUrl(`${BASE}/list`), { cache: "no-store" }),
  );
  return result.visualizers;
}

export async function installBundledVisualizer(id: string): Promise<void> {
  await json(
    await apiFetch(
      apiUrl(`${BASE}/bundled/${encodeURIComponent(id)}/install`),
      {
        method: "POST",
      },
    ),
  );
}

export async function setVisualizerEnabled(
  id: string,
  enabled: boolean,
): Promise<void> {
  await json(
    await apiFetch(
      apiUrl(
        `${BASE}/${encodeURIComponent(id)}/${enabled ? "enable" : "disable"}`,
      ),
      { method: "POST" },
    ),
  );
}

export async function uninstallVisualizer(id: string): Promise<void> {
  await json(
    await apiFetch(apiUrl(`${BASE}/${encodeURIComponent(id)}`), {
      method: "DELETE",
    }),
  );
}

export async function importVisualizer(file: File): Promise<void> {
  const body = new FormData();
  body.set("file", file);
  await json(
    await apiFetch(apiUrl(`${BASE}/import`), { method: "POST", body }),
  );
}
