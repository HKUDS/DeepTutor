"use client";

/**
 * Partner configuration panel: identity, soul, model, tool surface, and the
 * provisioned asset library (knowledge bases / skills / notebooks copied
 * into the partner workspace).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Plus, Save, Trash2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import PartnerModelSelect from "@/components/partners/PartnerModelSelect";
import { listLLMOptions, type LLMOption } from "@/lib/llm-options";
import type { LLMSelection } from "@/lib/unified-ws";
import {
  addPartnerAssets,
  getPartnerAssets,
  getPartnerSoul,
  getToolOptions,
  removePartnerAsset,
  savePartnerSoul,
  updatePartner,
  type PartnerAssets,
  type PartnerInfo,
  type ToolOptions,
} from "@/lib/partners-api";
import AssetPicker, {
  type AssetSelection,
} from "@/components/partners/AssetPicker";
import ToolPicker from "@/components/partners/ToolPicker";
import FaceEditor, { type FaceValue } from "@/components/partners/FaceEditor";
import SoulEditor from "@/components/partners/SoulEditor";

function Section({
  title,
  description,
  children,
  action,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-[var(--border)] p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-[13px] font-medium text-[var(--foreground)]">
            {title}
          </h3>
          {description && (
            <p className="mt-0.5 text-[11.5px] text-[var(--muted-foreground)]">
              {description}
            </p>
          )}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export default function PartnerConfigure({
  partner,
  onToast,
  onUpdated,
}: {
  partner: PartnerInfo;
  onToast: (msg: string) => void;
  onUpdated: () => void;
}) {
  const { t } = useTranslation();
  const partnerId = partner.partner_id;

  // Identity
  const [name, setName] = useState(partner.name);
  const [description, setDescription] = useState(partner.description ?? "");
  const [face, setFace] = useState<FaceValue>({
    emoji: partner.emoji ?? "",
    color: partner.color ?? "",
    avatar: partner.avatar ?? "",
  });
  const [language, setLanguage] = useState(partner.language ?? "");
  const [savingIdentity, setSavingIdentity] = useState(false);

  // Soul
  const [soul, setSoul] = useState("");
  const [soulLoaded, setSoulLoaded] = useState(false);
  const [savingSoul, setSavingSoul] = useState(false);

  // Model
  const [llmOptions, setLLMOptions] = useState<LLMOption[]>([]);
  const [activeLLMDefault, setActiveLLMDefault] = useState<LLMSelection | null>(
    null,
  );
  const [llmLoading, setLLMLoading] = useState(true);
  const [llmError, setLLMError] = useState(false);
  const [selection, setSelection] = useState<LLMSelection | null>(
    partner.llm_selection ?? null,
  );
  const [backupSelection, setBackupSelection] = useState<LLMSelection | null>(
    partner.backup_llm_selection ?? null,
  );

  // Tools
  const [toolOptions, setToolOptions] = useState<ToolOptions | null>(null);
  const [enabledTools, setEnabledTools] = useState<string[]>([]);
  const [builtinTools, setBuiltinTools] = useState<string[]>([]);
  const [mcpTools, setMcpTools] = useState<string[]>([]);
  const [savingTools, setSavingTools] = useState(false);

  // Assets
  const [assets, setAssets] = useState<PartnerAssets | null>(null);
  const [showAssetPicker, setShowAssetPicker] = useState(false);
  const [pendingAssets, setPendingAssets] = useState<AssetSelection>({
    knowledge_bases: [],
    skills: [],
    notebooks: [],
  });
  const [addingAssets, setAddingAssets] = useState(false);

  useEffect(() => {
    void getPartnerSoul(partnerId)
      .then((content) => {
        setSoul(content);
        setSoulLoaded(true);
      })
      .catch(() => setSoulLoaded(true));
    void getPartnerAssets(partnerId)
      .then(setAssets)
      .catch(() => {});
    void (async () => {
      try {
        const payload = await listLLMOptions();
        setLLMOptions(payload.options);
        setActiveLLMDefault(payload.active);
        setLLMError(false);
      } catch {
        setLLMError(true);
      } finally {
        setLLMLoading(false);
      }
    })();
    void getToolOptions()
      .then((options) => {
        setToolOptions(options);
        setEnabledTools(
          partner.enabled_tools ?? options.tools.map((tool) => tool.name),
        );
        setBuiltinTools(
          partner.builtin_tools ??
            options.builtin_tools.map((tool) => tool.name),
        );
        setMcpTools(
          partner.mcp_tools ?? options.mcp_tools.map((tool) => tool.name),
        );
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [partnerId]);

  const saveIdentity = async () => {
    setSavingIdentity(true);
    try {
      await updatePartner(partnerId, {
        name,
        description,
        emoji: face.emoji,
        color: face.color,
        avatar: face.avatar,
        language,
      });
      onToast(t("Saved"));
      onUpdated();
    } catch (e) {
      onToast(e instanceof Error ? e.message : t("Save failed"));
    } finally {
      setSavingIdentity(false);
    }
  };

  const saveSoul = async () => {
    setSavingSoul(true);
    try {
      await savePartnerSoul(partnerId, soul);
      onToast(t("Soul saved"));
    } catch (e) {
      onToast(e instanceof Error ? e.message : t("Save failed"));
    } finally {
      setSavingSoul(false);
    }
  };

  const saveModel = async (next: LLMSelection | null) => {
    setSelection(next);
    try {
      await updatePartner(partnerId, { llm_selection: next });
      onToast(t("Model updated — applies from the next message"));
      onUpdated();
    } catch (e) {
      onToast(e instanceof Error ? e.message : t("Save failed"));
    }
  };

  const saveBackupModel = async (next: LLMSelection | null) => {
    setBackupSelection(next);
    try {
      await updatePartner(partnerId, { backup_llm_selection: next });
      onToast(t("Model updated — applies from the next message"));
      onUpdated();
    } catch (e) {
      onToast(e instanceof Error ? e.message : t("Save failed"));
    }
  };

  const saveTools = async () => {
    setSavingTools(true);
    try {
      await updatePartner(partnerId, {
        enabled_tools: enabledTools,
        builtin_tools: builtinTools,
        mcp_tools: mcpTools,
      });
      onToast(t("Tools updated — applies from the next message"));
      onUpdated();
    } catch (e) {
      onToast(e instanceof Error ? e.message : t("Save failed"));
    } finally {
      setSavingTools(false);
    }
  };

  const submitAssets = async () => {
    setAddingAssets(true);
    try {
      const result = await addPartnerAssets(partnerId, pendingAssets);
      setAssets(result.assets);
      if (result.errors.length > 0) {
        onToast(
          t("Some items failed: {{names}}", {
            names: result.errors.map((e) => e.name).join(", "),
          }),
        );
      } else {
        onToast(t("Assets added"));
      }
      setPendingAssets({ knowledge_bases: [], skills: [], notebooks: [] });
      setShowAssetPicker(false);
    } catch (e) {
      onToast(e instanceof Error ? e.message : t("Save failed"));
    } finally {
      setAddingAssets(false);
    }
  };

  const removeAsset = useCallback(
    async (assetType: "knowledge_base" | "skill" | "notebook", id: string) => {
      try {
        const result = await removePartnerAsset(partnerId, assetType, id);
        setAssets(result.assets);
      } catch (e) {
        onToast(e instanceof Error ? e.message : t("Remove failed"));
      }
    },
    [partnerId, onToast, t],
  );

  const assetRows = useMemo(() => {
    if (!assets) return [];
    return [
      ...assets.knowledge_bases.map((kb) => ({
        type: "knowledge_base" as const,
        id: kb.name,
        label: kb.name,
        kind: t("Knowledge base"),
      })),
      ...assets.skills.map((skill) => ({
        type: "skill" as const,
        id: skill.name,
        label: skill.name,
        kind: t("Skill"),
      })),
      ...assets.notebooks.map((nb) => ({
        type: "notebook" as const,
        id: nb.id,
        label: nb.name || nb.id,
        kind: t("Notebook"),
      })),
    ];
  }, [assets, t]);

  const pendingCount =
    pendingAssets.knowledge_bases.length +
    pendingAssets.skills.length +
    pendingAssets.notebooks.length;

  return (
    <div className="space-y-4">
      <Section
        title={t("Identity")}
        action={
          <button
            type="button"
            onClick={() => void saveIdentity()}
            disabled={savingIdentity || !name.trim()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] disabled:opacity-40"
          >
            {savingIdentity ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
            {t("Save")}
          </button>
        }
      >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-[12px] font-medium">
              {t("Name")}
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-1.5 text-[13px] outline-none focus:border-[var(--ring)]"
            />
          </div>
          <div>
            <label className="mb-1 block text-[12px] font-medium">
              {t("Reply language")}
            </label>
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-1.5 text-[13px] outline-none focus:border-[var(--ring)]"
            >
              <option value="">{t("Auto (English)")}</option>
              <option value="en">English</option>
              <option value="zh">中文</option>
            </select>
          </div>
          <div className="sm:col-span-2">
            <label className="mb-1 block text-[12px] font-medium">
              {t("Description")}
            </label>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-transparent px-3 py-1.5 text-[13px] outline-none focus:border-[var(--ring)]"
            />
          </div>
          <div className="sm:col-span-2 mt-1">
            <span className="mb-2 block text-[12px] font-medium">
              {t("Face")}
            </span>
            <FaceEditor name={name} value={face} onChange={setFace} />
          </div>
        </div>
      </Section>

      <Section
        title={t("Soul")}
        description={t(
          "The partner's persona — injected into every conversation.",
        )}
        action={
          <button
            type="button"
            onClick={() => void saveSoul()}
            disabled={savingSoul || !soulLoaded}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] disabled:opacity-40"
          >
            {savingSoul ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
            {t("Save")}
          </button>
        }
      >
        <SoulEditor value={soul} onChange={setSoul} heightClass="h-[280px]" />
      </Section>

      <Section
        title={t("Model")}
        description={t(
          "The primary model answers every turn; if it fails outright, the turn is retried once on the backup.",
        )}
      >
        <div className="max-w-md space-y-3">
          <div>
            <label className="mb-1 block text-[12px] font-medium">
              {t("Primary model")}
            </label>
            <PartnerModelSelect
              options={llmOptions}
              activeDefault={activeLLMDefault}
              value={selection}
              loading={llmLoading}
              error={llmError}
              noneLabel={t("System default")}
              onChange={(next) => void saveModel(next)}
            />
          </div>
          <div>
            <label className="mb-1 block text-[12px] font-medium">
              {t("Backup model")}
            </label>
            <PartnerModelSelect
              options={llmOptions}
              activeDefault={activeLLMDefault}
              value={backupSelection}
              loading={llmLoading}
              error={llmError}
              noneLabel={t("No backup")}
              noneDetail={t("Failed turns are not retried.")}
              onChange={(next) => void saveBackupModel(next)}
            />
          </div>
        </div>
      </Section>

      <Section
        title={t("Tools")}
        description={t("What this partner is allowed to use.")}
        action={
          <button
            type="button"
            onClick={() => void saveTools()}
            disabled={savingTools || !toolOptions}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] disabled:opacity-40"
          >
            {savingTools ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
            {t("Save")}
          </button>
        }
      >
        <ToolPicker
          options={toolOptions}
          enabledTools={enabledTools}
          builtinTools={builtinTools}
          mcpTools={mcpTools}
          onChangeEnabledTools={setEnabledTools}
          onChangeBuiltinTools={setBuiltinTools}
          onChangeMcpTools={setMcpTools}
        />
      </Section>

      <Section
        title={t("Library")}
        description={t(
          "Knowledge bases, skills, and notebooks copied into this partner's workspace.",
        )}
        action={
          <button
            type="button"
            onClick={() => setShowAssetPicker((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-[12px] font-medium text-[var(--foreground)] hover:border-[var(--ring)]"
          >
            {showAssetPicker ? (
              <X className="h-3.5 w-3.5" />
            ) : (
              <Plus className="h-3.5 w-3.5" />
            )}
            {showAssetPicker ? t("Cancel") : t("Add")}
          </button>
        }
      >
        {showAssetPicker && (
          <div className="mb-4 rounded-xl border border-dashed border-[var(--border)] p-3.5">
            <AssetPicker
              value={pendingAssets}
              onChange={setPendingAssets}
              excluded={{
                knowledge_bases:
                  assets?.knowledge_bases.map((kb) => kb.name) ?? [],
                skills: assets?.skills.map((skill) => skill.name) ?? [],
                notebooks: assets?.notebooks.map((nb) => nb.id) ?? [],
              }}
            />
            <button
              type="button"
              onClick={() => void submitAssets()}
              disabled={addingAssets || pendingCount === 0}
              className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)] disabled:opacity-40"
            >
              {addingAssets ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Plus className="h-3.5 w-3.5" />
              )}
              {t("Copy into workspace")}
              {pendingCount > 0 ? ` (${pendingCount})` : ""}
            </button>
          </div>
        )}

        {assetRows.length === 0 ? (
          <p className="text-[12.5px] text-[var(--muted-foreground)]">
            {t(
              "Nothing assigned yet — this partner only knows what you tell it.",
            )}
          </p>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {assetRows.map((row) => (
              <li
                key={`${row.type}:${row.id}`}
                className="flex items-center justify-between py-1.5"
              >
                <span className="min-w-0 truncate text-[13px] text-[var(--foreground)]">
                  {row.label}
                  <span className="ml-2 text-[11px] text-[var(--muted-foreground)]">
                    {row.kind}
                  </span>
                </span>
                <button
                  type="button"
                  onClick={() => void removeAsset(row.type, row.id)}
                  className="rounded-md p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-red-500"
                  aria-label={t("Remove")}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
