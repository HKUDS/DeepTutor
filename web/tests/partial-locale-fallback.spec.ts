import { expect, it } from "vitest";

import { ensureLanguage, initI18n } from "@/i18n/init";

it("uses French copy now that the catalog is complete", async () => {
  const i18n = initI18n("fr");
  await ensureLanguage("fr");
  await i18n.changeLanguage("fr");

  expect(i18n.t("common.save")).toBe("Enregistrer");
});

it("loads Korean translations, preserves interpolation and falls back per key", async () => {
  const i18n = initI18n("ko-KR");
  await ensureLanguage("ko");
  await i18n.changeLanguage("ko");

  expect(i18n.t("common.save")).toBe("저장");
  expect(i18n.t("guidedLearning.title")).toBe("완전 학습 경로");
  expect(i18n.t("{{count}} resources selected", { count: 3 })).toBe("자료 3개 선택됨");
  expect(i18n.t("guidedLearning.masteredProgress", { mastered: 2, total: 5 })).toBe("2/5 습득 완료");
  expect(i18n.t("Speech synthesis and transcription models with saved providers.")).toBe(
    "Speech synthesis and transcription models with saved providers.",
  );
});

it("uses English copy for a key missing from a partial locale", async () => {
  const i18n = initI18n("en");
  i18n.addResourceBundle(
    "partial",
    "app",
    { "common.cancel": "Annuler" },
    true,
    true,
  );
  await i18n.changeLanguage("partial");

  expect(i18n.t("common.cancel")).toBe("Annuler");
  expect(i18n.t("common.save")).toBe("Save");

  i18n.removeResourceBundle("partial", "app");
});

it("uses Ukrainian copy when a translation exists", async () => {
  const i18n = initI18n("uk");
  await ensureLanguage("uk");
  await i18n.changeLanguage("uk");

  expect(i18n.t("common.save")).toBe("зберегти");
});
