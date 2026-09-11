"use client";

import type { UnitKind } from "@/lib/reading-api";

export const MAX_READING_REFERENCE_MATERIALS = 8;
export const MAX_READING_REFERENCE_UNITS = 24;

export interface SelectedReadingUnit {
  locator: number;
  title: string;
}

export interface SelectedReadingReference {
  materialId: string;
  revision: number;
  materialTitle: string;
  unit: UnitKind;
  units: SelectedReadingUnit[];
}

export interface ReadingReferencePayload {
  material_id: string;
  revision: number;
  locators: number[];
}

export function selectedReadingsToPayload(
  references: SelectedReadingReference[],
): ReadingReferencePayload[] {
  return normalizeReadingReferences(
    references.map((reference) => ({
      material_id: reference.materialId,
      revision: reference.revision,
      locators: reference.units.map((unit) => unit.locator),
    })),
  );
}

export function countSelectedReadingUnits(
  references: SelectedReadingReference[],
): number {
  return references.reduce(
    (total, reference) => total + reference.units.length,
    0,
  );
}

export function normalizeReadingReferences(
  value: unknown,
): ReadingReferencePayload[] {
  if (!Array.isArray(value)) return [];
  const byReference = new Map<string, ReadingReferencePayload>();
  const materialIds = new Set<string>();
  let total = 0;

  for (const item of value) {
    if (!item || typeof item !== "object") continue;
    const record = item as Record<string, unknown>;
    const materialId =
      typeof record.material_id === "string"
        ? record.material_id.trim().toLowerCase()
        : "";
    if (!/^[0-9a-f]{8,64}$/.test(materialId)) continue;
    const revision = record.revision;
    if (
      typeof revision !== "number" ||
      !Number.isSafeInteger(revision) ||
      revision <= 0
    ) {
      continue;
    }
    if (!Array.isArray(record.locators)) continue;
    const key = `${materialId}:${revision}`;
    let reference = byReference.get(key);
    if (
      !reference &&
      !materialIds.has(materialId) &&
      materialIds.size >= MAX_READING_REFERENCE_MATERIALS
    ) {
      continue;
    }
    for (const raw of record.locators) {
      if (
        typeof raw !== "number" ||
        !Number.isSafeInteger(raw) ||
        raw <= 0 ||
        reference?.locators.includes(raw)
      ) {
        continue;
      }
      if (total >= MAX_READING_REFERENCE_UNITS) break;
      if (!reference) {
        reference = { material_id: materialId, revision, locators: [] };
        byReference.set(key, reference);
        materialIds.add(materialId);
      }
      reference.locators.push(raw);
      total += 1;
    }
  }

  return [...byReference.values()].filter(
    (reference) => reference.locators.length > 0,
  );
}
