"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronDown, Loader2, Lock, Wrench } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useSettings } from "@/components/settings/SettingsContext";
import { SettingsPageHeader } from "@/components/settings/shared";
import { apiFetch, apiUrl } from "@/lib/api";
import { invalidateEnabledOptionalToolsCache } from "@/lib/tools-settings";

type ToolParameter = {
  name: string;
  type: string;
  description: string;
  required: boolean;
  default: unknown;
  enum: string[] | null;
};

type ToolHints = {
  short_description: string;
  when_to_use: string;
  input_format: string;
  guideline: string;
  note: string;
  phase: string;
  aliases: { name: string; description: string; phase: string }[];
};

type BuiltinTool = {
  name: string;
  description: string;
  parameters: ToolParameter[];
  hints: { en: ToolHints; zh: ToolHints };
  aliases: string[];
  toggleable: boolean;
  enabled: boolean;
  // ``coming_soon`` tools are listed for visibility but the chat agent
  // cannot invoke them. The settings UI surfaces them with a locked-off
  // toggle and a "Coming soon" badge.
  coming_soon?: boolean;
  // The capability that owns this tool (e.g. "solve" / "mastery"), or null
  // for a plain system built-in. Owned tools render in their own section
  // below the built-in tools.
  capability?: string | null;
};

type ToolsResponse = {
  tools: BuiltinTool[];
  enabled_optional_tools: string[];
};

type ToolSection = {
  key: string;
  label: string;
  hint: string;
  tools: BuiltinTool[];
};

// Display labels for capability-owned tool sections, keyed by the backend's
// capability id. Falls back to the raw id for any unmapped capability.
const CAPABILITY_LABELS: Record<string, { zh: string; en: string }> = {
  solve: { zh: "深度解题", en: "Deep Solve" },
  mastery: { zh: "精通路径", en: "Mastery Path" },
};

export default function ToolsSettingsPage() {
  const { t } = useTranslation();
  const { language } = useSettings();
  const [tools, setTools] = useState<BuiltinTool[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [enabled, setEnabled] = useState<Set<string>>(new Set());
  const [pending, setPending] = useState<Set<string>>(new Set());
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch(apiUrl("/api/v1/tools"));
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const payload = (await res.json()) as ToolsResponse;
        if (!cancelled) {
          setTools(payload.tools);
          setEnabled(new Set(payload.enabled_optional_tools ?? []));
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const persist = useCallback(async (next: Set<string>) => {
    const body = JSON.stringify({ enabled_tools: Array.from(next) });
    const res = await apiFetch(apiUrl("/api/v1/settings/enabled-tools"), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const payload = (await res.json()) as { enabled_optional_tools: string[] };
    // Bust the cached snapshot any other page in this tab is holding.
    invalidateEnabledOptionalToolsCache();
    return new Set(payload.enabled_optional_tools);
  }, []);

  const handleToggleEnabled = useCallback(
    async (toolName: string) => {
      if (pending.has(toolName)) return;
      const before = enabled;
      const next = new Set(before);
      if (next.has(toolName)) next.delete(toolName);
      else next.add(toolName);
      setEnabled(next);
      setPending((prev) => new Set(prev).add(toolName));
      setSaveError(null);
      try {
        const saved = await persist(next);
        setEnabled(saved);
      } catch (err) {
        setEnabled(before);
        setSaveError(err instanceof Error ? err.message : String(err));
      } finally {
        setPending((prev) => {
          const out = new Set(prev);
          out.delete(toolName);
          return out;
        });
      }
    },
    [enabled, pending, persist],
  );

  const sections = useMemo<ToolSection[] | null>(() => {
    if (!tools) return null;
    const zh = language === "zh";
    // Buckets: toggleable (体验增强) first, then locked-on built-ins, then one
    // section per capability for its owned tools. Backend order is preserved
    // within each bucket (mirrors USER_TOGGLEABLE_TOOL_NAMES / the
    // BUILTIN_TOOL_TYPES registration order). Coming-soon tools share the
    // toggleable bucket — same concept, just temporarily unavailable.
    const experience: BuiltinTool[] = [];
    const builtin: BuiltinTool[] = [];
    const capabilities = new Map<string, BuiltinTool[]>();
    for (const tool of tools) {
      if (tool.capability) {
        const list = capabilities.get(tool.capability) ?? [];
        list.push(tool);
        capabilities.set(tool.capability, list);
      } else if (tool.coming_soon) {
        experience.push(tool);
      } else {
        (tool.toggleable ? experience : builtin).push(tool);
      }
    }
    const out: ToolSection[] = [];
    if (experience.length) {
      out.push({
        key: "experience",
        label: zh ? "体验增强" : "Experience Enhancement",
        hint: zh
          ? "用户可选；按需为 chat agent 开启或关闭。"
          : "User-toggleable. Switch on or off to shape the chat agent's behavior.",
        tools: experience,
      });
    }
    if (builtin.length) {
      out.push({
        key: "builtin",
        label: zh ? "内置工具" : "Built-in Tools",
        hint: zh
          ? "Chat agent 在需要时自动挂载，无需手动开关。"
          : "Mounted automatically by the chat agent when needed. Not user-toggleable.",
        tools: builtin,
      });
    }
    for (const [cap, list] of capabilities) {
      const label = CAPABILITY_LABELS[cap]?.[zh ? "zh" : "en"] ?? cap;
      out.push({
        key: `cap:${cap}`,
        label: zh ? `${label} · 能力工具` : `${label} · Capability Tools`,
        hint: zh
          ? "该能力的专属工具，仅在此能力运行时挂载。"
          : "Tools specific to this capability; mounted only when it runs.",
        tools: list,
      });
    }
    return out;
  }, [tools, language]);

  const toggleExpanded = (name: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  return (
    <div data-tour="tour-tools">
      <SettingsPageHeader
        title={t("Tools")}
        description={t(
          "Switch user-toggleable tools on or off. Locked tools are mounted automatically when the chat agent needs them.",
        )}
      />

      {error && (
        <div className="rounded-xl border border-red-500/40 bg-red-500/5 px-4 py-3 text-[12px] text-red-500">
          {t("Failed to load tools")}: {error}
        </div>
      )}

      {saveError && (
        <div className="mb-4 rounded-xl border border-red-500/40 bg-red-500/5 px-4 py-3 text-[12px] text-red-500">
          {t("Failed to save")}: {saveError}
        </div>
      )}

      {!tools && !error && (
        <div className="flex items-center gap-2 text-[12px] text-[var(--muted-foreground)]">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          {t("Loading...")}
        </div>
      )}

      {sections && (
        <div className="space-y-8">
          {sections.map((section) => {
            const list = section.tools;
            if (list.length === 0) return null;
            return (
              <section key={section.key}>
                <header className="mb-3 flex items-baseline justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="text-[14px] font-semibold tracking-tight text-[var(--foreground)]">
                      {section.label}
                    </h2>
                    <p className="mt-0.5 text-[11.5px] text-[var(--muted-foreground)]">
                      {section.hint}
                    </p>
                  </div>
                  <span className="shrink-0 text-[11px] text-[var(--muted-foreground)]">
                    {list.length}
                  </span>
                </header>
                <div className="overflow-hidden rounded-xl border border-[var(--border)]/60 bg-[var(--card)]/40">
                  {list.map((tool, idx) => {
                    const isOpen = expanded.has(tool.name);
                    const hints = tool.hints[language];
                    const isPending = pending.has(tool.name);
                    const isComingSoon = !!tool.coming_soon;
                    const isEnabled =
                      !isComingSoon &&
                      (tool.toggleable ? enabled.has(tool.name) : true);
                    return (
                      <div
                        key={tool.name}
                        className={
                          idx > 0
                            ? "border-t border-[var(--border)]/50"
                            : undefined
                        }
                      >
                        <div className="flex w-full items-start gap-3 px-5 py-4">
                          <Wrench
                            className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${
                              isComingSoon
                                ? "text-[var(--muted-foreground)]/40"
                                : "text-[var(--muted-foreground)]"
                            }`}
                          />
                          <button
                            type="button"
                            onClick={() => toggleExpanded(tool.name)}
                            className="flex min-w-0 flex-1 items-start gap-3 text-left"
                            aria-expanded={isOpen}
                          >
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <span
                                  className={`font-mono text-[13px] font-medium ${
                                    isComingSoon
                                      ? "text-[var(--foreground)]/60"
                                      : "text-[var(--foreground)]"
                                  }`}
                                >
                                  {tool.name}
                                </span>
                                {tool.aliases.length > 0 && (
                                  <span className="text-[10.5px] text-[var(--muted-foreground)]/70">
                                    {tool.aliases.join(" · ")}
                                  </span>
                                )}
                                {isComingSoon && (
                                  <span className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--muted)]/40 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
                                    {language === "zh"
                                      ? "敬请期待"
                                      : "Coming soon"}
                                  </span>
                                )}
                              </div>
                              <p
                                className={`mt-1 text-[12.5px] leading-relaxed ${
                                  isComingSoon
                                    ? "text-[var(--muted-foreground)]/70"
                                    : "text-[var(--muted-foreground)]"
                                }`}
                              >
                                {hints.short_description || tool.description}
                              </p>
                            </div>
                            <ChevronDown
                              className={`mt-1 h-4 w-4 shrink-0 text-[var(--muted-foreground)] transition-transform ${
                                isOpen ? "rotate-180" : ""
                              }`}
                            />
                          </button>
                          <div className="mt-0.5 flex shrink-0 items-center gap-2">
                            {isComingSoon ? (
                              <ToolToggle
                                checked={false}
                                disabled
                                onChange={() => {
                                  /* locked */
                                }}
                                label={
                                  language === "zh" ? "敬请期待" : "Coming soon"
                                }
                              />
                            ) : tool.toggleable ? (
                              <ToolToggle
                                checked={isEnabled}
                                disabled={isPending}
                                onChange={() => handleToggleEnabled(tool.name)}
                                label={t(isEnabled ? "On" : "Off")}
                              />
                            ) : (
                              <span
                                className="inline-flex items-center gap-1 rounded-full bg-[var(--muted)]/40 px-2 py-0.5 text-[10.5px] text-[var(--muted-foreground)]"
                                title={t(
                                  "Auto-mounted by the agent when needed. Not user-toggleable.",
                                )}
                              >
                                <Lock className="h-3 w-3" />
                                {t("Always on")}
                              </span>
                            )}
                          </div>
                        </div>
                        {isOpen && (
                          <div className="space-y-4 border-t border-[var(--border)]/40 bg-[var(--background)]/40 px-5 py-4 text-[12.5px] leading-relaxed">
                            {hints.when_to_use && (
                              <Field
                                label={t("When to use")}
                                body={hints.when_to_use}
                              />
                            )}
                            {hints.input_format && (
                              <Field
                                label={t("Input format")}
                                body={hints.input_format}
                                mono
                              />
                            )}
                            {hints.guideline && (
                              <Field
                                label={t("Guideline")}
                                body={hints.guideline}
                              />
                            )}
                            {hints.note && (
                              <Field label={t("Note")} body={hints.note} />
                            )}
                            {tool.parameters.length > 0 && (
                              <div>
                                <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.14em] text-[var(--muted-foreground)]/80">
                                  {t("Parameters")}
                                </div>
                                <ul className="space-y-1.5">
                                  {tool.parameters.map((p) => (
                                    <li
                                      key={p.name}
                                      className="flex items-baseline gap-2"
                                    >
                                      <span className="font-mono text-[12px] text-[var(--foreground)]">
                                        {p.name}
                                      </span>
                                      <span className="text-[10.5px] text-[var(--muted-foreground)]/70">
                                        {p.type}
                                        {p.required
                                          ? ""
                                          : ` · ${t("optional")}`}
                                      </span>
                                      {p.description && (
                                        <span className="text-[12px] text-[var(--muted-foreground)]">
                                          — {p.description}
                                        </span>
                                      )}
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ToolToggle({
  checked,
  disabled,
  onChange,
  label,
}: {
  checked: boolean;
  disabled: boolean;
  onChange: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={onChange}
      className={`relative inline-flex h-[18px] w-[32px] shrink-0 items-center rounded-full border transition-colors ${
        checked
          ? "border-[var(--primary)] bg-[var(--primary)]/70"
          : "border-[var(--border)] bg-[var(--muted)]/50"
      } ${disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}
    >
      <span
        className={`inline-block h-[12px] w-[12px] transform rounded-full bg-white shadow transition-transform ${
          checked ? "translate-x-[16px]" : "translate-x-[2px]"
        }`}
      />
    </button>
  );
}

function Field({
  label,
  body,
  mono,
}: {
  label: string;
  body: string;
  mono?: boolean;
}) {
  return (
    <div>
      <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.14em] text-[var(--muted-foreground)]/80">
        {label}
      </div>
      <p
        className={`whitespace-pre-wrap text-[12.5px] leading-relaxed text-[var(--foreground)]/90 ${
          mono ? "font-mono" : ""
        }`}
      >
        {body}
      </p>
    </div>
  );
}
