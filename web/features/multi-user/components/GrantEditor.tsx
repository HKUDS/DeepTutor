"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, Save } from "lucide-react";
import { fetchAdminResources, fetchUserGrant, saveUserGrant } from "../api";
import type { GrantPayload, McpToolOption, MultiUserResources } from "../types";

type SaveState = "idle" | "saving" | "saved" | "error";

function emptyGrant(userId: string): GrantPayload {
  return {
    version: 2,
    user_id: userId,
    models: { llm: [] },
    knowledge_bases: [],
    skills: [],
    partners: [],
    enabled_tools: null,
    mcp_tools: null,
    exec_enabled: null,
  };
}

function hasModel(grant: GrantPayload, profileId: string, modelId?: string) {
  return grant.models.llm.some((item) => {
    if (item.profile_id !== profileId) return false;
    if (!modelId) return true;
    return Array.isArray(item.model_ids) && item.model_ids.includes(modelId);
  });
}

function grantFingerprint(grant: GrantPayload): string {
  return JSON.stringify(grant);
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
      {children}
    </h3>
  );
}

function CheckRow({
  label,
  description,
  checked,
  disabled,
  onToggle,
}: {
  label: string;
  description?: string;
  checked: boolean;
  disabled: boolean;
  onToggle: () => void;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-[var(--border)]/60 p-2 text-[var(--foreground)]">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={onToggle}
        className="mt-0.5"
      />
      <span className="min-w-0">
        <span className="block truncate">{label}</span>
        {description ? (
          <span className="block truncate text-[11px] text-[var(--muted-foreground)]">
            {description}
          </span>
        ) : null}
      </span>
    </label>
  );
}

/**
 * Default-vs-custom switch for a whitelist field. ``null`` selects the
 * "default" mode; what that resolves to server-side depends on the field —
 * built-in tools default to *all*, MCP tools default to *none* (deny until
 * explicitly granted) — so the default-mode label is caller-supplied.
 */
function ModeSwitch({
  isCustom,
  disabled,
  onDefault,
  onCustom,
  defaultLabel = "Default · all",
}: {
  isCustom: boolean;
  disabled: boolean;
  onDefault: () => void;
  onCustom: () => void;
  defaultLabel?: string;
}) {
  const base =
    "rounded-md px-2 py-0.5 text-[11px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45";
  return (
    <div className="mb-2 inline-flex gap-1 rounded-lg bg-[var(--muted)]/50 p-0.5">
      <button
        type="button"
        disabled={disabled}
        onClick={onDefault}
        className={`${base} ${
          !isCustom
            ? "bg-[var(--card)] text-[var(--foreground)] shadow-sm"
            : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
        }`}
      >
        {defaultLabel}
      </button>
      <button
        type="button"
        disabled={disabled}
        onClick={onCustom}
        className={`${base} ${
          isCustom
            ? "bg-[var(--card)] text-[var(--foreground)] shadow-sm"
            : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
        }`}
      >
        Custom
      </button>
    </div>
  );
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
  const partnerIds = useMemo(
    () =>
      new Set(
        grant.partners.map((item) => String(item.partner_id || item.id || "")),
      ),
    [grant.partners],
  );

  const selectedModelCount = useMemo(
    () =>
      grant.models.llm.reduce((total, item) => {
        if (Array.isArray(item.model_ids)) return total + item.model_ids.length;
        return total + 1;
      }, 0),
    [grant.models.llm],
  );

  const saving = saveState === "saving";
  const controlsDisabled = loading || saving;

  function toggleModel(profileId: string, modelId: string) {
    setGrant((current) => {
      const next = structuredClone(current) as GrantPayload;
      const items = next.models.llm;
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
      next.models.llm = items.filter((item) =>
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

  function togglePartner(partnerId: string, name: string) {
    setGrant((current) => {
      const next = structuredClone(current) as GrantPayload;
      const exists = partnerIds.has(partnerId);
      next.partners = exists
        ? next.partners.filter(
            (item) => String(item.partner_id || item.id || "") !== partnerId,
          )
        : [...next.partners, { partner_id: partnerId, name, source: "admin" }];
      return next;
    });
  }

  function setToolList(
    key: "enabled_tools" | "mcp_tools",
    value: string[] | null,
  ) {
    setGrant((current) => ({ ...current, [key]: value }));
  }

  function toggleToolName(key: "enabled_tools" | "mcp_tools", name: string) {
    setGrant((current) => {
      const list = current[key];
      if (list === null) return current;
      const next = list.includes(name)
        ? list.filter((item) => item !== name)
        : [...list, name];
      return { ...current, [key]: next };
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

  const toolsSummary =
    grant.enabled_tools === null
      ? "all tools"
      : `${grant.enabled_tools.length} tools`;
  // MCP tools deny-by-default for non-admin users: ``null`` grants none until
  // the admin switches to Custom and picks specific tool names.
  const mcpSummary =
    grant.mcp_tools === null ? "no MCP" : `${grant.mcp_tools.length} MCP`;

  const mcpByServer = useMemo(() => {
    const groups = new Map<string, McpToolOption[]>();
    for (const tool of resources?.mcp_tools || []) {
      const key = tool.server || "other";
      groups.set(key, [...(groups.get(key) ?? []), tool]);
    }
    return groups;
  }, [resources?.mcp_tools]);

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
              <span className="rounded-full bg-[var(--muted)]/60 px-2 py-1">
                {partnerIds.size} partners
              </span>
              <span className="rounded-full bg-[var(--muted)]/60 px-2 py-1">
                {toolsSummary}
              </span>
              <span className="rounded-full bg-[var(--muted)]/60 px-2 py-1">
                {mcpSummary}
              </span>
            </div>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 [scrollbar-gutter:stable]">
          <div className="grid gap-5 md:grid-cols-3">
            <section className="min-w-0">
              <SectionTitle>Models</SectionTitle>
              <div className="space-y-1.5 text-xs">
                {(resources?.models.llm || []).map((profile) => (
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
                            profile.profile_id,
                            model.model_id,
                          )}
                          disabled={controlsDisabled}
                          onChange={() =>
                            toggleModel(profile.profile_id, model.model_id)
                          }
                        />
                        <span className="truncate">{model.name}</span>
                      </label>
                    ))}
                  </div>
                ))}
              </div>
            </section>
            <section className="min-w-0">
              <SectionTitle>Knowledge</SectionTitle>
              <div className="space-y-1.5 text-xs">
                {(resources?.knowledge_bases || []).map((kb) => (
                  <CheckRow
                    key={kb.resource_id}
                    label={kb.name}
                    checked={kbIds.has(kb.resource_id)}
                    disabled={controlsDisabled}
                    onToggle={() => toggleKb(kb.resource_id, kb.name)}
                  />
                ))}
              </div>
            </section>
            <section className="min-w-0">
              <SectionTitle>Skills</SectionTitle>
              <div className="space-y-1.5 text-xs">
                {(resources?.skills || []).map((skill) => (
                  <CheckRow
                    key={skill.name}
                    label={skill.name}
                    checked={skillIds.has(skill.name)}
                    disabled={controlsDisabled}
                    onToggle={() => toggleSkill(skill.name)}
                  />
                ))}
              </div>
            </section>
            <section className="min-w-0">
              <SectionTitle>Partners</SectionTitle>
              <div className="space-y-1.5 text-xs">
                {(resources?.partners || []).length === 0 ? (
                  <p className="px-1 text-[11px] leading-relaxed text-[var(--muted-foreground)]">
                    No partners yet. Create one under Partners to assign it.
                  </p>
                ) : (
                  (resources?.partners || []).map((partner) => (
                    <CheckRow
                      key={partner.partner_id}
                      label={partner.name || partner.partner_id}
                      description={partner.description}
                      checked={partnerIds.has(partner.partner_id)}
                      disabled={controlsDisabled}
                      onToggle={() =>
                        togglePartner(
                          partner.partner_id,
                          partner.name || partner.partner_id,
                        )
                      }
                    />
                  ))
                )}
              </div>
            </section>

            <section className="min-w-0">
              <SectionTitle>System tools</SectionTitle>
              <ModeSwitch
                isCustom={grant.enabled_tools !== null}
                disabled={controlsDisabled}
                onDefault={() => setToolList("enabled_tools", null)}
                onCustom={() =>
                  setToolList(
                    "enabled_tools",
                    (resources?.tools || []).map((tool) => tool.name),
                  )
                }
              />
              {grant.enabled_tools !== null && (
                <div className="space-y-1.5 text-xs">
                  {(resources?.tools || []).map((tool) => (
                    <CheckRow
                      key={tool.name}
                      label={tool.name}
                      description={tool.description}
                      checked={grant.enabled_tools!.includes(tool.name)}
                      disabled={controlsDisabled}
                      onToggle={() =>
                        toggleToolName("enabled_tools", tool.name)
                      }
                    />
                  ))}
                </div>
              )}
            </section>
            <section className="min-w-0">
              <SectionTitle>MCP tools</SectionTitle>
              <ModeSwitch
                isCustom={grant.mcp_tools !== null}
                disabled={controlsDisabled}
                defaultLabel="Default · none"
                onDefault={() => setToolList("mcp_tools", null)}
                onCustom={() =>
                  setToolList(
                    "mcp_tools",
                    (resources?.mcp_tools || []).map((tool) => tool.name),
                  )
                }
              />
              {grant.mcp_tools === null ? (
                <p className="px-1 text-[11px] leading-relaxed text-[var(--muted-foreground)]">
                  MCP tools proxy host-side capabilities, so they stay denied by
                  default. Switch to Custom to grant specific tools.
                </p>
              ) : null}
              {grant.mcp_tools !== null &&
                (resources?.mcp_tools?.length ? (
                  <div className="space-y-2 text-xs">
                    {[...mcpByServer.entries()].map(([server, tools]) => (
                      <div key={server}>
                        <p className="mb-1 px-1 font-mono text-[11px] text-[var(--muted-foreground)]">
                          {server}
                        </p>
                        <div className="space-y-1.5">
                          {tools.map((tool) => (
                            <CheckRow
                              key={tool.name}
                              label={tool.name}
                              description={tool.description}
                              checked={grant.mcp_tools!.includes(tool.name)}
                              disabled={controlsDisabled}
                              onToggle={() =>
                                toggleToolName("mcp_tools", tool.name)
                              }
                            />
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-[var(--muted-foreground)]">
                    No MCP servers configured.
                  </p>
                ))}
            </section>
            <section className="min-w-0">
              <SectionTitle>Code execution</SectionTitle>
              <div className="space-y-1.5 text-xs">
                <CheckRow
                  label="Allow code execution"
                  description="Follows the deployment sandbox policy. Uncheck to disable exec for this user."
                  checked={grant.exec_enabled !== false}
                  disabled={controlsDisabled}
                  onToggle={() =>
                    setGrant((current) => ({
                      ...current,
                      exec_enabled:
                        current.exec_enabled === false ? null : false,
                    }))
                  }
                />
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
