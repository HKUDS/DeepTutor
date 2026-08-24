"use client";

import { AlertTriangle, Check, Loader2, Server } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ImaConnectionController } from "@/hooks/useImaConnection";

export default function ImaConnectionFields({
  connection,
  submitting,
}: {
  connection: ImaConnectionController;
  submitting: boolean;
}) {
  const { t } = useTranslation();
  const loading = connection.lookup.status === "loading";
  const credentialsReady = connection.credentialsReady;
  const showFields = connection.useOwnCredentials;

  return (
    <div className="space-y-3">
      <p className="text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
        {t(
          "DeepTutor searches and browses this library, and reads full sources when a matched snippet is too short. It only writes to IMA when you ask it to.",
        )}
      </p>

      {connection.accountConfigured && !showFields ? (
        <div className="flex items-start justify-between gap-3 rounded-lg border border-[var(--border)] bg-[var(--muted)]/30 px-3 py-2.5">
          <span className="flex items-start gap-1.5 text-[11.5px] leading-snug text-[var(--muted-foreground)]">
            <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" />
            {t(
              "Using the IMA credentials configured for this engine in the Knowledge Center.",
            )}
          </span>
          <button
            type="button"
            onClick={() => connection.setUseOwnCredentials(true)}
            disabled={submitting}
            className="shrink-0 text-[11.5px] font-medium text-[var(--foreground)] underline underline-offset-2 disabled:opacity-40"
          >
            {t("Use other credentials")}
          </button>
        </div>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                {t("Client ID")}
              </label>
              <input
                value={connection.clientId}
                onChange={(event) => connection.setClientId(event.target.value)}
                disabled={submitting}
                autoComplete="off"
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 font-mono text-[12.5px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25 disabled:opacity-50"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                {t("API key")}
              </label>
              <input
                value={connection.apiKey}
                onChange={(event) => connection.setApiKey(event.target.value)}
                disabled={submitting}
                type="password"
                autoComplete="off"
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[12.5px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25 disabled:opacity-50"
              />
            </div>
          </div>

          <p className="text-[11px] text-[var(--muted-foreground)]">
            {connection.accountConfigured ? (
              <button
                type="button"
                onClick={() => connection.setUseOwnCredentials(false)}
                disabled={submitting}
                className="font-medium text-[var(--foreground)] underline underline-offset-2 disabled:opacity-40"
              >
                {t("Use the engine's credentials instead")}
              </button>
            ) : (
              <>
                {t(
                  "Set these once for the engine in the Knowledge Center to skip this step next time.",
                )}{" "}
                <a
                  href="https://ima.qq.com/agent-interface"
                  target="_blank"
                  rel="noreferrer"
                  className="font-medium text-[var(--foreground)] underline underline-offset-2"
                >
                  {t("Open IMA")}
                </a>
              </>
            )}
          </p>
        </>
      )}

      <div className="flex flex-wrap gap-2">
        <ModeButton
          selected={connection.mode === "automatic"}
          disabled={submitting}
          onClick={() => connection.setMode("automatic")}
        >
          {t("Choose from knowledge base list")}
        </ModeButton>
        <ModeButton
          selected={connection.mode === "manual"}
          disabled={submitting}
          onClick={() => connection.setMode("manual")}
        >
          {t("Use knowledge base ID instead")}
        </ModeButton>
      </div>

      {connection.mode === "automatic" ? (
        <div className="space-y-2">
          <button
            type="button"
            onClick={() => void connection.load(true)}
            disabled={submitting || loading || !credentialsReady}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-2 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:border-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {loading && connection.lookup.knowledgeBases.length === 0 ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Server className="h-3.5 w-3.5" />
            )}
            {t("Verify and load knowledge bases")}
          </button>

          {connection.lookup.status === "empty" && (
            <div className="rounded-lg border border-[var(--border)] bg-[var(--muted)]/30 px-3 py-3 text-[12px] text-[var(--muted-foreground)]">
              {t("No accessible knowledge bases found.")}
            </div>
          )}

          {connection.lookup.knowledgeBases.length > 0 && (
            <div className="space-y-2">
              <div className="max-h-56 space-y-1.5 overflow-y-auto rounded-xl border border-[var(--border)] p-2">
                {connection.lookup.knowledgeBases.map((item) => {
                  const selected = connection.lookup.selectedId === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => connection.select(item)}
                      disabled={submitting}
                      className={`flex w-full items-start justify-between gap-3 rounded-lg border px-3 py-2 text-left transition-colors ${
                        selected
                          ? "border-[var(--primary)] bg-[var(--primary)]/5"
                          : "border-transparent hover:bg-[var(--muted)]/50"
                      }`}
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-[12.5px] font-medium text-[var(--foreground)]">
                          {item.name}
                        </span>
                        {item.description && (
                          <span className="mt-0.5 line-clamp-2 block text-[11px] leading-snug text-[var(--muted-foreground)]">
                            {item.description}
                          </span>
                        )}
                      </span>
                      {selected && (
                        <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--primary)]" />
                      )}
                    </button>
                  );
                })}
              </div>
              {!connection.lookup.isEnd && (
                <button
                  type="button"
                  onClick={() => void connection.load(false)}
                  disabled={submitting || loading}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[11.5px] font-medium text-[var(--foreground)] disabled:opacity-40"
                >
                  {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  {t("Load more")}
                </button>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          <label className="block text-[11px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
            {t("Knowledge Base ID")}
          </label>
          <div className="flex gap-2">
            <input
              value={connection.manualKnowledgeBaseId}
              onChange={(event) =>
                connection.setManualKnowledgeBaseId(event.target.value)
              }
              disabled={submitting}
              autoComplete="off"
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 font-mono text-[12.5px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--foreground)]/25 disabled:opacity-50"
            />
            <button
              type="button"
              onClick={() => void connection.probe()}
              disabled={
                submitting ||
                loading ||
                !credentialsReady ||
                !connection.manualKnowledgeBaseId.trim()
              }
              className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 text-[12px] font-medium text-[var(--foreground)] disabled:opacity-40"
            >
              {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              {t("Verify knowledge base")}
            </button>
          </div>

          {connection.manualProbe &&
            (connection.manualProbe.ok ? (
              <div className="rounded-lg border border-[var(--border)] bg-[var(--muted)]/40 px-3 py-2.5 text-[12px]">
                <div className="flex items-center gap-1.5 font-medium text-emerald-700 dark:text-emerald-300">
                  <Check className="h-3.5 w-3.5" />
                  {t("Knowledge base verified")}
                </div>
                {connection.manualProbe.knowledge_base_name && (
                  <p className="mt-1 text-[var(--foreground)]">
                    {connection.manualProbe.knowledge_base_name}
                  </p>
                )}
                {connection.manualProbe.description && (
                  <p className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
                    {connection.manualProbe.description}
                  </p>
                )}
              </div>
            ) : (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                <span className="flex items-center gap-1.5">
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                  {connection.manualProbe.error || t("Could not connect")}
                </span>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

function ModeButton({
  selected,
  disabled,
  onClick,
  children,
}: {
  selected: boolean;
  disabled: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`rounded-lg border px-3 py-1.5 text-[11.5px] font-medium transition-colors ${
        selected
          ? "border-[var(--primary)] bg-[var(--primary)]/5 text-[var(--foreground)]"
          : "border-[var(--border)] text-[var(--muted-foreground)]"
      }`}
    >
      {children}
    </button>
  );
}
