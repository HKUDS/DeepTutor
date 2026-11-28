import assert from "node:assert/strict";
import test from "node:test";

import {
  canRemoveModelFromCatalog,
  stageSelectedModelRemovals,
} from "../lib/provider-registry";
import type {
  Catalog,
  CatalogModel,
  CatalogProfile,
  CatalogService,
} from "../lib/model-catalog-types";

function makeProfile(id: string, modelId: string): CatalogProfile {
  const model: CatalogModel = { id: modelId, name: modelId, model: modelId };
  return {
    id,
    name: id,
    base_url: "",
    api_key: "",
    api_version: "",
    models: [model],
  };
}

function makeService(profiles: CatalogProfile[] = []): CatalogService {
  return { active_profile_id: null, active_model_id: null, profiles };
}

function makeCatalog(): Catalog {
  return {
    version: 1,
    services: {
      llm: makeService([makeProfile("llm-profile", "llm-model")]),
      task: makeService(),
      embedding: makeService(),
      search: makeService(),
      tts: makeService(),
      stt: makeService(),
      imagegen: makeService(),
      videogen: makeService(),
    },
  };
}

test("bulk removal allows an unassigned non-default language model", () => {
  assert.equal(
    canRemoveModelFromCatalog(
      makeCatalog(),
      "llm",
      "llm-profile",
      "llm-model",
    ),
    true,
  );
});

test("bulk removal protects active, task-assigned, and managed models", () => {
  const active = makeCatalog();
  active.services.llm.active_profile_id = "llm-profile";
  active.services.llm.active_model_id = "llm-model";

  const taskAssigned = makeCatalog();
  taskAssigned.services.task.mode = "reference";
  taskAssigned.services.task.selection = {
    profile_id: "llm-profile",
    model_id: "llm-model",
  };

  const managed = makeCatalog();
  managed.services.llm.profiles[0].read_only = true;

  for (const catalog of [active, taskAssigned, managed]) {
    assert.equal(
      canRemoveModelFromCatalog(
        catalog,
        "llm",
        "llm-profile",
        "llm-model",
      ),
      false,
    );
  }
});

test("bulk removal protects task models assigned by an override", () => {
  const catalog = makeCatalog();
  catalog.services.task.profiles.push(makeProfile("task-profile", "task-model"));
  catalog.services.task.overrides = {
    answer: {
      mode: "profiles",
      active_profile_id: "task-profile",
      active_model_id: "task-model",
    },
  };

  assert.equal(
    canRemoveModelFromCatalog(
      catalog,
      "task",
      "task-profile",
      "task-model",
    ),
    false,
  );
});

test("bulk removal stages every eligible selected model in one catalog mutation", () => {
  const catalog = makeCatalog();
  catalog.services.llm.profiles.push(makeProfile("second-profile", "second-model"));

  const removed = stageSelectedModelRemovals(catalog, [
    {
      service: "llm",
      profile_id: "llm-profile",
      model_id: "llm-model",
    },
    {
      service: "llm",
      profile_id: "second-profile",
      model_id: "second-model",
    },
  ]);

  assert.equal(removed.length, 2);
  assert.equal(
    catalog.services.llm.profiles.flatMap((profile) => profile.models).length,
    0,
  );
});
