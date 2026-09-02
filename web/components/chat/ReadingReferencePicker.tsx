"use client";

import { useEffect, useMemo, useState } from "react";
import { BookMarked, Check, ChevronRight, Loader2, Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import PickerHeader from "@/components/common/PickerHeader";
import PickerShell from "@/components/common/PickerShell";
import {
  getMaterial,
  listMaterials,
  type MaterialDetail,
  type MaterialInfo,
} from "@/lib/reading-api";
import {
  MAX_READING_REFERENCE_MATERIALS,
  MAX_READING_REFERENCE_UNITS,
  countSelectedReadingUnits,
  type SelectedReadingReference,
  type SelectedReadingUnit,
} from "@/lib/reading-references";

interface ReadingReferencePickerProps {
  open: boolean;
  initialReferences: SelectedReadingReference[];
  onClose: () => void;
  onApply: (references: SelectedReadingReference[]) => void;
}

function materialRevision(material: MaterialInfo): number {
  return material.revision ?? 1;
}

function unitKey(
  materialId: string,
  revision: number,
  locator: number,
): string {
  return `${materialId}:${revision}:${locator}`;
}

function unitTitle(
  detail: MaterialDetail,
  locator: number,
  fallback: string,
): string {
  const outlineTitle = detail.outline.find(
    (row) => row.locator === locator && row.title.trim(),
  )?.title;
  const nativeTitle = detail.unit_refs.find(
    (row) => row.locator === locator && row.title.trim(),
  )?.title;
  return outlineTitle?.trim() || nativeTitle?.trim() || fallback;
}

export default function ReadingReferencePicker({
  open,
  initialReferences,
  onClose,
  onApply,
}: ReadingReferencePickerProps) {
  const { t } = useTranslation();
  const [materials, setMaterials] = useState<MaterialInfo[]>([]);
  const [details, setDetails] = useState<Record<string, MaterialDetail>>({});
  const [activeMaterialId, setActiveMaterialId] = useState<string | null>(null);
  const [selected, setSelected] = useState<SelectedReadingReference[]>([]);
  const [query, setQuery] = useState("");
  const [loadingMaterials, setLoadingMaterials] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let mounted = true;
    // Re-seed the draft on every open; Cancel must not mutate the composer.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSelected(initialReferences);
    setQuery("");
    setError(null);
    setLoadingMaterials(true);
    void listMaterials()
      .then((rows) => {
        if (!mounted) return;
        setMaterials(rows);
        setActiveMaterialId((current) =>
          rows.some((row) => row.material_id === current)
            ? current
            : (rows[0]?.material_id ?? null),
        );
      })
      .catch((cause: unknown) => {
        if (!mounted) return;
        setMaterials([]);
        setError(
          cause instanceof Error
            ? cause.message
            : t("Unable to load reading materials."),
        );
      })
      .finally(() => {
        if (mounted) setLoadingMaterials(false);
      });
    return () => {
      mounted = false;
    };
  }, [initialReferences, open, t]);

  useEffect(() => {
    if (!open || !activeMaterialId || details[activeMaterialId]) return;
    let mounted = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoadingDetail(true);
    setError(null);
    void getMaterial(activeMaterialId)
      .then((detail) => {
        if (!mounted) return;
        setDetails((previous) => ({
          ...previous,
          [activeMaterialId]: detail,
        }));
      })
      .catch((cause: unknown) => {
        if (!mounted) return;
        setError(
          cause instanceof Error
            ? cause.message
            : t("Unable to load reading sections."),
        );
      })
      .finally(() => {
        if (mounted) setLoadingDetail(false);
      });
    return () => {
      mounted = false;
    };
  }, [activeMaterialId, details, open, t]);

  const filteredMaterials = useMemo(() => {
    const keyword = query.trim().toLocaleLowerCase();
    if (!keyword) return materials;
    return materials.filter((material) =>
      `${material.title} ${material.filename}`
        .toLocaleLowerCase()
        .includes(keyword),
    );
  }, [materials, query]);

  const activeMaterial =
    materials.find((material) => material.material_id === activeMaterialId) ??
    null;
  const activeDetail = activeMaterialId
    ? (details[activeMaterialId] ?? null)
    : null;
  const selectedCount = countSelectedReadingUnits(selected);
  const selectedKeys = useMemo(
    () =>
      new Set(
        selected.flatMap((reference) =>
          reference.units.map((unit) =>
            unitKey(reference.materialId, reference.revision, unit.locator),
          ),
        ),
      ),
    [selected],
  );
  const activeUnits = useMemo(() => {
    if (!activeDetail) return [];
    return Array.from({ length: activeDetail.unit_count }, (_, index) => {
      const locator = index + 1;
      const fallback = t("{{unit}} {{locator}}", {
        unit: t(activeDetail.unit),
        locator,
      });
      return {
        locator,
        title: unitTitle(activeDetail, locator, fallback),
      } satisfies SelectedReadingUnit;
    });
  }, [activeDetail, t]);
  const allActiveSelected =
    Boolean(activeMaterial) &&
    activeUnits.length > 0 &&
    activeUnits.every((unit) =>
      selectedKeys.has(
        unitKey(
          activeMaterial!.material_id,
          materialRevision(activeMaterial!),
          unit.locator,
        ),
      ),
    );

  const addUnits = (material: MaterialInfo, units: SelectedReadingUnit[]) => {
    const existing = selected.find(
      (reference) =>
        reference.materialId === material.material_id &&
        reference.revision === materialRevision(material),
    );
    if (!existing && selected.length >= MAX_READING_REFERENCE_MATERIALS) {
      setError(
        t("You can reference up to {{count}} reading materials at once.", {
          count: MAX_READING_REFERENCE_MATERIALS,
        }),
      );
      return;
    }
    const existingLocators = new Set(
      existing?.units.map((unit) => unit.locator) ?? [],
    );
    const pending = units.filter((unit) => !existingLocators.has(unit.locator));
    const remaining = MAX_READING_REFERENCE_UNITS - selectedCount;
    const additions = pending.slice(0, Math.max(0, remaining));
    if (!additions.length) {
      if (pending.length) {
        setError(
          t("You can reference up to {{count}} reading sections at once.", {
            count: MAX_READING_REFERENCE_UNITS,
          }),
        );
      }
      return;
    }
    if (additions.length < pending.length) {
      setError(
        t("Only the first {{count}} available sections were selected.", {
          count: additions.length,
        }),
      );
    } else {
      setError(null);
    }
    if (existing) {
      setSelected((previous) =>
        previous.map((reference) =>
          reference.materialId === material.material_id &&
          reference.revision === materialRevision(material)
            ? { ...reference, units: [...reference.units, ...additions] }
            : reference,
        ),
      );
      return;
    }
    setSelected((previous) => [
      ...previous,
      {
        materialId: material.material_id,
        revision: materialRevision(material),
        materialTitle: material.title || material.filename,
        unit: material.unit,
        units: additions,
      },
    ]);
  };

  const removeUnits = (
    materialId: string,
    revision: number,
    locators: Set<number>,
  ) => {
    setSelected((previous) =>
      previous
        .map((reference) =>
          reference.materialId === materialId && reference.revision === revision
            ? {
                ...reference,
                units: reference.units.filter(
                  (unit) => !locators.has(unit.locator),
                ),
              }
            : reference,
        )
        .filter((reference) => reference.units.length > 0),
    );
    setError(null);
  };

  const toggleUnit = (unit: SelectedReadingUnit) => {
    if (!activeMaterial) return;
    const revision = materialRevision(activeMaterial);
    if (
      selectedKeys.has(
        unitKey(activeMaterial.material_id, revision, unit.locator),
      )
    ) {
      removeUnits(
        activeMaterial.material_id,
        revision,
        new Set([unit.locator]),
      );
      return;
    }
    addUnits(activeMaterial, [unit]);
  };

  const toggleAllActive = () => {
    if (!activeMaterial || !activeUnits.length) return;
    if (allActiveSelected) {
      removeUnits(
        activeMaterial.material_id,
        materialRevision(activeMaterial),
        new Set(activeUnits.map((unit) => unit.locator)),
      );
      return;
    }
    addUnits(activeMaterial, activeUnits);
  };

  return (
    <PickerShell
      open={open}
      onClose={onClose}
      labelledBy="reading-reference-picker-title"
      className="p-4 backdrop-blur-md"
      backdropClass="bg-[var(--background)]/65"
    >
      <div className="surface-card flex h-[78vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] text-[var(--card-foreground)] shadow-[0_22px_70px_rgba(0,0,0,0.18)]">
        <PickerHeader
          icon={BookMarked}
          titleId="reading-reference-picker-title"
          title={t("Select Reading Sections")}
          subtitle={t(
            "Choose sections from imported reading materials to ground the next answer.",
          )}
          onClose={onClose}
        />

        {error ? (
          <div
            role="alert"
            className="border-b border-amber-500/20 bg-amber-500/8 px-5 py-2.5 text-sm text-amber-700 dark:text-amber-300"
          >
            {error}
          </div>
        ) : null}

        <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[300px_minmax(0,1fr)]">
          <aside className="flex min-h-0 flex-col border-b border-[var(--border)] bg-[var(--background)]/40 p-4 md:border-b-0 md:border-r">
            <div className="relative mb-3">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--muted-foreground)]" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t("Search reading materials")}
                className="w-full rounded-xl border border-[var(--border)] bg-[var(--card)] py-2.5 pl-9 pr-3 text-[13px] outline-none transition focus:border-[var(--primary)]/50 focus:ring-2 focus:ring-[var(--primary)]/15"
              />
            </div>
            <div className="min-h-[130px] flex-1 overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--card)] md:min-h-0">
              {loadingMaterials ? (
                <div className="flex h-full min-h-[140px] items-center justify-center">
                  <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
                </div>
              ) : filteredMaterials.length ? (
                <div className="divide-y divide-[var(--border)]">
                  {filteredMaterials.map((material) => {
                    const active = material.material_id === activeMaterialId;
                    const count =
                      selected.find(
                        (reference) =>
                          reference.materialId === material.material_id &&
                          reference.revision === materialRevision(material),
                      )?.units.length ?? 0;
                    return (
                      <button
                        type="button"
                        key={material.material_id}
                        onClick={() =>
                          setActiveMaterialId(material.material_id)
                        }
                        className={`flex w-full items-center gap-3 px-3 py-3 text-left transition-colors ${
                          active
                            ? "bg-[var(--primary)]/8"
                            : "hover:bg-[var(--muted)]/40"
                        }`}
                      >
                        <BookMarked className="h-4 w-4 shrink-0 text-[var(--muted-foreground)]" />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13px] font-medium text-[var(--foreground)]">
                            {material.title || material.filename}
                          </span>
                          <span className="mt-0.5 block text-[11px] text-[var(--muted-foreground)]">
                            {material.unit_count} {t("sections")}
                          </span>
                        </span>
                        {count > 0 ? (
                          <span className="rounded-full bg-[var(--primary)]/10 px-1.5 py-px text-[9px] font-semibold text-[var(--primary)]">
                            {count}
                          </span>
                        ) : null}
                        <ChevronRight className="h-4 w-4 text-[var(--muted-foreground)]" />
                      </button>
                    );
                  })}
                </div>
              ) : (
                <div className="px-5 py-10 text-center text-[13px] text-[var(--muted-foreground)]">
                  {t("No reading materials found.")}
                </div>
              )}
            </div>
          </aside>

          <section className="min-h-0 overflow-y-auto p-5">
            {!activeMaterial ? (
              <div className="flex h-full items-center justify-center text-sm text-[var(--muted-foreground)]">
                {t("Select a reading material to view sections.")}
              </div>
            ) : loadingDetail && !activeDetail ? (
              <div className="flex h-full items-center justify-center">
                <Loader2 className="h-5 w-5 animate-spin text-[var(--muted-foreground)]" />
              </div>
            ) : activeDetail ? (
              <div className="space-y-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <h3 className="truncate text-base font-semibold text-[var(--foreground)]">
                      {activeMaterial.title || activeMaterial.filename}
                    </h3>
                    <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                      {activeMaterial.filename}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={toggleAllActive}
                    className="shrink-0 rounded-xl border border-[var(--border)] px-3 py-2 text-xs font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]"
                  >
                    {allActiveSelected ? t("Clear material") : t("Select all")}
                  </button>
                </div>
                <div className="divide-y divide-[var(--border)] overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--background)]/35">
                  {activeUnits.map((unit) => {
                    const checked = selectedKeys.has(
                      unitKey(
                        activeMaterial.material_id,
                        materialRevision(activeMaterial),
                        unit.locator,
                      ),
                    );
                    return (
                      <button
                        type="button"
                        key={unit.locator}
                        onClick={() => toggleUnit(unit)}
                        className={`flex w-full items-start gap-3 px-4 py-3 text-left transition-colors ${
                          checked
                            ? "bg-[var(--primary)]/8"
                            : "hover:bg-[var(--muted)]/30"
                        }`}
                      >
                        <span
                          className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-colors ${
                            checked
                              ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                              : "border-[var(--border)] text-transparent"
                          }`}
                        >
                          <Check size={12} />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block text-[13px] font-medium text-[var(--foreground)]">
                            {unit.title}
                          </span>
                          <span className="mt-0.5 block text-[11px] text-[var(--muted-foreground)]">
                            {t("{{unit}} {{locator}}", {
                              unit: t(activeMaterial.unit),
                              locator: unit.locator,
                            })}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ) : null}
          </section>
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-[var(--border)] px-5 py-4">
          <div className="text-sm text-[var(--muted-foreground)]">
            {selectedCount
              ? t("{{count}} reading sections selected", {
                  count: selectedCount,
                })
              : t("No reading sections selected")}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setSelected([]);
                setError(null);
              }}
              className="rounded-xl border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            >
              {t("Clear")}
            </button>
            <button
              type="button"
              onClick={() => {
                onApply(selected);
                onClose();
              }}
              className="rounded-xl bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] transition-opacity hover:opacity-90"
            >
              {t("Apply")}
            </button>
          </div>
        </div>
      </div>
    </PickerShell>
  );
}
