"use client";

import { CategoryScroll } from "@/components/settings/CategoryScroll";

import ClaudeCodeAgentSettingsPage from "./claude-code/page";
import CodexAgentSettingsPage from "./codex/page";
import AntigravityAgentSettingsPage from "./antigravity/page";
import KimiAgentSettingsPage from "./kimi/page";
import OpencodeAgentSettingsPage from "./opencode/page";
import MimoAgentSettingsPage from "./mimo/page";
import HermesAgentSettingsPage from "./hermes/page";
import OpenClawAgentSettingsPage from "./openclaw/page";
import DeepSeekHarnessAgentSettingsPage from "./deepseek-harness/page";

/**
 * The Partners & Agents category, in full — see `ModelsSettingsPage` for the
 * pattern. All leaves persist to the same `subagent.json`, so this remains one
 * shared draft behind the individual routes.
 */
export default function AgentsSettingsPage() {
  return (
    <CategoryScroll
      sections={[
        { key: "agent-claude-code", Component: ClaudeCodeAgentSettingsPage },
        { key: "agent-codex", Component: CodexAgentSettingsPage },
        { key: "agent-antigravity", Component: AntigravityAgentSettingsPage },
        { key: "agent-kimi", Component: KimiAgentSettingsPage },
        { key: "agent-opencode", Component: OpencodeAgentSettingsPage },
        { key: "agent-mimo", Component: MimoAgentSettingsPage },
        { key: "agent-hermes", Component: HermesAgentSettingsPage },
        { key: "agent-openclaw", Component: OpenClawAgentSettingsPage },
        {
          key: "agent-deepseek-harness",
          Component: DeepSeekHarnessAgentSettingsPage,
        },
      ]}
    />
  );
}
