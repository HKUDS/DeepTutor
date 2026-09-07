"use client";

import { CategoryScroll } from "@/components/settings/CategoryScroll";
import { SubagentSettingsEditor } from "@/components/settings/SubagentSettingsEditor";
import { useSettingsAccess } from "@/features/settings/navigation/SettingsAccessProvider";
import { visibleSettingsChildren } from "@/features/settings/navigation/settings-nav";

const ClaudeCodeAgentSettingsPage = () => (
  <SubagentSettingsEditor kind="claude_code" />
);
const CodexAgentSettingsPage = () => <SubagentSettingsEditor kind="codex" />;
const AntigravityAgentSettingsPage = () => (
  <SubagentSettingsEditor kind="antigravity" />
);
const KimiAgentSettingsPage = () => <SubagentSettingsEditor kind="kimi" />;
const OpencodeAgentSettingsPage = () => (
  <SubagentSettingsEditor kind="opencode" />
);
const MimoAgentSettingsPage = () => <SubagentSettingsEditor kind="mimo" />;
const HermesAgentSettingsPage = () => <SubagentSettingsEditor kind="hermes" />;
const HermesRemoteAgentSettingsPage = () => (
  <SubagentSettingsEditor kind="hermes_remote" />
);
const OpenClawAgentSettingsPage = () => (
  <SubagentSettingsEditor kind="openclaw" />
);
const DeepSeekHarnessAgentSettingsPage = () => (
  <SubagentSettingsEditor kind="deepseek_harness" />
);

const AGENT_SECTIONS = [
  { key: "agent-claude-code", Component: ClaudeCodeAgentSettingsPage },
  { key: "agent-codex", Component: CodexAgentSettingsPage },
  { key: "agent-antigravity", Component: AntigravityAgentSettingsPage },
  { key: "agent-kimi", Component: KimiAgentSettingsPage },
  { key: "agent-opencode", Component: OpencodeAgentSettingsPage },
  { key: "agent-mimo", Component: MimoAgentSettingsPage },
  { key: "agent-hermes", Component: HermesAgentSettingsPage },
  { key: "agent-hermes-remote", Component: HermesRemoteAgentSettingsPage },
  { key: "agent-openclaw", Component: OpenClawAgentSettingsPage },
  {
    key: "agent-deepseek-harness",
    Component: DeepSeekHarnessAgentSettingsPage,
  },
] as const;

/**
 * The Partners & Agents category, in full — see `ModelsSettingsPage` for the
 * pattern. All leaves persist to the same `subagent.json`, so this remains one
 * shared draft behind the individual routes.
 */
export default function AgentsSettingsPage() {
  const access = useSettingsAccess();
  const visibleKeys = new Set(
    visibleSettingsChildren("agents", access).map((leaf) => leaf.key),
  );
  return (
    <CategoryScroll
      sections={AGENT_SECTIONS.filter(({ key }) => visibleKeys.has(key))}
      deferSections
    />
  );
}
