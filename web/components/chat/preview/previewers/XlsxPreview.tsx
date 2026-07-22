"use client";

import { useEffect, useState } from "react";
import { AlertCircle, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useBinarySource } from "./useBinarySource";

// Preview bounds — a spreadsheet can hold millions of cells; rendering them
// all would lock the tab. We cap and flag truncation; Download gets the rest.
const MAX_ROWS = 1000;
const MAX_COLS = 60;

interface SheetModel {
  name: string;
  rows: string[][];
  truncated: boolean;
}

/**
 * XLSX preview via ``exceljs`` (lazy-loaded). Each worksheet is rendered as a
 * lightweight HTML table with a sticky header row; a tab strip switches
 * between sheets. Cell display text only — formulas resolve to their cached
 * value, formatting is dropped (this is a quick look, not an editor).
 */
export default function XlsxPreview({ url }: { url: string }) {
  const { t } = useTranslation();
  const src = useBinarySource(url);
  const [sheets, setSheets] = useState<SheetModel[] | null>(null);
  const [active, setActive] = useState(0);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (src.kind === "error") {
      setFailed(true);
      return;
    }
    if (src.kind !== "ready") return;

    let cancelled = false;
    setFailed(false);
    setSheets(null);
    (async () => {
      try {
        const mod = await import("exceljs");
        const ExcelJS =
          (mod as unknown as { default?: typeof mod }).default ?? mod;
        if (cancelled) return;
        const wb = new ExcelJS.Workbook();
        await wb.xlsx.load(src.buffer);
        if (cancelled) return;

        const parsed: SheetModel[] = wb.worksheets.map((ws) => {
          const colCount = Math.min(ws.columnCount || 0, MAX_COLS);
          const rows: string[][] = [];
          let truncated = ws.columnCount > MAX_COLS;
          ws.eachRow({ includeEmpty: true }, (row, rowNumber) => {
            if (rowNumber > MAX_ROWS) {
              truncated = true;
              return;
            }
            const cells: string[] = [];
            for (let c = 1; c <= colCount; c += 1) {
              const text = row.getCell(c).text;
              cells.push(typeof text === "string" ? text : String(text ?? ""));
            }
            rows.push(cells);
          });
          return { name: ws.name, rows, truncated };
        });
        if (cancelled) return;
        setSheets(parsed.length ? parsed : []);
        setActive(0);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [src]);

  if (failed) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-8 text-center text-[12px] text-[var(--muted-foreground)]">
        <AlertCircle size={18} strokeWidth={1.7} className="opacity-70" />
        <p>
          {t("Couldn't render this spreadsheet — use Download to open it.")}
        </p>
      </div>
    );
  }

  if (!sheets) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-[12px] text-[var(--muted-foreground)]">
        <Loader2 size={14} className="animate-spin" />
        <span>{t("Loading preview…")}</span>
      </div>
    );
  }

  if (sheets.length === 0) {
    return (
      <div className="flex h-full items-center justify-center px-8 text-center text-[12px] text-[var(--muted-foreground)]">
        {t("This workbook has no sheets to preview.")}
      </div>
    );
  }

  const sheet = sheets[Math.min(active, sheets.length - 1)];

  return (
    <div className="flex h-full flex-col bg-[var(--card)]">
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="border-collapse text-[12px] text-[var(--foreground)]">
          <tbody>
            {sheet.rows.map((cells, r) => (
              <tr key={r}>
                <td className="sticky left-0 z-10 border border-[var(--border)]/50 bg-[var(--muted)]/55 px-2 py-1 text-right text-[10px] tabular-nums text-[var(--muted-foreground)]/70">
                  {r + 1}
                </td>
                {cells.map((cell, c) => (
                  <td
                    key={c}
                    className={`max-w-[280px] truncate border border-[var(--border)]/40 px-2 py-1 ${
                      r === 0
                        ? "bg-[var(--muted)]/35 font-medium"
                        : "bg-[var(--card)]"
                    }`}
                    title={cell}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {sheet.truncated ? (
          <p className="px-3 py-2 text-[11px] text-[var(--muted-foreground)]/70">
            {t("Large sheet — preview truncated. Download for the full file.")}
          </p>
        ) : null}
      </div>

      {/* Sheet tabs — only when the workbook has more than one. */}
      {sheets.length > 1 ? (
        <div className="flex shrink-0 items-center gap-1 overflow-x-auto border-t border-[var(--border)]/40 bg-[var(--muted)]/25 px-2 py-1.5">
          {sheets.map((s, i) => (
            <button
              key={`${s.name}-${i}`}
              type="button"
              onClick={() => setActive(i)}
              className={`shrink-0 rounded-md px-2.5 py-1 text-[11.5px] font-medium transition-colors ${
                i === active
                  ? "bg-[var(--card)] text-[var(--foreground)] shadow-sm"
                  : "text-[var(--muted-foreground)] hover:bg-[var(--card)]/70 hover:text-[var(--foreground)]"
              }`}
              title={s.name}
            >
              <span className="block max-w-[140px] truncate">{s.name}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
