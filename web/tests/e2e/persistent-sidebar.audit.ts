import { expect, test } from "@playwright/test";
import { sourceModuleInventory } from "./fixtures/modules";

for (const width of [1440, 390]) {
  test(`Chat → Space → Chat preserves the sidebar at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.route("**/api/**", route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/modules") return route.fulfill({ json: sourceModuleInventory });
      if (path === "/api/auth/status") return route.fulfill({ json: { enabled: false, authenticated: true } });
      if (path === "/api/sessions") return route.fulfill({ json: { sessions: [] } });
      if (path === "/api/settings/ui") return route.fulfill({ json: { ui: { language: "en" } } });
      return route.fulfill({ status: 404, json: {} });
    });
    await page.goto("/chat");
    const sidebar = page.locator("aside.dt-product-sidebar");
    const toggle = page.getByRole("button", { name: "Open navigation" });
    const mobile = width < 768;
    if (mobile) await toggle.click();
    await sidebar.locator("#category-resources").click();
    const original = await sidebar.elementHandle();
    await sidebar.locator('a[href="/space"]').click();
    await expect(page).toHaveURL(url => url.pathname === "/space");
    if (mobile) {
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
      await toggle.click();
    }
    await expect(sidebar.locator("#category-resources")).toBeVisible();
    expect(await sidebar.evaluate((current, first) => current === first, original)).toBe(true);
    await testInfo.attach("resources-sidebar", { body: await page.screenshot(), contentType: "image/png" });
    await sidebar.locator("a.dt-new-conversation").click();
    await expect(page).toHaveURL(url => url.pathname === "/chat");
    await expect(sidebar).toHaveCount(1);
    expect(await sidebar.evaluate((current, first) => current === first, original)).toBe(true);
    if (mobile) await expect(toggle).toHaveAttribute("aria-expanded", "false");
  });
}

for (const width of [1440, 390]) {
  for (const operation of ["delete", "move"] as const) {
    test(`Resources ${operation} keeps the page and evicts the old transcript at ${width}px`, async ({ page }, testInfo) => {
      const sessionId = "sidebar-mutation";
      const pageErrors: string[] = [];
      page.on("pageerror", error => pageErrors.push(error.message));
      const transcript = "Persisted transcript for navigation regression";
      let removed = false;
      const conversation = {
        id: sessionId, session_id: sessionId, title: "Navigation regression",
        created_at: 1, updated_at: 2, status: "completed",
        content_workspace_id: "", preferences: { capability: "chat", language: "en" },
        active_turns: [], message_count: 1, last_message: transcript,
        messages: [{
          id: 1, session_id: sessionId, role: "user", content: transcript,
          capability: "chat", events: [], attachments: [], metadata: {},
          created_at: 1, parent_message_id: null,
        }],
      };
      await page.setViewportSize({ width, height: 900 });
      await page.addInitScript(() => {
        localStorage.setItem("deeptutor.ui-layout", "modern");
        localStorage.setItem("deeptutor-language", "en");
      });
      await page.route("**/api/**", route => {
        const path = new URL(route.request().url()).pathname;
        const method = route.request().method();
        const json = (payload: unknown) => route.fulfill({ json: payload });
        if (path === "/api/modules") return json(sourceModuleInventory);
        if (path === "/api/auth/status") return json({ enabled: false, authenticated: true });
        if (path === `/api/sessions/${sessionId}`) {
          if (method === "DELETE") { removed = true; return json({ deleted: true }); }
          return removed ? route.fulfill({ status: 404, json: { detail: "Session not found" } }) : json(conversation);
        }
        if (path === `/api/sessions/${sessionId}/organization` && method === "PATCH") {
          removed = true;
          return json({ session: { ...conversation, preferences: { ...conversation.preferences, workspace_id: "other" } } });
        }
        if (path === "/api/sessions") return json({ sessions: removed ? [] : [conversation] });
        if (path === "/api/settings/workspace/registrations") return json({ workspaces: [{
          workspace_id: "other", display_name: "Other workspace", kind: "workspace",
          follows_root: false, path: "/other", archived: false,
          created_at: "2026-01-01", status: "ready", error: "",
        }] });
        if (path === "/api/settings" || path === "/api/settings/ui") return json({
          ui: { language: "en", response_language: "en" },
          providers: { llm: [] }, catalog: { version: 1, connections: [], services: {} },
        });
        if (path === "/api/settings/llm-options") return json({ options: [], active: null });
        if (path === "/api/capabilities/registered") return json({ capabilities: ["chat"] });
        if (path.includes("partners") || path.includes("personas")) return json([]);
        if (path.includes("tools")) return json({ tools: [] });
        return route.fulfill({ status: 404, json: {} });
      });
      await page.goto(`/chat/${sessionId}?dt_workspace=`);
      await expect(page.locator("main").getByText(transcript, { exact: true })).toBeVisible();
      const sidebar = page.locator("aside.dt-product-sidebar");
      const toggle = page.getByRole("button", { name: "Open navigation" });
      if (width < 768) await toggle.click();
      await sidebar.locator("#category-resources").click();
      const original = await sidebar.elementHandle();
      await sidebar.locator('a[href="/space"]').click();
      await expect(page).toHaveURL(url => url.pathname === "/space");
      if (width < 768) await toggle.click();
      await sidebar.locator("#category-home").click();
      await sidebar.getByRole("button", { name: "Conversation actions", exact: true }).click();
      page.once("dialog", dialog => dialog.accept());
      await page.getByRole("menuitem", { name: operation === "delete" ? "Delete chat" : "Other workspace", exact: true }).click();
      await expect(sidebar.getByText("Navigation regression", { exact: true })).toHaveCount(0);
      await expect(page).toHaveURL(url => url.pathname === "/space" && url.searchParams.get("dt_workspace") === "");
      expect(await sidebar.evaluate((current, first) => current === first, original)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath(`${operation}-resources-${width}.png`) });
      const reload = page.waitForResponse(response =>
        new URL(response.url()).pathname === `/api/sessions/${sessionId}` && response.status() === 404);
      await page.goBack();
      await reload;
      await expect(page).toHaveURL(url => url.pathname === `/chat/${sessionId}`);
      await expect(page.locator("main").getByText(transcript, { exact: true })).toHaveCount(0);
      expect(pageErrors).toEqual([]);
    });
  }
}
