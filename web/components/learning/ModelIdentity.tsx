"use client";

import { Boxes, GraduationCap } from "lucide-react";
import type { EvaluatorSnapshot } from "@/lib/feynman-learning";
import { protocolLabel } from "./contract";
import { LongId } from "./LongId";
import type { TrFn } from "./locale";

/** Teaching model identity (session-scoped, may switch per session/turn). */
export interface TeachingModelInfo {
  provider: string;
  profile: string;
  model: string;
  protocol: string;
}

/**
 * Model and protocol transparency (§7.6, §9.4, §13.3).
 *
 * The teaching provider/model/protocol and the frozen evaluator identity are
 * shown in their approved locations. Only audit-safe fields are rendered —
 * a base-URL fingerprint, never the private URL or credentials.
 */
export function ModelIdentityBlock({
  teaching,
  evaluator,
  tr,
}: {
  teaching: TeachingModelInfo | null;
  evaluator: EvaluatorSnapshot | null;
  tr: TrFn;
}) {
  return (
    <div className="grid gap-2" data-testid="model-identity">
      <div className="fw-block fw-amber">
        <div className="flex items-center gap-2">
          <GraduationCap className="h-4 w-4 shrink-0 text-[var(--fw-amber)]" />
          <strong>{tr("教学模型", "Teaching model")}</strong>
        </div>
        {teaching ? (
          <div className="grid gap-1 pt-1 text-sm">
            <ModelLine
              tr={tr}
              label={tr("Provider", "Provider")}
              value={`${teaching.provider} / ${teaching.profile}`}
            />
            <ModelLine
              tr={tr}
              label={tr("Model", "Model")}
              value={teaching.model}
            />
            <div className="text-xs text-[var(--fw-muted)]">
              {tr("协议", "Protocol")}：{protocolLabel(teaching.protocol)}
              <span className="opacity-70">
                {tr(" · 会话内可切换", " · switchable per session")}
              </span>
            </div>
          </div>
        ) : (
          <div className="pt-1 text-sm text-[var(--fw-muted)]">
            {tr("会话教学模型", "Session teaching model")}
          </div>
        )}
      </div>

      <div className="fw-block fw-violet">
        <div className="flex items-center gap-2">
          <Boxes className="h-4 w-4 shrink-0 text-[var(--fw-violet)]" />
          <strong>{tr("评估模型（冻结）", "Evaluator (frozen)")}</strong>
        </div>
        {evaluator ? (
          <div className="grid gap-1 pt-1 text-sm">
            <ModelLine
              tr={tr}
              label={tr("Profile", "Profile")}
              value={evaluator.profile_name || evaluator.profile_id}
            />
            <ModelLine
              tr={tr}
              label={tr("Model", "Model")}
              value={evaluator.resolved_model || evaluator.requested_model}
            />
            <div className="text-xs text-[var(--fw-muted)]">
              {tr("协议", "Protocol")}：
              {protocolLabel(
                evaluator.resolved_api_protocol || evaluator.requested_api_protocol,
              )}
              {evaluator.base_url_fingerprint ? (
                <span>
                  {" · "}
                  {tr("URL", "URL")}
                  {": "}
                  <LongId value={evaluator.base_url_fingerprint} maxChars={10} tr={tr} />
                </span>
              ) : null}
            </div>
            {evaluator.rubric_version ? (
              <div className="text-xs text-[var(--fw-muted)]">
                {tr("Rubric", "Rubric")} v{evaluator.rubric_version}
                {evaluator.strict_protocol ? (
                  <span className="text-[var(--fw-coral)]">
                    {" · "}
                    {tr("严格协议", "strict protocol")}
                  </span>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : (
          <div className="pt-1 text-sm text-[var(--fw-muted)]">
            {tr("尚无评估快照", "No evaluator snapshot yet")}
          </div>
        )}
      </div>
    </div>
  );
}

function ModelLine({
  label,
  value,
  tr,
}: {
  label: string;
  value: string;
  tr: TrFn;
}) {
  if (!value) return null;
  return (
    <div className="flex items-start gap-2">
      <span className="shrink-0 text-xs text-[var(--fw-muted)]">{label}</span>
      <LongId value={value} tr={tr} />
    </div>
  );
}
