"use client";

import type { WorkspaceTab } from "./workspaceReducer";
import type { TrFn } from "./locale";

const TABS: { key: WorkspaceTab; cn: string; en: string; color: string }[] = [
  { key: "map", cn: "知识地图", en: "Map", color: "fw-blue" },
  { key: "chat", cn: "对话", en: "Chat", color: "fw-green" },
  { key: "evidence", cn: "证据", en: "Evidence", color: "fw-coral" },
];

export function MobileTabs({
  activeTab,
  tr,
  onChange,
}: {
  activeTab: WorkspaceTab;
  tr: TrFn;
  onChange: (tab: WorkspaceTab) => void;
}) {
  return (
    <nav
      className="fw-mobile-tabs"
      role="tablist"
      aria-label={tr("学习工作台视图", "Workspace views")}
      data-testid="mobile-tabs"
    >
      {TABS.map((tab) => (
        <button
          key={tab.key}
          type="button"
          role="tab"
          className={`fw-mobile-tab ${tab.color}`}
          aria-selected={activeTab === tab.key}
          onClick={() => onChange(tab.key)}
          data-testid={`mobile-tab-${tab.key}`}
        >
          {tr(tab.cn, tab.en)}
        </button>
      ))}
    </nav>
  );
}
