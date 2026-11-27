import { beforeEach, expect, it, vi } from "vitest";
import { fetchAuthStatus, invalidateAuthStatusCache } from "@/lib/auth";
import { RECOVERY_PRINCIPAL_CHANGED, recoveryPrincipal, updateRecoveryPrincipal } from "@/lib/recovery-principal";
import { clearFailedSubmission, moveFailedSubmissions, readFailedSubmissions, storeFailedSubmission } from "@/lib/failed-submissions";

const fixture = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/api", () => ({ apiFetch: fixture.fetch, apiUrl: (path: string) => path, setRuntimeAuthEnabled: vi.fn() }));

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  fixture.fetch.mockReset();
  invalidateAuthStatusCache();
});

async function principal(user: string | null, enabled = true) {
  invalidateAuthStatusCache();
  fixture.fetch.mockResolvedValue({ ok: true, json: async () => ({ enabled,
    authenticated: user !== null, user_id: user ?? undefined }) });
  await fetchAuthStatus();
}

function save(id = "same-id", content = "Private draft") {
  return storeFailedSubmission("draft:general", { submissionId: id, content,
    requestSnapshot: { content, capability: "chat", attachments: [{ name: "private.pdf" }] } });
}

it("fails closed before the server establishes a principal", () => {
  expect(save()).toBeNull();
  expect(readFailedSubmissions("draft:general")).toEqual([]);
  expect(clearFailedSubmission("draft:general", "same-id")).toBe(false);
});

it("keeps each account's draft, attachment context and tombstones separate", async () => {
  await principal("account-a");
  expect(save()).toBe("same-id");
  await principal("account-b");
  expect(readFailedSubmissions("draft:general")).toEqual([]);
  save("same-id", "Other account draft");
  clearFailedSubmission("draft:general", "same-id");
  await principal("account-a");
  expect(readFailedSubmissions("draft:general")[0].content).toBe("Private draft");
  expect(readFailedSubmissions("draft:general")[0].requestSnapshot).toMatchObject({ attachments: [{ name: "private.pdf" }] });
});

it("separates authenticated, logged-out, unavailable and single-user modes", async () => {
  await principal("account-a");
  save();
  await principal(null);
  expect(readFailedSubmissions("draft:general")).toEqual([]);
  expect(save()).toBeNull();
  await principal(null, false);
  expect(readFailedSubmissions("draft:general")).toEqual([]);
  save("single", "Single-user draft");
  invalidateAuthStatusCache();
  fixture.fetch.mockRejectedValue(new Error("offline"));
  await fetchAuthStatus();
  expect(readFailedSubmissions("draft:general")).toEqual([]);
  await principal("account-a");
  expect(readFailedSubmissions("draft:general").map((r) => r.content)).toEqual(["Private draft"]);
});

it("preserves unowned legacy records without assigning them to any current account", async () => {
  const key = "deeptutor.failedSubmissions.record.draft%3Ageneral:legacy-id";
  const raw = JSON.stringify({ submissionId: "legacy-id", content: "Unowned private draft", savedAt: Date.now(),
    requestSnapshot: { content: "Unowned private draft" } });
  localStorage.setItem(key, raw);
  const legacyMap = JSON.stringify({ "draft:general": [JSON.parse(raw)] });
  localStorage.setItem("deeptutor.failedSubmissions", legacyMap);
  sessionStorage.setItem("deeptutor.failedSubmissions.fallback.draft%3Ageneral", raw);
  for (const user of ["account-a", null]) {
    await principal(user, user !== null);
    expect(readFailedSubmissions("draft:general")).toEqual([]);
    expect(localStorage.getItem(key)).toBe(raw);
    expect(localStorage.getItem("deeptutor.failedSubmissions")).toBe(legacyMap);
    expect(sessionStorage.getItem("deeptutor.failedSubmissions.fallback.draft%3Ageneral")).toBe(raw);
  }
});

it("does not expose another account through draft-to-session bindings", async () => {
  await principal("account-a");
  save();
  const original = Storage.prototype.setItem;
  const quota = vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (this: Storage, key, value) {
    if (key.includes(".record.same-session:")) throw new DOMException("Quota", "QuotaExceededError");
    return original.call(this, key, value);
  });
  expect(moveFailedSubmissions("draft:general", "same-session", ["same-id"])).toEqual(["same-id"]);
  quota.mockRestore();
  await principal("account-b");
  expect(readFailedSubmissions("same-session")).toEqual([]);
  clearFailedSubmission("same-session", "same-id");
  await principal("account-a");
  expect(readFailedSubmissions("same-session")[0].content).toBe("Private draft");
});

it("ignores an old auth response arriving after an account boundary", async () => {
  await principal("account-a");
  save();
  invalidateAuthStatusCache();
  let resolveOld!: (value: unknown) => void;
  fixture.fetch.mockReturnValueOnce(new Promise((resolve) => { resolveOld = resolve; }));
  const oldRequest = fetchAuthStatus();
  await principal("account-b");
  save("other", "Account B draft");
  resolveOld({ ok: true, json: async () => ({ enabled: true, authenticated: true, user_id: "account-a" }) });
  await oldRequest;
  expect(readFailedSubmissions("draft:general").map((r) => r.content)).toEqual(["Account B draft"]);
});

it("invalidates synchronously across tabs and resolves identity from the server, not the signal", async () => {
  await principal("account-a");
  save();
  fixture.fetch.mockResolvedValue({ ok: true, json: async () => ({ enabled: true,
    authenticated: true, user_id: "account-b" }) });
  window.dispatchEvent(new StorageEvent("storage", {
    key: "deeptutor.authBoundary", newValue: "user:account-a",
  }));
  expect(recoveryPrincipal()).toBeNull();
  expect(readFailedSubmissions("draft:general")).toEqual([]);
  await fetchAuthStatus();
  expect(recoveryPrincipal()).toBe("user:account-b");
  expect(readFailedSubmissions("draft:general")).toEqual([]);
});

it("emits one boundary event only when the effective principal changes", () => {
  const listener = vi.fn();
  window.addEventListener(RECOVERY_PRINCIPAL_CHANGED, listener);
  updateRecoveryPrincipal({ enabled: true, authenticated: true, user_id: "account-a" });
  updateRecoveryPrincipal({ enabled: true, authenticated: true, user_id: "account-a" });
  expect(listener).toHaveBeenCalledTimes(1);
  updateRecoveryPrincipal({ enabled: true, authenticated: true });
  expect(recoveryPrincipal()).toBeNull();
  expect(listener).toHaveBeenCalledTimes(2);
  window.removeEventListener(RECOVERY_PRINCIPAL_CHANGED, listener);
});

it("isolates two tab runtimes sharing local storage with different resolved principals", async () => {
  await principal("account-a");
  save();
  vi.resetModules();
  const otherPrincipal = await import("@/lib/recovery-principal");
  const otherRecovery = await import("@/lib/failed-submissions");
  otherPrincipal.updateRecoveryPrincipal({ enabled: true, authenticated: true, user_id: "account-b" });
  expect(otherRecovery.readFailedSubmissions("draft:general")).toEqual([]);
  otherRecovery.storeFailedSubmission("draft:general", { submissionId: "same-id", content: "B only",
    requestSnapshot: { content: "B only" } });
  otherRecovery.clearFailedSubmission("draft:general", "same-id");
  expect(readFailedSubmissions("draft:general")[0].content).toBe("Private draft");
});
