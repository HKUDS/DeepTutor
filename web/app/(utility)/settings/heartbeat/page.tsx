"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
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
  const { catalogEditable, registerExtension } = useSettings();
  const isAdmin = catalogEditable === true;

  const [config, setConfig] = useState<HeartbeatConfig | null>(null);
  const [intervalMin, setIntervalMin] = useState(30);
  const [llmSelection, setLlmSelection] = useState<LLMSelection | null>(null);
  const [llmOptions, setLlmOptions] = useState<LLMOption[]>([]);
  const [activeLLMDefault, setActiveLLMDefault] = useState<LLMSelection | null>(null);
  const [loading, setLoading] = useState(true);

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

  // 计算 dirty 状态
  const dirty =
    config !== null &&
    (Math.round(config.interval_s / 60) !== intervalMin ||
      !sameLLMSelection(config.llm_selection, llmSelection));

  // 使用 ref 确保闭包引用最新状态
  const intervalMinRef = useRef(intervalMin);
  intervalMinRef.current = intervalMin;
  const llmSelectionRef = useRef(llmSelection);
  llmSelectionRef.current = llmSelection;

  // save 函数：被全局 Apply 调用
  const save = useCallback(async () => {
    const res = await apiFetch(apiUrl("/api/v1/settings/heartbeat"), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        interval_s: intervalMinRef.current * 60,
        llm_selection: llmSelectionRef.current,
      }),
    });
    if (!res.ok) {
      throw new Error(
        t("Failed to save heartbeat settings (HTTP {{status}})", {
          status: res.status,
        }),
      );
    }
    const data = (await res.json()) as HeartbeatConfig;
    setConfig(data);
    setIntervalMin(Math.round(data.interval_s / 60));
    setLlmSelection(data.llm_selection);
  }, [t]);

  // 注册到全局 extensions，与 memory/capabilities 页面一致
  useEffect(() => {
    registerExtension("heartbeat", { dirty, save });
    return () => registerExtension("heartbeat", null);
  }, [dirty, save, registerExtension]);

  if (loading) {
    return (
      <div className="flex min-h-[320px] items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
      </div>
    );
  }

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

      {/* 权限提示 */}
      {!isAdmin && (
        <p className="text-[12px] text-[var(--muted-foreground)]">
          {t("Only administrators can modify these settings.")}
        </p>
      )}
    </div>
  );
}
