import { describe, expect, it } from "vitest";

import {
  DEFAULT_WEB_FETCH_BACKEND,
  webFetchBackendOptions,
  webFetchBackendValue,
  type WebFetchBackendChoice,
} from "../components/settings/web-fetch-backend";

// Choices as `GET /api/settings/web-fetch` serves them, derived from the
// backend FETCH_PROVIDERS spec table. The web app owns no backend table of
// its own, so these fixtures are the contract under test.
const choice = (
  value: string,
  label: string,
  extra: Partial<WebFetchBackendChoice> = {},
): WebFetchBackendChoice => ({
  value,
  label,
  requires_api_key: false,
  ...extra,
});

const CHOICES: WebFetchBackendChoice[] = [
  choice("local", "Local"),
  choice("deepseek", "DeepSeek Fetch", { requires_api_key: true }),
];

describe("webFetchBackendOptions", () => {
  it("passes the backend's own choices through in order", () => {
    expect(webFetchBackendOptions(CHOICES, "local")).toEqual([
      { value: "local", label: "Local" },
      { value: "deepseek", label: "DeepSeek Fetch" },
    ]);
  });

  it("falls back to the stored value alone while choices are unloaded", () => {
    // Before the choices arrive (or from an older backend) there is no table
    // to read — never invent one, show just the stored value.
    for (const choices of [null, undefined, []]) {
      expect(webFetchBackendOptions(choices, "deepseek")).toEqual([
        { value: "deepseek", label: "deepseek" },
      ]);
    }
    expect(webFetchBackendOptions(null, "")).toEqual([]);
  });

  it("keeps an empty or blank-labeled choice usable via its value", () => {
    expect(
      webFetchBackendOptions([choice("custom", ""), choice("", "No value")], "custom"),
    ).toEqual([{ value: "custom", label: "custom" }]);
  });
});

describe("webFetchBackendValue", () => {
  it("returns an offered value unchanged", () => {
    expect(webFetchBackendValue("deepseek", webFetchBackendOptions(CHOICES, "local"))).toBe(
      "deepseek",
    );
  });

  it("falls back to the default backend for unknown, empty, or missing values", () => {
    for (const value of ["tarball", "", null, undefined]) {
      expect(webFetchBackendValue(value, webFetchBackendOptions(CHOICES, "local"))).toBe(
        DEFAULT_WEB_FETCH_BACKEND,
      );
    }
  });

  it("falls back to the first option when the default backend is not offered", () => {
    const options = webFetchBackendOptions([choice("deepseek", "DeepSeek Fetch")], "deepseek");
    expect(webFetchBackendValue("local", options)).toBe("deepseek");
    expect(webFetchBackendValue(null, [])).toBe("");
  });
});
