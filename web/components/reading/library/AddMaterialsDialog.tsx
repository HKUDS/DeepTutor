"use client";

import {
  Check,
  Library,
  Link2,
  Loader2,
  Search,
  Upload,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
} from "react";
import { useTranslation } from "react-i18next";

import { uploadMaterial } from "@/lib/reading-api";
import {
  addReadingWorkspaceMaterial,
  checkReadingDuplicates,
  createReadingWorkspace,
  importReadingUrls,
  listReadingLibraryMaterials,
  readingContentId,
  type ReadingDuplicateMatch,
  type ReadingLibraryMaterial,
  type ReadingWorkspace,
} from "@/lib/reading-workspace-api";

import {
  formatBytes,
  MaterialGlyph,
  materialDetail,
  sourceKindKey,
} from "./shared";

const ACCEPT =
  ".pdf,.epub,.ppt,.pptx,.doc,.docx,.txt,.md,.html,.htm,.mp3,.wav,.m4a,.aac,.ogg,.mp4,.mov,.m4v,.webm,.mkv";

type PendingItem = {
  key: string;
  kind: "file" | "url" | "library";
  label: string;
  file?: File;
  url?: string;
  material?: ReadingLibraryMaterial;
  sizeBytes?: number;
  contentId?: string;
  match?: ReadingDuplicateMatch;
  /** Only meaningful once `match` is set. */
  decision: "reuse" | "separate";
};

export type AddMaterialsMode = "create" | "add" | "upload";

/**
 * One dialog for every way material enters Immersive Reading: a new
 * collection, an existing collection, or the library on its own. Files and
 * links share a single drop area — asking the user to first classify what they
 * are holding is the system's problem, not theirs.
 */
export function AddMaterialsDialog({
  mode,
  workspaceId,
  onClose,
  onDone,
}: {
  mode: AddMaterialsMode;
  workspaceId?: string;
  onClose: () => void;
  onDone: (result: { workspace?: ReadingWorkspace }) => void;
}) {
  const { t } = useTranslation();
  const fileInput = useRef<HTMLInputElement | null>(null);
  const [title, setTitle] = useState("");
  const [items, setItems] = useState<PendingItem[]>([]);
  const [linkDraft, setLinkDraft] = useState("");
  const [dragging, setDragging] = useState(false);
  const [checking, setChecking] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const [showPicker, setShowPicker] = useState(false);

  const heading =
    mode === "create"
      ? t("New collection")
      : mode === "add"
        ? t("Add material")
        : t("Upload material");

  const addFiles = useCallback((files: File[]) => {
    if (!files.length) return;
    setItems((current) => [
      ...current,
      ...files.map((file) => ({
        key: `file:${file.name}:${file.size}:${current.length}`,
        kind: "file" as const,
        label: file.name,
        file,
        sizeBytes: file.size,
        decision: "reuse" as const,
      })),
    ]);
  }, []);

  const addLink = useCallback(() => {
    const urls = linkDraft
      .split(/[\s\n]+/)
      .map((value) => value.trim())
      .filter((value) => /^https?:\/\//i.test(value));
    if (!urls.length) return;
    setItems((current) => [
      ...current,
      ...urls.map((url, index) => ({
        key: `url:${url}:${current.length + index}`,
        kind: "url" as const,
        label: url.replace(/^https?:\/\//, ""),
        url,
        decision: "reuse" as const,
      })),
    ]);
    setLinkDraft("");
  }, [linkDraft]);

  // Hash new files in the browser and ask the server what it already holds, so
  // a duplicate is surfaced while the user can still decide — not after the
  // upload silently collapsed onto an existing row.
  useEffect(() => {
    const unchecked = items.filter(
      (item) => item.kind !== "library" && item.match === undefined,
    );
    if (!unchecked.length) return;
    let alive = true;
    void (async () => {
      setChecking(true);
      try {
        const files = await Promise.all(
          unchecked
            .filter((item) => item.file)
            .map(async (item) => ({
              key: item.key,
              filename: item.file!.name,
              size_bytes: item.file!.size,
              content_id: await readingContentId(item.file!),
            })),
        );
        const urls = unchecked
          .filter((item) => item.url)
          .map((item) => item.url as string);
        const matches = await checkReadingDuplicates({
          files: files.map(({ key: _key, ...rest }) => rest),
          urls,
        });
        if (!alive) return;
        setItems((current) =>
          current.map((item) => {
            if (item.kind === "library" || item.match !== undefined)
              return item;
            const hashed = files.find((row) => row.key === item.key);
            const match = matches.find((row) =>
              item.url
                ? row.query.url === item.url
                : row.query.filename === item.file?.name,
            );
            return {
              ...item,
              contentId: hashed?.content_id,
              match: match ?? ({} as ReadingDuplicateMatch),
            };
          }),
        );
      } catch {
        // Duplicate detection is an assist, never a gate: on failure every item
        // just uploads as new.
        if (alive) {
          setItems((current) =>
            current.map((item) =>
              item.match === undefined
                ? { ...item, match: {} as ReadingDuplicateMatch }
                : item,
            ),
          );
        }
      } finally {
        if (alive) setChecking(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [items]);

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    const dropped = Array.from(event.dataTransfer.files ?? []);
    if (dropped.length) {
      addFiles(dropped);
      return;
    }
    const text = event.dataTransfer.getData("text/plain").trim();
    if (/^https?:\/\//i.test(text)) setLinkDraft(text);
  };

  const removeItem = (key: string) =>
    setItems((current) => current.filter((item) => item.key !== key));

  const setDecision = (key: string, decision: "reuse" | "separate") =>
    setItems((current) =>
      current.map((item) => (item.key === key ? { ...item, decision } : item)),
    );

  const pickLibrary = (material: ReadingLibraryMaterial) => {
    setShowPicker(false);
    setItems((current) =>
      current.some(
        (item) => item.material?.material_id === material.material_id,
      )
        ? current
        : [
            ...current,
            {
              key: `library:${material.material_id}`,
              kind: "library" as const,
              label: material.title,
              material,
              decision: "reuse" as const,
            },
          ],
    );
  };

  const submit = async () => {
    if (working || !items.length) return;
    setWorking(true);
    setError("");
    try {
      const materialIds: string[] = [];
      const urlsToImport: string[] = [];

      for (const item of items) {
        if (item.kind === "library" && item.material) {
          materialIds.push(item.material.material_id);
          continue;
        }
        const matched = item.match?.material;
        if (matched && item.decision === "reuse") {
          materialIds.push(matched.material_id);
          continue;
        }
        if (item.url) {
          urlsToImport.push(item.url);
          continue;
        }
        if (item.file) {
          const uploaded = await uploadMaterial(item.file, {
            reuse: item.decision === "reuse",
          });
          materialIds.push(uploaded.material_id);
        }
      }

      let workspace: ReadingWorkspace | undefined;
      if (mode === "create") {
        const name =
          title.trim() || items[0].label.replace(/\.[^.]+$/, "").slice(0, 80);
        if (urlsToImport.length) {
          const imported = await importReadingUrls({
            urls: urlsToImport,
            workspace_title: name,
          });
          workspace = imported.workspace;
          for (const materialId of materialIds) {
            workspace = await addReadingWorkspaceMaterial(
              workspace.workspace_id,
              materialId,
            );
          }
        } else {
          workspace = await createReadingWorkspace({
            title: name,
            material_ids: materialIds,
          });
        }
      } else if (mode === "add" && workspaceId) {
        if (urlsToImport.length) {
          const imported = await importReadingUrls({
            urls: urlsToImport,
            workspace_id: workspaceId,
          });
          workspace = imported.workspace;
        }
        for (const materialId of materialIds) {
          workspace = await addReadingWorkspaceMaterial(
            workspaceId,
            materialId,
            true,
          );
        }
      } else if (urlsToImport.length) {
        // Library-only upload: the URL importer always lands in a collection,
        // so a plain upload of links makes one named after the first link.
        await importReadingUrls({
          urls: urlsToImport,
          workspace_title: items[0].label.slice(0, 80),
        });
      }

      onDone({ workspace });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("Import failed."));
    } finally {
      setWorking(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-[var(--overlay)] p-4">
      <div className="flex max-h-[90vh] w-full max-w-xl flex-col overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-lg dark:bg-[var(--popover)]">
        <div className="flex items-start justify-between border-b border-[var(--border)] px-5 py-4">
          <div>
            <h2 className="font-serif text-[18px] font-semibold">{heading}</h2>
            <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
              {mode === "create"
                ? t(
                    "A collection holds several materials you read and discuss together.",
                  )
                : mode === "add"
                  ? t("Files, links and materials already in your library.")
                  : t(
                      "Uploaded material stays in your library until you put it in a collection.",
                    )}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("Close")}
            className="flex size-7 items-center justify-center rounded-lg text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
          >
            <X size={14} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {mode === "create" && (
            <label className="block text-[11px] text-[var(--muted-foreground)]">
              {t("Collection name")}
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder={t("Optional — taken from the first material")}
                className="mt-1.5 h-9 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 text-[12.5px] text-[var(--foreground)] outline-none focus:border-[var(--ring)]"
              />
            </label>
          )}

          <input
            ref={fileInput}
            type="file"
            multiple
            className="hidden"
            accept={ACCEPT}
            onChange={(event) => {
              addFiles(Array.from(event.target.files ?? []));
              event.target.value = "";
            }}
          />
          <div
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={`mt-4 rounded-xl border border-dashed px-5 py-6 text-center transition ${
              dragging
                ? "border-[var(--primary)] bg-[var(--muted)]"
                : "border-[var(--border)]"
            }`}
          >
            <button
              type="button"
              onClick={() => fileInput.current?.click()}
              className="flex w-full flex-col items-center"
            >
              <Upload size={18} className="text-[var(--primary)]" />
              <span className="mt-2.5 text-[12.5px] font-semibold">
                {t("Drop PDF, EPUB, Word, slides, audio or video here")}
              </span>
              <span className="mt-1 text-[10.5px] text-[var(--muted-foreground)]">
                {t("or click to choose files")}
              </span>
            </button>
            <div className="mx-auto mt-3.5 flex h-8 max-w-[340px] items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--background)] px-2.5">
              <Link2
                size={12}
                className="shrink-0 text-[var(--muted-foreground)]"
              />
              <input
                value={linkDraft}
                onChange={(event) => setLinkDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.nativeEvent.isComposing) {
                    event.preventDefault();
                    addLink();
                  }
                }}
                onBlur={addLink}
                placeholder={t("or paste a link — web page, YouTube, Bilibili")}
                className="min-w-0 flex-1 bg-transparent text-[11.5px] outline-none placeholder:text-[var(--muted-foreground)]"
              />
              {!!linkDraft && (
                <button
                  type="button"
                  onClick={addLink}
                  className="shrink-0 text-[11px] font-semibold text-[var(--primary)]"
                >
                  {t("Add")}
                </button>
              )}
            </div>
          </div>

          {!!items.length && (
            <ul className="mt-3.5 space-y-1.5">
              {items.map((item) => (
                <PendingRow
                  key={item.key}
                  item={item}
                  onRemove={() => removeItem(item.key)}
                  onDecide={(decision) => setDecision(item.key, decision)}
                />
              ))}
            </ul>
          )}

          {checking && (
            <p className="mt-2.5 flex items-center gap-1.5 text-[10.5px] text-[var(--muted-foreground)]">
              <Loader2 size={11} className="animate-spin" />
              {t("Checking your library for duplicates…")}
            </p>
          )}

          <button
            type="button"
            onClick={() => setShowPicker((current) => !current)}
            className="mt-4 flex w-full items-center gap-2 border-t border-[var(--border)] pt-3.5 text-[11.5px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
          >
            <Library size={13} />
            {t("Choose from material you already uploaded")}
            <span className="ml-auto">{showPicker ? "−" : "›"}</span>
          </button>
          {showPicker && <LibraryPicker onPick={pickLibrary} />}

          {error && (
            <p className="mt-3 text-[11px] text-[var(--destructive)]">
              {error}
            </p>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-[var(--border)] px-5 py-3.5">
          <button
            type="button"
            onClick={onClose}
            className="h-8 rounded-lg px-3 text-[11.5px] text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
          >
            {t("Cancel")}
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={working || !items.length}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3.5 text-[11.5px] font-semibold text-[var(--primary-foreground)] disabled:opacity-50"
          >
            {working && <Loader2 size={12} className="animate-spin" />}
            {mode === "create"
              ? t("Create and start reading")
              : mode === "add"
                ? t("Add to a collection")
                : t("Upload")}
          </button>
        </div>
      </div>
    </div>
  );
}

function PendingRow({
  item,
  onRemove,
  onDecide,
}: {
  item: PendingItem;
  onRemove: () => void;
  onDecide: (decision: "reuse" | "separate") => void;
}) {
  const { t } = useTranslation();
  const matched = item.match?.material;
  const collections = item.match?.collections ?? [];
  const where = collections.map((row) => row.title).join("、");

  return (
    <li className="rounded-lg bg-[var(--muted)] px-3 py-2">
      <div className="flex items-center gap-2">
        {matched ? (
          <MaterialGlyph
            material={matched}
            size={13}
            className="shrink-0 text-[var(--muted-foreground)]"
          />
        ) : item.url ? (
          <Link2
            size={13}
            className="shrink-0 text-[var(--muted-foreground)]"
          />
        ) : (
          <Upload
            size={13}
            className="shrink-0 text-[var(--muted-foreground)]"
          />
        )}
        <span className="min-w-0 flex-1 truncate text-[11.5px]">
          {item.label}
        </span>
        {!!item.sizeBytes && (
          <span className="shrink-0 text-[10.5px] text-[var(--muted-foreground)]">
            {formatBytes(item.sizeBytes)}
          </span>
        )}
        <button
          type="button"
          onClick={onRemove}
          aria-label={t("Remove")}
          className="shrink-0 text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
        >
          <X size={12} />
        </button>
      </div>

      {matched && item.match?.kind === "same_content" && (
        <p className="mt-1.5 flex flex-wrap items-center gap-1.5 pl-5 text-[10.5px] leading-relaxed text-[var(--muted-foreground)]">
          <Check size={11} className="text-[var(--primary)]" />
          {/* Naming the match matters: the file the user picked and the copy
              already in the library often have different names. */}
          {where
            ? t(
                "Already in your library as “{{title}}”, used by {{where}}. It will be reused, with its annotations.",
                { title: matched.title, where },
              )
            : t(
                "Already in your library as “{{title}}”. It will be reused, with its annotations.",
                { title: matched.title },
              )}
          <button
            type="button"
            onClick={() =>
              onDecide(item.decision === "reuse" ? "separate" : "reuse")
            }
            className="font-semibold text-[var(--primary)]"
          >
            {item.decision === "reuse"
              ? t("Add a separate copy instead")
              : t("Reuse the existing one")}
          </button>
        </p>
      )}

      {matched && item.match?.kind === "same_name" && (
        <div className="mt-1.5 pl-5">
          <p className="text-[10.5px] leading-relaxed text-[var(--muted-foreground)]">
            {where
              ? t(
                  "A material with this name is already in {{where}}, but its content differs.",
                  {
                    where,
                  },
                )
              : t(
                  "A material with this name is already in your library, but its content differs.",
                )}
          </p>
          <div className="mt-1.5 flex gap-1.5">
            <DecisionChip
              active={item.decision === "reuse"}
              label={t("Reuse the existing one")}
              detail={[
                matched.title,
                formatBytes(matched.size_bytes),
                matched.unit_count
                  ? t("{{count}} pages", { count: matched.unit_count })
                  : "",
              ]
                .filter(Boolean)
                .join(" · ")}
              onClick={() => onDecide("reuse")}
            />
            <DecisionChip
              active={item.decision === "separate"}
              label={t("Upload as a new one")}
              detail={formatBytes(item.sizeBytes)}
              onClick={() => onDecide("separate")}
            />
          </div>
        </div>
      )}
    </li>
  );
}

function DecisionChip({
  active,
  label,
  detail,
  onClick,
}: {
  active: boolean;
  label: string;
  detail: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`min-w-0 flex-1 rounded-lg border px-2.5 py-1.5 text-left transition ${
        active
          ? "border-[var(--primary)] text-[var(--foreground)]"
          : "border-[var(--border)] text-[var(--muted-foreground)]"
      }`}
    >
      <span className="flex items-center gap-1.5 text-[10.5px] font-semibold">
        {active && <Check size={10} className="text-[var(--primary)]" />}
        {label}
      </span>
      {!!detail && (
        <span className="mt-0.5 block truncate text-[10px] text-[var(--muted-foreground)]">
          {detail}
        </span>
      )}
    </button>
  );
}

function LibraryPicker({
  onPick,
}: {
  onPick: (material: ReadingLibraryMaterial) => void;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<ReadingLibraryMaterial[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    void listReadingLibraryMaterials()
      .then((payload) => {
        if (alive) setRows(payload.materials);
      })
      .catch(() => undefined)
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((row) =>
      `${row.title} ${row.filename} ${row.source_url}`
        .toLowerCase()
        .includes(needle),
    );
  }, [query, rows]);

  return (
    <div className="mt-2.5 rounded-lg border border-[var(--border)]">
      <label className="flex h-8 items-center gap-2 border-b border-[var(--border)] px-2.5">
        <Search size={12} className="shrink-0 text-[var(--muted-foreground)]" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("Search your library")}
          className="min-w-0 flex-1 bg-transparent text-[11.5px] outline-none placeholder:text-[var(--muted-foreground)]"
        />
      </label>
      <div className="max-h-44 overflow-y-auto">
        {loading ? (
          <p className="px-3 py-3 text-[10.5px] text-[var(--muted-foreground)]">
            {t("Loading…")}
          </p>
        ) : !filtered.length ? (
          <p className="px-3 py-3 text-[10.5px] text-[var(--muted-foreground)]">
            {t("Nothing here yet.")}
          </p>
        ) : (
          filtered.map((material) => (
            <button
              key={material.material_id}
              type="button"
              onClick={() => onPick(material)}
              className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-[var(--muted)]"
            >
              <MaterialGlyph
                material={material}
                size={13}
                className="shrink-0 text-[var(--muted-foreground)]"
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[11.5px]">
                  {material.title}
                </span>
                <span className="block truncate text-[10px] text-[var(--muted-foreground)]">
                  {materialDetail(material) ||
                    t(sourceKindKey[material.source_kind])}
                </span>
              </span>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
