"use client";

import { useEffect, useMemo, useState } from "react";
import {
  BookOpen,
  CheckCircle2,
  FileText,
  ImageIcon,
  Lock,
  RefreshCw,
  Save,
  Send,
  ShieldAlert,
  Trash2,
  X,
} from "lucide-react";
import type { MediaArtifact } from "@/lib/media-types";
import type { KnowledgeCardView } from "@/lib/knowledge-card-api";
import { cardActions, failureAssurance, generationSurface, type KbOption } from "./knowledgeCard";
import { LongId } from "./LongId";
import { SectionHead } from "./ui";
import type { TrFn } from "./locale";

function kbReasonLabel(reason: string, tr: TrFn): string {
  switch (reason) {
    case "connected":
      return tr("Connected · 只读", "Connected · read-only");
    case "assigned":
      return tr("已分配 · 只读", "Assigned · read-only");
    case "read_only":
      return tr("只读", "Read-only");
    case "unavailable":
      return tr("不可用", "Unavailable");
    case "error":
      return tr("错误", "Error");
    case "indexing":
      return tr("索引中", "Indexing");
    case "needs_reindex":
      return tr("需要重建索引", "Needs reindex");
    default:
      return tr("不可写入", "Not writable");
  }
}

function generationCopy(surface: string, tr: TrFn): string {
  switch (surface) {
    case "queued":
      return tr("正文生成排队中…", "Body generation queued…");
    case "running":
      return tr("正文生成中…", "Body generation running…");
    case "unknown":
      return tr("无法确认生成结果，不会自动重试。", "Generation result unconfirmed — no automatic retry.");
    case "failed":
      return tr("正文生成失败，草稿已保留。", "Body generation failed — draft retained.");
    case "superseded_by_edit":
      return tr("模型结果已被手动编辑取代，不再覆盖正文。", "Model result superseded by your edit — it will not overwrite this body.");
    default:
      return "";
  }
}

export interface KnowledgeCardFormProps {
  card: KnowledgeCardView;
  kbs: KbOption[];
  artifacts: MediaArtifact[];
  busy: Record<string, boolean>;
  tr: TrFn;
  onSaveDraft: (
    cardId: string,
    changes: { title: string; body: string; attach_artifact_ids: string[]; detach_artifact_ids: string[] },
  ) => void;
  onRetryGeneration: (cardId: string) => void;
  onPublish: (cardId: string, targetKbName: string) => void;
  onRetryPublish: (cardId: string) => void;
  onReconcilePublication: (cardId: string) => void;
  onRetract: (cardId: string) => void;
  onReconcileRetraction: (cardId: string) => void;
  onDiscard: (cardId: string) => void;
}

/**
 * Shared card editor form content (desktop center editor and mobile full-screen
 * editor). Title/body editing is limited to ``draft``; every other approved
 * state renders the appropriate status, recovery path and explicit actions.
 */
export function KnowledgeCardForm({
  card,
  kbs,
  artifacts,
  busy,
  tr,
  onSaveDraft,
  onRetryGeneration,
  onPublish,
  onRetryPublish,
  onReconcilePublication,
  onRetract,
  onReconcileRetraction,
  onDiscard,
}: KnowledgeCardFormProps) {
  const actions = cardActions(card);
  const generation = generationSurface(card);
  const editable = actions.canEdit;

  const [title, setTitle] = useState(card.title || "");
  const [body, setBody] = useState(card.body || "");
  const [selectedKb, setSelectedKb] = useState<string>(() => {
    if (card.target_kb_name) return card.target_kb_name;
    return kbs.find((k) => k.writable)?.name ?? "";
  });
  const [attach, setAttach] = useState<ReadonlySet<string>>(new Set());
  const [detach, setDetach] = useState<ReadonlySet<string>>(new Set());

  useEffect(() => {
    setTitle(card.title || "");
    setBody(card.body || "");
    setAttach(new Set());
    setDetach(new Set());
    setSelectedKb(card.target_kb_name ?? kbs.find((k) => k.writable)?.name ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [card.card_id]);

  const writableKbs = useMemo(() => kbs.filter((k) => k.writable), [kbs]);
  const selectedWritable = writableKbs.some((k) => k.name === selectedKb);
  const attached = card.artifacts.filter((a) => !detach.has(a.id));
  const available = useMemo(
    () => artifacts.filter((a) => !card.artifact_ids.includes(a.id) && !attach.has(a.id)),
    [artifacts, card.artifact_ids, attach],
  );

  const dirty =
    title !== (card.title || "") || body !== (card.body || "") || attach.size > 0 || detach.size > 0;

  const handleSaveDraft = () => {
    onSaveDraft(card.card_id, {
      title,
      body,
      attach_artifact_ids: [...attach],
      detach_artifact_ids: [...detach],
    });
    setAttach(new Set());
    setDetach(new Set());
  };

  const toggleAttach = (artifactId: string) => {
    const next = new Set(attach);
    if (next.has(artifactId)) next.delete(artifactId);
    else next.add(artifactId);
    setAttach(next);
  };

  const toggleDetach = (artifactId: string) => {
    const next = new Set(detach);
    if (next.has(artifactId)) next.delete(artifactId);
    else next.add(artifactId);
    setAttach((prev) => {
      const p = new Set(prev);
      p.delete(artifactId);
      return p;
    });
    setDetach(next);
  };

  const assurance = failureAssurance(card);

  return (
    <>
      <div className="fw-panel-scroll fw-kc-editor-scroll">
        {/* Title */}
        <div className="fw-kc-field">
          <label className="fw-kc-field-label" htmlFor="kc-title">
            {tr("标题", "Title")}
          </label>
          {editable ? (
            <input
              id="kc-title"
              className="fw-kc-input"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              data-testid="kc-title-input"
            />
          ) : (
            <div className="fw-kc-readonly" data-testid="kc-title-readonly">
              {title || tr("（无标题）", "(no title)")}
            </div>
          )}
        </div>

        {/* Body */}
        <div className="fw-kc-field">
          <span className="fw-kc-field-label">{tr("正文", "Body")}</span>
          {editable ? (
            <textarea
              className="fw-kc-textarea"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              rows={8}
              data-testid="kc-body-input"
            />
          ) : (
            <div className="fw-kc-readonly fw-kc-readonly-body" data-testid="kc-body-readonly">
              {body || tr("（无正文）", "(no body)")}
            </div>
          )}
        </div>

        {/* Generation status (draft only) */}
        {card.status === "draft" && generation !== "ready" && generation !== "none" ? (
          <div
            className={`fw-kc-note ${generation === "failed" || generation === "unknown" ? "coral" : "amber"}`}
            data-testid="generation-status"
          >
            <span>{generationCopy(generation, tr)}</span>
            {actions.canRetryGeneration ? (
              <button
                type="button"
                className="fw-ghost-button"
                onClick={() => onRetryGeneration(card.card_id)}
                disabled={Boolean(busy[`retry:${card.card_id}`])}
                data-testid="retry-generation"
              >
                <RefreshCw className="h-3.5 w-3.5" />
                {tr("重试生成", "Retry generation")}
              </button>
            ) : null}
          </div>
        ) : null}

        {/* Stale evidence gate */}
        {card.status === "stale_evidence" ? (
          <div className="fw-kc-note coral" data-testid="editor-stale-note">
            <ShieldAlert className="h-3.5 w-3.5 shrink-0" />
            <span>
              {tr(
                "需要新的稳定掌握证据：生成、编辑和发布已禁用，只能查看或丢弃。",
                "New stable evidence required: generation, editing and publishing are disabled — view or discard only.",
              )}
            </span>
          </div>
        ) : null}

        {/* Sources (immutable provenance) */}
        <div className="fw-kc-field">
          <SectionHead
            label={tr("来源引用", "Source references")}
            trailing={<span className="text-xs text-[var(--fw-violet)]">{tr("不可变", "immutable")}</span>}
          />
          <div className="fw-kc-source-list">
            {card.sources.length === 0 ? (
              <span className="text-sm text-[var(--fw-muted)]">
                {tr("尚无来源引用", "No source references yet")}
              </span>
            ) : (
              card.sources.map((s) => (
                <div key={s.id} className="fw-kc-source-row">
                  <BookOpen className="h-3.5 w-3.5 shrink-0 text-[var(--fw-violet)]" />
                  <div className="min-w-0">
                    <strong className="block text-sm">{s.title}</strong>
                    <span className="text-xs text-[var(--fw-muted)]">
                      {s.locator || s.id}
                      {s.anchors.length ? ` · ${s.anchors.join("、")}` : ""}
                    </span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Image references */}
        <div className="fw-kc-field">
          <SectionHead
            label={
              <span className="flex items-center gap-1.5">
                <ImageIcon className="h-3.5 w-3.5 text-[var(--fw-violet)]" />
                {tr("生成图片引用", "Generated image references")}
                <span className="text-[var(--fw-muted)]">{tr("可选", "optional")}</span>
              </span>
            }
          />
          <div className="fw-kc-artifact-list" data-testid="card-artifacts">
            {attached.length === 0 ? (
              <span className="text-sm text-[var(--fw-muted)]">
                {tr("未附加图片", "No images attached")}
              </span>
            ) : (
              attached.map((a) => (
                <div key={a.id} className="fw-kc-artifact-row">
                  {a.available && a.preview_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={a.preview_url}
                      alt=""
                      className="fw-kc-artifact-thumb"
                      loading="lazy"
                    />
                  ) : (
                    <span className="fw-kc-artifact-thumb fw-kc-artifact-missing" aria-hidden="true">
                      <ImageIcon className="h-4 w-4" />
                    </span>
                  )}
                  <div className="min-w-0">
                    <strong className="block text-sm break-all">{a.id.slice(0, 24)}…</strong>
                    {a.available ? (
                      <span className="text-xs text-[var(--fw-muted)]">
                        {a.mime_type || tr("图片", "image")}
                        {a.width && a.height ? ` · ${a.width}×${a.height}` : ""}
                      </span>
                    ) : (
                      <span className="text-xs text-[var(--fw-coral)]">
                        {tr("文件已不可用", "artifact unavailable")}
                      </span>
                    )}
                  </div>
                  {editable ? (
                    <button
                      type="button"
                      className="fw-icon-button h-7 w-7"
                      aria-label={tr("移除图片", "Remove image")}
                      onClick={() => toggleDetach(a.id)}
                      data-testid={`detach-artifact-${a.id}`}
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  ) : null}
                </div>
              ))
            )}
          </div>
          {editable && available.length > 0 ? (
            <div className="fw-kc-attach-list" data-testid="available-artifacts">
              <span className="text-xs text-[var(--fw-muted)]">
                {tr("从已生成图片中选择", "Choose from your generated images")}
              </span>
              {available.slice(0, 8).map((a) => (
                <div key={a.id} className="fw-kc-attach-row">
                  <span className="min-w-0 truncate text-sm">{a.id.slice(0, 20)}…</span>
                  <button
                    type="button"
                    className="fw-ghost-button h-7 px-2"
                    onClick={() => toggleAttach(a.id)}
                    data-testid={`attach-artifact-${a.id}`}
                  >
                    <span aria-hidden="true">+</span>
                    {tr("添加", "Add")}
                  </button>
                </div>
              ))}
            </div>
          ) : null}
        </div>

        {/* Target KB selector */}
        {card.status === "draft" || card.status === "publish_failed" ? (
          <div className="fw-kc-field">
            <SectionHead
              label={
                <span className="flex items-center gap-1.5">
                  <FileText className="h-3.5 w-3.5 text-[var(--fw-blue)]" />
                  {tr("目标知识库", "Target knowledge base")}
                </span>
              }
            />
            <div className="fw-kb-options" role="radiogroup" aria-label={tr("目标知识库", "Target knowledge base")}>
              {kbs.length === 0 || !writableKbs.length ? (
                <div className="fw-kc-note amber" data-testid="no-writable-kb">
                  <span className="min-w-0">
                    {tr(
                      "还没有可写入的知识库：可以先保存草稿，然后到",
                      "No writable knowledge base yet: save the draft, then go to",
                    )}{" "}
                    <a href="/knowledge" className="fw-kc-link" data-testid="go-to-kb-area">
                      {tr("知识库界面", "the Knowledge area")}
                    </a>{" "}
                    {tr("创建或修复。", "to create or fix one.")}
                  </span>
                </div>
              ) : (
                kbs.map((kb) => (
                  <div
                    key={kb.name}
                    className={`fw-kb-option${kb.writable ? "" : " disabled"}`}
                    role="radio"
                    aria-checked={selectedKb === kb.name}
                    aria-disabled={!kb.writable}
                    data-testid={`kb-option-${kb.name}`}
                  >
                    <label className="fw-kb-option-label">
                      <input
                        type="radio"
                        name="target-kb"
                        checked={selectedKb === kb.name}
                        disabled={!kb.writable}
                        onChange={() => setSelectedKb(kb.name)}
                      />
                      <span className="min-w-0">
                        <strong className="block text-sm break-all">{kb.name}</strong>
                        <small className="text-xs text-[var(--fw-muted)]">
                          {kb.writable
                            ? tr("本地 Indexed · 可写入", "Local indexed · writable")
                            : kbReasonLabel(kb.disableReason ?? "read_only", tr)}
                        </small>
                      </span>
                    </label>
                    {!kb.writable ? (
                      <Lock className="h-3.5 w-3.5 shrink-0 text-[var(--fw-muted)]" aria-hidden="true" />
                    ) : null}
                  </div>
                ))
              )}
            </div>
            {!selectedWritable && card.status === "draft" ? (
              <span className="text-xs text-[var(--fw-coral)]">
                {tr("需要一个可写入的本地知识库才能发布。", "A writable local knowledge base is required to publish.")}
              </span>
            ) : null}
          </div>
        ) : null}

        {/* Published provenance */}
        {card.status === "published" ? (
          <div className="fw-block fw-blue fw-kc-provenance" data-testid="published-provenance">
            <strong>{tr("已发布文档", "Published document")}</strong>
            <div className="text-sm">{tr("目标 KB", "Target KB")}: {card.target_kb_name ?? "—"}</div>
            <div className="text-sm">
              {tr("相对路径", "Path")}: <LongId value={card.document_rel_path ?? ""} maxChars={22} tr={tr} />
            </div>
            <div className="text-xs text-[var(--fw-muted)]">
              {tr("SHA-256", "SHA-256")}: <LongId value={card.document_sha256 ?? ""} maxChars={14} tr={tr} />
            </div>
          </div>
        ) : null}

        {/* Model identity */}
        {card.model_identity ? (
          <div className="fw-block fw-violet" data-testid="card-model-identity">
            <strong>{tr("生成模型（冻结）", "Generation model (frozen)")}</strong>
            <div className="text-sm">{tr("Provider", "Provider")}: {card.model_identity.provider || "—"}</div>
            <div className="text-sm">
              {tr("Model", "Model")}: <LongId value={card.model_identity.model || "—"} tr={tr} />
            </div>
            <div className="text-xs text-[var(--fw-muted)]">
              {tr("协议", "Protocol")}: {card.model_identity.protocol || "auto"}
              {card.model_identity.strict_protocol ? (
                <span className="text-[var(--fw-coral)]"> · {tr("严格协议", "strict protocol")}</span>
              ) : null}
            </div>
          </div>
        ) : null}

        {/* Failure / recovery states */}
        {assurance?.kind === "publish_failed" ? (
          <div className="fw-kc-note coral" data-testid="editor-publish-failed">
            <div className="min-w-0">
              <strong>{tr("发布失败 · 草稿已保留", "Publish failed · draft retained")}</strong>
              <p className="text-sm">
                {tr(
                  "重试沿用同一发布键和文档路径，不会创建重复知识库文档；稳定掌握不受影响。",
                  "Retry reuses the same publication key and path — no duplicate KB document; stable mastery is unaffected.",
                )}
              </p>
              {card.sanitized_error ? (
                <p className="text-xs text-[var(--fw-muted)]">{(card.sanitized_error ?? "").slice(0, 300)}</p>
              ) : null}
            </div>
            <button
              type="button"
              className="fw-ghost-button"
              onClick={() => onRetryPublish(card.card_id)}
              disabled={Boolean(busy[`retry-publish:${card.card_id}`])}
              data-testid="retry-publish"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              {tr("重试发布", "Retry publish")}
            </button>
          </div>
        ) : null}

        {card.status === "reconcile_required" ? (
          <div className="fw-kc-note amber" data-testid="reconcile-publication-note">
            <div className="min-w-0">
              <strong>{tr("发布结果无法确认", "Publication outcome unconfirmed")}</strong>
              <p className="text-sm">
                {tr(
                  "只核对固定路径、哈希与既有索引任务；核对确认失败后才可重试。",
                  "Reconcile checks the fixed path, hash and existing index task; retry is only allowed after reconcile proves the submission failed.",
                )}
              </p>
            </div>
            <button
              type="button"
              className="fw-ghost-button"
              onClick={() => onReconcilePublication(card.card_id)}
              disabled={Boolean(busy[`reconcile-pub:${card.card_id}`])}
              data-testid="reconcile-publication"
            >
              <CheckCircle2 className="h-3.5 w-3.5" />
              {tr("修复并核对", "Reconcile")}
            </button>
          </div>
        ) : null}

        {card.status === "retract_reconcile_required" ? (
          <div className="fw-kc-note amber" data-testid="reconcile-retraction-note">
            <div className="min-w-0">
              <strong>{tr("撤回结果无法确认", "Retraction outcome unconfirmed")}</strong>
              <p className="text-sm">
                {tr(
                  "只依据固定路径、哈希与既有索引任务完成恢复或撤回，不创建第二份文档。",
                  "Reconcile resolves to published or retracted using fixed paths, hashes and the existing index task — never a second document.",
                )}
              </p>
            </div>
            <button
              type="button"
              className="fw-ghost-button"
              onClick={() => onReconcileRetraction(card.card_id)}
              disabled={Boolean(busy[`reconcile-retract:${card.card_id}`])}
              data-testid="reconcile-retraction"
            >
              <CheckCircle2 className="h-3.5 w-3.5" />
              {tr("修复并核对", "Reconcile")}
            </button>
          </div>
        ) : null}

        {card.status === "retracting" ? (
          <div className="fw-kc-note amber" data-testid="retracting-note">
            <span>
              {tr(
                "正在从知识库撤回：在新索引确认前不会显示“已撤回”。",
                "Retracting from the knowledge base — not shown as retracted until the new index is confirmed.",
              )}
            </span>
          </div>
        ) : null}
      </div>

      {/* Footer */}
      <footer className="fw-kc-editor-footer">
        <small className="text-xs text-[var(--fw-muted)]">
          {tr("不会自动发布。发布与评分、掌握状态完全正交。", "Nothing is auto-published. Publishing is fully orthogonal to scores and mastery.")}
        </small>
        <div className="fw-kc-actions">
          {editable ? (
            <button
              type="button"
              className="fw-ghost-button"
              onClick={handleSaveDraft}
              disabled={!dirty || Boolean(busy[`edit:${card.card_id}`])}
              data-testid="save-draft"
            >
              <Save className="h-3.5 w-3.5" />
              {tr("保存草稿", "Save draft")}
            </button>
          ) : null}
          {card.status === "draft" ? (
            <button
              type="button"
              className="fw-primary-button"
              onClick={() => onPublish(card.card_id, selectedKb)}
              disabled={!selectedWritable || Boolean(busy[`publish:${card.card_id}`])}
              data-testid="publish-card"
            >
              <Send className="h-3.5 w-3.5" />
              {tr("发布", "Publish")}
            </button>
          ) : null}
          {card.status === "publish_failed" ? (
            <button
              type="button"
              className="fw-primary-button"
              onClick={() => onRetryPublish(card.card_id)}
              disabled={Boolean(busy[`retry-publish:${card.card_id}`])}
              data-testid="retry-publish-footer"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              {tr("重试发布", "Retry publish")}
            </button>
          ) : null}
          {card.status === "published" ? (
            <button
              type="button"
              className="fw-primary-button fw-danger-button"
              onClick={() => onRetract(card.card_id)}
              disabled={Boolean(busy[`retract:${card.card_id}`])}
              data-testid="retract-card"
            >
              {tr("撤回", "Retract")}
            </button>
          ) : null}
          {actions.canDiscard ? (
            <button
              type="button"
              className="fw-ghost-button fw-danger"
              onClick={() => onDiscard(card.card_id)}
              disabled={Boolean(busy[`discard:${card.card_id}`])}
              data-testid="discard-from-editor"
            >
              <Trash2 className="h-3.5 w-3.5" />
              {tr("丢弃", "Discard")}
            </button>
          ) : null}
        </div>
      </footer>
    </>
  );
}
