import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GitHubCopilotAuthCard } from "@/components/settings/GitHubCopilotAuthCard";
import {
  cancelGitHubCopilotLogin,
  getGitHubCopilotAuthStatus,
  logoutGitHubCopilot,
  startGitHubCopilotLogin,
  type GitHubCopilotAuthStatus,
} from "@/lib/github-copilot-auth";

const t = (key: string, params?: Record<string, unknown>) =>
  params?.user ? `${key}:${String(params.user)}` : key;

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t, i18n: { language: "en" } }),
}));

vi.mock("@/lib/github-copilot-auth", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/github-copilot-auth")
  >("@/lib/github-copilot-auth");
  return {
    ...actual,
    getGitHubCopilotAuthStatus: vi.fn(),
    startGitHubCopilotLogin: vi.fn(),
    cancelGitHubCopilotLogin: vi.fn(),
    logoutGitHubCopilot: vi.fn(),
  };
});

beforeEach(() => {
  vi.clearAllMocks();
});

describe("GitHubCopilotAuthCard", () => {
  it("shows device code and authorization link during login, then cancels cleanly", async () => {
    vi.mocked(getGitHubCopilotAuthStatus).mockResolvedValue({
      connection: "disconnected",
      operation_state: null,
      verification_uri: null,
      user_code: null,
      expires_at: null,
      account_id: null,
      error_code: null,
    });
    vi.mocked(startGitHubCopilotLogin).mockResolvedValue({
      connection: "authorizing",
      operation_state: "waiting",
      verification_uri: "https://github.com/login/device",
      user_code: "ABCD-1234",
      expires_at: 2_000_000_000,
      account_id: null,
      error_code: null,
    });
    vi.mocked(cancelGitHubCopilotLogin).mockResolvedValue({
      connection: "disconnected",
      operation_state: "cancelled",
      verification_uri: null,
      user_code: null,
      expires_at: null,
      account_id: null,
      error_code: null,
    });

    render(<GitHubCopilotAuthCard />);

    const signIn = await screen.findByRole("button", {
      name: "githubCopilot.auth.signIn",
    });
    fireEvent.click(signIn);

    expect(await screen.findByText("ABCD-1234")).toBeInTheDocument();
    const link = screen.getByRole("link", {
      name: "githubCopilot.auth.openAuthorization",
    });
    expect(link).toHaveAttribute("href", "https://github.com/login/device");

    fireEvent.click(
      screen.getByRole("button", { name: "githubCopilot.auth.cancel" }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "githubCopilot.auth.signIn" }),
      ).toBeInTheDocument(),
    );
  });

  it("renders signed-in account handle and supports sign out", async () => {
    vi.mocked(getGitHubCopilotAuthStatus).mockResolvedValue({
      connection: "connected",
      operation_state: "completed",
      verification_uri: null,
      user_code: null,
      expires_at: null,
      account_id: "octocat",
      error_code: null,
    });
    vi.mocked(logoutGitHubCopilot).mockResolvedValue({
      connection: "disconnected",
      operation_state: null,
      verification_uri: null,
      user_code: null,
      expires_at: null,
      account_id: null,
      error_code: null,
    });

    render(<GitHubCopilotAuthCard />);

    expect(
      await screen.findByText("githubCopilot.auth.loggedInAs:octocat"),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "githubCopilot.auth.logout" }),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "githubCopilot.auth.signIn" }),
      ).toBeInTheDocument(),
    );
  });

  it("offers sign-out recovery when stored credentials are invalid", async () => {
    vi.mocked(getGitHubCopilotAuthStatus).mockResolvedValue({
      connection: "error",
      operation_state: "failed",
      verification_uri: null,
      user_code: null,
      expires_at: null,
      account_id: null,
      error_code: "credentials_invalid",
    });
    vi.mocked(logoutGitHubCopilot).mockResolvedValue({
      connection: "disconnected",
      operation_state: null,
      verification_uri: null,
      user_code: null,
      expires_at: null,
      account_id: null,
      error_code: null,
    });

    render(<GitHubCopilotAuthCard />);

    expect(
      await screen.findByText("githubCopilot.auth.credentialsInvalid"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "githubCopilot.auth.signIn" }),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "githubCopilot.auth.logout" }),
    );
    await waitFor(() =>
      expect(
        screen.queryByText("githubCopilot.auth.credentialsInvalid"),
      ).not.toBeInTheDocument(),
    );
  });

  it("ignores stale status responses after unmount and never fires onAuthenticated", async () => {
    let resolveStatus!: (value: GitHubCopilotAuthStatus) => void;
    const pending = new Promise<GitHubCopilotAuthStatus>((resolve) => {
      resolveStatus = resolve;
    });
    vi.mocked(getGitHubCopilotAuthStatus)
      .mockResolvedValueOnce({
        connection: "authorizing",
        operation_state: "waiting",
        verification_uri: "https://github.com/login/device",
        user_code: "STALE-1234",
        expires_at: 2_000_000_000,
        account_id: null,
        error_code: null,
      })
      .mockReturnValueOnce(pending);

    const onAuthenticated = vi.fn();
    const { unmount } = render(
      <GitHubCopilotAuthCard onAuthenticated={onAuthenticated} />,
    );

    expect(await screen.findByText("STALE-1234")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "githubCopilot.auth.checkAgain" }),
    );
    unmount();

    resolveStatus({
      connection: "connected",
      operation_state: "completed",
      verification_uri: null,
      user_code: null,
      expires_at: null,
      account_id: "octocat",
      error_code: null,
    });
    await Promise.resolve();
    await Promise.resolve();

    expect(onAuthenticated).not.toHaveBeenCalled();
  });

  it("resumes automatic polling if the cancel request fails", async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(getGitHubCopilotAuthStatus)
        .mockResolvedValueOnce({
          connection: "authorizing",
          operation_state: "waiting",
          verification_uri: "https://github.com/login/device",
          user_code: "KEEP-5678",
          expires_at: 2_000_000_000,
          account_id: null,
          error_code: null,
        })
        .mockResolvedValueOnce({
          connection: "connected",
          operation_state: "completed",
          verification_uri: null,
          user_code: null,
          expires_at: null,
          account_id: "octocat",
          error_code: null,
        });
      vi.mocked(cancelGitHubCopilotLogin).mockRejectedValueOnce(
        new Error("temporary cancel failure"),
      );

      render(<GitHubCopilotAuthCard />);
      await act(async () => {
        await Promise.resolve();
      });
      expect(screen.getByText("KEEP-5678")).toBeInTheDocument();

      await act(async () => {
        fireEvent.click(
          screen.getByRole("button", { name: "githubCopilot.auth.cancel" }),
        );
        await Promise.resolve();
      });
      expect(screen.getByText("temporary cancel failure")).toBeInTheDocument();

      // Polling must resume after the failed cancel and observe completion.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2100);
      });
      expect(
        screen.getByText("githubCopilot.auth.loggedInAs:octocat"),
      ).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});
