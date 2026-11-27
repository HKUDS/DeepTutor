"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { ArrowUpRight, Bot, MessageCircle, Minus, Plus, UserRound, Users } from "lucide-react";
import { useTranslation } from "react-i18next";
import { agentGlyph, agentKindLabel } from "@/components/agents/agent-icons";
import PartnerAvatar from "@/components/partners/PartnerAvatar";
import { listPersonas, type PersonaInfo } from "@/lib/personas-api";
import type { PartnerInfo } from "@/lib/partners-api";
import type { PartnerGroup } from "@/lib/partner-groups-api";
import type { ResourceKind } from "@/lib/resource-reuse";
import {
  TrayFoot,
  TrayList,
  TrayMenu,
  TrayOption,
  TrayReuse,
  TraySearch,
  TraySection,
  type TrayPlacement,
} from "./ComposerTrayMenu";
import { PlainVoiceIcon } from "./ComposerIcons";

const BUDGET_MIN = 1;
const BUDGET_MAX = 12;
const SEARCH_FROM = 9;

type Agent = { name: string; kind?: string };

interface Choice<T> {
  options: T[];
  selected: string | null;
  onSelect: (id: string | null) => void;
  loading?: boolean;
  error?: boolean;
}

/** Everyone a turn can be handed to: `partner:<id>` or `subagent:<name>`. */
export interface Answerers {
  value: string | null;
  onChange: (value: string | null) => void;
  partners: PartnerInfo[];
  agents: Agent[];
  loading?: boolean;
  error?: boolean;
}

export interface AnswerModeProps {
  /** DeepTutor's own register for this conversation; "" is its usual voice. */
  persona?: { value: string; onChange: (persona: string) => void };
  answerers?: Answerers;
  /** Controlled open state, so `/persona` can open this list. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export interface PartnerLinkProps {
  partners?: Choice<PartnerInfo>;
  groups?: Choice<PartnerGroup>;
  agents?: Choice<Agent> & {
    /** Most times DeepTutor may ask the agent in one turn. */
    budget?: number | null;
    onBudgetChange?: (budget: number) => void;
  };
}

function PartnerFace({ partner, size }: { partner: PartnerInfo; size: number }) {
  return (
    <PartnerAvatar
      name={partner.name}
      emoji={partner.emoji}
      color={partner.color}
      image={partner.avatar}
      size={size}
      className="shrink-0"
    />
  );
}

function AgentFace({ kind, size }: { kind?: string; size: number }) {
  // Held in an object, as elsewhere: the glyph is a module constant, not a component made here.
  const glyph = { Icon: agentGlyph(kind) ?? Bot };
  return <glyph.Icon size={size} className="shrink-0" />;
}

/**
 * How this conversation is answered — the right end of the composer tray.
 *
 * Two questions in one list: in what voice DeepTutor answers, and who answers
 * at all. Choosing a partner or a connected agent hands the turn to them
 * whole: they get the message as written, their reply is the answer, and their
 * work shows in the conversation the way DeepTutor's own does. Asking them
 * something on DeepTutor's behalf is a different thing and lives in the
 * partner menu beside this one.
 */
export default function AnswerModeMenu({
  persona,
  answerers,
  open,
  onOpenChange,
  placement,
}: AnswerModeProps & { placement: TrayPlacement }) {
  const { t } = useTranslation();
  const chosen = answerers?.value ?? "";
  const kind = chosen.slice(0, Math.max(0, chosen.indexOf(":")));
  const id = kind ? chosen.slice(kind.length + 1) : "";
  const partner = kind === "partner" ? answerers?.partners.find((item) => item.partner_id === id) : undefined;
  const agent = kind === "subagent" ? answerers?.agents.find((item) => item.name === id) : undefined;
  // The trigger names whoever answers; a voice only when DeepTutor does.
  let icon: ReactNode = <UserRound size={14} strokeWidth={1.7} className="shrink-0" />;
  let value = persona?.value || t("Default");
  if (partner || kind === "partner") {
    icon = partner ? <PartnerFace partner={partner} size={16} /> : icon;
    value = partner?.name ?? id;
  } else if (kind === "subagent") {
    icon = <AgentFace kind={agent?.kind} size={14} />;
    value = id;
  }
  return (
    <TrayMenu
      icon={icon}
      label={t("Preferences")}
      value={value}
      active={Boolean(chosen || persona?.value)}
      placement={placement}
      align="end"
      open={onOpenChange ? open : undefined}
      onOpenChange={onOpenChange}
    >
      {(close) => <AnswerList persona={persona} answerers={answerers} close={close} />}
    </TrayMenu>
  );
}

function AnswerList({
  persona,
  answerers,
  close,
}: Pick<AnswerModeProps, "persona" | "answerers"> & { close: () => void }) {
  const { t } = useTranslation();
  const [personas, setPersonas] = useState<PersonaInfo[]>([]);
  const [query, setQuery] = useState("");
  const wantsPersonas = Boolean(persona);
  useEffect(() => {
    if (!wantsPersonas) return;
    let alive = true;
    void listPersonas()
      .then((items) => {
        if (alive) setPersonas(items);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [wantsPersonas]);

  const needle = query.trim().toLocaleLowerCase();
  const matches = (...text: (string | undefined)[]) =>
    !needle || text.join(" ").toLocaleLowerCase().includes(needle);
  const styleRows = personas.filter((item) => matches(item.name, item.description));
  const partnerRows = answerers?.partners.filter((item) => matches(item.name)) ?? [];
  const agentRows = answerers?.agents.filter((item) => matches(item.name)) ?? [];
  const total = personas.length + (answerers?.partners.length ?? 0) + (answerers?.agents.length ?? 0);
  const pick = (value: string | null) => {
    answerers?.onChange(value);
    close();
  };
  const reuse: ResourceKind[] = persona ? ["persona"] : [];

  return (
    <>
      {total >= SEARCH_FROM && (
        <TraySearch value={query} onChange={setQuery} placeholder={t("composer.tray.searchAnswer")} />
      )}
      <TrayList label={t("Preferences")}>
        {persona && (
          <TraySection title={t("Response style")}>
            {matches(t("Default")) && (
              <TrayOption
                selected={!persona.value}
                onSelect={() => {
                  persona.onChange("");
                  close();
                }}
                leading={<PlainVoiceIcon size={16} strokeWidth={1.6} />}
                title={t("Default")}
                meta={t("No persona — the assistant's standard behavior")}
              />
            )}
            {styleRows.map((item) => (
              <TrayOption
                key={item.name}
                selected={persona.value === item.name}
                onSelect={() => {
                  persona.onChange(item.name);
                  close();
                }}
                leading={<UserRound size={14} strokeWidth={1.7} />}
                title={item.name}
                meta={item.description}
              />
            ))}
          </TraySection>
        )}
        {answerers && (
          <TraySection title={t("composer.tray.whoAnswers")} hint={t("composer.tray.whoAnswersHint")}>
            {matches("DeepTutor") && (
              <TrayOption
                selected={!answerers.value}
                onSelect={() => pick(null)}
                leading={<MessageCircle size={14} strokeWidth={1.7} />}
                title={t("composer.tray.deeptutor")}
                meta={t("composer.tray.deeptutorAnswers")}
              />
            )}
            {partnerRows.map((item) => (
              <TrayOption
                key={`partner:${item.partner_id}`}
                selected={answerers.value === `partner:${item.partner_id}`}
                onSelect={() => pick(`partner:${item.partner_id}`)}
                leading={<PartnerFace partner={item} size={24} />}
                title={item.name}
                meta={item.description || undefined}
              />
            ))}
            {agentRows.map((item) => (
              <TrayOption
                key={`subagent:${item.name}`}
                selected={answerers.value === `subagent:${item.name}`}
                onSelect={() => pick(`subagent:${item.name}`)}
                leading={<AgentFace kind={item.kind} size={15} />}
                title={item.name}
                meta={agentKindLabel(item.kind) || undefined}
              />
            ))}
            {answerers.loading && <p className="dt-tray-empty">{t("Loading...")}</p>}
            {answerers.error && !answerers.loading && (
              <p role="alert" className="dt-tray-empty">
                {t("Could not load partners")}
              </p>
            )}
            {!answerers.loading && !needle && !partnerRows.length && !agentRows.length && (
              <p className="dt-tray-empty">{t("composer.tray.noHandOff")}</p>
            )}
          </TraySection>
        )}
        {needle && !styleRows.length && !partnerRows.length && !agentRows.length && (
          <p className="dt-tray-empty">{t("navigation.noResults")}</p>
        )}
      </TrayList>
      <TrayFoot>
        {reuse.length > 0 && <TrayReuse kinds={reuse} />}
        <Link href="/personalization" prefetch={false} onClick={close}>
          {t("navigation.personalization")}
          <ArrowUpRight size={13} strokeWidth={1.9} />
        </Link>
      </TrayFoot>
    </>
  );
}

/**
 * DeepTutor working with partners — the tray's partner menu.
 *
 * Here DeepTutor still answers: it asks one partner, convenes a partner
 * group, or puts questions to a connected agent, and writes the reply from
 * what they said. One of these at a time, and none while the turn is handed
 * to someone outright.
 */
export function PartnerLinkMenu({
  partners,
  groups,
  agents,
  placement,
}: PartnerLinkProps & { placement: TrayPlacement }) {
  const { t } = useTranslation();
  const partner = partners?.options.find((item) => item.partner_id === partners.selected);
  const group = groups?.options.find((item) => item.group_id === groups.selected);
  const agent = agents?.options.find((item) => item.name === agents.selected);
  let icon: ReactNode = <Users size={14} strokeWidth={1.7} className="shrink-0" />;
  let value = "";
  if (partners?.selected) {
    icon = partner ? <PartnerFace partner={partner} size={16} /> : icon;
    value = partner?.name ?? partners.selected;
  } else if (groups?.selected) {
    value = group?.name ?? groups.selected;
  } else if (agents?.selected) {
    icon = <AgentFace kind={agent?.kind} size={14} />;
    value = agents.selected;
  }
  return (
    <TrayMenu
      icon={icon}
      label={t("Partners")}
      value={value}
      active={Boolean(value)}
      placement={placement}
      align="end"
    >
      {(close) => <PartnerLinkList partners={partners} groups={groups} agents={agents} close={close} />}
    </TrayMenu>
  );
}

function PartnerLinkList({
  partners,
  groups,
  agents,
  close,
}: PartnerLinkProps & { close: () => void }) {
  const { t } = useTranslation();
  const reuse: ResourceKind[] = [
    ...(partners ? (["partner"] as const) : []),
    ...(groups ? (["partner_group"] as const) : []),
    ...(agents ? (["agent"] as const) : []),
  ];
  const nothing = !partners?.options.length && !groups?.options.length && !agents?.options.length;
  const loading = Boolean(partners?.loading || groups?.loading);
  const failed = Boolean(partners?.error || groups?.error);
  return (
    <>
      <TrayList label={t("Partners")}>
        {partners && partners.options.length > 0 && (
          <TraySection title={t("Ask partner")} hint={t("composer.tray.askPartnerHint")}>
            {partners.options.map((item) => {
              const chosen = partners.selected === item.partner_id;
              return (
                <TrayOption
                  key={item.partner_id}
                  selected={chosen}
                  onSelect={() => {
                    partners.onSelect(chosen ? null : item.partner_id);
                    close();
                  }}
                  leading={<PartnerFace partner={item} size={24} />}
                  title={item.name}
                  meta={item.description || undefined}
                />
              );
            })}
          </TraySection>
        )}
        {groups && groups.options.length > 0 && (
          <TraySection title={t("Organize partner discussion")}>
            {groups.options.map((item) => {
              const chosen = groups.selected === item.group_id;
              return (
                <TrayOption
                  key={item.group_id}
                  selected={chosen}
                  onSelect={() => {
                    groups.onSelect(chosen ? null : item.group_id);
                    close();
                  }}
                  leading={item.emoji ? <span className="text-[13px]">{item.emoji}</span> : <Users size={14} strokeWidth={1.7} />}
                  title={item.name}
                  meta={item.members.map((member) => member.name).join(" · ") || t("Organize partner discussion")}
                />
              );
            })}
          </TraySection>
        )}
        {agents && agents.options.length > 0 && (
          <TraySection title={t("Ask subagent")} hint={t("composer.tray.askAgentHint")}>
            {agents.options.map((item) => {
              const chosen = agents.selected === item.name;
              return (
                <div key={item.name}>
                  <TrayOption
                    selected={chosen}
                    onSelect={() => {
                      agents.onSelect(chosen ? null : item.name);
                      // Stay open on a new pick so its round limit can be set.
                      if (chosen || !agents.onBudgetChange) close();
                    }}
                    leading={<AgentFace kind={item.kind} size={15} />}
                    title={item.name}
                    meta={agentKindLabel(item.kind) || undefined}
                  />
                  {chosen && agents.onBudgetChange && (
                    <Budget value={agents.budget ?? null} onChange={agents.onBudgetChange} />
                  )}
                </div>
              );
            })}
          </TraySection>
        )}
        {loading && <p className="dt-tray-empty">{t("Loading...")}</p>}
        {failed && !loading && (
          <p role="alert" className="dt-tray-empty">
            {t("Could not load partners")}
          </p>
        )}
        {nothing && !loading && !failed && <p className="dt-tray-empty">{t("No partners yet")}</p>}
      </TrayList>
      <TrayFoot>
        {reuse.length > 0 && <TrayReuse kinds={reuse} />}
        <span className="dt-tray-foot-end">
          <Link href="/partners/groups/new" prefetch={false} onClick={close}>
            <Plus size={13} strokeWidth={1.9} />
            {t("Create a Partner Group")}
          </Link>
          <Link href="/partners" prefetch={false} onClick={close}>
            {t("Partners")}
            <ArrowUpRight size={13} strokeWidth={1.9} />
          </Link>
        </span>
      </TrayFoot>
    </>
  );
}

/** How many times DeepTutor may ask the chosen agent this turn. */
function Budget({ value, onChange }: { value: number | null; onChange: (value: number) => void }) {
  const { t } = useTranslation();
  const current = value ?? BUDGET_MIN;
  return (
    <div className="dt-tray-budget">
      <span>{t("Max rounds DeepTutor may ask")}</span>
      <span className="flex items-center gap-1">
        <button
          type="button"
          aria-label={t("Fewer rounds")}
          disabled={current <= BUDGET_MIN}
          onClick={() => onChange(Math.max(BUDGET_MIN, current - 1))}
        >
          <Minus size={12} />
        </button>
        <span className="dt-tray-budget-value">{value ?? "–"}</span>
        <button
          type="button"
          aria-label={t("More rounds")}
          disabled={current >= BUDGET_MAX}
          onClick={() => onChange(Math.min(BUDGET_MAX, current + 1))}
        >
          <Plus size={12} />
        </button>
      </span>
    </div>
  );
}
