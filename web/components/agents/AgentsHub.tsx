"use client";

import ConnectedAgents from "@/components/agents/ConnectedAgents";
import MyAgentsSection from "@/components/space/MyAgentsSection";

/**
 * "My Agents" hub — the top-level page. Two complementary halves: live agents
 * connected to the local Claude Code / Codex (consult them in chat now), and
 * the imported-history agents (replay and continue past transcripts).
 */
export default function AgentsHub() {
  return (
    <div className="space-y-12">
      <ConnectedAgents />
      <MyAgentsSection />
    </div>
  );
}
