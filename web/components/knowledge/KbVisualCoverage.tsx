"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch, apiUrl } from "@/shared/api/client";
import { knowledgeBaseFilePath } from "@/features/knowledge/api/files";

interface Coverage {
  documents: { source_path: string; retained_count: number; page_fallback: boolean; issues: { status: string; reason: string; page?: number; asset?: string }[] }[];
  assets: { asset_id: string; source_path: string; caption: string; page_number?: number }[];
  total_assets: number;
  offset: number;
  limit: number;
}

export default function KbVisualCoverage({ kbName, sourcePath, revision }: { kbName: string; sourcePath: string; revision: number }) {
  const { t } = useTranslation();
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const key = `${kbName}\0${sourcePath}\0${revision}\0${offset}`;
  const [result, setResult] = useState<{ key: string; data?: Coverage; error?: boolean }>();
  const current = result?.key === key ? result : undefined;
  useEffect(() => {
    if (!expanded) return;
    const controller = new AbortController();
    const query = new URLSearchParams({ source_path: sourcePath, offset: String(offset), limit: "20" });
    void apiFetch(`/api/knowledge-bases/${encodeURIComponent(kbName)}/visual-coverage?${query}`, { cache: "no-store", signal: controller.signal })
      .then(async (response) => { if (!response.ok) throw new Error(String(response.status)); return response.json() as Promise<Coverage>; })
      .then((data) => { if (!controller.signal.aborted) setResult({ key, data }); })
      .catch(() => { if (!controller.signal.aborted) setResult({ key, error: true }); });
    return () => controller.abort();
  }, [kbName, sourcePath, offset, key, expanded]);
  const data = current?.data;
  const report = data?.documents[0];
  return <details open={expanded} className="shrink-0 border-b border-[var(--border)] p-3 text-sm">
    <summary className="cursor-pointer font-medium" onClick={(event) => { event.preventDefault(); setExpanded((value) => !value); }}>{t("Source visual coverage")}</summary>
    <div className="mt-3 max-h-72 space-y-3 overflow-auto">
      <p>{t("Extracted figures do not prove complete visual coverage. Inspect the original page when labels, vectors or tables are missing.")}</p>
      {current?.error ? <p role="alert">{t("Could not read visual coverage. Open the original document to inspect the source.")}</p>
        : !data ? <p role="status">{t("Loading...")}</p>
        : !report ? <p role="alert">{t("Source document is unavailable. Refresh the file list.")}</p> : <>
          <p>{t("Retained source figures")}: {report.retained_count}</p>
          <a className="underline" href={apiUrl(knowledgeBaseFilePath(kbName, sourcePath))} target="_blank" rel="noreferrer">{t("Open original document")}</a>
          {report.page_fallback && <p>{t("PDF pages and higher-detail regions are available through source inspection in chat.")}</p>}
          {!!report.issues.length && <ul className="space-y-1">{report.issues.map((issue, i) => <li key={i} className="break-words">
            {issue.page && <a className="underline" href={`${apiUrl(knowledgeBaseFilePath(kbName, sourcePath))}#page=${issue.page}`} target="_blank" rel="noreferrer">{t("Page")} {issue.page}: </a>}
            {issue.asset && `${issue.asset}: `}{t(`visualCoverage.${issue.reason}`, { defaultValue: issue.reason })}
          </li>)}</ul>}
          <ul className="space-y-1">{data?.assets.map((asset) => <li key={asset.asset_id}>
            <a className="underline break-words" href={apiUrl(`/api/knowledge-bases/${encodeURIComponent(kbName)}/visual-assets/${asset.asset_id}`)} target="_blank" rel="noreferrer">{asset.caption || t("Source figure")}{asset.page_number ? ` (${t("Page")} ${asset.page_number})` : ""}</a>
          </li>)}</ul>
          {data && data.total_assets > data.limit && <div className="flex items-center gap-3">
            <button disabled={offset === 0} onClick={() => setOffset((n) => Math.max(0, n - 20))}>{t("Previous")}</button>
            <span>{offset + 1}–{Math.min(offset + 20, data.total_assets)} / {data.total_assets}</span>
            <button disabled={offset + 20 >= data.total_assets} onClick={() => setOffset((n) => n + 20)}>{t("Next")}</button>
          </div>}
        </>}
    </div>
  </details>;
}
