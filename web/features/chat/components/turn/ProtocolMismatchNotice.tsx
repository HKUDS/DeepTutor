"use client";

import { useTranslation } from "react-i18next";
import { Button, InlineAlert } from "@/shared/ui";

export interface ProtocolMismatchNoticeProps {
  clientVersion: string;
  serverVersion?: string;
  onReload?: () => void;
}

export function ProtocolMismatchNotice({
  clientVersion,
  serverVersion,
  onReload,
}: ProtocolMismatchNoticeProps) {
  const { t } = useTranslation();
  return (
    <InlineAlert
      tone="danger"
      title={t("Frontend update required")}
      action={
        onReload ? (
          <Button size="sm" variant="secondary" onClick={onReload}>
            {t("Reload")}
          </Button>
        ) : null
      }
    >
      {t(
        "This page uses protocol {{clientVersion}}, but the server reports {{serverVersion}}.",
        {
          clientVersion,
          serverVersion: serverVersion || t("an incompatible version"),
        },
      )}
    </InlineAlert>
  );
}
