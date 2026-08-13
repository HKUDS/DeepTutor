export interface SelectedReadingSection {
  sectionId: string;
  sectionTitle: string;
}
export interface SelectedReadingReference {
  documentId: string;
  documentTitle: string;
  sections: SelectedReadingSection[];
}

export interface ReadingReferencePayload {
  document_id: string;
  section_ids: string[];
}

export function selectedReadingsToPayload(
  references: SelectedReadingReference[],
): ReadingReferencePayload[] {
  return references
    .map((reference) => ({
      document_id: reference.documentId,
      section_ids: Array.from(new Set(reference.sections.map((section) => section.sectionId))).filter(Boolean),
    }))
    .filter((reference) => reference.document_id && reference.section_ids.length > 0);
}

export function normalizeReadingReferences(value: unknown): ReadingReferencePayload[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      const record = item && typeof item === "object" ? (item as Record<string, unknown>) : {};
      const documentId = typeof record.document_id === "string" ? record.document_id : "";
      const sectionIds = Array.isArray(record.section_ids)
        ? record.section_ids.filter((sectionId): sectionId is string => typeof sectionId === "string" && !!sectionId)
        : [];
      return documentId && sectionIds.length
        ? { document_id: documentId, section_ids: Array.from(new Set(sectionIds)) }
        : null;
    })
    .filter((item): item is ReadingReferencePayload => item !== null);
}
