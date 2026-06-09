"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Save } from "lucide-react";
import { useTranslation } from "react-i18next";
import { apiFetch, apiUrl } from "@/lib/api";
import { useSettings } from "@/components/settings/SettingsContext";
import ModelSelector from "@/components/chat/home/ModelSelector";
import {
  listLLMOptions,
  sameLLMSelection,
  type LLMOption,
} from "@/lib/llm-options";
import type { LLMSelection } from "@/lib/unified-ws";

interface HeartbeatConfig {
  version: number;
  interval_s: number;
  llm_selection: LLMSelection | null;
}

export default function HeartbeatSettingsPage() {
  const { t } = useTranslation();
  const { catalogEditable } = useSettings();
  const isAdmin = catalogEditable === true;

  const [config, setConfig] = useState<HeartbeatConfig | null>(null);
  const [intervalMin, setIntervalMin] = useState(30);
  const [llmSelection, setLlmSelection] = useState<LLMSelection | null>(null);
  const [llmOptions, setLlmOptions] = useState<LLMOption[]>([]);
  const [activeLLMDefault, setActiveLLMDefault] = useState<LLMSelection | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState("");

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3500);
    return () => clearTimeout(timer);
  }, [toast]);

  // 加载心跳配置
  const loadConfig = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(apiUrl("/api/v1/settings/heartbeat"));
      if (res.ok) {
        const data = (await res.json()) as HeartbeatConfig;
        setConfig(data);
        setIntervalMin(Math.round(data.interval_s / 60));
        setLlmSelection(data.llm_selection);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  // 加载 LLM 选项
  const loadLLMOptions = useCallback(async () => {
    try {
      const payload = await listLLMOptions();
      setLlmOptions(payload.options);
      setActiveLLMDefault(payload.active);
    } catch {
      setLlmOptions([]);
      setActiveLLMDefault(null);
    }
  }, []);

  useEffect(() => {
    void Promise.all([loadConfig(), loadLLMOptions()]);
  }, [loadConfig, loadLLMOptions]);

  const save = useCallback(async () => {
    setSaving(true);
    try {
      const res = await apiFetch(apiUrl("/api/v1/settings/heartbeat"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          interval_s: intervalMin * 60,
          llm_selection: llmSelection,
        }),
      });
      if (res.ok) {
        const data = (await res.json()) as HeartbeatConfig;
        setConfig(data);
        setToast(t("Heartbeat settings saved"));
      } else {
        const err = (await res.json().catch(() => ({}))) as { detail?: string };
        setToast(err.detail ?? t("Failed to save"));
      }
    } catch {
      setToast(t("Failed to save"));
    } finally {
      setSaving(false);
    }
  }, [intervalMin, llmSelection, t]);

  if (loading) {
    return (
      <div className="flex min-h-[320px] items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

  const hasChanges =
    config !== null &&
    (Math.round(config.interval_s / 60) !== intervalMin ||
      !sameLLMSelection(config.llm_selection, llmSelection));

  return (
    <div className="space-y-6" data-tour="tour-heartbeat">
      <div>
        <h2 className="text-[16px] font-semibold text-[var(--foreground)]">
          {t("Heartbeat")}
        </h2>
        <p className="mt-1 text-[13px] text-[var(--muted-foreground)]">
          {t(
            "Configure the heartbeat interval and model. The heartbeat periodically checks for active tasks."
          )}
        </p>
      </div>

      {/* 心跳间隔 */}
      <div className="rounded-xl border border-[var(--border)] p-4 space-y-3">
        <h3 className="text-[13px] font-medium text-[var(--foreground)]">
          {t("Interval")}
        </h3>
        <div className="flex items-center gap-3">
          <input
            type="number"
            min={1}
            max={1440}
            value={intervalMin}
            onChange={(e) => {
              const v = parseInt(e.target.value, 10);
              if (!isNaN(v)) setIntervalMin(Math.max(1, Math.min(1440, v)));
            }}
            disabled={!isAdmin}
            className="w-24 rounded-lg border border-[var(--border)] bg-transparent px-3 py-1.5 text-[13px] text-[var(--foreground)] outline-none focus:border-[var(--ring)] disabled:opacity-50"
          />
          <span className="text-[13px] text-[var(--muted-foreground)]">
            {t("minutes")}
          </span>
        </div>
        <p className="text-[11px] text-[var(--muted-foreground)]/60">
          {t("Range: 1–1440 minutes (1 minute to 24 hours). Default: 30 minutes.")}
        </p>
      </div>

      {/* 心跳模型 */}
      <div className="rounded-xl border border-[var(--border)] p-4 space-y-3">
        <h3 className="text-[13px] font-medium text-[var(--foreground)]">
          {t("Heartbeat Model")}
        </h3>
        <ModelSelector
          options={llmOptions}
          activeDefault={activeLLMDefault}
          value={llmSelection}
          loading={false}
          error={false}
          allowSystemDefault
          disabled={!isAdmin}
          helperText={t("Model used for heartbeat decision")}
          placement="bottom"
          onChange={isAdmin ? setLlmSelection : () => {}}
        />
        <p className="text-[11px] text-[var(--muted-foreground)]/60">
          {t(
            "Choose a lightweight model for heartbeat to reduce API costs. System default uses the main agent model."
          )}
        </p>
      </div>

      {/* 保存按钮 */}
      <div className="flex items-center gap-3">
        <button
          onClick={save}
          disabled={!isAdmin || saving || !hasChanges}
          className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-4 py-2 text-[13px] font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {saving ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Save className="h-3.5 w-3.5" />
          )}
          {t("Save")}
        </button>
        {!isAdmin && (
          <span className="text-[12px] text-[var(--muted-foreground)]">
            {t("Only administrators can modify these settings.")}
          </span>
        )}
        {toast && (
          <span className="text-[12px] text-[var(--primary)] animate-fade-in">
            {toast}
          </span>
        )}
      </div>
    </div>
  );
}
