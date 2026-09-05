"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Check, Loader2, MessageSquare } from "lucide-react";
import { useTranslation } from "react-i18next";
import { RouteDraftEditor } from "@/components/space/learning/RouteDraftEditor";
import { isRouteDraftValid } from "@/components/space/learning/route-draft";
import { createMasteryTopic, fetchLearningPlan, generateLearningPlanRouteDraft, saveLearningPlanRouteDraft, type LearningPlan, type TopicDraft } from "@/lib/learning-api";
import { useCourseScope } from "@/components/courses/CourseScope";
import { planningErrorMessage } from "@/lib/mastery-planning";
import { learningPlanRoute, shouldGenerateLearningPlanDraft } from "@/lib/mastery-planning-route";

export default function LearningPlanDraftPage() {
  const { t } = useTranslation(); const router = useRouter(); const searchParams = useSearchParams(); const scope = useCourseScope(); const { planId } = useParams<{ planId: string }>();
  const regenerate = searchParams.get("regenerate") === "1";
  const [plan, setPlan] = useState<LearningPlan | null>(null); const [draft, setDraft] = useState<TopicDraft | null>(null); const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  useEffect(() => { let active = true; void fetchLearningPlan(planId).then(async (next) => { if (!active) return; setPlan(next); if (next.draft && !shouldGenerateLearningPlanDraft(next.state, regenerate)) { setDraft(next.draft); return; } setBusy(true); try { setDraft(await generateLearningPlanRouteDraft(planId, { force: regenerate })); } catch (e) { setError(t(planningErrorMessage(e, "Could not generate the route draft.", t))); } finally { setBusy(false); } }).catch((e) => setError(t(planningErrorMessage(e, "Could not load planning workspace.", t)))).finally(() => active && setLoading(false)); return () => { active = false; }; }, [planId, regenerate, t]);
  const start = async () => { if (!plan || !draft || !isRouteDraftValid(draft) || busy) return; setBusy(true); try { const input = plan.brief || plan.input; const topic = await createMasteryTopic({ name: input.name, goal: input.goal, description: draft.description, sources: input.sources || [], modules: draft.modules }); await scope?.attach("mastery_path", topic.path_id, input.name.trim()); router.push(`/mastery/${encodeURIComponent(topic.path_id)}`); } catch (e) { setError(e instanceof Error ? e.message : t("Creation failed. Please retry.")); } finally { setBusy(false); } };
  const continuePlanning = async () => { if (!draft || busy) return; setBusy(true); setError(null); try { await saveLearningPlanRouteDraft(planId, draft); router.push(learningPlanRoute(planId, { courseId: scope?.id })); } catch (e) { setError(t(planningErrorMessage(e, "Could not save the route draft.", t))); } finally { setBusy(false); } };
  if (loading || busy && !draft) return <main className="mastery-shell flex h-full items-center justify-center"><div className="text-center"><Loader2 className="mx-auto h-6 w-6 animate-spin" /><p className="mt-3 text-sm text-[var(--muted-foreground)]">{t("Generating your learning route…")}</p></div></main>;
  if (!plan || !draft) return <main className="mastery-shell p-8"><p role="alert">{error || t("Could not generate the route draft.")}</p></main>;
  return <main className="mastery-shell min-h-full overflow-y-auto"><div className="mx-auto w-full max-w-[900px] px-4 py-8 sm:px-7"><h1 className="text-2xl font-semibold">{t("Your route draft")}</h1><p className="mt-2 text-sm text-[var(--muted-foreground)]">{t("Review and adjust the route before you start learning.")}</p><div className="mt-7"><RouteDraftEditor draft={draft} onChange={setDraft} moduleLimit={draft.module_limit} /></div>{error && <p role="alert" className="mt-4 text-sm text-red-600">{error}</p>}<div className="mt-8 flex flex-col gap-3 border-t border-[var(--border)] pt-6 sm:flex-row"><button type="button" onClick={() => void start()} disabled={busy || !isRouteDraftValid(draft)} className="inline-flex items-center justify-center gap-2 rounded-xl bg-[var(--primary)] px-5 py-3 text-sm font-medium text-[var(--primary-foreground)] disabled:opacity-50"><Check className="h-4 w-4" />{t("Start learning")}</button><button type="button" onClick={() => void continuePlanning()} disabled={busy} className="inline-flex items-center justify-center gap-2 rounded-xl border border-[var(--border)] px-5 py-3 text-sm font-medium"><MessageSquare className="h-4 w-4" />{t("Continue planning / continue modifying")}</button></div></div></main>;
}
