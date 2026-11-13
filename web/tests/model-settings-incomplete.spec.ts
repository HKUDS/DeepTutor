import { describe, expect, it } from "vitest";
import { firstIncompleteModel, MODEL_SERVICE_PAGES } from "@/lib/model-settings";
import type {
  Catalog,
  CatalogModel,
  CatalogProfile,
  ServiceName,
} from "@/lib/model-catalog-types";

const SERVICES: ServiceName[] = [
  "llm",
  "task",
  "embedding",
  "search",
  "tts",
  "stt",
  "imagegen",
  "videogen",
];

function emptyCatalog(): Catalog {
  const services = Object.fromEntries(
    SERVICES.map((service) => [
      service,
      { active_profile_id: null, active_model_id: null, profiles: [] },
    ]),
  );
  return { version: 1, connections: [], services } as unknown as Catalog;
}

function withModel(
  catalog: Catalog,
  service: ServiceName,
  model: Partial<CatalogModel>,
  profile: Partial<CatalogProfile> = {},
): Catalog {
  catalog.services[service].profiles.push({
    id: `${service}-profile`,
    name: `${service} account`,
    binding: "custom",
    api_key: "",
    base_url: "",
    api_version: "",
    models: [{ id: `${service}-model`, name: "", model: "", ...model }],
    ...profile,
  });
  return catalog;
}

describe("firstIncompleteModel", () => {
  it("returns nothing when every model has an ID", () => {
    const catalog = withModel(emptyCatalog(), "llm", { model: "deepseek-flash" });
    expect(firstIncompleteModel(catalog)).toBeNull();
  });

  it.each([
    ["llm", "/settings/llm", "Language models"],
    ["task", "/settings/llm", "Language models"],
    ["embedding", "/settings/embedding", "Embedding models"],
    ["tts", "/settings/voice", "Voice"],
    ["stt", "/settings/voice", "Voice"],
    ["imagegen", "/settings/multimodal", "Multimodal generation"],
    ["videogen", "/settings/multimodal", "Multimodal generation"],
  ] as const)(
    "points a blank %s model at the page that edits it",
    (service, path, labelKey) => {
      const catalog = withModel(emptyCatalog(), service, { model: "" });
      const result = firstIncompleteModel(catalog);
      expect(result).toMatchObject({
        service,
        profileId: `${service}-profile`,
        modelId: `${service}-model`,
        page: { path, labelKey },
      });
      expect(MODEL_SERVICE_PAGES[service]).toEqual({ path, labelKey });
    },
  );

  it("ignores managed and read-only models the editor cannot repair", () => {
    const catalog = withModel(emptyCatalog(), "llm", {
      model: "",
      managed_by: "codex",
    });
    withModel(catalog, "embedding", { model: "" }, { read_only: true });
    expect(firstIncompleteModel(catalog)).toBeNull();
  });

  it("ignores search, which has no model ID to fill in", () => {
    const catalog = emptyCatalog();
    catalog.services.search.profiles.push({
      id: "search",
      name: "Search",
      provider: "tavily",
      api_key: "k",
      base_url: "",
      api_version: "",
      models: [],
    });
    expect(firstIncompleteModel(catalog)).toBeNull();
  });

  it("reports the first blank model in service order", () => {
    const catalog = withModel(emptyCatalog(), "llm", { model: "ok" });
    withModel(catalog, "embedding", { model: "" });
    withModel(catalog, "tts", { model: "" });
    expect(firstIncompleteModel(catalog)?.service).toBe("embedding");
  });
});
