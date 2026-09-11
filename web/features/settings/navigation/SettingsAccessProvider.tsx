"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";

import { fetchAuthStatus } from "@/lib/auth";
import {
  PENDING_SETTINGS_ACCESS,
  settingsAccessFromAuthStatus,
  type SettingsAccess,
} from "@/features/settings/navigation/settings-access";

const SettingsAccessContext = createContext<SettingsAccess>(
  PENDING_SETTINGS_ACCESS,
);

/** Resolve settings access once for the entire persistent settings document. */
export function SettingsAccessProvider({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const [access, setAccess] = useState<SettingsAccess>(PENDING_SETTINGS_ACCESS);

  useEffect(() => {
    let cancelled = false;
    void fetchAuthStatus().then((authStatus) => {
      if (!cancelled) setAccess(settingsAccessFromAuthStatus(authStatus));
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const value = useMemo(() => access, [access]);
  return (
    <SettingsAccessContext.Provider value={value}>
      {children}
    </SettingsAccessContext.Provider>
  );
}

export function useSettingsAccess(): SettingsAccess {
  return useContext(SettingsAccessContext);
}
