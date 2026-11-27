import { afterEach, it, expect, vi } from "vitest";
import { setPendingLLMSelection, consumePendingLLMSelection } from "@/lib/pending-llm-selection";
import { browserStorage } from "@/shared/storage";

vi.mock("@/shared/storage", () => ({
  browserStorage: { readRaw: vi.fn(), writeRaw: vi.fn(), removeRaw: vi.fn() },
}));

afterEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

it("consume returns a one-time clone with the original ids", () => {
  vi.stubGlobal("window", { sessionStorage: {} });
  const original = { profile_id: "prof-rt", model_id: "model-rt" };
  setPendingLLMSelection("rt-scope", original);
  original.profile_id = "mutated";
  original.model_id = "mutated";
  const consumed = consumePendingLLMSelection("rt-scope");
  expect(consumed).toEqual({ profile_id: "prof-rt", model_id: "model-rt" });
  expect(browserStorage.writeRaw).toHaveBeenCalledWith("session", "deeptutor.pendingLLMSelection.rt-scope", expect.any(String));
  expect(consumePendingLLMSelection("rt-scope")).toBeNull();
});

it("topic scopes are isolated from each other", () => {
  vi.stubGlobal("window", { sessionStorage: {} });
  setPendingLLMSelection("topic-111", { profile_id: "prof-111", model_id: "model-111" });
  setPendingLLMSelection("topic-222", { profile_id: "prof-222", model_id: "model-222" });
  expect(consumePendingLLMSelection("topic-111")).toEqual({ profile_id: "prof-111", model_id: "model-111" });
  expect(consumePendingLLMSelection("topic-222")).toEqual({ profile_id: "prof-222", model_id: "model-222" });
});

it("null clears only the exact scope", () => {
  vi.stubGlobal("window", { sessionStorage: {} });
  setPendingLLMSelection("keeper", { profile_id: "prof-keep", model_id: "model-keep" });
  setPendingLLMSelection("dropped", { profile_id: "prof-drop", model_id: "model-drop" });
  setPendingLLMSelection("dropped", null);
  expect(consumePendingLLMSelection("dropped")).toBeNull();
  expect(consumePendingLLMSelection("keeper")).toEqual({ profile_id: "prof-keep", model_id: "model-keep" });
});

it('prefers the per-tab map over persisted data when writes fail and tombstones consumed entries', () => {
  const scope = 'b-failed-persist';
  const key = `deeptutor.pendingLLMSelection.${scope}`;
  const stale = { profile_id: 'profile-stale', model_id: 'model-stale' };
  const fresh = { profile_id: 'profile-fresh', model_id: 'model-fresh' };
  vi.spyOn(browserStorage, 'readRaw').mockReturnValue(JSON.stringify(stale));
  const write = vi.spyOn(browserStorage, 'writeRaw').mockImplementation(() => {
    throw new Error('write failed');
  });
  const remove = vi.spyOn(browserStorage, 'removeRaw').mockImplementation(() => {
    throw new Error('remove failed');
  });
  setPendingLLMSelection(scope, fresh);
  const [storageArea, writtenKey, writtenValue] = write.mock.calls[0];
  expect(storageArea).toBe('session');
  expect(writtenKey).toBe(key);
  expect(JSON.parse(writtenValue)).toEqual(fresh);
  const consumed = consumePendingLLMSelection(scope);
  expect(consumed).toEqual(fresh);
  expect(consumed).not.toBe(fresh);
  expect(remove).toHaveBeenCalledWith('session', key);
  expect(consumePendingLLMSelection(scope)).toBeNull();
});

it('returns null for malformed JSON and invalid ids in persisted data', () => {
  vi.spyOn(browserStorage, 'readRaw')
    .mockReturnValueOnce('{oops')
    .mockReturnValueOnce(JSON.stringify({ profile_id: '', model_id: 'model-x' }))
    .mockReturnValueOnce(JSON.stringify({ profile_id: 'profile-x', model_id: 42 }));
  expect(consumePendingLLMSelection('b-malformed')).toBeNull();
  expect(consumePendingLLMSelection('b-empty-id')).toBeNull();
  expect(consumePendingLLMSelection('b-nonstring-id')).toBeNull();
});

it('returns null for empty scope and SSR without touching browserStorage methods', () => {
  const read = vi.spyOn(browserStorage, 'readRaw');
  const write = vi.spyOn(browserStorage, 'writeRaw');
  const remove = vi.spyOn(browserStorage, 'removeRaw');
  expect(consumePendingLLMSelection('')).toBeNull();
  expect(consumePendingLLMSelection('   ')).toBeNull();
  vi.stubGlobal('window', undefined);
  setPendingLLMSelection('b-ssr', { profile_id: 'profile-x', model_id: 'model-x' });
  expect(consumePendingLLMSelection('b-ssr')).toBeNull();
  expect(read).not.toHaveBeenCalled();
  expect(write).not.toHaveBeenCalled();
  expect(remove).not.toHaveBeenCalled();
});
