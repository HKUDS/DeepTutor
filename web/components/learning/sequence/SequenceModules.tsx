"use client";

import { useTranslation } from "react-i18next";
import { inputClass } from "@/components/settings/shared";
import type { SequenceModule } from "@/lib/sequence-api";

function groupByCategory(modules: SequenceModule[]): { category: string; modules: SequenceModule[] }[] {
  const groups: { category: string; modules: SequenceModule[] }[] = [];
  const index = new Map<string, number>();
  modules.forEach(module => {
    const existing = index.get(module.category);
    if (existing === undefined) {
      index.set(module.category, groups.length);
      groups.push({ category: module.category, modules: [module] });
      return;
    }
    groups[existing].modules.push(module);
  });
  return groups;
}

export function SequenceModules({
  modules,
  topic,
  disabled,
  onTopicChange,
  onSelect,
  onCreate,
}: {
  modules: SequenceModule[];
  topic: string;
  disabled: boolean;
  onTopicChange: (topic: string) => void;
  onSelect: (topic: string) => void;
  onCreate: () => void;
}) {
  const { t } = useTranslation();
  const groups = groupByCategory(modules);

  return (
    <div className="space-y-8">
      {groups.map(group => (
        <section key={group.category}>
          <h2 className="mb-3 text-base font-semibold text-[var(--primary)]">
            {group.category || t("Course")}
          </h2>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
            {group.modules.map(module => (
              <button
                key={module.id}
                type="button"
                className="flex min-h-24 flex-col justify-between rounded-lg border border-[var(--border)] bg-[var(--background)] p-4 text-left transition-colors hover:border-[var(--primary)] hover:bg-[var(--muted)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:opacity-60"
                onClick={() => onSelect(module.topic)}
                disabled={disabled}
              >
                <span className="font-semibold text-[var(--foreground)]">{module.topic}</span>
                <span className="mt-2 text-sm text-[var(--muted-foreground)]">
                  {t("Solved {{count}} of {{goal}}", { count: module.solved, goal: module.goal })}
                </span>
              </button>
            ))}
          </div>
        </section>
      ))}
      <form
        className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end"
        onSubmit={event => {
          event.preventDefault();
          onCreate();
        }}
      >
        <label className="grid gap-1 text-sm">
          <span>{t("Or name your own topic")}</span>
          <input
            className={inputClass}
            value={topic}
            onChange={event => onTopicChange(event.target.value)}
            placeholder={t("Chain rule for a product, or the section you just read")}
            maxLength={200}
            disabled={disabled}
          />
        </label>
        <button
          type="submit"
          className="min-h-10 rounded-lg bg-[var(--primary)] px-4 text-sm text-[var(--primary-foreground)] disabled:opacity-60"
          disabled={disabled}
        >
          {t("New problem")}
        </button>
      </form>
    </div>
  );
}
