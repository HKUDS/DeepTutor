"use client";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { invidiousAccountResultMessage } from "@/lib/invidious-account-result";
export default function InvidiousAccountFeedback() {
  const { t } = useTranslation();
  const params = useSearchParams();
  const result = params.get("account");
  const message = invidiousAccountResultMessage(result);
  const [dismissed, setDismissed] = useState(false);
  useEffect(() => {
    if (!params.has("account")) return;
    const url = new URL(window.location.href);
    url.searchParams.delete("account");
    window.history.replaceState(null, "", url.pathname + url.search + url.hash);
  }, [params]);
  if (!message || dismissed) return null;
  return <div role={result === "connected" ? "status" : "alert"} className="mb-4 flex items-center gap-3 rounded-lg border border-border p-3 text-sm">
    <span className="flex-1">{t(message)}</span>
    <button type="button" onClick={() => setDismissed(true)}>{t("Dismiss")}</button>
  </div>;
}
