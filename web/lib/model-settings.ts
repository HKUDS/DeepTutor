import { modelProvider } from "./provider-registry";
import { randomUuid } from "./random-uuid";
import type {
  Catalog,
  CatalogModel,
  CatalogProfile,
  ServiceName,
} from "./model-catalog-types";

export const MODEL_SERVICES: ServiceName[] = [
  "llm",
  "task",
  "embedding",
  "tts",
  "stt",
  "imagegen",
  "videogen",
];
export const MODEL_SERVICE_LABELS: Record<ServiceName, string> = {
  llm: "Chat model",
  task: "Task model",
  embedding: "Embedding",
  search: "Search",
  tts: "Text-to-Speech",
  stt: "Speech-to-Text",
  imagegen: "Image Generation",
  videogen: "Video Generation",
};

export type ProviderGroup = {
  id: string;
  name: string;
  provider: string;
  connectionId?: string;
  profiles: { service: ServiceName; profile: CatalogProfile }[];
};

/** A view over existing IDs. Only an explicit connection can group profiles:
 * two accounts with the same vendor or URL must never be merged by inference. */
export function providerGroups(catalog: Catalog): ProviderGroup[] {
  const groups = new Map<string, ProviderGroup>();
  for (const connection of catalog.connections ?? []) {
    groups.set(`connection:${connection.id}`, {
      id: `connection:${connection.id}`,
      connectionId: connection.id,
      name: connection.name,
      provider: connection.provider,
      profiles: [],
    });
  }
  for (const service of MODEL_SERVICES) {
    for (const profile of catalog.services[service].profiles) {
      const linked =
        profile.connection_id &&
        groups.get(`connection:${profile.connection_id}`);
      if (linked) linked.profiles.push({ service, profile });
      else
        groups.set(`${service}:${profile.id}`, {
          id: `${service}:${profile.id}`,
          name: profile.name,
          provider: profile.binding ?? "",
          profiles: [{ service, profile }],
        });
    }
  }
  return [...groups.values()];
}

export function modelTestKey(
  service: ServiceName,
  profileId: string,
  modelId?: string | null,
): string {
  return JSON.stringify([service, profileId, modelId ?? null]);
}

/** Kept in memory only: includes credentials so editing a key invalidates a
 * previous test. Never persist this signature or expose it in the DOM. */
export function modelTestFingerprint(
  catalog: Catalog,
  service: ServiceName,
  profileId: string,
  modelId?: string | null,
): string {
  const profile = catalog.services[service].profiles.find(
    (item) => item.id === profileId,
  );
  const model = profile?.models.find((item) => item.id === modelId);
  const { models: _models, name: _name, ...connection } = profile ?? {};
  const {
    name: _modelName,
    context_window: _window,
    context_window_tokens: _legacyWindow,
    context_window_source: _source,
    context_window_detected_at: _date,
    dimension: _dimension,
    supported_dimensions: _dimensions,
    ...requestModel
  } = model ?? {};
  const providerSource = profile
    ? modelProvider(catalog, service, profile, model)?.source
    : undefined;
  const credentials = providerSource
    ? Object.fromEntries(
        [
          "provider",
          "binding",
          "api_key",
          "base_url",
          "api_version",
          "app_id",
          "extra_headers",
          "api_format",
          "wire_api",
          "proxy",
        ].map((key) => [key, Reflect.get(providerSource, key)]),
      )
    : undefined;
  return JSON.stringify([
    connection,
    requestModel,
    credentials,
    catalog.connections?.find((item) => item.id === profile?.connection_id),
  ]);
}

export type ModelTestState = {
  state: "running" | "success" | "failed";
  fingerprint: string;
  message: string;
  logs: string;
  response?: string;
  context?: {
    value: number;
    source: string;
    detail?: string;
    detectedAt?: string;
  };
  dimension?: number;
  supportedDimensions?: number[];
};

/** Preserve IDs, names, per-model overrides, and the current default. */
export function addDiscoveredModels(
  profile: CatalogProfile,
  ids: string[],
): string[] {
  return ids.map((value) => {
    const existing = profile.models.find((model) => model.model === value);
    if (existing) return existing.id;
    const blank = profile.models.find((model) => !model.model.trim());
    if (blank) {
      blank.model = value;
      blank.name = value;
      return blank.id;
    }
    const model: CatalogModel = {
      id: `model-${randomUuid()}`,
      name: value,
      model: value,
    };
    profile.models.push(model);
    return model.id;
  });
}

/** Apply the server's normalized/masked response only where the user has not
 * edited further while saving. Unrelated drafts and new selections survive. */
export function reconcileProviderSave(
  current: Catalog,
  submitted: Catalog,
  live: Catalog,
  service: ServiceName,
  profileId: string,
): Catalog {
  const next = structuredClone(current);
  const profile = submitted.services[service].profiles.find(
    (item) => item.id === profileId,
  );
  const saved = live.services[service].profiles.find(
    (item) => item.id === profileId,
  );
  const index = next.services[service].profiles.findIndex(
    (item) => item.id === profileId,
  );
  if (
    saved &&
    index >= 0 &&
    JSON.stringify(next.services[service].profiles[index]) ===
      JSON.stringify(profile)
  )
    next.services[service].profiles[index] = structuredClone(saved);
  const connection = submitted.connections?.find(
    (item) => item.id === profile?.connection_id,
  );
  const savedConnection = live.connections?.find(
    (item) => item.id === connection?.id,
  );
  const connectionIndex =
    next.connections?.findIndex((item) => item.id === connection?.id) ?? -1;
  if (
    savedConnection &&
    connectionIndex >= 0 &&
    JSON.stringify(next.connections![connectionIndex]) ===
      JSON.stringify(connection)
  )
    next.connections![connectionIndex] = structuredClone(savedConnection);
  return next;
}

/** Detaching retains the credentials currently visible in the editor, including
 * unsaved connection edits that have not yet been mirrored into the profile. */
export function detachProfileConnection(
  catalog: Catalog,
  service: ServiceName,
  profile: CatalogProfile,
): void {
  const connection = catalog.connections?.find(
    (item) => item.id === profile.connection_id,
  );
  if (connection) {
    profile.api_key = connection.api_key;
    profile.api_version = connection.api_version ?? "";
    profile.extra_headers = structuredClone(connection.extra_headers ?? {});
    const base = connection.base_url.trim().replace(/\/+$/, "");
    const nativeEmbedding =
      service === "embedding" &&
      /:batchEmbedContents?$|:embedContent$/.test(profile.base_url);
    if (base && !nativeEmbedding)
      profile.base_url = base + (service === "embedding" ? "/embeddings" : "");
  }
  delete profile.connection_id;
}
