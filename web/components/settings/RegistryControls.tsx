"use client";

import { type KeyboardEvent, useEffect, useId, useRef, useState } from "react";
import { Check, ChevronDown, Loader2, Pencil, PlugZap, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { apiFetch, apiUrl } from "@/lib/api";
import type { Discovery } from "@/lib/provider-registry";
import { useOutsideClick } from "@/hooks/use-outside-click";
import type { ProviderProbeInput } from "./ProviderModelDiscovery";
import { inputClass, subPanelClass } from "./shared";

// These buttons only ever had a hover fill, so pressing one produced no
// response at all and the pages felt like inert blocks. Every variant now moves
// on press and shows a real focus ring. Disabled buttons keep pointer events —
// several of them explain why they are disabled through `title`.
const registryButtonBase =
  "inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border px-3 text-xs font-medium outline-none transition-[background-color,border-color,color,box-shadow,transform] duration-150 active:scale-[0.97] focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--background)] disabled:opacity-40 disabled:active:scale-100";
export const registryButton =
  `${registryButtonBase} border-[var(--border)] hover:border-[color-mix(in_srgb,var(--foreground)_20%,var(--border))] hover:bg-[var(--accent)] disabled:hover:border-[var(--border)] disabled:hover:bg-transparent`;
/** Destructive action: reads as neutral until you reach for it. */
export const registryDanger =
  `${registryButtonBase} border-[var(--border)] text-[var(--muted-foreground)] hover:border-red-300 hover:bg-red-50 hover:text-red-600 disabled:hover:border-[var(--border)] disabled:hover:bg-transparent disabled:hover:text-[var(--muted-foreground)] dark:hover:border-red-900 dark:hover:bg-red-950 dark:hover:text-red-400`;
export const registryPrimary =
  "inline-flex min-h-9 items-center justify-center gap-2 rounded-lg bg-[var(--foreground)] px-4 text-xs font-medium text-[var(--background)] outline-none transition-[background-color,box-shadow,transform] duration-150 hover:bg-[color-mix(in_srgb,var(--foreground)_86%,var(--background))] active:scale-[0.97] focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--background)] disabled:opacity-40 disabled:hover:bg-[var(--foreground)] disabled:active:scale-100";

export function EditableRegistryName({
  name,
  onChange,
  label,
}: {
  name: string;
  onChange: (value: string) => void;
  label: string;
}) {
  const [editing, setEditing] = useState(false);
  if (editing)
    return (
      <input
        autoFocus
        aria-label={label}
        className={inputClass}
        value={name}
        onChange={(e) => onChange(e.target.value)}
        onBlur={() => setEditing(false)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === "Escape") setEditing(false);
        }}
      />
    );
  return (
    <div className="flex min-w-0 items-center gap-2">
      <h3
        className="min-w-0 break-all text-base font-semibold"
        onDoubleClick={() => {
          setEditing(true);
        }}
      >
        {name}
      </h3>
      <button
        type="button"
        aria-label={label}
        title={label}
        onClick={() => {
          setEditing(true);
        }}
        className="shrink-0 rounded-md p-2 text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
      >
        <Pencil size={14} />
      </button>
    </div>
  );
}

const PROBE_MESSAGES: Record<string, string> = {
  connected: "Provider connected",
  auth_error:
    "The provider rejected these credentials. Check the API key and its permissions.",
  unavailable:
    "This provider does not expose a model list. Its connection can be verified when you test a model or search configuration.",
  rate_limited: "The provider is rate limiting requests. Try again later.",
  timeout:
    "The connection timed out. Check the address and network, then try again.",
  unreachable: "Could not reach the provider. Check the address and network.",
  invalid_url: "Enter a valid HTTP or HTTPS provider address.",
  http_error:
    "The provider returned an error. Check the address or try again later.",
};
const CATEGORIES = [
  "Language models",
  "Embedding models",
  "Search",
  "Voice",
  "Multimodal generation",
];
const CATEGORY_KEYS = ["llm", "embedding", "search", "voice", "generation"];

export function RegistryProbe({
  input,
  discovery,
  onResult,
  listing = false,
  hints = [],
}: {
  input: ProviderProbeInput;
  discovery?: Discovery;
  onResult: (result: Discovery) => void;
  listing?: boolean;
  hints?: string[];
}) {
  // Credentials are only an in-memory request signature, never rendered or persisted.
  return (
    <ProbeForm
      key={JSON.stringify(input)}
      input={input}
      discovery={discovery}
      onResult={onResult}
      listing={listing}
      hints={hints}
    />
  );
}
function ProbeForm({
  input,
  discovery,
  onResult,
  listing,
  hints,
}: {
  input: ProviderProbeInput;
  discovery?: Discovery;
  onResult: (result: Discovery) => void;
  listing: boolean;
  hints: string[];
}) {
  const { t } = useTranslation();
  const [result, setResult] = useState(discovery);
  const [pending, setPending] = useState(false);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const probe = async () => {
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setPending(true);
    try {
      const response = await apiFetch(apiUrl("/api/settings/test-provider"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input),
        signal: request.signal,
      });
      const payload = await response.json();
      if (request.signal.aborted) return;
      const next: Discovery = response.ok
        ? { ...payload, checked_at: new Date().toISOString() }
        : { status: "http_error", models: [] };
      setResult(next);
      onResult(next);
    } catch {
      if (!request.signal.aborted)
        setResult({ status: "unreachable", models: [] });
    } finally {
      if (!request.signal.aborted) setPending(false);
    }
  };
  return (
    <section className={`space-y-3 p-4 ${subPanelClass}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium">
            {t(listing ? "Provider model list" : "Provider connection")}
          </p>
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">
            {t(
              listing
                ? "Choose a listed model or enter any model ID below."
                : "Check access and discover the services this provider offers.",
            )}
          </p>
        </div>
        <button
          type="button"
          disabled={pending}
          onClick={() => void probe()}
          className={registryButton}
        >
          {pending ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <PlugZap size={14} />
          )}{" "}
          {t(
            pending ? "Testing…" : listing ? "Get model list" : "Test provider",
          )}
        </button>
      </div>
      {result && (
        <div
          role="status"
          className={`text-xs leading-relaxed ${result.status === "connected" ? "text-emerald-700 dark:text-emerald-400" : "text-[var(--muted-foreground)]"}`}
        >
          {t(PROBE_MESSAGES[result.status] || PROBE_MESSAGES.http_error)}
          {result.status === "connected" &&
            input.service !== "search" &&
            ` · ${t("{{count}} models available", { count: result.models.length })}`}
        </div>
      )}
      {!listing && (
        <>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {CATEGORIES.map((label, i) => {
              const evidence = result?.capabilities?.find(
                (c) => c.category === CATEGORY_KEYS[i],
              );
              const status =
                evidence?.evidence === "metadata"
                  ? "Detected"
                  : evidence || hints.includes(CATEGORY_KEYS[i])
                    ? "Provider supports"
                    : "Unknown";
              return (
                <div
                  key={label}
                  className="rounded-lg border border-[color-mix(in_srgb,var(--border)_70%,transparent)] bg-[var(--background)] px-3 py-2"
                >
                  <p className="text-xs font-medium">{t(label)}</p>
                  <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
                    {t(status)}
                  </p>
                </div>
              );
            })}
          </div>
          <p className="text-[11px] leading-relaxed text-[var(--muted-foreground)]">
            {t(
              "Detected describes model modalities, not API compatibility. Provider support indicates an available integration; test a specific model to verify your account access.",
            )}
          </p>
        </>
      )}
    </section>
  );
}
export function RegistryField({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-xs font-medium">
        {label}
      </label>
      <input
        id={id}
        type={type}
        disabled={disabled}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={inputClass}
      />
    </div>
  );
}

/**
 * The model ID, with the provider's listed models offered as suggestions.
 *
 * This was a native input with a datalist, which hands the popup to the
 * browser — and the browser draws every option at once. A provider that lists
 * thirty models covered the page from above its header to below its footer, in
 * the browser's styling rather than ours. A datalist popup takes no CSS at all,
 * so capping that height means owning the list.
 *
 * The field stays free text: a model the provider does not list is still a
 * model the user may have to type, so the suggestions narrow as they type and
 * simply stay shut when nothing matches — an unlisted ID is this field working,
 * not an error to report.
 */
export function RegistryModelIdField({
  label,
  value,
  options,
  onChange,
  placeholder,
  disabled = false,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const id = useId();
  const box = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  useOutsideClick(box, open, () => setOpen(false));

  // A value that *is* one of the options keeps the list whole: narrowing it to
  // the single option the field already holds would turn "show me the models"
  // into "show me the one I picked".
  const query = value.trim().toLowerCase();
  const matches =
    !query || options.some((option) => option.toLowerCase() === query)
      ? options
      : options.filter((option) => option.toLowerCase().includes(query));
  const visible = open && matches.length > 0;

  useEffect(() => {
    if (!visible) return;
    listRef.current
      ?.querySelector('[data-active="true"]')
      // Optional call, as elsewhere: a host without the method (jsdom) has
      // nothing to scroll, and keyboard navigation must not depend on it.
      ?.scrollIntoView?.({ block: "nearest" });
  }, [visible, active]);

  const pick = (option: string) => {
    onChange(option);
    setActive(-1);
    setOpen(false);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      if (!open) return;
      // Contained on purpose: Escape in an open list means "close the list",
      // not "leave the editor" to whatever is listening further up.
      event.stopPropagation();
      setOpen(false);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (!matches.length) return;
      // Otherwise the caret jumps to either end of the ID being typed.
      event.preventDefault();
      if (!visible) {
        setActive(event.key === "ArrowDown" ? 0 : matches.length - 1);
        setOpen(true);
        return;
      }
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((current) => {
        const next = current + step;
        if (next < 0) return matches.length - 1;
        return next >= matches.length ? 0 : next;
      });
      return;
    }
    if (event.key === "Enter" && visible && active >= 0) {
      event.preventDefault();
      pick(matches[active]);
    }
  };

  return (
    <div ref={box} className="space-y-1.5">
      <label htmlFor={id} className="block text-xs font-medium">
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          role="combobox"
          aria-label={label}
          aria-expanded={visible}
          aria-controls={`${id}-listbox`}
          aria-autocomplete="list"
          aria-activedescendant={
            visible && active >= 0 ? `${id}-option-${active}` : undefined
          }
          disabled={disabled}
          className={`${inputClass} pr-9 font-mono placeholder:font-sans`}
          value={value}
          placeholder={placeholder}
          onChange={(event) => {
            onChange(event.target.value);
            setActive(-1);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
        />
        {options.length > 0 && !disabled && (
          <button
            type="button"
            aria-label={t("Show listed models")}
            // Not a tab stop: the keyboard already opens the list from the
            // field itself, so this would only be a second way to the same
            // place on the way to the next field.
            tabIndex={-1}
            onClick={() => {
              setActive(-1);
              setOpen((current) => !current);
            }}
            className="absolute inset-y-0 right-0 flex w-9 items-center justify-center text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
          >
            <ChevronDown
              size={15}
              className={`transition-transform ${visible ? "rotate-180" : ""}`}
            />
          </button>
        )}
        {visible && (
          <div
            ref={listRef}
            id={`${id}-listbox`}
            role="listbox"
            aria-label={label}
            // Seven rows and a sliver of the eighth, then a scrollbar. The
            // point of the cap: the list is a control on the page, not a
            // second page over it — and the clipped row says it scrolls.
            className="absolute inset-x-0 top-full z-40 mt-1 max-h-[248px] overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--popover)] py-1 shadow-lg"
          >
            {matches.map((option, index) => (
              <button
                key={option}
                type="button"
                id={`${id}-option-${index}`}
                role="option"
                aria-selected={option === value}
                data-active={index === active ? "true" : undefined}
                onMouseEnter={() => setActive(index)}
                onClick={() => pick(option)}
                // The page's own font, not the field's monospace: the popup
                // this replaced was drawn by the browser in the UI font, and a
                // list of names reads better in it than a column of typewriter
                // text. The field stays monospaced, where an ID is edited a
                // character at a time.
                className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-[13px] leading-5 transition-colors ${
                  index === active
                    ? "bg-[var(--accent)]"
                    : "hover:bg-[var(--accent)]"
                }`}
              >
                <span className="min-w-0 flex-1 truncate">{option}</span>
                {option === value && <Check size={13} className="shrink-0" />}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
