import type {
  ProviderRef,
  Catalog,
  CatalogConnection,
  CatalogModel,
  CatalogProfile,
  CatalogService,
  ConnectionTarget,
  ProviderOption,
  ServiceName,
  TaskChoiceMode,
} from "./model-catalog-types";
export type { ProviderRef, Discovery } from "./model-catalog-types";

export type ProviderSource = {
  id: string;
  ref: ProviderRef;
  name: string;
  provider: string;
  source: CatalogConnection | CatalogProfile;
  service?: ServiceName;
};
export type RegistryEdit = {
  kind: "provider" | "model" | "default" | "task_choice";
  task?: {
    /**
     * Which choice this edit is. Absent means the global task model; otherwise
     * a `TaskKind` from the settings payload, and `"global"` clears that task's
     * own model so it follows the global one again.
     */
    task_kind?: string;
    mode?: TaskChoiceMode | "global";
    selection?: CatalogService["selection"];
    active_profile_id?: string | null;
    active_model_id?: string | null;
  };
  ref?: ProviderRef;
  fields?: Record<string, unknown>;
  service?: ServiceName;
  profile_id?: string;
  model_id?: string;
  model?: CatalogModel;
  config?: Partial<CatalogProfile>;
  delete?: boolean;
};
export const REGISTRY_SERVICES: ServiceName[] = [
  "llm",
  "task",
  "embedding",
  "search",
  "tts",
  "stt",
  "imagegen",
  "videogen",
];
export const SERVICE_TITLES: Record<ServiceName, string> = {
  llm: "Language models",
  task: "Task model",
  embedding: "Embedding models",
  search: "Search",
  tts: "Text-to-Speech",
  stt: "Speech-to-Text",
  imagegen: "Image Generation",
  videogen: "Video Generation",
};
export function providerIdentity(ref: ProviderRef): string {
  return ref.connection_id
    ? `connection:${ref.connection_id}`
    : `${ref.service}:${ref.profile_id}`;
}
export function providerRegistry(catalog: Catalog): ProviderSource[] {
  const result: ProviderSource[] = (catalog.connections ?? []).map(
    (source) => ({
      id: `connection:${source.id}`,
      ref: { connection_id: source.id },
      name: source.name,
      provider: source.provider,
      source,
    }),
  );
  for (const service of REGISTRY_SERVICES)
    for (const source of catalog.services[service].profiles) {
      if (
        source.provider_ref ||
        (source.connection_id &&
          result.some((p) => p.ref.connection_id === source.connection_id))
      )
        continue;
      result.push({
        id: `${service}:${source.id}`,
        ref: { service, profile_id: source.id },
        name: source.name,
        provider: source.binding || source.provider || "custom",
        source,
        service,
      });
    }
  return result;
}
export function modelProviderRef(
  service: ServiceName,
  profile: CatalogProfile,
  model?: CatalogModel | null,
): ProviderRef {
  return (
    model?.provider_ref ||
    profile.provider_ref ||
    (profile.connection_id
      ? { connection_id: profile.connection_id }
      : { service, profile_id: profile.id })
  );
}
export function modelProvider(
  catalog: Catalog,
  service: ServiceName,
  profile: CatalogProfile,
  model?: CatalogModel | null,
): ProviderSource | undefined {
  const id = providerIdentity(modelProviderRef(service, profile, model));
  return providerRegistry(catalog).find((p) => p.id === id);
}
export type RegistryModelRow = {
  key: string;
  service: ServiceName;
  profile: CatalogProfile;
  model: CatalogModel | null;
};
export function flattenModels(
  catalog: Catalog,
  services: ServiceName[],
): RegistryModelRow[] {
  const result: RegistryModelRow[] = [];
  for (const service of services)
    for (const profile of catalog.services[service].profiles) {
      if (profile.provider_only) continue;
      if (service === "search")
        result.push({
          key: `${service}:${profile.id}`,
          service,
          profile,
          model: null,
        });
      else
        for (const model of profile.models)
          result.push({
            key: `${service}:${profile.id}:${model.id}`,
            service,
            profile,
            model,
          });
    }
  return result;
}
export function providerUsage(
  catalog: Catalog,
  source: ProviderSource,
): number {
  return flattenModels(catalog, REGISTRY_SERVICES).filter(
    (item) =>
      providerIdentity(
        modelProviderRef(item.service, item.profile, item.model),
      ) === source.id,
  ).length;
}
export function providerAdapter(
  source: ProviderSource,
  service: ServiceName,
  targets: ConnectionTarget[],
  providers: Record<ServiceName, ProviderOption[]>,
) {
  const target = targets.find((t) => t.provider === source.provider)?.services[
    service === "task" ? "llm" : service
  ];
  const exact = providers[service]?.find((p) => p.value === source.provider);
  const binding =
    target?.provider ||
    exact?.value ||
    (service === "llm" || service === "task" || source.service === service
      ? source.provider
      : "custom");
  return {
    ...source.ref,
    binding,
    default_base_url: target?.base_url || exact?.base_url || "",
  };
}
export function providerProbeInput(source: ProviderSource, fallbackUrl = "") {
  const s = source.source;
  return {
    ...source.ref,
    binding: source.provider,
    base_url: s.base_url || fallbackUrl,
    api_key: s.api_key,
    api_version: s.api_version,
    api_format: s.api_format || "auto",
    extra_headers: s.extra_headers,
    service: source.service || (s as CatalogConnection).source_service || "llm",
  };
}
export function updateProvider(
  catalog: Catalog,
  ref: ProviderRef,
  field: string,
  value: unknown,
): void {
  const source = providerRegistry(catalog).find(
    (p) => p.id === providerIdentity(ref),
  )?.source;
  if (!source) return;
  Object.assign(source, { [field]: value });
  if (!["name", "discovery"].includes(field)) delete source.discovery;
}

/** Three-way, entity-scoped reconciliation: edits made while a save was in
 * flight and unrelated model/provider drafts are not replaced by its response. */
export function reconcileRegistrySave(
  current: Catalog,
  submitted: Catalog,
  live: Catalog,
  edit: RegistryEdit,
): Catalog {
  const next = structuredClone(current);
  const same = (a: unknown, b: unknown) =>
    JSON.stringify(a) === JSON.stringify(b);
  if (edit.kind === "task_choice") {
    // `overrides` rides along: a per-task pin is not visible in any of the four
    // pointer fields, so without it the row would snap back to whatever the
    // draft still held until the next full settings load.
    for (const field of [
      "mode",
      "selection",
      "active_profile_id",
      "active_model_id",
      "overrides",
    ] as const) {
      if (!same(next.services.task[field], submitted.services.task[field]))
        continue;
      const applied = live.services.task[field];
      // The whole key disappears when the last pin is cleared; copying the
      // `undefined` instead would leave a key that no longer exists upstream.
      if (applied === undefined) Reflect.deleteProperty(next.services.task, field);
      else Reflect.set(next.services.task, field, structuredClone(applied));
    }
  } else if (edit.kind === "provider" && edit.ref) {
    const id = providerIdentity(edit.ref);
    const before = providerRegistry(submitted).find((p) => p.id === id)?.source;
    const now = providerRegistry(next).find((p) => p.id === id)?.source;
    const saved = providerRegistry(live).find((p) => p.id === id)?.source;
    if (now && before && saved) {
      for (const key of Object.keys(edit.fields ?? {}))
        if (same(Reflect.get(now, key), Reflect.get(before, key)))
          Reflect.set(now, key, structuredClone(Reflect.get(saved, key)));
    } else if (now && !saved && edit.delete) {
      if (edit.ref.connection_id)
        next.connections = next.connections?.filter(
          (c) => c.id !== edit.ref!.connection_id,
        );
      else if (edit.ref.service)
        next.services[edit.ref.service].profiles = next.services[
          edit.ref.service
        ].profiles.filter((p) => p.id !== edit.ref!.profile_id);
    }
  } else if (edit.service) {
    const service = edit.service;
    const bucket = next.services[service];
    const before = submitted.services[service].profiles.find(
      (p) => p.id === edit.profile_id,
    );
    const now = bucket.profiles.find((p) => p.id === edit.profile_id);
    const saved = live.services[service].profiles.find(
      (p) => p.id === edit.profile_id,
    );
    if (now && before && edit.kind === "model") {
      if (service === "search") {
        if (same(now, before)) {
          if (saved) Object.assign(now, structuredClone(saved));
          else bucket.profiles = bucket.profiles.filter((p) => p.id !== now.id);
        }
      } else {
        const id = edit.model_id || edit.model?.id;
        const previousModel = before.models.find((m) => m.id === id);
        const currentModel = now.models.find((m) => m.id === id);
        const savedModel = saved?.models.find((m) => m.id === id);
        if (same(currentModel, previousModel)) {
          now.models = now.models.filter((m) => m.id !== id);
          if (savedModel) {
            const index = before.models.findIndex((m) => m.id === id);
            now.models.splice(
              Math.max(index, 0),
              0,
              structuredClone(savedModel),
            );
          }
          if (!saved && now.models.length === 0)
            bucket.profiles = bucket.profiles.filter((p) => p.id !== now.id);
        }
      }
    }
    if (
      same(
        [bucket.active_profile_id, bucket.active_model_id],
        [
          submitted.services[service].active_profile_id,
          submitted.services[service].active_model_id,
        ],
      )
    ) {
      bucket.active_profile_id = live.services[service].active_profile_id;
      bucket.active_model_id = live.services[service].active_model_id;
      if (service === "task") bucket.mode = live.services.task.mode;
    }
  }
  return next;
}

/** Apply list actions to the editable catalog; only the global toolbar persists it. */
export function stageRegistryAction(catalog: Catalog, edit: RegistryEdit): void {
  if (edit.kind === "task_choice" && edit.task) {
    const { task_kind, ...choice } = edit.task;
    const task = catalog.services.task;
    if (task_kind) {
      const overrides = { ...task.overrides };
      if (choice.mode === "global") delete overrides[task_kind];
      else overrides[task_kind] = choice as NonNullable<CatalogService["overrides"]>[string];
      task.overrides = overrides;
      if (!Object.keys(overrides).length) delete task.overrides;
    } else Object.assign(task, choice);
    return;
  }
  if (edit.kind === "provider" && edit.delete && edit.ref) {
    if (edit.ref.connection_id) {
      catalog.connections = catalog.connections?.filter((p) => p.id !== edit.ref!.connection_id);
    } else if (edit.ref.service) {
      const bucket = catalog.services[edit.ref.service];
      bucket.profiles = bucket.profiles.filter((p) => p.id !== edit.ref!.profile_id);
    }
    return;
  }
  if (!edit.service) return;
  const bucket = catalog.services[edit.service];
  const profile = bucket.profiles.find((p) => p.id === edit.profile_id);
  if (!profile) return;
  if (edit.kind === "default") {
    bucket.active_profile_id = profile.id;
    bucket.active_model_id = edit.model_id ?? null;
    if (edit.service === "task") bucket.mode = "profiles";
  } else if (edit.delete) {
    if (edit.service === "search") {
      if (profile.provider_ref) bucket.profiles = bucket.profiles.filter((p) => p !== profile);
      else profile.provider_only = true;
    } else {
      profile.models = profile.models.filter((m) => m.id !== edit.model_id);
      if (!profile.models.length && profile.provider_ref) bucket.profiles = bucket.profiles.filter((p) => p !== profile);
    }
    const candidates = bucket.profiles.filter((p) => !p.provider_only && (edit.service === "search" || p.models.length));
    const active = candidates.find((p) => p.id === bucket.active_profile_id) ?? candidates[0];
    bucket.active_profile_id = active?.id ?? null;
    if (!active?.models.some((m) => m.id === bucket.active_model_id)) bucket.active_model_id = active?.models[0]?.id ?? null;
  }
}
