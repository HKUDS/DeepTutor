"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Server } from "lucide-react";
import Modal from "@/components/common/Modal";
import { listKiwixArchives, probeKiwix } from "@/features/knowledge/api/catalog";
import type { KiwixArchive } from "@/features/knowledge/api/client";

interface Props {
  onClose: () => void;
  onConnect: (params: { name: string; serverUrl: string; zimName: string }) => Promise<void>;
}

export default function ConnectKiwixModal({ onClose, onConnect }: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [serverUrl, setServerUrl] = useState("");
  const [zimName, setZimName] = useState("");
  const [verifiedTitle, setVerifiedTitle] = useState("");
  const [catalogQuery, setCatalogQuery] = useState("");
  const [archives, setArchives] = useState<KiwixArchive[]>([]);
  const [catalogSearched, setCatalogSearched] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const [busy, setBusy] = useState<"probe" | "connect" | null>(null);
  const [error, setError] = useState("");

  const inputClass = "mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]";
  const fieldChanged = () => { setVerifiedTitle(""); setError(""); };
  const browse = async () => {
    setBrowsing(true);
    setError("");
    setCatalogSearched(false);
    try {
      setArchives(await listKiwixArchives(serverUrl.trim(), catalogQuery.trim()));
      setCatalogSearched(true);
    } catch (cause) {
      setArchives([]);
      setError(cause instanceof Error ? cause.message : t("Could not browse Kiwix archives"));
    } finally {
      setBrowsing(false);
    }
  };
  const probe = async () => {
    setBusy("probe");
    setError("");
    try {
      const result = await probeKiwix({ serverUrl: serverUrl.trim(), zimName: zimName.trim() });
      setVerifiedTitle(result.title);
    } catch (cause) {
      setVerifiedTitle("");
      setError(cause instanceof Error ? cause.message : t("Could not reach Kiwix archive"));
    } finally {
      setBusy(null);
    }
  };
  const connect = async () => {
    setBusy("connect");
    setError("");
    try {
      await onConnect({ name: name.trim(), serverUrl: serverUrl.trim(), zimName: zimName.trim() });
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("Could not connect Kiwix archive"));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal isOpen onClose={onClose} title={t("Connect Kiwix archive")} titleIcon={<Server className="h-4 w-4" />} footer={
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onClose} disabled={!!busy} className="rounded-lg px-3 py-2 text-[13px] text-[var(--muted-foreground)]">{t("Cancel")}</button>
        <button type="button" onClick={() => void connect()} disabled={!!busy || !name.trim() || !serverUrl.trim() || !zimName.trim()} className="rounded-lg bg-[var(--primary)] px-3 py-2 text-[13px] font-medium text-[var(--primary-foreground)] disabled:opacity-50">
          {busy === "connect" && <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />}{t("Connect archive")}
        </button>
      </div>
    }>
      <div className="space-y-4 p-4">
        <p className="text-[12px] text-[var(--muted-foreground)]">{t("Each knowledge base connects one searchable ZIM on one kiwix-serve instance. Connect other archives or servers separately. DeepTutor reads matching articles on demand.")}</p>
        <label className="block text-[12px] font-medium">{t("Knowledge base name")}
          <input value={name} onChange={(event) => { setName(event.target.value); setError(""); }} className={inputClass} placeholder={t("my-archive")} data-autofocus />
        </label>
        <label className="block text-[12px] font-medium">{t("Kiwix server URL")}
          <input value={serverUrl} onChange={(event) => { setServerUrl(event.target.value); setZimName(""); setArchives([]); setCatalogSearched(false); fieldChanged(); }} className={inputClass} placeholder={t("http://localhost:8080")} />
        </label>
        <div className="flex gap-2">
          <label className="min-w-0 flex-1 text-[12px] font-medium">{t("Find archive")}
            <input value={catalogQuery} onChange={(event) => setCatalogQuery(event.target.value)} className={inputClass} placeholder={t("Search loaded archives")} />
          </label>
          <button type="button" onClick={() => void browse()} disabled={!serverUrl.trim() || !!busy || browsing} className="mt-5 shrink-0 rounded-lg border border-[var(--border)] px-3 py-2 text-[12px] font-medium disabled:opacity-50">
            {browsing && <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />}{t("Browse archives")}
          </button>
        </div>
        {archives.length > 0 && (
          <label className="block text-[12px] font-medium">{t("Loaded archives")}
            <select value={archives.some((archive) => archive.zim_name === zimName) ? zimName : ""} onChange={(event) => { setZimName(event.target.value); fieldChanged(); }} className={inputClass}>
              <option value="">{t("Choose archive")}</option>
              {archives.map((archive) => <option key={archive.zim_name} value={archive.zim_name}>{archive.title} ({archive.zim_name})</option>)}
            </select>
          </label>
        )}
        {catalogSearched && archives.length === 0 && <p className="text-[11px] text-[var(--muted-foreground)]">{t("No archives returned. Enter the ZIM name manually or search by title.")}</p>}
        <label className="block text-[12px] font-medium">{t("ZIM name")}
          <input value={zimName} onChange={(event) => { setZimName(event.target.value); fieldChanged(); }} className={inputClass} placeholder={t("wikipedia_en_all")} />
        </label>
        <div className="flex items-center gap-3">
          <button type="button" onClick={() => void probe()} disabled={!!busy || !serverUrl.trim() || !zimName.trim()} className="rounded-lg border border-[var(--border)] px-3 py-2 text-[12px] font-medium disabled:opacity-50">
            {busy === "probe" && <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />}{t("Check connection")}
          </button>
          {verifiedTitle && <span className="min-w-0 truncate text-[12px] text-emerald-600">{t("Ready")}: {verifiedTitle}</span>}
        </div>
        {error && <p role="alert" className="text-[12px] text-red-600">{error}</p>}
      </div>
    </Modal>
  );
}
