import React, { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { RegistryModelIdField } from "@/components/settings/RegistryControls";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (s: string) => s }),
}));

/**
 * A provider that lists a lot of models. The bug this field replaced was
 * exactly this case: the browser's own datalist popup drew all of them at once
 * and covered the page top to bottom.
 */
const MANY = Array.from({ length: 30 }, (_, i) => `qwen/qwen3.${i}-flash`);

/**
 * The real parent writes each keystroke into the catalog and re-renders, so the
 * harness holds the value too — filtering reads the value, and a static prop
 * would let a broken filter pass.
 */
function show(options: string[], initial = "") {
  const onChange = vi.fn();
  function Harness() {
    const [value, setValue] = useState(initial);
    return (
      <RegistryModelIdField
        label="Model ID"
        value={value}
        options={options}
        onChange={(next) => {
          onChange(next);
          setValue(next);
        }}
      />
    );
  }
  render(<Harness />);
  return onChange;
}

const open = () => fireEvent.click(screen.getByLabelText("Show listed models"));

it("offers every listed model inside a capped, scrolling list", () => {
  show(MANY);
  open();

  const list = screen.getByRole("listbox");
  // Nothing is dropped from the list — the cap is on its height, not on how
  // many models a provider may have.
  expect(within(list).getAllByRole("option")).toHaveLength(MANY.length);
  expect(list.className).toContain("max-h-[248px]");
  expect(list.className).toContain("overflow-y-auto");
});

it("writes the model ID you pick and closes", () => {
  const onChange = show(MANY);
  open();
  fireEvent.click(screen.getByRole("option", { name: /qwen3\.4-flash/ }));

  expect(onChange).toHaveBeenCalledWith("qwen/qwen3.4-flash");
  expect(screen.queryByRole("listbox")).toBeNull();
});

it("narrows as you type, and stays shut for an ID nobody lists", () => {
  show(["gpt-5", "gpt-5-mini", "claude-opus"]);
  const input = screen.getByLabelText("Model ID");

  fireEvent.change(input, { target: { value: "mini" } });
  expect(
    within(screen.getByRole("listbox"))
      .getAllByRole("option")
      .map((option) => option.textContent),
  ).toEqual(["gpt-5-mini"]);

  // An unlisted ID is this field working, not an error: no popup, no complaint.
  fireEvent.change(input, { target: { value: "my-own-deployment" } });
  expect(screen.queryByRole("listbox")).toBeNull();
});

it("walks the list from the keyboard", () => {
  const onChange = show(["gpt-5", "gpt-5-mini"]);
  const input = screen.getByLabelText("Model ID");

  fireEvent.keyDown(input, { key: "ArrowDown" });
  fireEvent.keyDown(input, { key: "ArrowDown" });
  fireEvent.keyDown(input, { key: "Enter" });

  expect(onChange).toHaveBeenCalledWith("gpt-5-mini");

  fireEvent.keyDown(input, { key: "ArrowDown" });
  fireEvent.keyDown(input, { key: "Escape" });
  expect(screen.queryByRole("listbox")).toBeNull();
});

it("still shows the whole list when the field already holds one of them", () => {
  // Filtering on an exact hit would leave "open the list" showing one row: the
  // model already selected, and no way to reach the other twenty-nine.
  show(MANY, MANY[7]);
  open();

  expect(screen.getAllByRole("option")).toHaveLength(MANY.length);
  expect(screen.getByRole("option", { selected: true }).textContent).toBe(
    MANY[7],
  );
});
