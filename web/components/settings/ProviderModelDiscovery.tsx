"use client";

import { useEffect, useId, useRef, useState } from "react";
import { CheckCircle2, Loader2, PlugZap } from "lucide-react";
import { useTranslation } from "react-i18next";
import { apiFetch, apiUrl } from "@/lib/api";
import { inputClass, selectClass } from "./shared";

export type ProviderProbeInput = {
  binding: string;
  base_url: string;
  api_key?: string | string[] | null;
  api_format?: string;
  api_version?: string;
  extra_headers?: Record<string, string> | string;
  service?: string;
  profile_id?: string;
  connection_id?: string;
};

const messages: Record<string, string> = {
  connected: "Connected. Available models are ready to choose below.",
  auth_error:
    "The provider rejected these credentials. Check the API key and its permissions.",
  unavailable:
    "This endpoint cannot list models. Enter a model ID manually, then test the model to verify access.",
  rate_limited: "The provider is rate limiting requests. Try again later.",
  timeout:
    "The connection timed out. Check the address and network, then try again.",
  unreachable:
    "Could not reach the provider. Check the address and network.",
  invalid_url: "Enter a valid HTTP or HTTPS provider address.",
  http_error:
    "The provider returned an error. Check the address or try again later.",
};

type DiscoveryProps = {
  input: ProviderProbeInput;
  onPick?: (model: string) => void;
  onPickMany?: (models: string[]) => void;
  selectedModels?: string[];
};

/** A changed credential set remounts the probe, cancelling stale requests/results. */
export function ProviderModelDiscovery(props: DiscoveryProps) {
  return <DiscoveryForm key={JSON.stringify(props.input)} {...props} />;
}

function DiscoveryForm({
  input,
  onPick,
  onPickMany,
  selectedModels = [],
}: DiscoveryProps) {
  const { t } = useTranslation();
  const pickerId = useId();
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<{
    status: string;
    models: { id: string }[];
  } | null>(null);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const testConnection = async () => {
    const request = new AbortController();
    controller.current?.abort();
    controller.current = request;
    setRunning(true);
    setResult(null);
    setError("");
    try {
      const response = await apiFetch(
        apiUrl("/api/settings/test-provider"),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(input),
          signal: request.signal,
        },
      );
      const payload = await response.json();
      if (!response.ok)
        throw new Error(
          typeof payload.detail === "string"
            ? payload.detail
            : t("Could not reach provider."),
        );
      if (!request.signal.aborted) setResult(payload);
    } catch (cause) {
      if (!request.signal.aborted)
        setError(
          cause instanceof Error
            ? cause.message
            : t("Could not reach provider."),
        );
    } finally {
      if (!request.signal.aborted) setRunning(false);
    }
  };
  const models = (result?.models ?? []).filter((model) =>
    model.id.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={running || !input.base_url.trim()}
          onClick={() => void testConnection()}
          className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-[var(--border)] px-3 text-sm hover:bg-[var(--muted)] disabled:opacity-50"
        >
          {running ? (
            <Loader2 size={15} className="animate-spin" />
          ) : (
            <PlugZap size={15} />
          )}
          {running
            ? t("Testing connection…")
            : t("Test provider connection")}
        </button>
        <span className="text-xs text-[var(--muted-foreground)]">
          {t("No model needed. Testing also retrieves available models.")}
        </span>
      </div>
      <div role="status" aria-live="polite" className="break-words text-sm">
        {error && <p className="text-red-600 dark:text-red-400">{error}</p>}
        {result && (
          <p
            className={
              result.status === "connected"
                ? "text-emerald-700 dark:text-emerald-400"
                : "text-amber-700 dark:text-amber-400"
            }
          >
            {result.status === "connected" && (
              <CheckCircle2 size={14} className="mr-1 inline" />
            )}
            {t(
              result.status === "connected" && !result.models.length
                ? "Connected, but the provider returned no models. You can enter a model ID manually."
                : result.status === "connected" && !onPick && !onPickMany
                  ? "Connected. The provider returned {{count}} models."
                  : messages[result.status] || messages.http_error,
              { count: result.models.length },
            )}
          </p>
        )}
      </div>
      {!!result?.models.length && (onPick || onPickMany) && (
        <div className="space-y-2 rounded-lg bg-[var(--muted)]/35 p-3">
          <div className="block text-sm font-medium">
            <label htmlFor={pickerId}>
              {t("Choose a model from this provider")}
            </label>
            {result.models.length > 10 && (
              <input
                aria-label={t("Search available models")}
                className={`${inputClass} mt-2`}
                placeholder={t("Search available models")}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            )}
            {onPickMany ? (
              <div className="mt-2 space-y-2">
                <div
                  id={pickerId}
                  className="max-h-52 overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--background)] p-1"
                  role="group"
                  aria-label={t("Choose a model from this provider")}
                >
                  {models.map((model) => {
                    const added = selectedModels.includes(model.id);
                    return (
                      <label
                        key={model.id}
                        className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-2 text-xs hover:bg-[var(--accent)]"
                      >
                        <input
                          type="checkbox"
                          disabled={added}
                          checked={added || picked.includes(model.id)}
                          onChange={(event) =>
                            setPicked((current) =>
                              event.target.checked
                                ? [...current, model.id]
                                : current.filter((id) => id !== model.id),
                            )
                          }
                        />
                        <span className="min-w-0 flex-1 break-all font-mono">
                          {model.id}
                        </span>
                        {added && (
                          <span className="text-[var(--muted-foreground)]">
                            {t("Added")}
                          </span>
                        )}
                      </label>
                    );
                  })}
                  {!models.length && (
                    <p className="p-3 text-xs">{t("No matching models")}</p>
                  )}
                </div>
                <button
                  type="button"
                  disabled={
                    !picked.some((id) => !selectedModels.includes(id))
                  }
                  onClick={() => {
                    onPickMany(
                      picked.filter((id) => !selectedModels.includes(id)),
                    );
                    setPicked([]);
                  }}
                  className="rounded-lg bg-[var(--foreground)] px-3 py-2 text-xs text-[var(--background)] disabled:opacity-40"
                >
                  {t("Add selected models")}
                </button>
              </div>
            ) : (
              <select
                id={pickerId}
                className={`${selectClass} mt-2`}
                value=""
                onChange={(event) => {
                  if (event.target.value) onPick?.(event.target.value);
                }}
              >
                <option value="">{t("Select a model...")}</option>
                {models.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.id}
                  </option>
                ))}
              </select>
            )}
          </div>
          <p className="text-xs text-[var(--muted-foreground)]">
            {t(
              "You can also enter a model ID manually. Listing a model does not guarantee access to every feature.",
            )}
          </p>
        </div>
      )}
    </div>
  );
}
