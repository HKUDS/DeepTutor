import { expect, test } from "@playwright/test";

const RELEASE_URL =
  "https://github.com/HKUDS/DeepTutor/releases/tag/v1.6.0";
const AVAILABLE_UPDATE = {
  status: "available",
  current_version: "1.5.4",
  latest_version: "1.6.0",
  install_mode: "pypi",
  can_auto_update: true,
  release_url: RELEASE_URL,
  detail: "installed distribution",
};

test("version badge links to the latest release when an update is available", async ({
  page,
}) => {
  let markRequestStarted = () => {};
  const requestStarted = new Promise<void>((resolve) => {
    markRequestStarted = resolve;
  });
  let releaseResponse = () => {};
  const responseGate = new Promise<void>((resolve) => {
    releaseResponse = resolve;
  });
  await page.route("**/api/v1/system/update", async (route) => {
    markRequestStarted();
    await responseGate;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(AVAILABLE_UPDATE),
    });
  });

  await page.goto("/");

  await expect(page.getByTestId("version-badge")).toContainText(
    "Checking for updates…",
  );
  await requestStarted;
  releaseResponse();

  const updateStatus = page.getByTestId("update-status");
  await expect(updateStatus).toBeVisible();
  await expect(updateStatus).toHaveAttribute("href", RELEASE_URL);
  await expect(updateStatus).toHaveAccessibleName(
    /update available.*v1\.6\.0/i,
  );
  const updateAction = page.getByTestId("update-action");
  await expect(updateAction).toBeVisible();
  await expect(updateAction).toHaveAccessibleName(/v1\.6\.0/i);
  expect((await updateAction.boundingBox())?.width).toBeLessThanOrEqual(32);
  expect(
    await updateStatus.evaluate(
      (element) => element.scrollWidth <= element.clientWidth,
    ),
  ).toBe(true);
});

test("version badge reports an up-to-date installation", async ({ page }) => {
  await page.route("**/api/v1/system/update", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...AVAILABLE_UPDATE,
        status: "up_to_date",
        latest_version: "1.5.4",
        release_url: "https://github.com/HKUDS/DeepTutor/releases/tag/v1.5.4",
      }),
    }),
  );

  await page.goto("/");

  const badge = page.getByTestId("version-badge");
  await expect(badge).toContainText("Up to date");
  await expect(page.getByTestId("update-status")).toHaveAttribute(
    "href",
    "https://github.com/HKUDS/DeepTutor/releases/tag/v1.5.4",
  );
});

test("version badge reports a failed update check", async ({ page }) => {
  await page.route("**/api/v1/system/update", (route) =>
    route.fulfill({ status: 503, body: "service unavailable" }),
  );

  await page.goto("/");

  await expect(page.getByTestId("version-badge")).toContainText(
    "Update check failed",
  );
});

test("Docker installations direct updates to the host without an update action", async ({
  page,
}) => {
  await page.route("**/api/v1/system/update", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...AVAILABLE_UPDATE,
        install_mode: "docker",
        can_auto_update: false,
        detail: "Update the image on the Docker host and recreate the container.",
      }),
    }),
  );

  await page.goto("/");

  const badge = page.getByTestId("version-badge");
  await expect(badge).toContainText("v1.6.0");
  await expect(badge).toContainText(/update on host/i);
  await expect(badge.getByRole("button", { name: /update/i })).toHaveCount(0);
});

test("admin can confirm an update and reconnect after the managed restart", async ({
  page,
}) => {
  let requested = false;
  let confirmation: unknown;
  let poll = 0;
  await page.route("**/api/v1/auth/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        enabled: true,
        authenticated: true,
        role: "admin",
        is_admin: true,
      }),
    }),
  );
  await page.route("**/api/v1/system/update", async (route) => {
    if (route.request().method() === "POST") {
      requested = true;
      confirmation = route.request().postDataJSON();
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          id: "job-1",
          status: "pending",
          current_version: "1.5.4",
          target_version: "1.6.0",
          error: null,
          restart_count: 0,
        }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(AVAILABLE_UPDATE),
    });
  });
  await page.route("**/api/v1/system/update/job", async (route) => {
    if (!requested) {
      await route.fulfill({ status: 200, contentType: "application/json", body: "null" });
      return;
    }
    poll += 1;
    if (poll === 2) {
      await route.abort("connectionfailed");
      return;
    }
    const status = poll === 1 ? "running" : poll === 3 ? "restarting" : "succeeded";
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "job-1",
        status,
        current_version: "1.5.4",
        target_version: "1.6.0",
        error: null,
        restart_count: status === "succeeded" ? 1 : 0,
      }),
    });
  });

  await page.goto("/");
  await page.getByTestId("update-action").click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("v1.6.0");
  await dialog.getByRole("button", { name: /update and restart/i }).click();

  await expect(page.getByTestId("update-action")).toContainText(/reconnected/i);
  expect(confirmation).toEqual({ confirmation: "update-and-restart" });

  await page.reload();
  await expect(page.getByTestId("update-action")).toContainText(/reconnected/i);
});

test("failed Web update remains visible to the user", async ({ page }) => {
  let requested = false;
  await page.route("**/api/v1/auth/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        enabled: false,
        authenticated: true,
        role: "admin",
        is_admin: true,
      }),
    }),
  );
  await page.route("**/api/v1/system/update", (route) => {
    if (route.request().method() === "POST") {
      requested = true;
      return route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          id: "job-2",
          status: "pending",
          current_version: "1.5.4",
          target_version: "1.6.0",
          error: null,
          restart_count: 0,
        }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(AVAILABLE_UPDATE),
    });
  });
  await page.route("**/api/v1/system/update/job", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: requested
        ? JSON.stringify({
            id: "job-2",
            status: "failed",
            current_version: "1.5.4",
            target_version: "1.6.0",
            error: "pip exited with status 1",
            restart_count: 0,
          })
        : "null",
    }),
  );

  await page.goto("/");
  await page.getByTestId("update-action").click();
  await page
    .getByRole("alertdialog")
    .getByRole("button", { name: /update and restart/i })
    .click();

  await expect(page.getByTestId("update-action")).toContainText(/update failed/i);
});
