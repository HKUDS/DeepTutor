export type ResearchMode =
  | ""
  | "notes"
  | "report"
  | "comparison"
  | "learning_path";
export type ResearchDepth = "" | "quick" | "standard" | "deep" | "manual";

export interface OutlineItem {
  title: string;
  overview: string;
}

export interface DeepResearchFormConfig {
  mode: ResearchMode;
  depth: ResearchDepth;
  manual_subtopics?: number;
  manual_max_iterations?: number;
  confirmed_outline?: OutlineItem[];
}

export interface ResearchConfigValidationResult {
  valid: boolean;
  errors: Record<string, string>;
}

export function createEmptyResearchConfig(): DeepResearchFormConfig {
  return {
    mode: "",
    depth: "",
  };
}

export function normalizeResearchConfig(
  raw: Record<string, unknown> | undefined,
): DeepResearchFormConfig {
  const empty = createEmptyResearchConfig();
  return {
    mode:
      raw?.mode === "notes" ||
      raw?.mode === "report" ||
      raw?.mode === "comparison" ||
      raw?.mode === "learning_path"
        ? raw.mode
        : empty.mode,
    depth:
      raw?.depth === "quick" ||
      raw?.depth === "standard" ||
      raw?.depth === "deep" ||
      raw?.depth === "manual"
        ? raw.depth
        : empty.depth,
  };
}

export function validateResearchConfig(
  cfg: DeepResearchFormConfig,
): ResearchConfigValidationResult {
  const errors: Record<string, string> = {};

  if (!cfg.mode) {
    errors.mode = "Required";
  }
  if (!cfg.depth) {
    errors.depth = "Required";
  }

  return { valid: Object.keys(errors).length === 0, errors };
}

export function buildResearchWSConfig(
  cfg: DeepResearchFormConfig,
  confirmedOutline?: OutlineItem[],
): Record<string, unknown> {
  const validation = validateResearchConfig(cfg);
  if (!validation.valid) {
    throw new Error("Deep research settings are incomplete.");
  }

  const result: Record<string, unknown> = {
    mode: cfg.mode,
    depth: cfg.depth,
  };

  if (cfg.depth === "manual") {
    if (cfg.manual_subtopics != null)
      result.manual_subtopics = cfg.manual_subtopics;
    if (cfg.manual_max_iterations != null)
      result.manual_max_iterations = cfg.manual_max_iterations;
  }

  const outline = confirmedOutline ?? cfg.confirmed_outline;
  if (outline && outline.length > 0) {
    result.confirmed_outline = outline;
  }

  return result;
}

const RESEARCH_MODE_LABELS: Record<string, string> = {
  notes: "Study Notes",
  report: "Report",
  comparison: "Comparison",
  learning_path: "Learning Path",
};

const RESEARCH_DEPTH_LABELS: Record<string, string> = {
  quick: "Quick",
  standard: "Standard",
  deep: "Deep",
  manual: "Manual",
};

export function summarizeResearchConfig(
  cfg: DeepResearchFormConfig,
  translate?: (key: string) => string,
): string {
  const validation = validateResearchConfig(cfg);
  const tr = translate ?? ((s: string) => s);
  if (!validation.valid) return tr("Incomplete settings");
  const modeLabel =
    RESEARCH_MODE_LABELS[cfg.mode] ?? cfg.mode.replace("_", " ");
  const depthLabel = RESEARCH_DEPTH_LABELS[cfg.depth] ?? cfg.depth;
  return [tr(modeLabel), tr(depthLabel)].join(" · ");
}
