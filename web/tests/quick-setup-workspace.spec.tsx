import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { mockApiFetch, mockInvalidateLLMOptionsCache, mockUseSettings } = vi.hoisted(() => ({
  mockApiFetch: vi.fn(),
  mockInvalidateLLMOptionsCache: vi.fn(),
  mockUseSettings: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { resolvedLanguage: "zh", language: "zh" },
  }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/api", () => ({
  apiFetch: mockApiFetch,
  apiUrl: (path: string) => path,
}));

vi.mock("@/lib/llm-options", () => ({
  invalidateLLMOptionsCache: mockInvalidateLLMOptionsCache,
}));

vi.mock("@/components/common/ProviderIcon", () => ({
  default: ({ provider }: { provider: string }) => <span data-testid={`icon-${provider}`} />,
}));

vi.mock("@/features/settings/store/SettingsStore", () => ({
  useSettings: mockUseSettings,
}));

import { QuickModelSetupWorkspace } from "@/components/settings/QuickModelSetupWorkspace";
import type { Catalog } from "@/lib/model-catalog-types";

function emptyCatalog(): Catalog {
  return {
    version: 1,
    connections: [],
    services: {
      llm: { active_profile_id: null, active_model_id: null, profiles: [] },
      task: { active_profile_id: null, active_model_id: null, profiles: [] },
      embedding: { active_profile_id: null, active_model_id: null, profiles: [] },
      search: { active_profile_id: null, profiles: [] },
      tts: { active_profile_id: null, active_model_id: null, profiles: [] },
      stt: { active_profile_id: null, active_model_id: null, profiles: [] },
      imagegen: { active_profile_id: null, active_model_id: null, profiles: [] },
      videogen: { active_profile_id: null, active_model_id: null, profiles: [] },
    },
  };
}

function makeSettings(overrides: Record<string, unknown> = {}) {
  return {
    catalog: emptyCatalog(),
    connectionTargets: [
      {
        provider: "deepseek",
        default_base_url: "https://api.deepseek.com",
        services: {},
      },
      {
        provider: "siliconflow",
        default_base_url: "https://api.siliconflow.cn/v1",
        services: {},
      },
      {
        provider: "minimax",
        default_base_url: "https://api.minimax.io/v1",
        services: {},
      },
    ],
    providers: {
      llm: [],
      task: [],
      embedding: [],
      search: [],
      tts: [],
      stt: [],
      imagegen: [],
      videogen: [],
    },
    catalogEditable: true,
    settingsLoading: false,
    reloadSettings: vi.fn().mockResolvedValue(undefined),
    saveRegistry: vi.fn().mockResolvedValue(true),
    ...overrides,
  };
}

function jsonResponse(payload: unknown, ok = true, status = 200) {
  return Promise.resolve({
    ok,
    status,
    json: async () => payload,
  });
}

describe("QuickModelSetupWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows an administrator-only notice when catalogEditable is false", () => {
    mockUseSettings.mockReturnValue(makeSettings({ catalogEditable: false }));
    render(<QuickModelSetupWorkspace />);
    expect(screen.getByText("Only administrators can manage providers.")).toBeTruthy();
    expect(screen.queryByText("quickSetup.step1.title")).toBeNull();
  });

  it("collapses the add form once settings load for returning users with an active LLM", async () => {
    const catalog = emptyCatalog();
    catalog.services.llm = {
      active_profile_id: "p1",
      active_model_id: "m1",
      profiles: [
        {
          id: "p1",
          name: "DeepSeek",
          binding: "deepseek",
          base_url: "https://api.deepseek.com",
          api_key: "***",
          api_version: "",
          models: [{ id: "m1", name: "deepseek-chat", model: "deepseek-chat" }],
        },
      ],
    };

    const { rerender } = render(
      (() => {
        mockUseSettings.mockReturnValue(
          makeSettings({ settingsLoading: true, catalogEditable: null }),
        );
        return <QuickModelSetupWorkspace />;
      })(),
    );
    expect(screen.queryByText("quickSetup.step1.title")).toBeNull();

    mockUseSettings.mockReturnValue(
      makeSettings({ catalog, settingsLoading: false, catalogEditable: true }),
    );
    rerender(<QuickModelSetupWorkspace />);

    await waitFor(() => {
      expect(screen.getByText("quickSetup.activeCard.label")).toBeTruthy();
    });
    expect(screen.queryByText("quickSetup.step1.title")).toBeNull();
  });

  it("resets manualModel when switching vendors so auto-discovered models take effect and invalidates LLM cache", async () => {
    const settings = makeSettings();
    mockUseSettings.mockReturnValue(settings);
    mockApiFetch.mockImplementation((url: string) => {
      if (url === "/api/settings/test-provider") {
        return jsonResponse({
          status: "connected",
          models: [{ id: "Qwen/Qwen3-32B" }],
        });
      }
      if (url === "/api/settings/apply/provider") {
        return jsonResponse({ catalog: emptyCatalog() });
      }
      return jsonResponse({});
    });

    render(<QuickModelSetupWorkspace />);
    // Click SiliconFlow card — must NOT prefill manualModel with recommendedModels[0].
    fireEvent.click(screen.getByText("quickSetup.vendor.siliconflow.name"));
    fireEvent.change(screen.getByPlaceholderText("sk-..."), {
      target: { value: "sk-test-siliconflow" },
    });
    fireEvent.click(screen.getByRole("button", { name: /quickSetup\.action\.verifyAndEnable/ }));

    await waitFor(() => {
      expect(mockInvalidateLLMOptionsCache).toHaveBeenCalledTimes(1);
    });

    const applyCall = mockApiFetch.mock.calls.find(
      ([url]) => url === "/api/settings/apply/provider",
    );
    expect(applyCall).toBeTruthy();
    const applyBody = JSON.parse(applyCall![1].body as string);
    // Auto-discovered Qwen/Qwen3-32B was picked rather than a prefilled recommendedModels[0].
    expect(applyBody.profile.models[0].model).toBe("Qwen/Qwen3-32B");
    expect(settings.saveRegistry).toHaveBeenCalledWith({
      kind: "task_choice",
      task: { mode: "inherit" },
    });
  });

  it("aligns MiniMax region selector with both Get Key link and probed base URL", async () => {
    mockUseSettings.mockReturnValue(makeSettings());
    mockApiFetch.mockImplementation((url: string) => {
      if (url === "/api/settings/test-provider") {
        return jsonResponse({
          status: "connected",
          models: [{ id: "MiniMax-M3.1-Flash" }],
        });
      }
      return jsonResponse({ catalog: emptyCatalog() });
    });

    render(<QuickModelSetupWorkspace />);
    fireEvent.click(screen.getByText("quickSetup.step1.moreProviders"));
    fireEvent.click(screen.getByText("quickSetup.vendor.minimax.name"));

    // In zh UI, China region is active by default and matches platform.minimaxi.com.
    const keyLink = screen.getByRole("link", { name: /quickSetup\.step2\.getKeyLink/ });
    expect(keyLink.getAttribute("href")).toContain("platform.minimaxi.com");

    // Switch to International region -> link switches to platform.minimax.io and base_url to api.minimax.io/v1.
    fireEvent.click(screen.getByRole("button", { name: "quickSetup.region.minimax.global" }));
    expect(keyLink.getAttribute("href")).toContain("platform.minimax.io");

    fireEvent.change(screen.getByPlaceholderText("quickSetup.placeholder.apiKey"), {
      target: { value: "minimax-global-key" },
    });
    fireEvent.click(screen.getByRole("button", { name: /quickSetup\.action\.verifyAndEnable/ }));

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith(
        "/api/settings/test-provider",
        expect.anything(),
      );
    });
    const probeCall = mockApiFetch.mock.calls.find(
      ([url]) => url === "/api/settings/test-provider",
    );
    const probeBody = JSON.parse(probeCall![1].body as string);
    expect(probeBody.base_url).toBe("https://api.minimax.io/v1");
  });

  it("allows saving custom relays when /models probe returns unavailable", async () => {
    mockUseSettings.mockReturnValue(makeSettings());
    mockApiFetch.mockImplementation((url: string) => {
      if (url === "/api/settings/test-provider") {
        return jsonResponse({ status: "unavailable", models: [], http_status: 404 });
      }
      return jsonResponse({ catalog: emptyCatalog() });
    });

    render(<QuickModelSetupWorkspace />);
    fireEvent.click(screen.getByText("quickSetup.step1.moreProviders"));
    fireEvent.click(screen.getByText("quickSetup.vendor.custom.name"));

    fireEvent.change(screen.getByPlaceholderText("https://api.example.com/v1"), {
      target: { value: "https://relay.example.com/v1" },
    });
    fireEvent.change(screen.getByPlaceholderText("sk-..."), {
      target: { value: "sk-relay-key" },
    });
    fireEvent.change(screen.getByPlaceholderText("gpt-4o-mini"), {
      target: { value: "my-relay-model" },
    });
    fireEvent.click(screen.getByRole("button", { name: /quickSetup\.action\.verifyAndEnable/ }));

    await waitFor(() => {
      expect(screen.getByText("quickSetup.success.probeSkipped")).toBeTruthy();
    });
    expect(mockInvalidateLLMOptionsCache).toHaveBeenCalledTimes(1);
  });
});
