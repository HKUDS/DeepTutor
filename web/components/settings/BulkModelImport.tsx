"use client";

import type { ApiFormat } from "@/lib/model-catalog-types";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useSettings, type ServiceName } from "@/features/settings/store/SettingsStore";
import { providerProbeInput, updateProvider, type ProviderSource } from "@/lib/provider-registry";
import { RegistryProbe, registryButton, registryPrimary } from "./RegistryControls";
import { inputClass } from "./shared";

type Props = {
  source: ProviderSource;
  service: ServiceName;
  existingModels: string[];
  onImport: (models: string[]) => void;
};

export function BulkModelImport(props: Props) {
  const { providers } = useSettings();
  const { source, service } = props;
  const sourceService = source.service ||
    ("source_service" in source.source && source.source.source_service) || "llm";
  const option = providers[sourceService]?.find((p) => p.value === source.provider) ||
    providers[service]?.find((p) => p.value === source.provider);
  const apiFormat = source.source.api_format || (option?.default_api_format as ApiFormat) || "auto";
  const input = {
    ...providerProbeInput(source, option?.base_urls?.[apiFormat] || option?.base_url),
    api_format: apiFormat,
  };
  // Provider, service and credential changes discard selections and pending probes.
  return <ImportForm key={JSON.stringify([source.id, service, input])} {...props} input={input} />;
}

function ImportForm({ source, service, existingModels, onImport, input }: Props & {
  input: ReturnType<typeof providerProbeInput>;
}) {
  const { t } = useTranslation();
  const { mutateCatalog } = useSettings();
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const discovery = source.source.discovery;
  const kind = service === "task" ? "llm" : service;
  const candidates = discovery?.status === "connected"
    ? (discovery.models || []).filter((model) => !model.services?.length || model.services.includes(kind))
    : [];
  const models = [...new Set(candidates.map((model) => model.id.trim()).filter(Boolean))];
  const existing = new Set(existingModels);
  const available = models.filter((id) => !existing.has(id));
  const selected = picked.filter((id) => available.includes(id));
  const filtered = models.filter((id) => id.toLowerCase().includes(query.trim().toLowerCase()));
  const selectable = filtered.filter((id) => !existing.has(id));
  return (
    <div className="mt-4 space-y-3">
      <RegistryProbe
        input={input}
        discovery={discovery}
        listing
        automatic
        onResult={(result) => {
          setPicked([]);
          mutateCatalog((next) => updateProvider(next, source.ref, "discovery", result));
        }}
      />
      {discovery?.status === "connected" && (
        <fieldset className="min-w-0 space-y-3">
          <legend className="text-[13px] font-medium">{t("settings.modelImport.title")}</legend>
          <input
            type="search"
            aria-label={t("Search models…")}
            placeholder={t("Search models…")}
            className={inputClass}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <div className="flex flex-wrap gap-2">
            <button type="button" className={registryButton}
              disabled={!selectable.some((id) => !selected.includes(id))}
              onClick={() => setPicked([...new Set([...selected, ...selectable])])}>
              {t("settings.modelImport.selectFiltered")}
            </button>
            <button type="button" className={registryButton} disabled={!selected.length}
              onClick={() => setPicked([])}>{t("settings.modelImport.clear")}</button>
          </div>
          <div className="max-h-60 overflow-y-auto rounded-lg border border-[var(--border)] p-2">
            {filtered.map((id) => (
              <label key={id} className="flex items-center gap-2 rounded-md px-2 py-2 text-[13px] hover:bg-[var(--accent)]">
                <input type="checkbox" disabled={existing.has(id)}
                  checked={existing.has(id) || selected.includes(id)}
                  onChange={(event) => setPicked(event.target.checked ? [...selected, id] : selected.filter((value) => value !== id))} />
                <span className="min-w-0 flex-1 break-all">{id}</span>
                {existing.has(id) && <span className="text-[var(--muted-foreground)]">{t("Added")}</span>}
              </label>
            ))}
            {!filtered.length && <p className="p-2 text-[13px] text-[var(--muted-foreground)]">{t("No matching models")}</p>}
          </div>
          {candidates.some((model) => !model.services?.length) && (
            <p className="text-[13px] text-[var(--muted-foreground)]">{t("settings.modelImport.unverified")}</p>
          )}
          <p className="text-[13px] text-[var(--muted-foreground)]">{t("settings.modelImport.draftHint")}</p>
          <div className="flex flex-wrap items-center gap-3">
            <button type="button" className={registryPrimary} disabled={!selected.length}
              onClick={() => onImport(selected)}>{t("Add selected models")}</button>
            <span role="status" className="text-[13px]">{t("settings.modelImport.selected", { count: selected.length })}</span>
          </div>
        </fieldset>
      )}
    </div>
  );
}
