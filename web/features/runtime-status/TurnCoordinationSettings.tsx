"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Field, InlineAlert } from "@/shared/ui";
import { validateTurnCoordination, type TurnCoordinationDraft } from "./model";

export interface TurnCoordinationSettingsProps {
  value: TurnCoordinationDraft;
  redisConfigured: boolean;
  onChange?: (next: TurnCoordinationDraft) => void;
  onSaveRedisUrl?: (url: string) => Promise<void>;
}

const controlClass =
  "min-h-10 w-full rounded-xl border border-border bg-background px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60";

export function TurnCoordinationSettings({
  value,
  redisConfigured,
  onChange,
  onSaveRedisUrl,
}: TurnCoordinationSettingsProps) {
  const { t } = useTranslation();
  const [redisUrl, setRedisUrl] = useState("");
  const [savingSecret, setSavingSecret] = useState(false);
  const [secretError, setSecretError] = useState("");
  const errors = validateTurnCoordination(value, redisConfigured);
  const readOnly = !onChange;
  const update = (patch: Partial<TurnCoordinationDraft>) =>
    onChange?.({ ...value, ...patch });

  const saveSecret = async () => {
    if (!onSaveRedisUrl || !redisUrl.trim()) return;
    setSavingSecret(true);
    setSecretError("");
    try {
      await onSaveRedisUrl(redisUrl.trim());
      setRedisUrl("");
    } catch (error) {
      setSecretError(
        error instanceof Error ? error.message : t("Failed to save."),
      );
    } finally {
      setSavingSecret(false);
    }
  };

  return (
    <section className="mt-6 rounded-2xl border border-border bg-card p-5">
      <h2 className="text-sm font-semibold text-foreground">
        {t("Turn coordination")}
      </h2>
      <p className="mt-1 text-xs leading-5 text-muted-foreground">
        {readOnly
          ? t("These startup settings are shown from the active runtime.")
          : t("Changes apply after the backend restarts.")}
      </p>

      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <Field label={t("Backend workers")}>
          <input
            className={controlClass}
            type="number"
            min={1}
            max={32}
            disabled={readOnly}
            value={value.backendWorkers}
            onChange={(event) =>
              update({ backendWorkers: Number(event.target.value) })
            }
          />
        </Field>
        <Field label={t("Coordination backend")}>
          <select
            className={controlClass}
            disabled={readOnly}
            value={value.coordinationMode}
            onChange={(event) =>
              update({
                coordinationMode: event.target.value as "memory" | "redis",
              })
            }
          >
            <option value="memory">{t("In process")}</option>
            <option value="redis">Redis</option>
          </select>
        </Field>
      </div>

      {onSaveRedisUrl ? (
        <div className="mt-4 flex items-end gap-2">
          <Field
            label={t("Redis URL")}
            hint={
              redisConfigured
                ? t(
                    "A Redis secret is configured. Enter a new value only to replace it.",
                  )
                : t(
                    "The value is encrypted at rest and is never returned by the server.",
                  )
            }
            error={secretError || undefined}
            className="min-w-0 flex-1"
          >
            <input
              className={controlClass}
              type="password"
              autoComplete="new-password"
              value={redisUrl}
              onChange={(event) => setRedisUrl(event.target.value)}
            />
          </Field>
          <Button
            loading={savingSecret}
            disabled={!redisUrl.trim()}
            onClick={() => void saveSecret()}
          >
            {t("Save secret")}
          </Button>
        </div>
      ) : null}

      <details className="mt-5 border-t border-border pt-4">
        <summary className="cursor-pointer text-sm font-medium text-foreground">
          {t("Advanced")}
        </summary>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <Field label={t("Lease TTL (seconds)")}>
            <input
              className={controlClass}
              type="number"
              min={5}
              max={300}
              disabled={readOnly}
              value={value.leaseTtlSeconds}
              onChange={(event) =>
                update({ leaseTtlSeconds: Number(event.target.value) })
              }
            />
          </Field>
          <Field label={t("Recovery interval (seconds)")}>
            <input
              className={controlClass}
              type="number"
              min={1}
              max={60}
              disabled={readOnly}
              value={value.recoveryIntervalSeconds}
              onChange={(event) =>
                update({ recoveryIntervalSeconds: Number(event.target.value) })
              }
            />
          </Field>
        </div>
      </details>

      {errors.length ? (
        <InlineAlert
          tone="warning"
          title={t("Check runtime settings")}
          className="mt-4"
        >
          <ul className="list-disc space-y-1 pl-4">
            {errors.map((error) => (
              <li key={error}>{t(error)}</li>
            ))}
          </ul>
        </InlineAlert>
      ) : null}
    </section>
  );
}
