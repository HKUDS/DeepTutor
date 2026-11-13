import { expect, test, type Page } from "@playwright/test";
import { sourceModuleInventory } from "./fixtures/modules";

async function parserSettings(page: Page) {
  let available = false;
  let fail = false;
  let reads = 0;
  const writes: string[] = [];
  const engines = ["text_only", "docling", "markitdown", "pymupdf4llm", "liteparse"];
  const catalog = { version: 1, connections: [], services: Object.fromEntries(
    ["llm", "task", "embedding", "search", "tts", "stt", "imagegen", "videogen"].map(
      key => [key, { active_profile_id: null, active_model_id: null, profiles: [] }],
    ),
  ) };
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    if (method !== "GET") writes.push(path);
    let json: unknown = {};
    if (path === "/api/auth/status") json = { enabled: false, authenticated: true, is_admin: true };
    else if (path === "/api/modules") json = sourceModuleInventory;
    else if (path === "/api/settings" || path === "/api/settings/ui") json = {
      catalog, ui: { theme: "light", language: "en", response_language: "en" }, providers: {}, connection_targets: [],
    };
    else if (path === "/api/settings/draft") json = { draft: null };
    else if (path === "/api/settings/document-parsing") {
      reads++;
      if (fail) return route.fulfill({ status: 503, json: { detail: "Parser availability is temporarily unavailable. Try again." } });
      json = {
        engine: "docling", engines: { docling: { mode: "local" } },
        available_engines: engines.map(id => ({ id, name: id === "text_only" ? "Text-only" : id, description: "", needs_local_models: false, available: id === "text_only" || available })),
        readiness: {}, installable: engines.slice(1), mineru: { api_token_set: false }, docling: { api_token_set: false },
      };
    } else if (path.includes("llm/options")) json = { options: [] };
    else if (path === "/api/settings/readiness") json = { schema_version: "deeptutor.settings-readiness/v2", ok: true, summary: {}, rows: [], notices: [] };
    else if (path === "/api/system/status") json = { backend: { status: "online" } };
    return route.fulfill({ json });
  });
  return { writes, reads: () => reads, installed: () => { available = true; }, fail: (value: boolean) => { fail = value; } };
}

for (const viewport of [{ width: 1280, height: 900 }, { width: 390, height: 844 }]) {
  test(`parser guidance and recheck at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const state = await parserSettings(page);
    await page.goto("/settings/document-parsing");
    for (const engine of ["docling", "markitdown", "pymupdf4llm", "liteparse"]) {
      await page.getByRole("button", { name: new RegExp(`^${engine} `) }).click();
      await expect(page.getByRole("heading", { name: "Docker", exact: true })).toBeVisible();
      await expect(page.getByText(`parse-${engine}`, { exact: true })).toBeVisible();
      await expect(page.getByText(`python scripts/install_extras.py parse-${engine}`, { exact: true })).toBeVisible();
      await expect(page.getByText(`deeptutor module install parser-${engine}`, { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Download & install", exact: true })).toHaveCount(0);
    }
    const recheck = page.getByRole("button", { name: "Recheck availability", exact: true });
    await recheck.scrollIntoViewIfNeeded();
    await page.screenshot({ path: test.info().outputPath(`parser-guidance-${viewport.width}.png`), fullPage: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await recheck.click();
    await expect(page.getByRole("status").filter({ hasText: "still unavailable" })).toBeVisible();
    state.fail(true);
    await recheck.click();
    await expect(page.getByRole("alert").filter({ hasText: "Parser availability is temporarily unavailable" })).toBeVisible();
    await expect(recheck).toBeEnabled();
    state.fail(false);
    state.installed();
    await recheck.focus();
    await page.keyboard.press("Enter");
    await expect(recheck).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Docker", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^liteparse Active/ })).toBeVisible();
    expect(state.reads()).toBeGreaterThanOrEqual(4);
    expect(state.writes.filter(path => path !== "/api/settings/draft")).toEqual([]);
  });
}
