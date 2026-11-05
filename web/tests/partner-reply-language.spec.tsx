import { render, screen } from "@testing-library/react";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import { expect, it } from "vitest";

import PartnerReplyLanguageSelect from "@/components/partners/PartnerReplyLanguageSelect";
import { writeStoredResponseLanguage } from "@/context/app-shell-storage";

it("labels Auto with the account response language and offers every language", async () => {
  const i18n = createInstance();
  await i18n.init({
    lng: "fr",
    fallbackLng: "en",
    defaultNS: "app",
    resources: {
      en: { app: { "Auto ({{value}})": "Auto ({{value}})" } },
      fr: { app: { "Auto ({{value}})": "Auto ({{value}})" } },
    },
  });
  writeStoredResponseLanguage("fr");

  render(
    <I18nextProvider i18n={i18n}>
      <PartnerReplyLanguageSelect value="" onChange={() => undefined} />
    </I18nextProvider>,
  );

  const select = screen.getByRole("combobox");
  expect(select).toHaveValue("");
  expect(
    screen.getByRole("option", { name: "Auto (Français)" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("option", { name: "Українська" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("option", { name: "Français" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("option", { name: "Tiếng Việt" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("option", { name: "Türkçe" }),
  ).toBeInTheDocument();
});
