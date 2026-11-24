import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import ReasoningEffortSelector from "@/components/chat/home/ReasoningEffortSelector";
import type { LLMOption } from "@/lib/llm-options";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

const base = {
  profile_name: "Alt",
  model_name: "Alt Model",
  provider: "openai",
  provider_label: "OpenAI",
  is_active_default: false,
} as const;

function option(overrides: Partial<LLMOption>): LLMOption {
  return {
    ...base,
    profile_id: "p-alt",
    model_id: "m-alt",
    model: "gpt-5.2",
    ...overrides,
  } as LLMOption;
}

it("offers only wire-vocabulary levels and reports the choice", () => {
  const onChange = vi.fn();
  render(
    <ReasoningEffortSelector
      option={option({ model: "claude-opus-5", provider: "anthropic" })}
      value={null}
      onChange={onChange}
    />,
  );
  // claude-opus-5's table only offers none/adaptive; adaptive is outside the
  // turn vocabulary, so the menu must not offer it.
  fireEvent.click(screen.getByRole("button", { name: "Reasoning effort" }));
  const items = screen
    .getAllByRole("button")
    .map((button) => button.textContent)
    .filter((text): text is string => Boolean(text));
  expect(items).toContain("Provider default (Auto)");
  expect(items).toContain("None");
  expect(items).not.toContain("Adaptive");
  fireEvent.click(screen.getByRole("button", { name: "None" }));
  expect(onChange).toHaveBeenLastCalledWith("none");
});

it("uses the catalog's supported levels when the model publishes them", () => {
  const onChange = vi.fn();
  render(
    <ReasoningEffortSelector
      option={option({
        supported_reasoning_efforts: ["minimal", "low", "high"],
      })}
      value="low"
      onChange={onChange}
    />,
  );
  // The trigger names the active override (aria-label stays on the control name).
  const trigger = screen.getByRole("button", { name: "Reasoning effort" });
  expect(trigger.textContent).toContain("Low");
  fireEvent.click(trigger);
  fireEvent.click(screen.getByRole("button", { name: "High" }));
  expect(onChange).toHaveBeenLastCalledWith("high");
});

it("resets to the provider default with null", () => {
  const onChange = vi.fn();
  render(
    <ReasoningEffortSelector
      option={option({ supported_reasoning_efforts: ["low", "high"] })}
      value="high"
      onChange={onChange}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Reasoning effort" }));
  fireEvent.click(screen.getByRole("button", { name: "Provider default (Auto)" }));
  expect(onChange).toHaveBeenLastCalledWith(null);
});

it("hides when the model exposes no selectable level", () => {
  const { container } = render(
    <ReasoningEffortSelector
      option={option({ model: "gpt-4o", declared_reasoning: false })}
      value={null}
      onChange={vi.fn()}
    />,
  );
  expect(container.firstChild).toBeNull();
});

it("hides while no model option is resolved", () => {
  const { container } = render(
    <ReasoningEffortSelector option={null} value="high" onChange={vi.fn()} />,
  );
  expect(container.firstChild).toBeNull();
});

it("drops a stored value the selected model no longer supports (#641)", () => {
  const onChange = vi.fn();
  render(
    <ReasoningEffortSelector
      option={option({ supported_reasoning_efforts: ["low", "high"] })}
      value="xhigh"
      onChange={onChange}
    />,
  );
  // The stale override is not a selectable level: Auto shows as selected…
  const trigger = screen.getByRole("button", { name: "Reasoning effort" });
  expect(trigger.textContent).toContain("Auto");
  // …and the menu must not re-list it.
  fireEvent.click(trigger);
  const items = screen
    .getAllByRole("button")
    .map((button) => button.textContent)
    .filter((text): text is string => Boolean(text));
  expect(items).not.toContain("Extra high");
  expect(items).toContain("Low");
  expect(items).toContain("High");
  // A real level still reports normally; the composer resets the persisted
  // override through this same onChange path.
  fireEvent.click(screen.getByRole("button", { name: "Low" }));
  expect(onChange).toHaveBeenLastCalledWith("low");
});
