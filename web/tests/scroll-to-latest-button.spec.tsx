import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import ScrollToLatestButton from "@/components/chat/ScrollToLatestButton";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

it("is hidden until the reader is detached", () => {
  const { rerender } = render(
    <ScrollToLatestButton visible={false} onClick={() => {}} />,
  );
  expect(screen.queryByRole("button", { name: "Back to latest" })).toBeNull();

  rerender(<ScrollToLatestButton visible onClick={() => {}} />);
  expect(screen.getByRole("button", { name: "Back to latest" })).toBeVisible();
});

it("returns the reader to the latest content when clicked", () => {
  const onClick = vi.fn();
  render(<ScrollToLatestButton visible onClick={onClick} />);
  fireEvent.click(screen.getByRole("button", { name: "Back to latest" }));
  expect(onClick).toHaveBeenCalledTimes(1);
});
