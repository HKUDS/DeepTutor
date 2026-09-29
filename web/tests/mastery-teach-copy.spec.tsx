import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { LearnerProfileCard } from "@/components/space/learning/LearnerProfileCard";
import { ModeSwitch } from "@/components/space/learning/ModeSwitch";
import {
  NEXT_CTA_LABELS,
  NEXT_LABELS,
  TEACH_FIRST_PROFILE_LABEL,
} from "@/components/space/learning/next-step-copy";
import type { LearnerProfile } from "@/lib/learning-api";

const locale = vi.hoisted(() => ({ language: "zh-CN" }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (value: string) => value,
    i18n: { language: locale.language },
  }),
}));

afterEach(() => {
  locale.language = "zh-CN";
});

const emptyProfile: LearnerProfile = {
  prior_knowledge: "",
  target_level: "",
  time_budget: "",
  preferences: "",
  notes: "",
  updated_at: 1,
};

it("gives the teach action explicit Chinese and English next steps", () => {
  expect(NEXT_LABELS.teach.zh).toContain("先讲解");
  expect(NEXT_LABELS.teach.en).toContain("Learn this knowledge point");
  expect(NEXT_CTA_LABELS.teach.zh).toContain("开始学习");
  expect(NEXT_CTA_LABELS.teach.en).toContain("Learn this knowledge point");
});

it("shows a profile whose only preference is teach first", () => {
  render(
    <LearnerProfileCard
      profile={{ ...emptyProfile, teaching_strategy: "teach_first" }}
    />,
  );

  expect(screen.getByText(TEACH_FIRST_PROFILE_LABEL.zh)).toBeInTheDocument();
  expect(screen.queryByText(/has not asked about you yet/)).not.toBeInTheDocument();
});

it("shows the teaching sequence alongside a free text preference", () => {
  locale.language = "en";
  render(
    <LearnerProfileCard
      profile={{
        ...emptyProfile,
        preferences: "Use diagrams",
        teaching_strategy: "teach_first",
      }}
    />,
  );

  expect(
    screen.getByText(`Use diagrams · ${TEACH_FIRST_PROFILE_LABEL.en}`),
  ).toBeInTheDocument();
});

it("explains why a mode cannot change during a live turn", () => {
  render(<ModeSwitch mode="study" onSelect={vi.fn()} disabled />);

  for (const button of screen.getAllByRole("button")) {
    expect(button).toBeDisabled();
    expect(button).not.toHaveAttribute("title");
    expect(
      document.getElementById(button.getAttribute("aria-describedby")!),
    ).toHaveTextContent("Wait for the tutor to finish before changing mode");
  }
});
