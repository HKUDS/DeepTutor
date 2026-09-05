"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { ArrowLeft, ArrowRight, Check, Loader2, Sparkles } from "lucide-react";

import { useCourseScope } from "@/components/courses/CourseScope";
import { CoverageNotice } from "@/components/space/learning/CoverageNotice";
import { RouteDraftEditor } from "@/components/space/learning/RouteDraftEditor";
import { SourcesStep } from "@/components/space/learning/TopicWizardSteps";
import { hydrateTopicSource, toggleSourceSelection, useTopicSourceLibrary } from "@/hooks/useTopicSourceLibrary";
import { createLearningPlan, createMasteryTopic, generateMasteryTopicDraftCompatible, type MasteryTopic, type StructuredTopicDraftInput, type TopicDraft, type TopicSourceInput } from "@/lib/learning-api";
import { isRouteDraftValid } from "@/components/space/learning/route-draft";
import { buildStructuredTopicDraftInput, structuredPlanIssues, type MasteryPathFormValues } from "@/lib/mastery-path-form";
import { learningPlanRoute } from "@/lib/mastery-planning-route";
import { useAppShell } from "@/context/AppShellContext";

const ACTIVITY_LABELS = {
  reading: "Reading",
  practice: "Practice",
  projects: "Projects",
  discussion: "Discussion",
  assessment: "Assessment",
} as const;

export default function NewMasteryPathPage() {
  const { t } = useTranslation();
  const router = useRouter();
  const scope = useCourseScope();
  const { experimentalMasteryPlanning, experimentalMasteryPlanningReady } = useAppShell();
  const [step, setStep] = useState(1);
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");
  const [background, setBackground] = useState("");
  const [level, setLevel] = useState<string | null>(null);
  const [knownTopics, setKnownTopics] = useState("");
  const [skippedTopics, setSkippedTopics] = useState("");
  const [learningPurpose, setLearningPurpose] = useState<string | null>(null);
  const [customPurpose, setCustomPurpose] = useState("");
  const [scopeMode, setScopeMode] = useState<string | null>(null);
  const [scopeInclude, setScopeInclude] = useState("");
  const [scopeExclude, setScopeExclude] = useState("");
  const [approach, setApproach] = useState<string | null>(null);
  const [granularity, setGranularity] = useState<string | null>(null);
  const [rigor, setRigor] = useState<string | null>(null);
  const [activities, setActivities] = useState<string[]>([]);
  const [timeMode, setTimeMode] = useState<string | null>(null);
  const [weeklyHours, setWeeklyHours] = useState<string>("");
  const [durationWeeks, setDurationWeeks] = useState<string>("");
  const [deadline, setDeadline] = useState("");
  const [sessionMinutes, setSessionMinutes] = useState<string>("");
  const [milestonePreference, setMilestonePreference] = useState<string | null>(null);
  const [milestones, setMilestones] = useState<Array<{ name: string; description: string; target_week: string }>>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const { library, loading, candidates, files, loadKnowledgeBaseFiles } = useTopicSourceLibrary(t);
  const [draft, setDraft] = useState<TopicDraft | null>(null);
  const [sources, setSources] = useState<TopicSourceInput[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (experimentalMasteryPlanningReady && !experimentalMasteryPlanning) {
      router.replace("/mastery");
    }
  }, [experimentalMasteryPlanning, experimentalMasteryPlanningReady, router]);
  if (experimentalMasteryPlanningReady && !experimentalMasteryPlanning) return null;

  const toggle = (key: string) => setSelected((s) => toggleSourceSelection(s, key, candidates));
  const formValues = (): MasteryPathFormValues => ({ name, goal, learningPurpose, customPurpose, level, knownTopics, skippedTopics, scopeMode, scopeInclude, scopeExclude, approach, granularity, rigor, activities, timeMode, weeklyHours, durationWeeks, deadline, sessionMinutes, milestonePreference, milestones });
  const buildPlanInput = async (): Promise<StructuredTopicDraftInput> => {
    const hydrated = sources.length ? sources : await Promise.all(candidates.filter((c) => selected.has(c.key)).map(hydrateTopicSource));
    return buildStructuredTopicDraftInput(formValues(), hydrated);
  };
  const generate = async (must_cover: string[] = []) => {
    const values = formValues();
    if (structuredPlanIssues(values).length) { setError(t("Please complete the required fields for your selected options.")); return; }
    setBusy(true); setError(null);
    try {
      const hydrated = await Promise.all(candidates.filter((c) => selected.has(c.key)).map(hydrateTopicSource));
      const payload: StructuredTopicDraftInput = buildStructuredTopicDraftInput(values, hydrated, must_cover);
      const result = await generateMasteryTopicDraftCompatible(payload);
      setSources(result.sources ?? hydrated); setDraft(result); setStep(4);
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("Could not generate the outline. Please retry.")); }
    finally { setBusy(false); }
  };
  const discuss = async () => {
    const values = formValues();
    if (structuredPlanIssues(values).length) { setError(t("Please complete the required fields for your selected options.")); return; }
    setBusy(true); setError(null);
    try {
      const plan = await createLearningPlan(await buildPlanInput());
      router.push(learningPlanRoute(plan.plan_id, { courseId: scope?.id }));
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("Could not start planning discussion. Please retry.")); }
    finally { setBusy(false); }
  };
  const create = async () => {
    if (!draft || !isRouteDraftValid(draft)) return;
    setBusy(true); setError(null);
    try {
      const topic: MasteryTopic = await createMasteryTopic({ name: name.trim(), goal: goal.trim(), description: draft.description.trim(), sources, modules: draft.modules });
      await scope?.attach("mastery_path", topic.path_id, name.trim());
      router.push(`/mastery/${encodeURIComponent(topic.path_id)}`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("Creation failed. Please retry.")); }
    finally { setBusy(false); }
  };
  const inputClass = "mt-2 w-full rounded-lg border border-[var(--input)] bg-[var(--background)] px-3.5 py-2.5 text-sm outline-none focus:border-[var(--ring)] focus:ring-2 focus:ring-[var(--ring)]/15";
  return <main className="mastery-shell h-full overflow-y-auto"><div className="mx-auto max-w-4xl px-5 py-8 sm:px-8 lg:py-10">
    <header className="mb-8"><button type="button" onClick={() => router.push("/mastery")} className="mb-4 inline-flex items-center gap-2 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)]"><ArrowLeft className="h-4 w-4" />{t("Back to topics")}</button><div className="flex items-center gap-2 text-xs font-medium text-[var(--primary)]"><Sparkles className="h-3.5 w-3.5" />{t("New topic")}</div><h1 className="mt-1 font-serif text-2xl font-semibold">{t("Chart a learning path")}</h1></header>
    <ol className="mb-8 grid grid-cols-4 gap-2" aria-label={t("Creation steps")}>{[t("Topic & sources"), t("Goal & background"), t("Study plan"), t("Review")].map((label, i) => <li key={label} className={`rounded-lg border px-3 py-2 text-xs ${step === i + 1 ? "border-[var(--primary)] bg-[var(--primary)]/8 text-[var(--foreground)]" : "border-[var(--border)] text-[var(--muted-foreground)]"}`}>{i + 1}. {label}</li>)}</ol>
    <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-5 sm:p-7">
      {step === 1 && <><h2 className="text-lg font-semibold">{t("Choose a topic and materials")}</h2><label className="mt-5 block text-xs font-medium">{t("Topic name")}<input autoFocus value={name} onChange={(e) => setName(e.target.value)} maxLength={120} placeholder={t("e.g. Linear algebra")} className={inputClass} required /></label><div className="mt-7"><SourcesStep library={library} loading={loading} selected={selected} onToggle={toggle} files={files} onExpand={loadKnowledgeBaseFiles} /></div></>}
      {step === 2 && <><h2 className="text-lg font-semibold">{t("Set your learning goal")}</h2><label className="mt-5 block text-xs font-medium">{t("Topic purpose")}<textarea value={goal} onChange={(e) => setGoal(e.target.value)} rows={5} maxLength={2000} className={inputClass} placeholder={t("What would you like to be able to do?")} required /></label><label className="mt-5 block text-xs font-medium">{t("Learning purpose (optional)")}<select value={learningPurpose ?? ""} onChange={(e) => setLearningPurpose(e.target.value || null)} className={inputClass}><option value="">{t("Not specified")}</option><option value="exam">{t("Exam")}</option><option value="course">{t("Course")}</option><option value="work">{t("Work")}</option><option value="research">{t("Research")}</option><option value="interest">{t("Personal interest")}</option><option value="custom">{t("Custom")}</option></select></label>{learningPurpose === "custom" && <label className="mt-5 block text-xs font-medium">{t("Custom purpose")}<input value={customPurpose} onChange={(e) => setCustomPurpose(e.target.value)} maxLength={500} className={inputClass} /></label>}<label className="mt-5 block text-xs font-medium">{t("Background (optional)")}<textarea value={background} onChange={(e) => setBackground(e.target.value)} rows={3} className={inputClass} placeholder={t("Prior experience, context, or constraints")} /></label><label className="mt-5 block text-xs font-medium">{t("Current level (optional)")}<select value={level ?? ""} onChange={(e) => setLevel(e.target.value || null)} className={inputClass}><option value="">{t("Not specified")}</option><option value="beginner">{t("Beginner")}</option><option value="intermediate">{t("Intermediate")}</option><option value="advanced">{t("Advanced")}</option></select></label><label className="mt-5 block text-xs font-medium">{t("Known topics (optional)")}<input value={knownTopics} onChange={(e) => setKnownTopics(e.target.value)} className={inputClass} placeholder={t("Comma-separated topics you already know")} /></label><label className="mt-5 block text-xs font-medium">{t("Skipped topics (optional)")}<input value={skippedTopics} onChange={(e) => setSkippedTopics(e.target.value)} className={inputClass} placeholder={t("Comma-separated topics to skip")} /></label></>}
      {step === 3 && <><h2 className="text-lg font-semibold">{t("Choose your study approach")}</h2><label className="mt-5 block text-xs font-medium">{t("Scope (optional)")}<select value={scopeMode ?? ""} onChange={(e) => setScopeMode(e.target.value || null)} className={inputClass}><option value="">{t("Not specified")}</option><option value="full_topic">{t("Full topic")}</option><option value="selected">{t("Selected areas")}</option><option value="custom">{t("Custom scope")}</option></select></label>{scopeMode && scopeMode !== "full_topic" && <><label className="mt-3 block text-xs font-medium">{t("Include (optional)")}<input value={scopeInclude} onChange={(e) => setScopeInclude(e.target.value)} className={inputClass} placeholder={t("Comma-separated areas")} /></label><label className="mt-3 block text-xs font-medium">{t("Exclude (optional)")}<input value={scopeExclude} onChange={(e) => setScopeExclude(e.target.value)} className={inputClass} placeholder={t("Comma-separated areas")} /></label></>}<label className="mt-5 block text-xs font-medium">{t("Balance (optional)")}<select value={approach ?? ""} onChange={(e) => setApproach(e.target.value || null)} className={inputClass}><option value="">{t("Not specified")}</option><option value="balanced">{t("Balanced")}</option><option value="theory">{t("More theory")}</option><option value="practice">{t("More practice")}</option></select></label><label className="mt-3 block text-xs font-medium">{t("Granularity (optional)")}<select value={granularity ?? ""} onChange={(e) => setGranularity(e.target.value || null)} className={inputClass}><option value="">{t("Not specified")}</option><option value="overview">{t("Overview")}</option><option value="standard">{t("Standard")}</option><option value="detailed">{t("Detailed")}</option></select></label><label className="mt-3 block text-xs font-medium">{t("Mathematical rigor (optional)")}<select value={rigor ?? ""} onChange={(e) => setRigor(e.target.value || null)} className={inputClass}><option value="">{t("Not specified")}</option><option value="intuitive">{t("Intuitive")}</option><option value="standard">{t("Standard")}</option><option value="rigorous">{t("Rigorous")}</option></select></label><fieldset className="mt-4"><legend className="text-xs font-medium">{t("Activities (optional)")}</legend><div className="mt-2 flex flex-wrap gap-2">{Object.entries(ACTIVITY_LABELS).map(([activity, label]) => <button key={activity} type="button" aria-pressed={activities.includes(activity)} onClick={() => setActivities((a) => a.includes(activity) ? a.filter((x) => x !== activity) : [...a, activity])} className={`rounded-lg border px-3 py-2 text-xs ${activities.includes(activity) ? "border-[var(--primary)] bg-[var(--primary)]/10" : "border-[var(--border)]"}`}>{t(label)}</button>)}</div></fieldset><label className="mt-5 block text-xs font-medium">{t("Time commitment (optional)")}<select value={timeMode ?? ""} onChange={(e) => setTimeMode(e.target.value || null)} className={inputClass}><option value="">{t("Not specified")}</option><option value="weekly">{t("Weekly hours")}</option><option value="duration">{t("Target duration")}</option><option value="deadline">{t("Deadline")}</option></select></label>{timeMode === "weekly" && <label className="mt-3 block text-xs font-medium">{t("Hours per week")}<input type="number" min="1" value={weeklyHours} onChange={(e) => setWeeklyHours(e.target.value)} className={inputClass} /></label>}{timeMode === "duration" && <label className="mt-3 block text-xs font-medium">{t("Duration in weeks")}<input type="number" min="1" value={durationWeeks} onChange={(e) => setDurationWeeks(e.target.value)} className={inputClass} /></label>}{timeMode === "deadline" && <label className="mt-3 block text-xs font-medium">{t("Target date")}<input type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} className={inputClass} /></label>}<label className="mt-3 block text-xs font-medium">{t("Session duration in minutes (optional)")}<input type="number" min="1" value={sessionMinutes} onChange={(e) => setSessionMinutes(e.target.value)} className={inputClass} /></label><label className="mt-5 block text-xs font-medium">{t("Milestones (optional)")}<select value={milestonePreference ?? ""} onChange={(e) => setMilestonePreference(e.target.value || null)} className={inputClass}><option value="">{t("Not specified")}</option><option value="none">{t("No milestones")}</option><option value="suggest">{t("Suggest milestones")}</option><option value="learner_defined">{t("I’ll define them later")}</option></select></label>{milestonePreference === "learner_defined" && <div className="mt-3 space-y-2">{milestones.map((m, i) => <div key={i} className="grid gap-2 sm:grid-cols-[1fr_1fr_100px]"><input aria-label={t("Milestone name")} value={m.name} onChange={(e) => setMilestones((all) => all.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} placeholder={t("Milestone name")} className={inputClass} /><input aria-label={t("Milestone description")} value={m.description} onChange={(e) => setMilestones((all) => all.map((x, j) => j === i ? { ...x, description: e.target.value } : x))} placeholder={t("Description")} className={inputClass} /><input aria-label={t("Target week")} type="number" min="1" value={m.target_week} onChange={(e) => setMilestones((all) => all.map((x, j) => j === i ? { ...x, target_week: e.target.value } : x))} placeholder={t("Week")} className={inputClass} /></div>)}<button type="button" onClick={() => setMilestones((all) => [...all, { name: "", description: "", target_week: "" }])} className="rounded-lg border border-[var(--border)] px-3 py-2 text-xs">{t("Add milestone")}</button></div>}</>}
      {step === 4 && draft && <><CoverageNotice coverage={draft.coverage} busy={busy} onCover={(missing) => void generate(missing)} /><RouteDraftEditor draft={draft} onChange={setDraft} moduleLimit={draft.module_limit} /><div className="mt-6 rounded-lg border border-[var(--border)] bg-[var(--background)] p-4"><p className="text-sm font-medium">{t("Want help shaping this plan?")}</p><p className="mt-1 text-xs text-[var(--muted-foreground)]">{t("Discuss your goals and constraints with AI before creating a learning path.")}</p><button type="button" onClick={() => void discuss()} disabled={busy} className="mt-3 inline-flex items-center gap-2 rounded-lg border border-[var(--primary)] px-3 py-2 text-sm text-[var(--primary)] disabled:opacity-50"><Sparkles className="h-4 w-4" />{t("Discuss with AI first")}</button></div></>}
      {error && <p role="alert" className="mt-5 rounded-lg border border-red-500/20 bg-red-500/[0.06] p-3 text-sm text-red-700 dark:text-red-300">{error}</p>}
    </section>
    <footer className="mt-5 flex justify-between"><button type="button" onClick={() => setStep((s) => Math.max(1, s - 1))} disabled={step === 1 || busy} className="inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm text-[var(--muted-foreground)] disabled:invisible"><ArrowLeft className="h-4 w-4" />{t("Back")}</button>{step < 3 ? <button type="button" onClick={() => setStep(step + 1)} disabled={(step === 1 && !name.trim()) || (step === 2 && !goal.trim())} className="inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] disabled:opacity-40">{t("Continue")}<ArrowRight className="h-4 w-4" /></button> : step === 3 ? <button type="button" onClick={() => void generate()} disabled={busy || !name.trim() || !goal.trim()} className="inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] disabled:opacity-50">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}{busy ? t("Charting…") : t("Generate outline")}</button> : <button type="button" onClick={() => void create()} disabled={busy || !draft || !isRouteDraftValid(draft)} className="inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] disabled:opacity-50">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}{busy ? t("Saving map…") : t("Start learning")}</button>}</footer>
  </div></main>;
}
