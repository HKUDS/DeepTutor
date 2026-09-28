import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReadingExtensionBar } from "@/components/reading/ReadingExtensionBar";
import { initI18n } from "@/i18n/init";
import { fetchAuthStatus } from "@/lib/auth";
import { getOwnLearnerProfile } from "@/lib/profile-api";
import { listReadingExtensions, runReadingExtension } from "@/lib/reading-api";
import {
  readingActionClass,
  resolveReadingAgeMode,
} from "@/lib/reading-age-presentation";

vi.mock("@/lib/auth", () => ({ fetchAuthStatus: vi.fn() }));
vi.mock("@/lib/profile-api", () => ({ getOwnLearnerProfile: vi.fn() }));
vi.mock("@/lib/reading-api", () => ({
  listReadingExtensions: vi.fn(),
  runReadingExtension: vi.fn(),
  submitReadingQuizAnswers: vi.fn(),
}));

initI18n("en");

const extensions = [
  {
    id: "quiz",
    name: "Quiz",
    version: "1",
    protocol_version: "1",
    actions: [{ id: "start", label: "Quiz me", trigger: "toolbar", requires: [] }],
    result_types: ["quiz"],
  },
  {
    id: "custom",
    name: "Custom",
    version: "1",
    protocol_version: "1",
    actions: [{ id: "open", label: "Custom action", trigger: "toolbar", requires: [] }],
    result_types: ["card"],
  },
  {
    id: "vocabulary",
    name: "Vocabulary",
    version: "1",
    protocol_version: "1",
    actions: [
      { id: "explain", label: "Explain vocabulary", trigger: "toolbar", requires: ["selection"] },
    ],
    result_types: ["card"],
  },
  {
    id: "read_aloud",
    name: "Read aloud",
    version: "1",
    protocol_version: "1",
    actions: [{ id: "read", label: "Read aloud", trigger: "toolbar", requires: [] }],
    result_types: ["browser_speech"],
  },
] as Awaited<ReturnType<typeof listReadingExtensions>>;

beforeEach(() => {
  vi.mocked(listReadingExtensions).mockResolvedValue(extensions);
  vi.mocked(runReadingExtension).mockImplementation(() => new Promise(() => undefined));
  vi.mocked(fetchAuthStatus).mockResolvedValue({
    enabled: true,
    authenticated: true,
    preset: "learner",
    learning_policy: {
      age_band: "9-12",
      locked_persona: "",
      allowed_capabilities: [],
      default_capability: "chat",
    },
  });
  vi.mocked(getOwnLearnerProfile).mockResolvedValue({ age: 8 });
});

describe("host-owned Reading age presentation", () => {
  it("uses exact profile ages and a conservative policy fallback only in learner mode", () => {
    expect(resolveReadingAgeMode({ learnerMode: false, profileAge: 5, policyAgeBand: "6-8" })).toBe("default");
    expect(resolveReadingAgeMode({ learnerMode: true, profileAge: 5 })).toBe("early");
    expect(resolveReadingAgeMode({ learnerMode: true, profileAge: 6 })).toBe("early");
    expect(resolveReadingAgeMode({ learnerMode: true, profileAge: 8 })).toBe("young");
    expect(resolveReadingAgeMode({ learnerMode: true, profileAge: 12 })).toBe("older");
    expect(resolveReadingAgeMode({ learnerMode: true, profileAge: 13 })).toBe("default");
    expect(resolveReadingAgeMode({ learnerMode: true, profileAge: 2, policyAgeBand: "6-8" })).toBe("young");
    expect(resolveReadingAgeMode({ learnerMode: true, profileAge: null, policyAgeBand: "9-12" })).toBe("older");
    expect(resolveReadingAgeMode({ learnerMode: true, profileAge: null, policyAgeBand: "13-15" })).toBe("default");
  });

  it.each([
    { age: 5, mode: "early", size: "min-h-14" },
    { age: 8, mode: "young", size: "min-h-12" },
    { age: 12, mode: "older", size: "min-h-11" },
  ])("shows the three fixed actions for age $age without styling plugins", async ({ age, mode, size }) => {
    vi.mocked(getOwnLearnerProfile).mockResolvedValue({ age });
    const onError = vi.fn();
    const { container } = render(
      <ReadingExtensionBar materialId="material-1" locator={4} onError={onError} />,
    );

    await waitFor(() =>
      expect(container.querySelector("[data-reading-presentation]")).toHaveAttribute(
        "data-reading-presentation",
        mode,
      ),
    );
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((button) => button.textContent?.trim())).toEqual(
      age === 5
        ? ["Listen", "Look up word", "Quiz", "Custom action"]
        : ["Read aloud", "Explain vocabulary", "Quiz me", "Custom action"],
    );
    for (const button of buttons.slice(0, 3)) {
      expect(button).toHaveClass(size);
      expect(button).toHaveAccessibleName();
    }
    expect(buttons[3]).toHaveClass("h-8");
    expect(buttons[3]).not.toHaveClass(size);
    expect(buttons[1]).toBeDisabled();
    expect(onError).not.toHaveBeenCalled();
    if (age === 5) {
      expect(buttons.slice(0, 3).map((button) => button.getAttribute("aria-label"))).toEqual([
        "Listen — Read aloud",
        "Look up word — Explain vocabulary",
        "Quiz — Quiz me",
      ]);
    }
  });

  it("keeps adult styling for a standard account and never fetches its learner profile", async () => {
    vi.mocked(fetchAuthStatus).mockResolvedValue({
      enabled: true,
      authenticated: true,
      preset: "standard",
      learning_policy: null,
    });
    const { container } = render(
      <ReadingExtensionBar materialId="material-1" locator={4} onError={vi.fn()} />,
    );
    await screen.findByRole("button", { name: "Read aloud" });
    expect(container.querySelector("[data-reading-presentation]")).toHaveAttribute(
      "data-reading-presentation",
      "default",
    );
    expect(screen.getByRole("button", { name: "Read aloud" })).toHaveClass("h-8");
    expect(getOwnLearnerProfile).not.toHaveBeenCalled();
  });

  it("keeps the action request and keyboard order free of age metadata", async () => {
    vi.mocked(getOwnLearnerProfile).mockResolvedValue({ age: 5 });
    render(<ReadingExtensionBar materialId="material-1" locator={4} onError={vi.fn()} />);
    const readButton = await screen.findByRole("button", { name: /Listen.*Read aloud/ });
    await waitFor(() => expect(readButton.closest("[data-reading-presentation]")).toHaveAttribute("data-reading-presentation", "early"));
    expect(screen.getAllByRole("button")[0]).toBe(readButton);
    fireEvent.click(readButton);
    expect(runReadingExtension).toHaveBeenCalledWith("material-1", "read_aloud", "read", {
      locator: 4,
      selection: "",
      locale: "en",
    });
  });

  it("only animates under motion-safe, including the early entrance", () => {
    expect(readingActionClass("early", "read_aloud:read")).toContain("motion-safe:animate-");
    expect(readingActionClass("early", "read_aloud:read")).not.toMatch(/(?:^|\s)animate-/);
    expect(readingActionClass("early", "read_aloud:read")).not.toContain("transition-colors");
    expect(readingActionClass("default", "read_aloud:read")).not.toContain("motion-safe:animate-");
  });
});
