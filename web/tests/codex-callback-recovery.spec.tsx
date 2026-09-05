import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { CodexOAuthCard } from "@/components/settings/CodexOAuthCard";
import { completeCodexLogin } from "@/lib/codex-oauth";
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (s: string) => s }),
}));
vi.mock("@/features/settings/store/SettingsStore", () => ({
  useSettings: () => ({
    reloadSettings: vi.fn(),
    setToast: vi.fn(),
    hasUnsavedChanges: false,
  }),
}));
vi.mock("@/lib/codex-oauth", async () => ({
  ...(await vi.importActual("@/lib/codex-oauth")),
  getCodexStatus: vi.fn().mockResolvedValue({
    connection: "authorizing",
    operation_id: "op",
    operation_state: "waiting",
    models: [],
  }),
  completeCodexLogin: vi.fn().mockResolvedValue({ accepted: true }),
}));
test("localhost users can submit a hidden callback and the field is cleared", async () => {
  render(<CodexOAuthCard />);
  const input = await screen.findByLabelText("codex.oauth.callbackInput");
  expect(input).toHaveAttribute("type", "password");
  const url = "http://localhost:1455/auth/callback?code=sample&state=sample";
  fireEvent.change(input, { target: { value: url } });
  fireEvent.click(
    screen.getByRole("button", { name: "codex.oauth.completeLogin" }),
  );
  await waitFor(() => expect(completeCodexLogin).toHaveBeenCalledWith(url));
  expect(input).toHaveValue("");
});

test("a rejected callback stays recoverable without retaining the URL", async () => {
  const { CodexOAuthApiError } = await import("@/lib/codex-oauth");
  vi.mocked(completeCodexLogin).mockRejectedValueOnce(
    new CodexOAuthApiError("state_mismatch", "private details"),
  );
  render(<CodexOAuthCard />);
  const input = await screen.findByLabelText("codex.oauth.callbackInput");
  fireEvent.change(input, {
    target: {
      value: "http://localhost:1455/auth/callback?code=sample&state=wrong",
    },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "codex.oauth.completeLogin" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "codex.oauth.callbackMismatch",
  );
  expect(input).toHaveValue("");
  expect(screen.queryByText("private details")).toBeNull();
});
