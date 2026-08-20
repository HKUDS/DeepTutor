"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { FileText, Loader2, Trash2, Upload } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  deleteMaterial,
  getSupportedFormats,
  listMaterials,
  uploadMaterial,
  type MaterialDetail,
  type MaterialInfo,
} from "@/lib/reading-api";

export interface MaterialPickerProps {
  onOpen: (material: MaterialDetail | MaterialInfo) => void;
  /** Bumped by the parent to force a reload after an external change. */
  refreshToken?: number;
}

/**
 * Empty state of the reader: drop a file in, or reopen one already read.
 *
 * Uploads are content-addressed server-side, so re-adding a file the user has
 * read before reopens it *with its annotations* rather than creating a duplicate.
 * The copy says so, because otherwise the behaviour looks like a bug.
 */
export function MaterialPicker({
  onOpen,
  refreshToken = 0,
}: MaterialPickerProps) {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [materials, setMaterials] = useState<MaterialInfo[]>([]);
  const [accept, setAccept] = useState<string>("");
  const [maxBytes, setMaxBytes] = useState(0);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    try {
      setMaterials(await listMaterials());
    } catch {
      // A listing failure must not block uploading — leave the list empty.
      setMaterials([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload, refreshToken]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const formats = await getSupportedFormats();
        if (cancelled) return;
        setAccept(formats.extensions.join(","));
        setMaxBytes(formats.max_bytes);
      } catch {
        // Leave `accept` empty: the file dialog then shows everything and the
        // server rejects what it cannot read, with a message.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const ingest = useCallback(
    async (file: File | undefined | null) => {
      if (!file || busy) return;
      setBusy(true);
      setError(null);
      try {
        const material = await uploadMaterial(file);
        await reload();
        onOpen(material);
      } catch (uploadError) {
        setError(
          uploadError instanceof Error
            ? uploadError.message
            : t("This file could not be opened."),
        );
      } finally {
        setBusy(false);
      }
    },
    [busy, onOpen, reload, t],
  );

  const remove = useCallback(
    async (materialId: string) => {
      try {
        await deleteMaterial(materialId);
      } catch {
        // Fall through to the reload: if it is already gone, the list is right.
      }
      await reload();
    },
    [reload],
  );

  return (
    <div className="flex h-full flex-col items-center overflow-y-auto px-6 py-8">
      <div className="w-full max-w-[520px]">
        <div
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            void ingest(event.dataTransfer.files?.[0]);
          }}
          onClick={() => inputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              inputRef.current?.click();
            }
          }}
          className={`flex cursor-pointer flex-col items-center justify-center gap-2.5 rounded-2xl border-2 border-dashed px-6 py-10 text-center transition ${
            dragging
              ? "border-[var(--ring)] bg-[var(--primary)]/[0.06]"
              : "border-[var(--border)] hover:border-[var(--ring)]/60 hover:bg-[var(--muted)]/30"
          }`}
        >
          {busy ? (
            <Loader2
              size={20}
              className="animate-spin text-[var(--muted-foreground)]"
            />
          ) : (
            <Upload size={20} className="text-[var(--muted-foreground)]" />
          )}
          <p className="font-serif text-[16px] font-medium text-[var(--foreground)]">
            {busy ? t("Preparing document…") : t("Open a document to read")}
          </p>
          <p className="max-w-[360px] text-[11.5px] leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "Drop a PDF, EPUB, Word, slide deck or text file here. The assistant reads it with you and cites what it uses.",
            )}
            {maxBytes > 0
              ? ` ${t("Up to {{mb}} MB.", { mb: Math.floor(maxBytes / (1024 * 1024)) })}`
              : ""}
          </p>
          <input
            ref={inputRef}
            type="file"
            accept={accept || undefined}
            className="hidden"
            onChange={(event) => {
              void ingest(event.target.files?.[0]);
              // Reset so choosing the same file twice still fires a change.
              event.target.value = "";
            }}
          />
        </div>

        {error && (
          <p
            role="alert"
            className="mt-3 rounded-lg border border-[var(--destructive)]/30 bg-[var(--destructive)]/[0.06] px-3 py-2 text-[11.5px] leading-relaxed text-[var(--destructive)]"
          >
            {error}
          </p>
        )}

        {!loading && materials.length > 0 && (
          <div className="mt-7">
            <h3 className="mb-2 px-1 font-mono text-[10px] uppercase tracking-[0.07em] text-[var(--muted-foreground)]">
              {t("Recently read")}
            </h3>
            <ul className="space-y-1">
              {materials.map((material) => (
                <li key={material.material_id}>
                  <div className="group/mat flex items-center gap-2.5 rounded-xl border border-transparent px-2.5 py-2 transition hover:border-[var(--border)] hover:bg-[var(--muted)]/40">
                    <button
                      type="button"
                      onClick={() => onOpen(material)}
                      className="flex min-w-0 flex-1 items-center gap-2.5 text-left"
                    >
                      <FileText
                        size={15}
                        className="shrink-0 text-[var(--muted-foreground)]"
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[12.5px] font-medium text-[var(--foreground)]">
                          {material.filename}
                        </span>
                        <span className="block truncate font-mono text-[10.5px] text-[var(--muted-foreground)]">
                          {material.unit_count} {material.unit}
                          {material.unit_count === 1 ? "" : "s"}
                          {material.annotation_count > 0
                            ? ` · ${t("{{count}} annotations", {
                                count: material.annotation_count,
                              })}`
                            : ""}
                        </span>
                      </span>
                    </button>
                    <button
                      type="button"
                      title={t("Remove")}
                      aria-label={t("Remove")}
                      onClick={() => void remove(material.material_id)}
                      className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)] opacity-0 transition hover:bg-[var(--destructive)]/10 hover:text-[var(--destructive)] focus-visible:opacity-100 group-hover/mat:opacity-100"
                    >
                      <Trash2 size={12.5} />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
