import { expect, it } from "vitest";

import { ensureLanguage, initI18n } from "@/i18n/init";

it("uses English copy for a missing French translation", async () => {
  const i18n = initI18n("fr");
  await ensureLanguage("fr");
  await i18n.changeLanguage("fr");

  expect(i18n.t("common.save")).toBe("Save");
});

it("uses Ukrainian copy when a translation exists", async () => {
  const i18n = initI18n("uk");
  await ensureLanguage("uk");
  await i18n.changeLanguage("uk");

  expect(i18n.t("common.save")).toBe("зберегти");
});
