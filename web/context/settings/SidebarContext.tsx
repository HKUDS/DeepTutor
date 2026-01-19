"use client";

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
} from "react";
import { apiUrl } from "@/lib/api";
import {
  SidebarNavOrder,
  SIDEBAR_MIN_WIDTH,
  SIDEBAR_MAX_WIDTH,
  SIDEBAR_DEFAULT_WIDTH,
  DEFAULT_SIDEBAR_DESCRIPTION,
  DEFAULT_NAV_ORDER,
} from "@/types/sidebar";

// Helper to get initial sidebar width from localStorage
function getInitialSidebarWidth(): number {
  if (typeof window === "undefined") return SIDEBAR_DEFAULT_WIDTH;
  const storedWidth = localStorage.getItem("sidebarWidth");
  if (storedWidth) {
    const width = parseInt(storedWidth, 10);
    if (!isNaN(width) && width >= SIDEBAR_MIN_WIDTH && width <= SIDEBAR_MAX_WIDTH) {
      return width;
    }
  }
  return SIDEBAR_DEFAULT_WIDTH;
}

// Helper to get initial collapsed state from localStorage
function getInitialCollapsed(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem("sidebarCollapsed") === "true";
}

// Context type
interface SidebarContextType {
  // Sidebar dimensions
  sidebarWidth: number;
  setSidebarWidth: (width: number) => void;
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (collapsed: boolean) => void;
  toggleSidebar: () => void;
  // Sidebar customization
  sidebarDescription: string;
  setSidebarDescription: (description: string) => Promise<void>;
  sidebarNavOrder: SidebarNavOrder;
  setSidebarNavOrder: (order: SidebarNavOrder) => Promise<void>;
}

const SidebarContext = createContext<SidebarContextType | undefined>(undefined);

export function SidebarProvider({ children }: { children: React.ReactNode }) {
  // Sidebar dimensions state - use lazy initialization
  const [sidebarWidth, setSidebarWidthState] = useState<number>(getInitialSidebarWidth);
  const [sidebarCollapsed, setSidebarCollapsedState] = useState<boolean>(getInitialCollapsed);

  // Sidebar customization state
  const [sidebarDescription, setSidebarDescriptionState] = useState<string>(
    DEFAULT_SIDEBAR_DESCRIPTION,
  );
  const [sidebarNavOrder, setSidebarNavOrderState] =
    useState<SidebarNavOrder>(DEFAULT_NAV_ORDER);

  // Initialize sidebar customization from backend API
  useEffect(() => {
    const loadSidebarSettings = async () => {
      try {
        const response = await fetch(apiUrl("/api/v1/settings/sidebar"));
        if (response.ok) {
          const data = await response.json();
          if (data.description) {
            setSidebarDescriptionState(data.description);
          }
          if (data.nav_order) {
            setSidebarNavOrderState(data.nav_order);
          }
        }
      } catch (e) {
        console.error("Failed to load sidebar settings from backend:", e);
      }
    };
    loadSidebarSettings();
  }, []);

  const setSidebarWidth = useCallback((width: number) => {
    const clampedWidth = Math.max(
      SIDEBAR_MIN_WIDTH,
      Math.min(SIDEBAR_MAX_WIDTH, width),
    );
    setSidebarWidthState(clampedWidth);
    if (typeof window !== "undefined") {
      localStorage.setItem("sidebarWidth", clampedWidth.toString());
    }
  }, []);

  const setSidebarCollapsed = useCallback((collapsed: boolean) => {
    setSidebarCollapsedState(collapsed);
    if (typeof window !== "undefined") {
      localStorage.setItem("sidebarCollapsed", collapsed.toString());
    }
  }, []);

  const toggleSidebar = useCallback(() => {
    setSidebarCollapsedState((prev) => {
      const newValue = !prev;
      if (typeof window !== "undefined") {
        localStorage.setItem("sidebarCollapsed", newValue.toString());
      }
      return newValue;
    });
  }, []);

  const setSidebarDescription = useCallback(async (description: string) => {
    setSidebarDescriptionState(description);
    // Save to backend
    try {
      await fetch(apiUrl("/api/v1/settings/sidebar/description"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description }),
      });
    } catch (e) {
      console.error("Failed to save sidebar description:", e);
    }
  }, []);

  const setSidebarNavOrder = useCallback(async (order: SidebarNavOrder) => {
    setSidebarNavOrderState(order);
    // Save to backend
    try {
      await fetch(apiUrl("/api/v1/settings/sidebar/nav-order"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nav_order: order }),
      });
    } catch (e) {
      console.error("Failed to save sidebar nav order:", e);
    }
  }, []);

  return (
    <SidebarContext.Provider
      value={{
        sidebarWidth,
        setSidebarWidth,
        sidebarCollapsed,
        setSidebarCollapsed,
        toggleSidebar,
        sidebarDescription,
        setSidebarDescription,
        sidebarNavOrder,
        setSidebarNavOrder,
      }}
    >
      {children}
    </SidebarContext.Provider>
  );
}

export const useSidebar = () => {
  const context = useContext(SidebarContext);
  if (!context)
    throw new Error("useSidebar must be used within SidebarProvider");
  return context;
};

// Re-export the SidebarNavOrder type for convenience
export type { SidebarNavOrder };
