"use client";

import { CategoryScroll } from "@/components/settings/CategoryScroll";

import ClaudeCodeAgentSettingsPage from "./claude-code/page";
import CodexAgentSettingsPage from "./codex/page";
import GeminiAgentSettingsPage from "./gemini/page";
import AntigravityAgentSettingsPage from "./antigravity/page";
import KimiAgentSettingsPage from "./kimi/page";
import OpencodeAgentSettingsPage from "./opencode/page";
import MimoAgentSettingsPage from "./mimo/page";

/**
 * The Partners & Agents category, in full — see `ModelsSettingsPage` for the
 * pattern. All seven leaves persist to the same `subagent.json`, so this was
 * already one shared draft behind nine separate routes.
 */
export default function AgentsSettingsPage() {
  return (
    <CategoryScroll
      sections={[
        { key: "agent-claude-code", Component: ClaudeCodeAgentSettingsPage },
        { key: "agent-codex", Component: CodexAgentSettingsPage },
        { key: "agent-gemini", Component: GeminiAgentSettingsPage },
        { key: "agent-antigravity", Component: AntigravityAgentSettingsPage },
        { key: "agent-kimi", Component: KimiAgentSettingsPage },
        { key: "agent-opencode", Component: OpencodeAgentSettingsPage },
        { key: "agent-mimo", Component: MimoAgentSettingsPage },
      ]}
    />
  );
}
