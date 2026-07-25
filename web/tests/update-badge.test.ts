import test from "node:test";
import assert from "node:assert/strict";
import { presentUpdateBadge } from "../lib/update-badge";

test("presentUpdateBadge exposes an actionable release link for available updates", () => {
  const presentation = presentUpdateBadge({
    status: "available",
    current_version: "1.5.4",
    latest_version: "1.6.0",
    install_mode: "pypi",
    can_auto_update: true,
    release_url: "https://github.com/HKUDS/DeepTutor/releases/tag/v1.6.0",
    detail: "installed distribution",
  });

  assert.deepEqual(presentation, {
    kind: "available",
    version: "v1.6.0",
    href: "https://github.com/HKUDS/DeepTutor/releases/tag/v1.6.0",
    hostManaged: false,
    installMode: "pypi",
    canAutoUpdate: true,
  });
});

test("presentUpdateBadge marks Docker updates as host-managed", () => {
  const presentation = presentUpdateBadge({
    status: "available",
    current_version: "1.5.4",
    latest_version: "1.6.0",
    install_mode: "docker",
    can_auto_update: false,
    release_url: "https://github.com/HKUDS/DeepTutor/releases/tag/v1.6.0",
    detail: "Update the image on the Docker host and recreate the container.",
  });

  assert.deepEqual(presentation, {
    kind: "available",
    version: "v1.6.0",
    href: "https://github.com/HKUDS/DeepTutor/releases/tag/v1.6.0",
    hostManaged: true,
    installMode: "docker",
    canAutoUpdate: false,
  });
});

test("presentUpdateBadge preserves up-to-date and failed states", () => {
  const base = {
    current_version: "1.5.4",
    latest_version: "1.5.4",
    install_mode: "pypi" as const,
    can_auto_update: true,
    release_url: "https://github.com/HKUDS/DeepTutor/releases/tag/v1.5.4",
    detail: "installed distribution",
  };

  assert.deepEqual(presentUpdateBadge({ ...base, status: "up_to_date" }), {
    kind: "up_to_date",
    version: "v1.5.4",
    href: "https://github.com/HKUDS/DeepTutor/releases/tag/v1.5.4",
  });
  assert.deepEqual(
    presentUpdateBadge({
      ...base,
      status: "failed",
      latest_version: null,
      release_url: null,
    }),
    { kind: "failed" },
  );
});
