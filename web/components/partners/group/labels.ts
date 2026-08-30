"use client";

import { useTranslation } from "react-i18next";

/**
 * What kind of turn a message is, in one word.
 *
 * Shared by the transcript seat and the reasoning panel so the same message is
 * never named two different things — in a debate the panel otherwise shows
 * five identical-looking cards ("John, Frank, John, Frank, John") with no way
 * to tell an opening from a clash.
 */
export function useSeatKindLabel() {
  const { t } = useTranslation();
  return (kind?: string): string => {
    switch (kind) {
      case "debate_rebuttal":
        return t("Rebuttal");
      case "round_summary":
        return t("Summary");
      case "invocation_question":
      case "invocation_reply":
        return t("Follow-up");
      default:
        return "";
    }
  };
}
