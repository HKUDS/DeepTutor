"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, Save } from "lucide-react";
import { fetchAdminResources, fetchUserGrant, saveUserGrant } from "../api";
import type { GrantPayload, MultiUserResources } from "../types";

type SaveState = "idle" | "saving" | "saved" | "error";

function emptyGrant(userId: string): GrantPayload {
  return {
    version: 1,
    user_id: userId,
    models: { llm: [], embedding: [], search: [] },
    knowledge_bases: [],
    skills: [],
    spaces: [],
  };
}

function hasModel(
  grant: GrantPayload,
  service: "llm" | "embedding" | "search",
  profileId: string,
  modelId?: string,
) {
  return grant.models[service].some((item) => {
    if (item.profile_id !== profileId) return false;
    if (!modelId) return true;
    return Array.isArray(item.model_ids) && item.model_ids.includes(modelId);
  });
}

function grantFingerprint(grant: GrantPayload): string {
  return JSON.stringify(grant);
}

export function GrantEditor({ userId }: { userId: string }) {
  const [resources, setResources] = useState<MultiUserResources | null>(null);
  const [grant, setGrant] = useState<GrantPayload>(() => emptyGrant(userId));
  const [loading, setLoading] = useState(true);
  const [savedFingerprint, setSavedFingerprint] = useState("");
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setSaveState("idle");
    setMessage("");
    Promise.all([fetchAdminResources(), fetchUserGrant(userId)])
      .then(([nextResources, nextGrant]) => {
        if (cancelled) return;
        setResources(nextResources);
        setGrant(nextGrant);
        setSavedFingerprint(grantFingerprint(nextGrant));
      })
      .catch((error) => {
        setSaveState("error");
        setMessage(
          error instanceof Error ? error.message : "Failed to load grants",
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [userId]);

  const currentFingerprint = useMemo(() => grantFingerprint(grant), [grant]);
  const dirty =
    Boolean(savedFingerprint) && currentFingerprint !== savedFingerprint;

  const kbIds = useMemo(
    () =>
      new Set(
        grant.knowledge_bases.map((item) =>
          String(item.resource_id || item.id || ""),
        ),
      ),
    [grant.knowledge_bases],
  );
  const skillIds = useMemo(
    () =>
      new Set(
        grant.skills.map((item) => String(item.skill_id || item.id || "")),
      ),
    [grant.skills],
  );

  const selectedModelCount = useMemo(
    () =>
      (["llm", "embedding", "search"] as const).reduce(
        (total, service) =>
          total +
          grant.models[service].reduce((serviceTotal, item) => {
            if (Array.isArray(item.model_ids))
              return serviceTotal + item.model_ids.length;
            return serviceTotal + 1;
          }, 0),
        0,
      ),
    [grant.models],
  );

  const saving = saveState === "saving";
  const controlsDisabled = loading || saving;

  function toggleModel(
    service: "llm" | "embedding" | "search",
    profileId: string,
    modelId?: string,
  ) {
    setGrant((current) => {
      const next = structuredClone(current) as GrantPayload;
      const items = next.models[service];
      if (service === "search" || !modelId) {
        next.models[service] = hasModel(next, service, profileId)
          ? items.filter((item) => item.profile_id !== profileId)
          : [...items, { profile_id: profileId, source: "admin" }];
        return next;
      }
      const existing = items.find((item) => item.profile_id === profileId);
      if (!existing) {
        items.push({
          profile_id: profileId,
          model_ids: [modelId],
          source: "admin",
        });
        return next;
      }
      const modelIds = new Set(
        Array.isArray(existing.model_ids) ? existing.model_ids : [],
      );
      if (modelIds.has(modelId)) modelIds.delete(modelId);
      else modelIds.add(modelId);
      existing.model_ids = Array.from(modelIds);
      next.models[service] = items.filter((item) =>
        Array.isArray(item.model_ids) ? item.model_ids.length > 0 : true,
      );
      return next;
    });
  }

  function toggleKb(resourceId: string, name: string) {
    setGrant((current) => {
      const next = structuredClone(current) as GrantPayload;
      const exists = kbIds.has(resourceId);
      next.knowledge_bases = exists
        ? next.knowledge_bases.filter(
            (item) => String(item.resource_id || item.id || "") !== resourceId,
          )
        : [
            ...next.knowledge_bases,
            { resource_id: resourceId, name, access: "read", source: "admin" },
          ];
      return next;
    });
  }

  function toggleSkill(name: string) {
    setGrant((current) => {
      const next = structuredClone(current) as GrantPayload;
      const exists = skillIds.has(name);
      next.skills = exists
        ? next.skills.filter(
            (item) => String(item.skill_id || item.id || "") !== name,
          )
        : [...next.skills, { skill_id: name, access: "use", source: "admin" }];
      return next;
    });
  }

  async function save() {
    setSaveState("saving");
    setMessage("");
    try {
      const saved = await saveUserGrant(userId, grant);
      setGrant(saved);
      setSavedFingerprint(grantFingerprint(saved));
      setSaveState("saved");
      setMessage("Saved just now");
    } catch (error) {
      setSaveState("error");
      setMessage(error instanceof Error ? error.message : "Failed to save");
    }
  }

  const status = loading
    ? "Loading assignments..."
    : saveState === "saving"
      ? "Saving changes..."
      : saveState === "error"
        ? message || "Failed to save"
        : saveState === "saved" && !dirty
          ? message || "Saved just now"
          : dirty
            ? "Unsaved changes"
            : "Ready";

  const statusTone =
    saveState === "error"
      ? "text-red-600 dark:text-red-400"
      : saveState === "saved" && !dirty
        ? "text-emerald-700 dark:text-emerald-300"
        : "text-[var(--muted-foreground)]";

  if (loading && !resources) {
    return (
      <div className="border-t border-[var(--border)] bg-[var(--background)]/40 p-4">
        <div className="flex h-[420px] items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--card)] text-sm text-[var(--muted-foreground)]">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          Loading assignments...
        </div>
      </div>
    );
  }

  return (
    <div className="border-t border-[var(--border)] bg-[var(--background)]/40 p-4">
      <div className="flex h-[620px] max-h-[calc(100vh-170px)] min-h-[420px] flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-sm">
        <div className="shrink-0 border-b border-[var(--border)] px-5 py-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-[var(--foreground)]">
                Assign access
              </h2>
              <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                Admin resources stay linked server-side; users only receive
                allowed access.
              </p>
            </div>
            <div className="flex flex-wrap gap-1.5 text-[11px] text-[var(--muted-foreground)]">
              <span className="rounded-full bg-[var(--muted)]/60 px-2 py-1">
                {selectedModelCount} models
              </span>
              <span className="rounded-full bg-[var(--muted)]/60 px-2 py-1">
                {kbIds.size} KBs
              </span>
              <span className="rounded-full bg-[var(--muted)]/60 px-2 py-1">
                {skillIds.size} skills
              </span>
            </div>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 [scrollbar-gutter:stable]">
          <div className="grid gap-5 md:grid-cols-3">
            <section className="min-w-0">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                Models
              </h3>
              <div className="space-y-3 text-xs">
                {(["llm", "embedding"] as const).map((service) => (
                  <div key={service} className="space-y-1.5">
                    <div className="font-medium text-[var(--foreground)]">
                      {service.toUpperCase()}
                    </div>
                    {(resources?.models[service] || []).map((profile) => (
                      <div
                        key={profile.profile_id}
                        className="rounded-lg border border-[var(--border)]/60 p-2"
                      >
                        <div className="mb-1 truncate text-[var(--muted-foreground)]">
                          {profile.name}
                        </div>
                        {(profile.models || []).map((model) => (
                          <label
                            key={model.model_id}
                            className="flex cursor-pointer items-center gap-2 py-1 text-[var(--foreground)]"
                          >
                            <input
                              type="checkbox"
                              checked={hasModel(
                                grant,
                                service,
                                profile.profile_id,
                                model.model_id,
                              )}
                              disabled={controlsDisabled}
                              onChange={() =>
                                toggleModel(
                                  service,
                                  profile.profile_id,
                                  model.model_id,
                                )
                              }
                            />
                            <span className="truncate">{model.name}</span>
                          </label>
                        ))}
                      </div>
                    ))}
                  </div>
                ))}
                <div className="space-y-1.5">
                  <div className="font-medium text-[var(--foreground)]">
                    SEARCH
                  </div>
                  {(resources?.models.search || []).map((profile) => (
                    <label
                      key={profile.profile_id}
                      className="flex cursor-pointer items-center gap-2 rounded-lg border border-[var(--border)]/60 p-2 text-[var(--foreground)]"
                    >
                      <input
                        type="checkbox"
                        checked={hasModel(grant, "search", profile.profile_id)}
                        disabled={controlsDisabled}
                        onChange={() =>
                          toggleModel("search", profile.profile_id)
                        }
                      />
                      <span className="truncate">{profile.name}</span>
                    </label>
                  ))}
                </div>
              </div>
            </section>
            <section className="min-w-0">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                Knowledge
              </h3>
              <div className="space-y-1.5 text-xs">
                {(resources?.knowledge_bases || []).map((kb) => (
                  <label
                    key={kb.resource_id}
                    className="flex cursor-pointer items-center gap-2 rounded-lg border border-[var(--border)]/60 p-2 text-[var(--foreground)]"
                  >
                    <input
                      type="checkbox"
                      checked={kbIds.has(kb.resource_id)}
                      disabled={controlsDisabled}
                      onChange={() => toggleKb(kb.resource_id, kb.name)}
                    />
                    <span className="truncate">{kb.name}</span>
                  </label>
                ))}
              </div>
            </section>
            <section className="min-w-0">
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
                Skills
              </h3>
              <div className="space-y-1.5 text-xs">
                {(resources?.skills || []).map((skill) => (
                  <label
                    key={skill.name}
                    className="flex cursor-pointer items-center gap-2 rounded-lg border border-[var(--border)]/60 p-2 text-[var(--foreground)]"
                  >
                    <input
                      type="checkbox"
                      checked={skillIds.has(skill.name)}
                      disabled={controlsDisabled}
                      onChange={() => toggleSkill(skill.name)}
                    />
                    <span className="truncate">{skill.name}</span>
                  </label>
                ))}
              </div>
            </section>
          </div>
        </div>

        <div className="flex shrink-0 items-center justify-between gap-3 border-t border-[var(--border)] bg-[var(--card)] px-5 py-3">
          <div
            aria-live="polite"
            className={`flex min-w-0 items-center gap-1.5 text-xs ${statusTone}`}
          >
            {saveState === "error" ? (
              <AlertCircle className="h-3.5 w-3.5 shrink-0" />
            ) : saveState === "saved" && !dirty ? (
              <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
            ) : null}
            <span className="truncate">{status}</span>
          </div>
          <button
            onClick={save}
            disabled={controlsDisabled || !dirty}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-xs font-medium text-[var(--background)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-45"
          >
            {saving ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : saveState === "saved" && !dirty ? (
              <CheckCircle2 className="h-3 w-3" />
            ) : (
              <Save className="h-3 w-3" />
            )}
            {saving
              ? "Saving..."
              : saveState === "saved" && !dirty
                ? "Saved"
                : "Save assignments"}
          </button>
        </div>
      </div>
    </div>
  );
}
