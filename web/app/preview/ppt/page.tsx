"use client";

import { useState } from "react";
import { ResearchDashboard } from "@/components/research/ResearchDashboard";
import { initialResearchState } from "@/hooks/useResearchReducer";
import { ResearchState } from "@/types/research";
import { useGlobal } from "@/context/GlobalContext";
import { getTranslation } from "@/lib/i18n";

const PREVIEW_START_TIME = 1_700_000_000_000;

const buildPreviewState = (t: (key: string) => string): ResearchState => {
  const generatedReport = `# ${t("AI Research Report")}

## 1. ${t("Background")}

- ${t("Problem framing and context")}
- ${t("Why this matters now")}

## 2. ${t("Key Findings")}

- ${t("Finding A: concise insight")}
- ${t("Finding B: concise insight")}
- ${t("Finding C: concise insight")}

## 3. ${t("Implications")}

- ${t("Impact on product strategy")}
- ${t("Risks and mitigations")}

## 4. ${t("Next Steps")}

- ${t("Short-term actions")}
- ${t("Long-term roadmap")}
`;

  return {
    ...initialResearchState,
    global: {
      ...initialResearchState.global,
      stage: "completed",
      startTime: PREVIEW_START_TIME,
      totalBlocks: 6,
      completedBlocks: 6,
      topic: "AI Research Preview",
    },
    planning: {
      ...initialResearchState.planning,
      originalTopic: "AI Research Preview",
      optimizedTopic: "AI Research Preview (Optimized)",
      progress: "Completed",
    },
    reporting: {
      ...initialResearchState.reporting,
      outline: {
        title: t("AI Research Report"),
        introduction: "",
        sections: [
          { title: `1. ${t("Background")}`, instruction: "" },
          { title: `2. ${t("Key Findings")}`, instruction: "" },
          { title: `3. ${t("Implications")}`, instruction: "" },
          { title: `4. ${t("Next Steps")}`, instruction: "" },
        ],
        conclusion: "",
      },
      progress: "Completed",
      generatedReport,
      wordCount: 420,
      sectionCount: 4,
      citationCount: 0,
      sectionIndex: 4,
      totalSections: 4,
    },
  };
};

export default function PptPreviewPage() {
  const [pptStylePrompt, setPptStylePrompt] = useState<string>("");
  const { uiSettings } = useGlobal();
  const t = (key: string) => getTranslation(uiSettings.language, key);

  const state = buildPreviewState(t);

  return (
    <div className="h-screen w-screen">
      <ResearchDashboard
        state={state}
        selectedTaskId={null}
        onTaskSelect={() => {}}
        onExportMarkdown={() => {}}
        onExportPdf={() => {}}
        onExportPptx={() => {}}
        pptStylePrompt={pptStylePrompt}
        onPptStylePromptChange={setPptStylePrompt}
        isExportingPdf={false}
        isExportingPptx={false}
      />
    </div>
  );
}
