"use client";

import { useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import {
  History,
  BookOpen,
  Edit3,
  Settings,
  Book,
  ChevronsLeft,
  ChevronsRight,
  MessageSquare,
  Calculator,
} from "lucide-react";
import { useGlobal } from "@/context/GlobalContext";
import { getTranslation } from "@/lib/i18n";

const SIDEBAR_EXPANDED_WIDTH = 256;
const SIDEBAR_COLLAPSED_WIDTH = 64;
const BRAND_NAME = "Hi-NoteBook";
const BRAND_LOGO_SRC = "/logo.png";
const BRAND_LOGO_SIZE_COLLAPSED = 40;
const BRAND_LOGO_HEIGHT_EXPANDED = 36;

export default function Sidebar() {
  const pathname = usePathname();
  const { uiSettings, sidebarCollapsed, toggleSidebar } = useGlobal();
  const lang = uiSettings.language;

  const t = (key: string) => getTranslation(lang, key);

  const [showTooltip, setShowTooltip] = useState<string | null>(null);

  const navGroups = [
    {
      name: "",
      items: [
        { name: t("Notebooks"), href: "/notebooks", icon: Book },
        { name: t("Knowledge Bases"), href: "/knowledge", icon: BookOpen },
        { name: t("History"), href: "/history", icon: History },
      ],
    },
    {
      name: t("Tools"),
      items: [
        { name: t("Chat"), href: "/chat", icon: MessageSquare },
        { name: t("Co-Writer"), href: "/co_writer", icon: Edit3 },
        { name: t("Smart Solver"), href: "/solver", icon: Calculator },
      ],
    },
  ];

  const currentWidth = sidebarCollapsed
    ? SIDEBAR_COLLAPSED_WIDTH
    : SIDEBAR_EXPANDED_WIDTH;

  // Collapsed sidebar
  if (sidebarCollapsed) {
    return (
      <div
        className="relative flex-shrink-0 bg-background h-full border-r border-border flex flex-col"
        style={{ width: SIDEBAR_COLLAPSED_WIDTH }}
      >
        {/* Header */}
        <div className="px-2 py-3 border-b border-border-light flex justify-center">
          <div className="w-10 h-10 rounded-lg flex items-center justify-center overflow-hidden">
            <Image
              src={BRAND_LOGO_SRC}
              alt={`${BRAND_NAME} Logo`}
              width={BRAND_LOGO_SIZE_COLLAPSED}
              height={BRAND_LOGO_SIZE_COLLAPSED}
              className="object-cover object-left"
              unoptimized
              priority
            />
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto py-2 space-y-1">
          {navGroups.map((group, idx) => (
            <div key={idx} className="space-y-0.5 px-2">
              {group.items.map((item) => {
                const isActive = pathname === item.href;
                return (
                  <div key={item.href} className="relative">
                    <Link
                      href={item.href}
                      className={`group flex items-center justify-center p-2 rounded-lg border ${
                        isActive
                          ? "bg-secondary text-primary shadow-sm border-border-light"
                          : "text-secondary-foreground hover:bg-secondary hover:text-primary hover:shadow-sm border-transparent hover:border-border-light"
                      }`}
                      onMouseEnter={() => setShowTooltip(item.href)}
                      onMouseLeave={() => setShowTooltip(null)}
                    >
                      <item.icon
                        className={`w-5 h-5 flex-shrink-0 ${
                          isActive
                            ? "text-primary"
                            : "text-muted-foreground group-hover:text-primary"
                        }`}
                      />
                    </Link>
                    {showTooltip === item.href && (
                      <div className="absolute left-full ml-2 top-1/2 -translate-y-1/2 z-50 px-2.5 py-1.5 bg-foreground text-background text-xs rounded-lg shadow-lg whitespace-nowrap pointer-events-none">
                        {item.name}
                        <div className="absolute right-full top-1/2 -translate-y-1/2 border-4 border-transparent border-r-foreground" />
                      </div>
                    )}
                  </div>
                );
              })}
              {idx < navGroups.length - 1 && (
                <div className="h-px bg-border-light my-2" />
              )}
            </div>
          ))}
        </nav>

        {/* Footer */}
        <div className="px-2 py-2 border-t border-border bg-muted">
          <div className="relative">
            <Link
              href="/settings"
              className={`flex items-center justify-center p-2 rounded-lg ${
                pathname === "/settings"
                  ? "bg-secondary text-primary shadow-sm border border-border-light"
                  : "text-secondary-foreground hover:bg-secondary hover:text-foreground"
              }`}
              onMouseEnter={() => setShowTooltip("/settings")}
              onMouseLeave={() => setShowTooltip(null)}
            >
              <Settings
                className={`w-5 h-5 flex-shrink-0 ${
                  pathname === "/settings"
                    ? "text-primary"
                    : "text-muted-foreground"
                }`}
              />
            </Link>
            {showTooltip === "/settings" && (
              <div className="absolute left-full ml-2 top-1/2 -translate-y-1/2 z-50 px-2.5 py-1.5 bg-foreground text-background text-xs rounded-lg shadow-lg whitespace-nowrap pointer-events-none">
                {t("Settings")}
                <div className="absolute right-full top-1/2 -translate-y-1/2 border-4 border-transparent border-r-foreground" />
              </div>
            )}
          </div>

          {/* Expand button at bottom */}
          <button
            onClick={toggleSidebar}
            className="w-full mt-2 flex items-center justify-center p-2 rounded-lg text-muted-foreground hover:bg-secondary hover:text-primary hover:shadow-sm border border-transparent hover:border-border-light"
            title={t("Expand sidebar")}
          >
            <ChevronsRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    );
  }

  // Expanded sidebar
  return (
    <div
      className="relative flex-shrink-0 bg-background h-full border-r border-border flex flex-col"
      style={{ width: currentWidth }}
    >
      {/* Header */}
      <div className="px-6 py-5 border-b border-border-light flex items-center shrink-0">
        <div
          className="relative flex-shrink-0 flex items-center justify-start"
          style={{ height: BRAND_LOGO_HEIGHT_EXPANDED, width: 140 }}
        >
          <Image
            src={BRAND_LOGO_SRC}
            alt={`${BRAND_NAME} Logo`}
            fill
            sizes="140px"
            className="object-contain object-left"
            unoptimized
            priority
          />
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-4 py-4 space-y-5">
        {navGroups.map((group, idx) => (
          <div key={idx}>
            {group.name && (
              <div className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider px-3 mb-2 truncate">
                {group.name}
              </div>
            )}
            <div className="space-y-1">
              {group.items.map((item) => {
                const isActive = pathname === item.href;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`group flex items-center gap-3 px-3 py-2 rounded-lg transition-colors border ${
                      isActive
                        ? "bg-secondary text-primary shadow-sm border-border-light"
                        : "text-secondary-foreground hover:bg-secondary hover:text-primary border-transparent"
                    }`}
                  >
                    <item.icon
                      className={`w-4 h-4 flex-shrink-0 ${
                        isActive
                          ? "text-primary"
                          : "text-muted-foreground group-hover:text-primary"
                      }`}
                    />
                    <span className="font-medium text-sm truncate">
                      {item.name}
                    </span>
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-border bg-muted flex items-center justify-between gap-2 shrink-0">
        <Link
          href="/settings"
          className={`flex-1 flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors border ${
            pathname === "/settings"
              ? "bg-secondary text-primary shadow-sm border-border-light"
              : "text-secondary-foreground hover:bg-secondary hover:text-foreground border-transparent hover:border-border-light"
          }`}
        >
          <Settings
            className={`w-4 h-4 flex-shrink-0 ${
              pathname === "/settings"
                ? "text-primary"
                : "text-muted-foreground"
            }`}
          />
          <span className="font-medium">{t("Settings")}</span>
        </Link>

        {/* Collapse button moved to footer */}
        <button
          onClick={toggleSidebar}
          className="p-2 text-muted-foreground hover:bg-secondary hover:text-primary rounded-lg border border-transparent hover:border-border-light transition-colors"
          title={t("Collapse sidebar")}
        >
          <ChevronsLeft className="w-5 h-5 flex-shrink-0" />
        </button>
      </div>
    </div>
  );
}
