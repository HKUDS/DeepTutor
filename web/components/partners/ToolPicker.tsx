"use client";

/**
 * Tool surface configuration: the user-toggleable system tools (same pool as
 * the chat composer) plus configured MCP tools, grouped by server.
 *
 * Semantics mirror the backend config: `null` = everything allowed (default),
 * an explicit array = whitelist. The picker materialises `null` into "all
 * selected" for editing and hands back an array.
 */

import { useTranslation } from "react-i18next";
import type { ToolOptions } from "@/lib/partners-api";

function ToggleRow({
  name,
  description,
  checked,
  onToggle,
}: {
  name: string;
  description?: string;
  checked: boolean;
  onToggle: () => void;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-2 rounded-lg px-2 py-1.5 hover:bg-[var(--muted)]">
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        className="mt-0.5"
      />
      <span className="min-w-0">
        <span className="block text-[13px] text-[var(--foreground)]">
          {name}
        </span>
        {description && (
          <span className="block truncate text-[11.5px] text-[var(--muted-foreground)]">
            {description}
          </span>
        )}
      </span>
    </label>
  );
}

export default function ToolPicker({
  options,
  enabledTools,
  builtinTools,
  mcpTools,
  onChangeEnabledTools,
  onChangeBuiltinTools,
  onChangeMcpTools,
}: {
  options: ToolOptions | null;
  enabledTools: string[];
  builtinTools: string[];
  mcpTools: string[];
  onChangeEnabledTools: (next: string[]) => void;
  onChangeBuiltinTools: (next: string[]) => void;
  onChangeMcpTools: (next: string[]) => void;
}) {
  const { t } = useTranslation();
  if (!options) {
    return (
      <p className="text-[13px] text-[var(--muted-foreground)]">
        {t("Loading tools…")}
      </p>
    );
  }

  const toggle = (
    list: string[],
    name: string,
    setter: (next: string[]) => void,
  ) => {
    setter(
      list.includes(name) ? list.filter((n) => n !== name) : [...list, name],
    );
  };

  const mcpByServer = new Map<string, typeof options.mcp_tools>();
  for (const tool of options.mcp_tools) {
    const key = tool.server || "other";
    mcpByServer.set(key, [...(mcpByServer.get(key) ?? []), tool]);
  }

  return (
    <div className="space-y-4">
      <div>
        <div className="mb-1.5 flex items-baseline justify-between">
          <h4 className="text-[13px] font-medium text-[var(--muted-foreground)]">
            {t("System tools")}
          </h4>
          <div className="flex gap-2 text-[12px]">
            <button
              type="button"
              className="text-[var(--primary)] hover:underline"
              onClick={() =>
                onChangeEnabledTools(options.tools.map((tl) => tl.name))
              }
            >
              {t("All")}
            </button>
            <button
              type="button"
              className="text-[var(--muted-foreground)] hover:underline"
              onClick={() => onChangeEnabledTools([])}
            >
              {t("None")}
            </button>
          </div>
        </div>
        <div className="grid grid-cols-1 gap-0.5 sm:grid-cols-2">
          {options.tools.map((tool) => (
            <ToggleRow
              key={tool.name}
              name={tool.name}
              description={tool.description}
              checked={enabledTools.includes(tool.name)}
              onToggle={() =>
                toggle(enabledTools, tool.name, onChangeEnabledTools)
              }
            />
          ))}
        </div>
      </div>

      {options.builtin_tools.length > 0 && (
        <div>
          <div className="mb-1.5 flex items-baseline justify-between">
            <h4 className="text-[13px] font-medium text-[var(--muted-foreground)]">
              {t("Built-in tools")}
            </h4>
            <div className="flex gap-2 text-[12px]">
              <button
                type="button"
                className="text-[var(--primary)] hover:underline"
                onClick={() =>
                  onChangeBuiltinTools(
                    options.builtin_tools.map((tl) => tl.name),
                  )
                }
              >
                {t("All")}
              </button>
              <button
                type="button"
                className="text-[var(--muted-foreground)] hover:underline"
                onClick={() => onChangeBuiltinTools([])}
              >
                {t("None")}
              </button>
            </div>
          </div>
          <p className="mb-1.5 px-2 text-[11.5px] text-[var(--muted-foreground)]">
            {t(
              "Mounted automatically when the context calls for it — a knowledge base attached, memory available, the sandbox enabled. Deny any you don't want this partner to have.",
            )}
          </p>
          <div className="grid grid-cols-1 gap-0.5 sm:grid-cols-2">
            {options.builtin_tools.map((tool) => (
              <ToggleRow
                key={tool.name}
                name={tool.name}
                description={tool.description}
                checked={builtinTools.includes(tool.name)}
                onToggle={() =>
                  toggle(builtinTools, tool.name, onChangeBuiltinTools)
                }
              />
            ))}
          </div>
        </div>
      )}

      <div>
        <h4 className="mb-1.5 text-[13px] font-medium text-[var(--muted-foreground)]">
          {t("Memory")}
        </h4>
        <p className="px-2 text-[11.5px] text-[var(--muted-foreground)]">
          {t(
            "Always on and built in — not configurable. partner_read sees the owner's shared memory plus the partner's own; partner_memorize writes only the partner's own memory; partner_search keyword-searches past conversations.",
          )}
        </p>
      </div>

      {options.mcp_tools.length > 0 && (
        <div>
          <div className="mb-1.5 flex items-baseline justify-between">
            <h4 className="text-[13px] font-medium text-[var(--muted-foreground)]">
              {t("MCP tools")}
            </h4>
            <div className="flex gap-2 text-[12px]">
              <button
                type="button"
                className="text-[var(--primary)] hover:underline"
                onClick={() =>
                  onChangeMcpTools(options.mcp_tools.map((tl) => tl.name))
                }
              >
                {t("All")}
              </button>
              <button
                type="button"
                className="text-[var(--muted-foreground)] hover:underline"
                onClick={() => onChangeMcpTools([])}
              >
                {t("None")}
              </button>
            </div>
          </div>
          {[...mcpByServer.entries()].map(([server, tools]) => (
            <div key={server} className="mb-2">
              <p className="mb-0.5 px-2 font-mono text-[11.5px] text-[var(--muted-foreground)]">
                {server}
              </p>
              <div className="grid grid-cols-1 gap-0.5 sm:grid-cols-2">
                {tools.map((tool) => (
                  <ToggleRow
                    key={tool.name}
                    name={tool.name}
                    description={tool.description}
                    checked={mcpTools.includes(tool.name)}
                    onToggle={() =>
                      toggle(mcpTools, tool.name, onChangeMcpTools)
                    }
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
