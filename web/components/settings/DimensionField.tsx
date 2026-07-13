"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { CatalogModel, EmbeddingCapabilities } from "./SettingsContext";
import { nativeSelectClass, selectOptionClass } from "./shared";

const CUSTOM_DIM_SENTINEL = "__custom__";
const AUTO_DIM_SENTINEL = "";

function parseSupportedCsv(csv: string | undefined): number[] {
  if (!csv) return [];
  return csv
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => Number(s))
    .filter((n) => Number.isFinite(n) && n > 0);
}

function sourceBadge(
  source: string | undefined,
  t: (key: string) => string,
): { label: string; tone: "muted" | "ok" | "warn" } | null {
  if (source === "detected") {
    return { label: t("Source: detected from API probe"), tone: "ok" };
  }
  return null;
}

export function DimensionField({
  activeModel,
  activeBinding,
  capabilities,
  embeddingDefaultDim,
  inputClass,
  onChangeDimension,
}: {
  activeModel: CatalogModel;
  activeBinding?: string;
  capabilities: EmbeddingCapabilities | null;
  embeddingDefaultDim: (binding?: string) => string;
  inputClass: string;
  onChangeDimension: (value: string) => void;
}) {
  const { t } = useTranslation();
  const fallback = embeddingDefaultDim(activeBinding);
  const rawValue = activeModel.dimension ?? "";
  const isEmpty = rawValue === "";
  const currentNum = isEmpty ? NaN : Number(rawValue);

  const liveSupported = capabilities?.supported_dimensions;
  const cachedSupported = parseSupportedCsv(activeModel.supported_dimensions);
  const supported =
    liveSupported && liveSupported.length > 0 ? liveSupported : cachedSupported;
  const supportsVariable =
    capabilities?.supports_variable_dimensions ?? supported.length > 1;

  const useDropdown = supported.length > 1 && supportsVariable;
  const currentInList =
    Number.isFinite(currentNum) && supported.includes(currentNum);
  const [customRequested, setCustomRequested] = useState<boolean>(false);
  const customMode =
    customRequested || (useDropdown && !isEmpty && !currentInList);

  const detected = capabilities?.detected_dim;
  const showDetectedBadge =
    typeof detected === "number" &&
    detected > 0 &&
    detected !== currentNum &&
    !isEmpty;

  const sourceInfo = sourceBadge(capabilities?.active_dim_source, t);
  const disabled = activeModel.send_dimensions === false;

  const handleSelect = (value: string) => {
    if (value === CUSTOM_DIM_SENTINEL) {
      setCustomRequested(true);
      return;
    }
    setCustomRequested(false);
    onChangeDimension(value);
  };

  const dropdownValue = isEmpty
    ? AUTO_DIM_SENTINEL
    : currentInList
      ? String(currentNum)
      : CUSTOM_DIM_SENTINEL;

  return (
    <div className="space-y-1.5">
      {useDropdown && !customMode ? (
        <select
          className={nativeSelectClass}
          value={dropdownValue}
          onChange={(e) => handleSelect(e.target.value)}
          disabled={disabled}
        >
          <option className={selectOptionClass} value={AUTO_DIM_SENTINEL}>
            {t("Auto (probe on next test)")}
          </option>
          {supported.map((dim) => (
            <option className={selectOptionClass} key={dim} value={String(dim)}>
              {dim}
            </option>
          ))}
          <option className={selectOptionClass} value={CUSTOM_DIM_SENTINEL}>
            {t("Custom…")}
          </option>
        </select>
      ) : (
        <input
          className={inputClass}
          value={rawValue}
          placeholder={fallback}
          onChange={(e) => onChangeDimension(e.target.value)}
          disabled={disabled}
          inputMode="numeric"
        />
      )}
      {useDropdown && customMode && (
        <button
          type="button"
          onClick={() => {
            setCustomRequested(false);
            if (isEmpty) {
              return;
            }
            const closest = supported.reduce((acc, dim) =>
              Math.abs(dim - currentNum) < Math.abs(acc - currentNum)
                ? dim
                : acc,
            );
            onChangeDimension(String(closest));
          }}
          className="text-[11px] text-[var(--muted-foreground)] underline-offset-2 hover:underline"
        >
          {t("Use a supported value")}
        </button>
      )}
      {sourceInfo && (
        <div
          className={`text-[11px] ${
            sourceInfo.tone === "warn"
              ? "text-amber-600 dark:text-amber-400"
              : sourceInfo.tone === "ok"
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-[var(--muted-foreground)]"
          }`}
        >
          {sourceInfo.label}
        </div>
      )}
      {showDetectedBadge && (
        <div className="flex items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
          <span>
            {t("Detected")}: <strong>{detected}d</strong>
          </span>
          <button
            type="button"
            onClick={() => onChangeDimension(String(detected))}
            className="rounded-md border border-[var(--border)]/60 px-1.5 py-0.5 text-[10px] text-[var(--foreground)] transition-colors hover:border-[var(--border)]"
            disabled={disabled}
          >
            {t("Use this")}
          </button>
        </div>
      )}
    </div>
  );
}
