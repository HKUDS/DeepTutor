"use client";

import { useEffect, useState } from "react";
import { browserStorage } from "@/shared/storage";

const STORAGE_NAME = "deeptutor.userMessageMath";
const CHANGE_EVENT = "deeptutor:user-message-math";

/** Whether the learner opted into math rendering in their own chat bubbles. */
export function readUserMessageMath(): boolean {
  return browserStorage.readRaw("local", STORAGE_NAME) === "1";
}

export function setUserMessageMath(enabled: boolean): void {
  browserStorage.writeRaw("local", STORAGE_NAME, enabled ? "1" : "0");
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }
}

/** Read the preference, defaulting to off on the server and before hydration. */
export function useUserMessageMath(): boolean {
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    const sync = () => setEnabled(readUserMessageMath());
    sync();
    window.addEventListener(CHANGE_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(CHANGE_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  return enabled;
}
