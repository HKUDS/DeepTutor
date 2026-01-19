"use client";

import { useState, useRef, useEffect, useMemo, useCallback } from "react";
import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import {
  Home,
  History,
  BookOpen,
  PenTool,
  Calculator,
  Microscope,
  Edit3,
  Settings,
  Book,
  GraduationCap,
  Lightbulb,
  Github,
  Globe,
  ChevronsLeft,
  ChevronsRight,
  GripVertical,
  Check,
  X,
  LucideIcon,
} from "lucide-react";
import { useGlobal } from "@/context/GlobalContext";
import { getTranslation } from "@/lib/i18n";

const SIDEBAR_EXPANDED_WIDTH = 256;
const SIDEBAR_COLLAPSED_WIDTH = 64;

// Navigation item type
interface NavItem {
  name: string;
  href: string;
  icon: LucideIcon;
}

// All available navigation items (static reference)
const ALL_NAV_ITEMS: Record<string, { icon: LucideIcon; nameKey: string }> = {
  "/": { icon: Home, nameKey: "Home" },
  "/history": { icon: History, nameKey: "History" },
  "/knowledge": { icon: BookOpen, nameKey: "Knowledge Bases" },
  "/notebook": { icon: Book, nameKey: "Notebooks" },
  "/question": { icon: PenTool, nameKey: "Question Generator" },
  "/solver": { icon: Calculator, nameKey: "Smart Solver" },
  "/guide": { icon: GraduationCap, nameKey: "Guided Learning" },
  "/ideagen": { icon: Lightbulb, nameKey: "IdeaGen" },
  "/research": { icon: Microscope, nameKey: "Deep Research" },
  "/co_writer": { icon: Edit3, nameKey: "Co-Writer" },
};

export default function Sidebar() {
  const pathname = usePathname();
  const {
    uiSettings,
    sidebarCollapsed,
    toggleSidebar,
    sidebarDescription,
    setSidebarDescription,
    sidebarNavOrder,
    setSidebarNavOrder,
  } = useGlobal();
  const lang = uiSettings.language;

  const t = useCallback((key: string) => getTranslation(lang, key), [lang]);

  const [showTooltip, setShowTooltip] = useState<string | null>(null);

  // Editable description state
  const [isEditingDescription, setIsEditingDescription] = useState(false);
  const [editingDescriptionValue, setEditingDescriptionValue] =
    useState(sidebarDescription);
  const descriptionInputRef = useRef<HTMLInputElement>(null);

  // Drag and drop state
  const [draggedItem, setDraggedItem] = useState<string | null>(null);
  const [dragOverItem, setDragOverItem] = useState<string | null>(null);
  const [dragGroup, setDragGroup] = useState<"start" | "learnResearch" | null>(
    null,
  );

  // Build navigation items from saved order - defined inside useMemo to properly capture dependencies
  const navGroups = useMemo(() => {
    const buildNavItems = (hrefs: string[]): NavItem[] => {
      return hrefs
        .filter((href) => ALL_NAV_ITEMS[href])
        .map((href) => ({
          name: t(ALL_NAV_ITEMS[href].nameKey),
          href,
          icon: ALL_NAV_ITEMS[href].icon,
        }));
    };
    
    return [
      {
        id: "start" as const,
        name: "WORKSPACE",
        items: buildNavItems(sidebarNavOrder.start),
      },
      {
        id: "learnResearch" as const,
        name: t("Learn") + " & " + t("Research"),
        items: buildNavItems(sidebarNavOrder.learnResearch),
      },
    ];
  }, [sidebarNavOrder, t]);

  // Handle description edit
  const handleDescriptionEdit = () => {
    setEditingDescriptionValue(sidebarDescription);
    setIsEditingDescription(true);
  };

  const handleDescriptionSave = () => {
    setSidebarDescription(
      editingDescriptionValue.trim() || "✨ Your description here",
    );
    setIsEditingDescription(false);
  };

  const handleDescriptionCancel = () => {
    setEditingDescriptionValue(sidebarDescription);
    setIsEditingDescription(false);
  };

  const handleDescriptionKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      handleDescriptionSave();
    } else if (e.key === "Escape") {
      handleDescriptionCancel();
    }
  };

  // Focus input when editing starts
  useEffect(() => {
    if (isEditingDescription && descriptionInputRef.current) {
      descriptionInputRef.current.focus();
      descriptionInputRef.current.select();
    }
  }, [isEditingDescription]);

  // Drag and drop handlers
  const handleDragStart = (
    e: React.DragEvent,
    href: string,
    groupId: "start" | "learnResearch",
  ) => {
    setDraggedItem(href);
    setDragGroup(groupId);
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", href);
  };

  const handleDragOver = (
    e: React.DragEvent,
    href: string,
    groupId: "start" | "learnResearch",
  ) => {
    e.preventDefault();
    if (dragGroup !== groupId) return; // Only allow drag within same group
    if (draggedItem !== href) {
      setDragOverItem(href);
    }
  };

  const handleDragLeave = () => {
    setDragOverItem(null);
  };

  const handleDrop = (
    e: React.DragEvent,
    targetHref: string,
    groupId: "start" | "learnResearch",
  ) => {
    e.preventDefault();
    if (!draggedItem || dragGroup !== groupId) return;

    const groupKey = groupId;
    const currentOrder = [...sidebarNavOrder[groupKey]];
    const draggedIndex = currentOrder.indexOf(draggedItem);
    const targetIndex = currentOrder.indexOf(targetHref);

    if (
      draggedIndex !== -1 &&
      targetIndex !== -1 &&
      draggedIndex !== targetIndex
    ) {
      // Remove dragged item and insert at new position
      currentOrder.splice(draggedIndex, 1);
      currentOrder.splice(targetIndex, 0, draggedItem);

      setSidebarNavOrder({
        ...sidebarNavOrder,
        [groupKey]: currentOrder,
      });
    }

    setDraggedItem(null);
    setDragOverItem(null);
    setDragGroup(null);
  };

  const handleDragEnd = () => {
    setDraggedItem(null);
    setDragOverItem(null);
    setDragGroup(null);
  };

  const currentWidth = sidebarCollapsed
    ? SIDEBAR_COLLAPSED_WIDTH
    : SIDEBAR_EXPANDED_WIDTH;

  return (
    <div
      className="relative flex-shrink-0 bg-slate-50/80 dark:bg-slate-800/80 h-full border-r border-slate-200 dark:border-slate-700 flex flex-col transition-all duration-300 ease-in-out overflow-hidden"
      style={{ width: currentWidth }}
    >
      {/* Header */}
      <div
        className={`border-b border-slate-100 dark:border-slate-700 transition-all duration-300 ${
          sidebarCollapsed ? "px-2 py-3" : "px-4 py-3"
        }`}
      >
        <div className="flex flex-col gap-2">
          <div
            className={`flex items-center ${sidebarCollapsed ? "justify-center" : "justify-between"}`}
          >
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg flex items-center justify-center overflow-hidden flex-shrink-0">
                <Image
                  src="/logo.png"
                  alt="DeepTutor Logo"
                  width={32}
                  height={32}
                  className="object-contain"
                  priority
                />
              </div>
              <h1
                className={`font-bold text-slate-900 dark:text-slate-100 tracking-tight text-base whitespace-nowrap transition-all duration-300 ${
                  sidebarCollapsed
                    ? "opacity-0 w-0 overflow-hidden"
                    : "opacity-100"
                }`}
              >
                DeepTutor
              </h1>
            </div>
            <div
              className={`flex items-center gap-0.5 transition-all duration-300 ${
                sidebarCollapsed
                  ? "opacity-0 w-0 overflow-hidden"
                  : "opacity-100"
              }`}
            >
              {/* Collapse button */}
              <button
                onClick={toggleSidebar}
                className="text-slate-400 hover:text-blue-500 dark:hover:text-blue-400 p-1.5 hover:bg-slate-100 dark:hover:bg-slate-700 rounded transition-colors"
                title={t("Collapse sidebar")}
              >
                <ChevronsLeft className="w-4 h-4" />
              </button>
              <a
                href="https://hkuds.github.io/DeepTutor/"
                target="_blank"
                rel="noopener noreferrer"
                className="text-slate-400 hover:text-blue-500 dark:hover:text-blue-400 p-1.5 hover:bg-slate-100 dark:hover:bg-slate-700 rounded transition-colors"
                title="Visit DeepTutor Homepage"
              >
                <Globe className="w-4 h-4" />
              </a>
              <a
                href="https://github.com/HKUDS/DeepTutor"
                target="_blank"
                rel="noopener noreferrer"
                className="text-slate-400 hover:text-slate-800 dark:hover:text-slate-200 p-1.5 hover:bg-slate-100 dark:hover:bg-slate-700 rounded transition-colors"
                title="View on GitHub"
              >
                <Github className="w-4 h-4" />
              </a>
            </div>
          </div>

          {/* Editable Description - only show when expanded */}
          <div
            className={`transition-all duration-300 ${
              sidebarCollapsed ? "opacity-0 h-0 overflow-hidden" : "opacity-100"
            }`}
          >
            {isEditingDescription ? (
              <div className="flex items-center gap-1">
                <input
                  ref={descriptionInputRef}
                  type="text"
                  value={editingDescriptionValue}
                  onChange={(e) => setEditingDescriptionValue(e.target.value)}
                  onKeyDown={handleDescriptionKeyDown}
                  className="flex-1 text-[10px] font-medium text-slate-700 dark:text-slate-300 bg-white dark:bg-slate-600 px-2 py-1.5 rounded-md border border-blue-300 dark:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20"
                  placeholder="Enter your description..."
                />
                <button
                  onClick={handleDescriptionSave}
                  className="p-1 text-green-500 hover:text-green-600 dark:text-green-400 dark:hover:text-green-300"
                  title="Save"
                >
                  <Check className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={handleDescriptionCancel}
                  className="p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                  title="Cancel"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ) : (
              <div
                onClick={handleDescriptionEdit}
                className="text-[10px] font-medium text-slate-500 dark:text-slate-400 bg-slate-100/50 dark:bg-slate-700/50 px-2 py-1.5 rounded-md border border-slate-100 dark:border-slate-600 truncate cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-700 hover:border-slate-200 dark:hover:border-slate-500 transition-colors group"
                title="Click to edit"
              >
                <span className="group-hover:hidden">{sidebarDescription}</span>
                <span className="hidden group-hover:inline text-blue-500 dark:text-blue-400">
                  ✏️ {t("Click to edit")}
                </span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav
        className={`flex-1 overflow-y-auto py-2 space-y-4 transition-all duration-300 ${
          sidebarCollapsed ? "px-2" : "px-2"
        }`}
      >
        {navGroups.map((group, idx) => (
          <div key={group.id}>
            {/* Group title - only show when expanded */}
            <div
              className={`text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider mb-2 truncate transition-all duration-300 ${
                sidebarCollapsed
                  ? "opacity-0 h-0 overflow-hidden px-0"
                  : "opacity-100 px-1"
              }`}
            >
              {group.name}
            </div>
            <div className="space-y-1">
              {group.items.map((item) => {
                const isActive = pathname === item.href;
                const isDragging = draggedItem === item.href;
                const isDragOver =
                  dragOverItem === item.href && dragGroup === group.id;

                return (
                  <div
                    key={item.href}
                    draggable={!sidebarCollapsed}
                    onDragStart={(e) =>
                      !sidebarCollapsed &&
                      handleDragStart(e, item.href, group.id)
                    }
                    onDragOver={(e) =>
                      !sidebarCollapsed &&
                      handleDragOver(e, item.href, group.id)
                    }
                    onDragLeave={handleDragLeave}
                    onDrop={(e) =>
                      !sidebarCollapsed && handleDrop(e, item.href, group.id)
                    }
                    onDragEnd={handleDragEnd}
                    className={`group relative ${isDragging ? "opacity-50" : ""} ${
                      isDragOver ? "border-t-2 border-blue-500" : ""
                    }`}
                  >
                    <Link
                      href={item.href}
                      className={`flex items-center rounded-md border transition-all duration-200 ${
                        sidebarCollapsed
                          ? "justify-center p-2"
                          : "gap-2.5 pl-2 pr-1.5 py-2"
                      } ${
                        isActive
                          ? "bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm border-slate-100 dark:border-slate-600"
                          : "text-slate-600 dark:text-slate-300 hover:bg-white dark:hover:bg-slate-700 hover:text-blue-600 dark:hover:text-blue-400 hover:shadow-sm border-transparent hover:border-slate-100 dark:hover:border-slate-600"
                      }`}
                      onMouseEnter={() =>
                        sidebarCollapsed && setShowTooltip(item.href)
                      }
                      onMouseLeave={() => setShowTooltip(null)}
                    >
                      <item.icon
                        className={`w-5 h-5 flex-shrink-0 transition-colors ${
                          isActive
                            ? "text-blue-500 dark:text-blue-400"
                            : "text-slate-400 dark:text-slate-500 group-hover:text-blue-500 dark:group-hover:text-blue-400"
                        }`}
                      />
                      <span
                        className={`font-medium text-sm whitespace-nowrap flex-1 transition-all duration-300 ${
                          sidebarCollapsed
                            ? "opacity-0 w-0 overflow-hidden"
                            : "opacity-100"
                        }`}
                      >
                        {item.name}
                      </span>
                      {/* Drag handle - only show when expanded and hovering, now on right */}
                      <div
                        className={`flex-shrink-0 transition-all duration-300 ${
                          sidebarCollapsed
                            ? "w-0 opacity-0 overflow-hidden"
                            : "opacity-0 group-hover:opacity-100"
                        }`}
                      >
                        <GripVertical className="w-3.5 h-3.5 text-slate-300 dark:text-slate-600 cursor-grab active:cursor-grabbing" />
                      </div>
                    </Link>
                    {/* Tooltip for collapsed state */}
                    {sidebarCollapsed && showTooltip === item.href && (
                      <div className="absolute left-full ml-2 top-1/2 -translate-y-1/2 z-50 px-2.5 py-1.5 bg-slate-900 dark:bg-slate-700 text-white text-xs rounded-lg shadow-lg whitespace-nowrap pointer-events-none">
                        {item.name}
                        <div className="absolute right-full top-1/2 -translate-y-1/2 border-4 border-transparent border-r-slate-900 dark:border-r-slate-700" />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            {/* Divider between groups in collapsed mode */}
            {sidebarCollapsed && idx < navGroups.length - 1 && (
              <div className="h-px bg-slate-200 dark:bg-slate-700 my-2 mx-1" />
            )}
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div
        className={`border-t border-slate-100 dark:border-slate-700 bg-slate-50/30 dark:bg-slate-800/30 transition-all duration-300 ${
          sidebarCollapsed ? "px-2 py-2" : "px-2 py-2"
        }`}
      >
        <div className="relative">
          <Link
            href="/settings"
            className={`flex items-center rounded-md text-sm transition-all duration-200 ${
              sidebarCollapsed
                ? "justify-center p-2"
                : "gap-2.5 pl-2 pr-1.5 py-2"
            } ${
              pathname === "/settings"
                ? "bg-white dark:bg-slate-700 text-blue-600 dark:text-blue-400 shadow-sm border border-slate-100 dark:border-slate-600"
                : "text-slate-600 dark:text-slate-300 hover:bg-white dark:hover:bg-slate-700 hover:text-slate-900 dark:hover:text-slate-100"
            }`}
            onMouseEnter={() => sidebarCollapsed && setShowTooltip("/settings")}
            onMouseLeave={() => setShowTooltip(null)}
          >
            <Settings
              className={`w-5 h-5 flex-shrink-0 transition-colors ${
                pathname === "/settings"
                  ? "text-blue-500 dark:text-blue-400"
                  : "text-slate-400 dark:text-slate-500"
              }`}
            />
            <span
              className={`whitespace-nowrap flex-1 transition-all duration-300 ${
                sidebarCollapsed
                  ? "opacity-0 w-0 overflow-hidden"
                  : "opacity-100"
              }`}
            >
              {t("Settings")}
            </span>
          </Link>
          {/* Tooltip for collapsed state */}
          {sidebarCollapsed && showTooltip === "/settings" && (
            <div className="absolute left-full ml-2 top-1/2 -translate-y-1/2 z-50 px-2.5 py-1.5 bg-slate-900 dark:bg-slate-700 text-white text-xs rounded-lg shadow-lg whitespace-nowrap pointer-events-none">
              {t("Settings")}
              <div className="absolute right-full top-1/2 -translate-y-1/2 border-4 border-transparent border-r-slate-900 dark:border-r-slate-700" />
            </div>
          )}
        </div>

        {/* Expand/Collapse button at bottom */}
        <button
          onClick={toggleSidebar}
          className={`w-full mt-2 flex items-center rounded-md text-slate-400 dark:text-slate-500 hover:bg-white dark:hover:bg-slate-700 hover:text-blue-500 dark:hover:text-blue-400 hover:shadow-sm border border-transparent hover:border-slate-100 dark:hover:border-slate-600 transition-all duration-200 ${
            sidebarCollapsed ? "justify-center p-2" : "gap-2.5 pl-2 pr-1.5 py-2"
          }`}
          title={sidebarCollapsed ? t("Expand sidebar") : t("Collapse sidebar")}
        >
          <div className="w-5 h-5 flex items-center justify-center flex-shrink-0">
            {sidebarCollapsed ? (
              <ChevronsRight className="w-4 h-4" />
            ) : (
              <ChevronsLeft className="w-4 h-4" />
            )}
          </div>
          <span
            className={`text-sm whitespace-nowrap flex-1 transition-all duration-300 ${
              sidebarCollapsed ? "opacity-0 w-0 overflow-hidden" : "opacity-100"
            }`}
          >
            {t("Collapse sidebar")}
          </span>
        </button>
      </div>
    </div>
  );
}
