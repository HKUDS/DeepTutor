import { render } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ComponentProps, ReactNode } from "react";

import { SidebarShell } from "@/components/sidebar/SidebarShell";

const fixture = vi.hoisted(() => ({
  collapsed: false,
  push: vi.fn(),
  close: vi.fn(),
  setCollapsed: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({
    children,
    prefetch,
    ...props
  }: Omit<ComponentProps<"a">, "prefetch"> & {
    children?: ReactNode;
    prefetch?: boolean;
  }) => (
    <a data-prefetch={String(prefetch)} {...props}>
      {children}
    </a>
  ),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/chat",
  useRouter: () => ({ push: fixture.push }),
}));
vi.mock("next/image", () => ({ default: () => null }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("@/context/AppShellContext", () => ({
  useAppShell: () => ({
    sidebarCollapsed: fixture.collapsed,
    setSidebarCollapsed: fixture.setCollapsed,
  }),
}));
vi.mock("@/components/access/CapabilityAccessContext", () => ({
  useCapabilityAccess: () => ({ has: () => true }),
}));
vi.mock("@/components/layout/AppShell", () => ({
  useSidebarDrawer: () => ({ close: fixture.close }),
}));
vi.mock("@/hooks/useDevice", () => ({
  useDevice: () => ({ isMobile: false }),
}));
vi.mock("@/hooks/useChatWorkspaces", () => ({
  useChatWorkspaces: () => ({ workspaces: [], error: "" }),
}));
vi.mock("@/lib/app-update", () => ({
  fetchAppUpdateStatus: vi.fn(() => Promise.resolve({ current_version: "1.0" })),
  subscribeAppUpdateStatus: vi.fn(() => () => undefined),
}));

function expectSidebarLinksToDisablePrefetch() {
  const links = [
    ...document.querySelectorAll<HTMLAnchorElement>("a[data-prefetch]"),
  ];
  expect(links.length).toBeGreaterThan(0);
  for (const link of links) {
    expect(link).toHaveAttribute("data-prefetch", "false");
  }
}

it("disables viewport prefetch for expanded sidebar navigation", () => {
  fixture.collapsed = false;
  render(<SidebarShell />);

  expectSidebarLinksToDisablePrefetch();
});

it("disables viewport prefetch for collapsed sidebar navigation", () => {
  fixture.collapsed = true;
  render(<SidebarShell />);

  expectSidebarLinksToDisablePrefetch();
});
