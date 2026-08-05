"use client";

import { useCallback } from "react";
import { useTranslation } from "react-i18next";

/** Bilingual ``tr(cn, en)`` helper matching the existing learning surfaces. */
export type TrFn = (cn: string, en: string) => string;

export function useFeynmanTr(): TrFn {
  const { i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");
  return useCallback((cn: string, en: string) => (zh ? cn : en), [zh]);
}
