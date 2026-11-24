import { describe, expect, it } from "vitest";

import {
  allowPrivateTargets,
  isNetworkDraftDirty,
  networkDraftPayload,
  normalizeNetworkDraft,
  splitNetworkList,
  ssrfProtectionFromToggle,
  type NetworkSettingsPayload,
} from "../features/settings/sections/network-draft";

// Shapes as `GET /api/settings/network` serves them.
function payload(
  overrides: Partial<NetworkSettingsPayload["settings"]> = {},
): NetworkSettingsPayload {
  return {
    settings: {
      backend_port: 8001,
      frontend_port: 3782,
      public_api_base: "",
      cors_origins: ["https://learn.example.com"],
      ssrf_protection_enabled: true,
      network_synthetic_ranges: [],
      ...overrides,
    },
    effective: {
      backend_url: "http://localhost:8001",
      frontend_url: "http://localhost:3782",
      browser_api_base: "http://localhost:8001",
      api_base_source: "default_backend_url",
      cors_mode: "explicit",
      cors_origins: [],
      allow_remote_http_origins: false,
      ssrf_protection_enabled: true,
      network_synthetic_ranges: [],
      ssrf_policy_env_override: false,
    },
    auth: {
      enabled: true,
      cookie_secure: true,
      cookie_samesite: "none",
      cross_site_cookie_ready: true,
    },
    restart_required: true,
  };
}

describe("splitNetworkList", () => {
  it("accepts comma, semicolon and newline separators", () => {
    expect(splitNetworkList("198.18.0.0/15\nfd27:712::/32")).toEqual([
      "198.18.0.0/15",
      "fd27:712::/32",
    ]);
    expect(splitNetworkList(" 198.18.0.0/15 , 10.0.0.0/8;")).toEqual([
      "198.18.0.0/15",
      "10.0.0.0/8",
    ]);
    expect(splitNetworkList("")).toEqual([]);
  });

  it("keeps IPv6 CIDRs whole", () => {
    // Colons are part of the value, so only commas/semicolons/newlines split.
    expect(splitNetworkList("fd27:712::/32")).toEqual(["fd27:712::/32"]);
  });
});

describe("normalizeNetworkDraft", () => {
  it("mirrors the server defaults when the policy keys are absent", () => {
    const legacy = payload();
    delete (legacy.settings as Partial<NetworkSettingsPayload["settings"]>)
      .ssrf_protection_enabled;
    delete (legacy.settings as Partial<NetworkSettingsPayload["settings"]>)
      .network_synthetic_ranges;

    const draft = normalizeNetworkDraft(legacy);

    // An older backend guards by default; the form must not claim otherwise.
    expect(draft.ssrf_protection_enabled).toBe(true);
    expect(draft.network_synthetic_ranges).toEqual([]);
  });

  it("carries a saved policy through", () => {
    const draft = normalizeNetworkDraft(
      payload({
        ssrf_protection_enabled: false,
        network_synthetic_ranges: ["198.18.0.0/15"],
      }),
    );

    expect(draft.ssrf_protection_enabled).toBe(false);
    expect(draft.network_synthetic_ranges).toEqual(["198.18.0.0/15"]);
    expect(allowPrivateTargets(draft)).toBe(true);
  });
});

describe("networkDraftPayload", () => {
  it("makes the textareas authoritative for both lists", () => {
    const draft = normalizeNetworkDraft(
      payload({ network_synthetic_ranges: ["10.0.0.0/8"] }),
    );

    expect(
      networkDraftPayload(
        draft,
        "https://a.example.com",
        "198.18.0.0/15\nfd27:712::/32",
      ),
    ).toMatchObject({
      cors_origins: ["https://a.example.com"],
      network_synthetic_ranges: ["198.18.0.0/15", "fd27:712::/32"],
    });
  });
});

describe("isNetworkDraftDirty", () => {
  it("is clean when nothing changed", () => {
    const base = payload({ network_synthetic_ranges: ["198.18.0.0/15"] });
    const draft = normalizeNetworkDraft(base);

    expect(
      isNetworkDraftDirty(
        base,
        draft,
        "https://learn.example.com",
        "198.18.0.0/15",
      ),
    ).toBe(false);
  });

  it("notices an edited range and a flipped switch", () => {
    const base = payload();
    const draft = normalizeNetworkDraft(base);

    expect(
      isNetworkDraftDirty(
        base,
        draft,
        "https://learn.example.com",
        "fd27:712::/32",
      ),
    ).toBe(true);
    expect(
      isNetworkDraftDirty(
        base,
        { ...draft, ssrf_protection_enabled: false },
        "https://learn.example.com",
        "",
      ),
    ).toBe(true);
  });
});

describe("toggle mapping", () => {
  it("stores the guard, not the permission", () => {
    expect(ssrfProtectionFromToggle(true)).toBe(false);
    expect(ssrfProtectionFromToggle(false)).toBe(true);
    expect(
      allowPrivateTargets({
        ...normalizeNetworkDraft(payload()),
        ssrf_protection_enabled: false,
      }),
    ).toBe(true);
    expect(allowPrivateTargets(normalizeNetworkDraft(payload()))).toBe(false);
  });
});
