/**
 * useTheme hook for managing theme throughout the application
 */
import { useState, useSyncExternalStore } from "react";
import {
  setTheme,
  getStoredTheme,
  initializeTheme,
  type Theme,
} from "@/lib/theme";

// Use useSyncExternalStore for safe client-side initialization
const emptySubscribe = () => () => {};
function useIsClient() {
  return useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false
  );
}

export function useTheme() {
  const isClient = useIsClient();
  const [theme, setThemeState] = useState<Theme>(() => {
    // Lazy initialization - safe for SSR
    if (typeof window !== "undefined") {
      return initializeTheme();
    }
    return "light";
  });
  const isLoaded = isClient;

  const updateTheme = (newTheme: Theme) => {
    setTheme(newTheme);
    setThemeState(newTheme);
  };

  return {
    theme: theme || "light",
    isLoaded,
    setTheme: updateTheme,
    isDark: theme === "dark",
    isLight: theme === "light",
  };
}
