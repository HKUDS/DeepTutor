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
  await expect(updateStatus).toContainText("v1.6.0");
  await expect(updateStatus).toHaveAttribute("href", RELEASE_URL);
  await expect(updateStatus).toHaveAccessibleName(/update available.*v1\.6\.0/i);
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
