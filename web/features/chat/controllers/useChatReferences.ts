"use client";

import { useCallback, useMemo, useState } from "react";

export interface ChatReferenceState {
  history: string[];
  notebooks: Array<{ notebook_id: string; record_ids: string[] }>;
  books: Array<{ book_id: string; page_ids: string[] }>;
  readings: Array<{
    material_id: string;
    revision: number;
    locators: number[];
  }>;
}

const EMPTY_REFERENCES: ChatReferenceState = {
  history: [],
  notebooks: [],
  books: [],
  readings: [],
};

export function boundedReferences(
  state: ChatReferenceState,
  limit = 20,
): ChatReferenceState {
  return {
    history: state.history.filter(Boolean).slice(0, limit),
    notebooks: state.notebooks
      .filter((item) => item.notebook_id && item.record_ids.length)
      .slice(0, limit),
    books: state.books
      .filter((item) => item.book_id && item.page_ids.length)
      .slice(0, limit),
    readings: state.readings
      .filter(
        (item) => item.material_id && item.revision > 0 && item.locators.length,
      )
      .slice(0, limit),
  };
}

export function useChatReferences(
  initial: ChatReferenceState = EMPTY_REFERENCES,
) {
  const [references, setReferences] = useState(initial);
  const payload = useMemo(() => boundedReferences(references), [references]);
  const clear = useCallback(() => setReferences(EMPTY_REFERENCES), []);
  return { clear, payload, references, setReferences };
}
