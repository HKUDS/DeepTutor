import {
  BarChart3,
  BrainCircuit,
  CircleHelp,
  Clapperboard,
  Code2,
  Compass,
  FileSearch,
  Globe,
  GraduationCap,
  Image as ImageIcon,
  Lightbulb,
  MessageSquare,
  Microscope,
  PenLine,
  Signpost,
  Sparkles,
  Youtube,
  type LucideIcon,
} from "lucide-react";

import type { CapabilityDescriptor } from "./model";

export type ToolName =
  | "brainstorm"
  | "geogebra_analysis"
  | "web_search"
  | "code_execution"
  | "reason"
  | "paper_search"
  | "imagegen"
  | "videogen";

export interface ToolDef {
  name: ToolName;
  label: string;
  icon: LucideIcon;
}

export const ALL_TOOLS: ToolDef[] = [
  { name: "brainstorm", label: "Brainstorm", icon: Lightbulb },
  { name: "geogebra_analysis", label: "GeoGebra", icon: Compass },
  { name: "web_search", label: "Web Search", icon: Globe },
  { name: "code_execution", label: "Code", icon: Code2 },
  { name: "reason", label: "Reason", icon: Sparkles },
  { name: "paper_search", label: "Arxiv Search", icon: FileSearch },
  { name: "imagegen", label: "Image Gen", icon: ImageIcon },
  { name: "videogen", label: "Video Gen", icon: Clapperboard },
];

export interface CapabilityDef {
  value: string;
  label: string;
  description: string;
  icon: LucideIcon;
  allowedTools: string[];
  secondary?: boolean;
  legacy?: boolean;
}

export interface ChatCapabilityDef extends CapabilityDef {
  allowedTools: ToolName[];
  defaultTools: ToolName[];
  /** Direct CLI/SDK capability retained for existing callers, not a browser action. */
  legacy?: boolean;
}

/** Authoritative capability catalog shared by Home and learning workspaces. */
export const CHAT_CAPABILITIES: ChatCapabilityDef[] = [
  {
    value: "",
    label: "Chat",
    description: "Flexible conversation with any tool",
    icon: MessageSquare,
    allowedTools: [
      "brainstorm",
      "geogebra_analysis",
      "web_search",
      "code_execution",
      "reason",
      "paper_search",
      "imagegen",
      "videogen",
    ],
    defaultTools: [],
  },
  {
    value: "deep_solve",
    label: "Solve",
    description: "Multi-step reasoning & problem solving",
    icon: BrainCircuit,
    allowedTools: ["web_search", "code_execution", "reason"],
    defaultTools: ["web_search", "code_execution", "reason"],
    secondary: true,
  },
  {
    value: "ask_questions",
    label: "Ask Questions",
    description: "Let the model ask you questions to fill in missing context",
    icon: CircleHelp,
    allowedTools: [
      "brainstorm",
      "geogebra_analysis",
      "web_search",
      "code_execution",
      "reason",
      "paper_search",
      "imagegen",
      "videogen",
    ],
    defaultTools: [],
  },
  {
    value: "deep_question",
    label: "Quiz",
    description: "Auto-validated question generation",
    icon: PenLine,
    allowedTools: ["web_search", "code_execution"],
    defaultTools: ["web_search", "code_execution"],
  },
  {
    value: "deep_research",
    label: "Research",
    description: "Comprehensive multi-agent research",
    icon: Microscope,
    allowedTools: ["web_search", "paper_search", "code_execution"],
    defaultTools: ["web_search", "paper_search", "code_execution"],
    secondary: true,
  },
  {
    value: "visualize",
    label: "Visualize",
    description:
      "Generate charts, diagrams, interactive pages, or math animations",
    icon: BarChart3,
    allowedTools: [],
    defaultTools: [],
  },
  {
    value: "immersive_watching",
    label: "Immersive Watching",
    description: "Learn from YouTube with timestamp-grounded tutoring",
    icon: Youtube,
    allowedTools: ["web_search", "code_execution", "reason"],
    defaultTools: [],
  },
  {
    value: "course_study",
    label: "Course Study",
    description: "See where a course stands and what to do next",
    icon: Signpost,
    allowedTools: ["web_search", "code_execution", "reason"],
    defaultTools: [],
  },
  {
    value: "mastery_path",
    label: "Mastery Path",
    description: "Mastery-based tutoring with a hard gate",
    icon: GraduationCap,
    allowedTools: ["web_search", "code_execution"],
    defaultTools: [],
    legacy: true,
  },
];

export const VISIBLE_CHAT_CAPABILITIES = CHAT_CAPABILITIES.filter(
  (capability) => capability.value !== "course_study" && !capability.legacy,
);

/** Actions offered inside Reading and Mastery; workspace identity is separate. */
export const WORKSPACE_CHAT_CAPABILITIES = CHAT_CAPABILITIES.filter(
  (capability) =>
    capability.value !== "course_study" &&
    capability.value !== "mastery_path" &&
    capability.value !== "immersive_watching",
);

export function getChatCapability(value: string | null): ChatCapabilityDef {
  return (
    CHAT_CAPABILITIES.find(
      (capability) => capability.value === (value || ""),
    ) ?? CHAT_CAPABILITIES[0]
  );
}

const UNKNOWN_PRESENTATION: Omit<
  ChatCapabilityDef,
  "value" | "label" | "description"
> = {
  icon: BrainCircuit,
  allowedTools: [],
  defaultTools: [],
  secondary: true,
};

function humanizeCapabilityId(id: string): string {
  return id
    .split(/[_-]+/)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

export function mergeCapabilityPresentations(
  capabilities: readonly CapabilityDescriptor[],
): ChatCapabilityDef[] {
  const byId = new Map(
    CHAT_CAPABILITIES.map((entry) => [entry.value || "chat", entry] as const),
  );

  return capabilities
    .filter((capability) => capability.available)
    .map((capability) => {
      const known = byId.get(capability.id);
      if (known) {
        return {
          ...known,
          allowedTools: [...known.allowedTools],
          defaultTools: [...known.defaultTools],
        };
      }
      const label =
        typeof capability.manifest?.name === "string" &&
        capability.manifest.name.trim()
          ? capability.manifest.name.trim()
          : humanizeCapabilityId(capability.id);
      return {
        ...UNKNOWN_PRESENTATION,
        value: capability.id,
        label,
        description:
          typeof capability.manifest?.description === "string"
            ? capability.manifest.description
            : "Extension capability",
        allowedTools: [],
        defaultTools: [],
      };
    });
}

export function visibleCapabilityPresentations(
  capabilities: readonly ChatCapabilityDef[],
): ChatCapabilityDef[] {
  return capabilities.filter(
    (capability) => capability.value !== "course_study" && !capability.legacy,
  );
}
