"use client";

/**
 * New-partner wizard: five full-page steps —
 * Identity → Soul → Mind (model + tools) → Library (assets) → Review.
 * One decision per screen; channels are connected after creation on the
 * partner's Channels tab.
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, ArrowRight, Check, Loader2, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  listLLMOptions,
  sameLLMSelection,
  type LLMOption,
} from "@/lib/llm-options";
import type { LLMSelection } from "@/lib/unified-ws";
import {
  createPartner,
  getToolOptions,
  type SoulSpec,
  type ToolOptions,
} from "@/lib/partners-api";
import AssetPicker, {
  type AssetSelection,
} from "@/components/partners/AssetPicker";
import PartnerAvatar from "@/components/partners/PartnerAvatar";
import FaceEditor, { type FaceValue } from "@/components/partners/FaceEditor";
import PartnerModelPicker from "@/components/partners/PartnerModelPicker";
import PartnerModelSelect from "@/components/partners/PartnerModelSelect";
import SoulPicker from "@/components/partners/SoulPicker";
import ToolPicker from "@/components/partners/ToolPicker";

type StepKey = "identity" | "soul" | "mind" | "library" | "review";

export default function NewPartnerPage() {
  const router = useRouter();
  const { t } = useTranslation();

  const steps: { key: StepKey; label: string }[] = [
    { key: "identity", label: t("Identity") },
    { key: "soul", label: t("Soul") },
    { key: "mind", label: t("Mind") },
    { key: "library", label: t("Library") },
    { key: "review", label: t("Review") },
  ];
  const [stepIndex, setStepIndex] = useState(0);
  const step = steps[stepIndex].key;

  // ── form state ────────────────────────────────────────────────
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [face, setFace] = useState<FaceValue>({
    emoji: "",
    color: "",
    avatar: "",
  });
  const [language, setLanguage] = useState("");
  const [soul, setSoul] = useState<SoulSpec>({ source: "default" });
  const [selection, setSelection] = useState<LLMSelection | null>(null);
  const [backupSelection, setBackupSelection] = useState<LLMSelection | null>(
    null,
  );
  const [assets, setAssets] = useState<AssetSelection>({
    knowledge_bases: [],
    skills: [],
    notebooks: [],
  });

  const [llmOptions, setLLMOptions] = useState<LLMOption[]>([]);
  const [activeLLMDefault, setActiveLLMDefault] = useState<LLMSelection | null>(
    null,
  );
  const [llmLoading, setLLMLoading] = useState(true);
  const [llmError, setLLMError] = useState(false);

  const [toolOptions, setToolOptions] = useState<ToolOptions | null>(null);
  const [enabledTools, setEnabledTools] = useState<string[]>([]);
  const [builtinTools, setBuiltinTools] = useState<string[]>([]);
  const [mcpTools, setMcpTools] = useState<string[]>([]);
  const [toolsTouched, setToolsTouched] = useState(false);

  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void (async () => {
      try {
        const payload = await listLLMOptions();
        setLLMOptions(payload.options);
        setActiveLLMDefault(payload.active);
      } catch {
        setLLMError(true);
      } finally {
        setLLMLoading(false);
      }
    })();
    void getToolOptions()
      .then((options) => {
        setToolOptions(options);
        setEnabledTools(options.tools.map((tool) => tool.name));
        setBuiltinTools(options.builtin_tools.map((tool) => tool.name));
        setMcpTools(options.mcp_tools.map((tool) => tool.name));
      })
      .catch(() => {});
  }, []);

  const canContinue = step !== "identity" || Boolean(name.trim());

  const goNext = () => {
    if (!canContinue) return;
    setStepIndex((index) => Math.min(index + 1, steps.length - 1));
  };
  const goBack = () => setStepIndex((index) => Math.max(index - 1, 0));

  const submit = async () => {
    if (!name.trim()) return;
    setCreating(true);
    setError("");
    try {
      const allTools = toolOptions?.tools.map((tool) => tool.name) ?? [];
      const allBuiltin =
        toolOptions?.builtin_tools.map((tool) => tool.name) ?? [];
      const allMcp = toolOptions?.mcp_tools.map((tool) => tool.name) ?? [];
      const result = await createPartner({
        name: name.trim(),
        description: description.trim() || undefined,
        soul,
        llm_selection: selection,
        backup_llm_selection: backupSelection,
        language: language || undefined,
        emoji: face.emoji || undefined,
        color: face.color || undefined,
        avatar: face.avatar || undefined,
        // Untouched = default-everything → persist as null so newly
        // configured tools are picked up automatically later.
        enabled_tools: toolsTouched
          ? enabledTools
          : enabledTools.length === allTools.length
            ? null
            : enabledTools,
        builtin_tools: toolsTouched
          ? builtinTools
          : builtinTools.length === allBuiltin.length
            ? null
            : builtinTools,
        mcp_tools: toolsTouched
          ? mcpTools
          : mcpTools.length === allMcp.length
            ? null
            : mcpTools,
        assets,
        start: true,
      });
      // Land in the chat tab — the partner is ready to talk to right away
      // (any provisioning misses are visible on the Configure tab's library).
      router.push(`/partners/${result.partner_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("Create failed"));
      setCreating(false);
    }
  };

  // ── review summary helpers ────────────────────────────────────
  const soulSummary = useMemo(() => {
    switch (soul.source) {
      case "library":
        return `${t("Soul library")} · ${soul.id ?? ""}`;
      case "persona":
        return `${t("Clone a persona")} · ${soul.id ?? ""}`;
      case "custom":
        return t("Write your own");
      default:
        return t("Default soul");
    }
  }, [soul, t]);

  const describeSelection = useMemo(
    () =>
      (candidate: LLMSelection | null, noneText: string): string => {
        if (!candidate) return noneText;
        const option = llmOptions.find((opt) =>
          sameLLMSelection(opt, candidate),
        );
        return option ? option.model_name || option.model : candidate.model_id;
      },
    [llmOptions],
  );
  const modelSummary = describeSelection(selection, t("System default"));
  const backupSummary = describeSelection(backupSelection, t("No backup"));

  const assetCount =
    assets.knowledge_bases.length +
    assets.skills.length +
    assets.notebooks.length;

  const stepTitle: Record<StepKey, { title: string; subtitle: string }> = {
    identity: {
      title: t("Who is this partner?"),
      subtitle: t("A name and a face — everything else can change later."),
    },
    soul: {
      title: t("Give it a soul"),
      subtitle: t(
        "Who this partner is. Start from a template, clone a chat persona, or write it yourself.",
      ),
    },
    mind: {
      title: t("Shape its mind"),
      subtitle: t("The model it thinks with and the tools it may use."),
    },
    library: {
      title: t("Hand over some knowledge"),
      subtitle: t(
        "Give it a slice of your knowledge — copied into the partner's own workspace.",
      ),
    },
    review: {
      title: t("Ready to meet {{name}}?", {
        name: name.trim() || t("your partner"),
      }),
      subtitle: t("Almost there — check the essentials before creating."),
    },
  };

  return (
    <div className="flex h-full flex-col">
      {/* Top bar: back link + step indicator */}
      <div className="flex items-center justify-between px-6 pt-5">
        <Link
          href="/partners"
          className="inline-flex items-center gap-1.5 text-[13px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
        >
          <ArrowLeft className="h-4 w-4" />
          {t("Partners")}
        </Link>
        <ol className="flex items-center gap-1.5">
          {steps.map(({ key, label }, index) => {
            const stateClass =
              index === stepIndex
                ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                : index < stepIndex
                  ? "border-[var(--primary)] text-[var(--primary)]"
                  : "border-[var(--border)] text-[var(--muted-foreground)]";
            return (
              <li key={key} className="flex items-center gap-1.5">
                {index > 0 && (
                  <span
                    className={`h-px w-5 transition-colors ${
                      index <= stepIndex
                        ? "bg-[var(--primary)]/40"
                        : "bg-[var(--border)]"
                    }`}
                  />
                )}
                <button
                  type="button"
                  disabled={index > stepIndex}
                  onClick={() => setStepIndex(index)}
                  className="group flex items-center gap-1.5 disabled:cursor-default"
                  aria-label={label}
                >
                  <span
                    className={`flex h-6 w-6 items-center justify-center rounded-full border text-[11px] font-semibold transition-all duration-200 group-enabled:group-hover:scale-105 ${stateClass}`}
                  >
                    {index < stepIndex ? (
                      <Check className="h-3.5 w-3.5" strokeWidth={3} />
                    ) : (
                      index + 1
                    )}
                  </span>
                  <span
                    className={`hidden text-[12.5px] transition-colors sm:block ${
                      index === stepIndex
                        ? "font-medium text-[var(--foreground)]"
                        : "text-[var(--muted-foreground)] group-enabled:group-hover:text-[var(--foreground)]"
                    }`}
                  >
                    {label}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
        <span className="w-16" />
      </div>

      {/* Step body */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div
          key={step}
          className="mx-auto w-full max-w-2xl px-6 pb-8 pt-10 animate-fade-in"
        >
          <header className="mb-7 flex items-start gap-4">
            {step === "identity" || step === "review" ? (
              <PartnerAvatar
                name={name || "?"}
                emoji={face.emoji}
                color={face.color}
                image={face.avatar}
                size={48}
              />
            ) : null}
            <div>
              <h1 className="text-[22px] font-semibold tracking-tight text-[var(--foreground)]">
                {stepTitle[step].title}
              </h1>
              <p className="mt-1 text-[13.5px] leading-relaxed text-[var(--muted-foreground)]">
                {stepTitle[step].subtitle}
              </p>
            </div>
          </header>

          {step === "identity" && (
            <div className="space-y-5">
              <div>
                <label className="mb-1.5 block text-[13px] font-medium">
                  {t("Name")}
                </label>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") goNext();
                  }}
                  placeholder={t("e.g. Ada")}
                  autoFocus
                  className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3.5 py-2.5 text-[14px] outline-none transition-colors focus:border-[var(--ring)]"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-[13px] font-medium">
                  {t("Description")}
                </label>
                <input
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder={t("What is this partner for?")}
                  className="w-full rounded-xl border border-[var(--border)] bg-transparent px-3.5 py-2.5 text-[14px] outline-none transition-colors focus:border-[var(--ring)]"
                />
              </div>
              <div>
                <label className="mb-2 block text-[13px] font-medium">
                  {t("Face")}
                </label>
                <FaceEditor name={name} value={face} onChange={setFace} />
              </div>
              <div>
                <label className="mb-1.5 block text-[13px] font-medium">
                  {t("Reply language")}
                </label>
                <select
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                  className="w-48 rounded-xl border border-[var(--border)] bg-transparent px-3 py-2 text-[14px] outline-none transition-colors focus:border-[var(--ring)]"
                >
                  <option value="">{t("Auto (English)")}</option>
                  <option value="en">English</option>
                  <option value="zh">中文</option>
                </select>
              </div>
            </div>
          )}

          {step === "soul" && <SoulPicker value={soul} onChange={setSoul} />}

          {step === "mind" && (
            <div className="space-y-6">
              <div>
                <h3 className="mb-2 text-[13px] font-medium text-[var(--muted-foreground)]">
                  {t("Primary model")}
                </h3>
                <PartnerModelPicker
                  options={llmOptions}
                  activeDefault={activeLLMDefault}
                  value={selection}
                  loading={llmLoading}
                  error={llmError}
                  onChange={setSelection}
                />
              </div>
              <div>
                <h3 className="mb-2 text-[13px] font-medium text-[var(--muted-foreground)]">
                  {t("Backup model")}
                </h3>
                <PartnerModelSelect
                  options={llmOptions}
                  activeDefault={activeLLMDefault}
                  value={backupSelection}
                  loading={llmLoading}
                  error={llmError}
                  noneLabel={t("No backup")}
                  noneDetail={t("Failed turns are not retried.")}
                  onChange={setBackupSelection}
                />
              </div>
              <ToolPicker
                options={toolOptions}
                enabledTools={enabledTools}
                builtinTools={builtinTools}
                mcpTools={mcpTools}
                onChangeEnabledTools={(next) => {
                  setToolsTouched(true);
                  setEnabledTools(next);
                }}
                onChangeBuiltinTools={(next) => {
                  setToolsTouched(true);
                  setBuiltinTools(next);
                }}
                onChangeMcpTools={(next) => {
                  setToolsTouched(true);
                  setMcpTools(next);
                }}
              />
            </div>
          )}

          {step === "library" && (
            <AssetPicker
              value={assets}
              onChange={setAssets}
              preselectAllSkills
            />
          )}

          {step === "review" && (
            <div className="space-y-3">
              <dl className="divide-y divide-[var(--border)] rounded-2xl border border-[var(--border)]">
                {[
                  [t("Name"), name.trim() || "—"],
                  [t("Description"), description.trim() || "—"],
                  [t("Soul"), soulSummary],
                  [t("Model"), modelSummary],
                  [t("Backup model"), backupSummary],
                  [
                    t("Tools"),
                    `${enabledTools.length} ${t("System tools")}${
                      mcpTools.length
                        ? ` · ${mcpTools.length} ${t("MCP tools")}`
                        : ""
                    }`,
                  ],
                  [
                    t("Library"),
                    assetCount > 0
                      ? t("{{count}} items will be copied", {
                          count: assetCount,
                        })
                      : t(
                          "Nothing assigned yet — this partner only knows what you tell it.",
                        ),
                  ],
                ].map(([label, valueText]) => (
                  <div
                    key={label}
                    className="flex items-baseline gap-4 px-4 py-3"
                  >
                    <dt className="w-24 shrink-0 text-[12.5px] text-[var(--muted-foreground)]">
                      {label}
                    </dt>
                    <dd className="min-w-0 truncate text-[13.5px] text-[var(--foreground)]">
                      {valueText}
                    </dd>
                  </div>
                ))}
              </dl>
              <p className="text-[12.5px] text-[var(--muted-foreground)]">
                {t(
                  "You can connect Feishu, Telegram, Slack and more right after creating.",
                )}
              </p>
              {error && (
                <p className="rounded-lg border border-[var(--destructive)] bg-[var(--secondary)] px-3 py-2 text-[13px] text-[var(--destructive)]">
                  {error}
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Footer actions */}
      <div className="border-t border-[var(--border)] px-6 py-3.5">
        <div className="mx-auto flex w-full max-w-2xl items-center justify-between">
          <button
            type="button"
            onClick={goBack}
            disabled={stepIndex === 0}
            className="inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-[13.5px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] disabled:invisible"
          >
            <ArrowLeft className="h-4 w-4" />
            {t("Back")}
          </button>
          {step === "review" ? (
            <button
              type="button"
              onClick={() => void submit()}
              disabled={creating || !name.trim()}
              className="inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-5 py-2.5 text-[13.5px] font-medium text-[var(--primary-foreground)] shadow-sm transition-all duration-150 hover:opacity-90 active:scale-[0.98] disabled:opacity-40"
            >
              {creating ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )}
              {t("Create partner")}
            </button>
          ) : (
            <button
              type="button"
              onClick={goNext}
              disabled={!canContinue}
              className="inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-5 py-2.5 text-[13.5px] font-medium text-[var(--primary-foreground)] shadow-sm transition-all duration-150 hover:opacity-90 active:scale-[0.98] disabled:opacity-40"
            >
              {t("Continue")}
              <ArrowRight className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
