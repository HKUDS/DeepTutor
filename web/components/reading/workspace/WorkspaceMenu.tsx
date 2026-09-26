"use client";

import { MoreHorizontal } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type WorkspaceMenuHost,
  type WorkspaceMenuItem,
  type WorkspaceMenuSection,
} from "@/components/reading/workspace-menu-context";
import { MenuItem } from "./WorkspaceChrome";

export type WorkspaceMenuSections = Partial<
  Record<WorkspaceMenuSection, WorkspaceMenuItem[]>
>;

/**
 * The collector behind the workspace's single ⋯.
 *
 * The reader and the companion hand their ⋯ items up through the host, so
 * the page has one ⋯ instead of three a hand's width apart.
 */
export function useWorkspaceMenuHost(): {
  host: WorkspaceMenuHost;
  sections: WorkspaceMenuSections;
} {
  const [sections, setSections] = useState<WorkspaceMenuSections>({});
  const host = useMemo<WorkspaceMenuHost>(
    () => ({
      register: (section, items) =>
        setSections((current) =>
          current[section] === (items ?? undefined)
            ? current
            : { ...current, [section]: items ?? undefined },
        ),
    }),
    [],
  );
  return { host, sections };
}

export function WorkspaceMenu({
  collection,
  sections,
}: {
  /** What acts on the whole collection; always first. */
  collection: WorkspaceMenuItem[];
  sections: WorkspaceMenuSections;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open]);

  const groups: Array<[string, string, WorkspaceMenuItem[] | undefined]> = [
    ["collection", t("Collection"), collection],
    ["material", t("Document"), sections.material],
    ["conversation", t("Conversation"), sections.conversation],
  ];

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="flex size-7 items-center justify-center rounded-md text-[var(--muted-foreground)] transition hover:bg-[var(--muted)]"
        aria-label={t("More")}
        title={t("More")}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <MoreHorizontal size={14} />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div
            role="menu"
            aria-label={t("More")}
            className="absolute right-0 top-8 z-40 max-h-[calc(100vh-4rem)] w-64 overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--card)] p-1 text-[12px] shadow-md dark:bg-[var(--popover)]"
          >
            {groups.map(([key, heading, items], index) => {
              if (!items?.length) return null;
              return (
                <div key={key}>
                  {index > 0 && (
                    <div
                      className="mx-1.5 my-1 h-px bg-[var(--border)]"
                      aria-hidden
                    />
                  )}
                  <p className="px-2.5 pb-0.5 pt-1.5 text-[10.5px] font-medium text-[var(--muted-foreground)]">
                    {heading}
                  </p>
                  {items.map((item) => (
                    <MenuItem
                      key={item.key}
                      icon={item.icon}
                      label={item.label}
                      hint={item.hint}
                      active={item.active}
                      spinning={item.spinning}
                      disabled={item.disabled}
                      onClick={() => {
                        // A toggle stays open so the learner sees it flip.
                        if (item.active === undefined) setOpen(false);
                        item.onSelect();
                      }}
                    />
                  ))}
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
