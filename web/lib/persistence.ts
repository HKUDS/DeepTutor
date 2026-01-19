/**
 * Persistence utility library for localStorage operations
 * Provides safe read/write operations with error handling, versioning, and selective persistence
 */

// Storage key prefix to avoid conflicts with other apps
const STORAGE_PREFIX = "deeptutor_";

// Current storage version for data migration support
const STORAGE_VERSION = 1;

// Version key suffix
const VERSION_SUFFIX = "_version";

/**
 * Storage wrapper interface for storing versioned data
 */
interface StorageWrapper<T> {
  version: number;
  data: T;
  timestamp: number;
}

/**
 * Safely load data from localStorage
 * @param key Storage key (will be prefixed automatically)
 * @param defaultValue Default value if key doesn't exist or data is invalid
 * @returns The stored value or default value
 */
export function loadFromStorage<T>(key: string, defaultValue: T): T {
  if (typeof window === "undefined") {
    return defaultValue;
  }

  try {
    const prefixedKey = STORAGE_PREFIX + key;
    const raw = localStorage.getItem(prefixedKey);

    if (!raw) {
      return defaultValue;
    }

    const wrapper: StorageWrapper<T> = JSON.parse(raw);

    // Version check - if version mismatch, return default (can add migration logic here)
    if (wrapper.version !== STORAGE_VERSION) {
      console.warn(
        `Storage version mismatch for ${key}. Expected ${STORAGE_VERSION}, got ${wrapper.version}. Using default value.`
      );
      return defaultValue;
    }

    return wrapper.data;
  } catch (error) {
    // Handle JSON parse errors or other issues
    console.warn(`Failed to load ${key} from localStorage:`, error);
    return defaultValue;
  }
}

/**
 * Safely save data to localStorage
 * @param key Storage key (will be prefixed automatically)
 * @param value Value to store
 */
export function saveToStorage<T>(key: string, value: T): void {
  if (typeof window === "undefined") {
    return;
  }

  try {
    const prefixedKey = STORAGE_PREFIX + key;
    const wrapper: StorageWrapper<T> = {
      version: STORAGE_VERSION,
      data: value,
      timestamp: Date.now(),
    };

    localStorage.setItem(prefixedKey, JSON.stringify(wrapper));
  } catch (error) {
    // Handle quota exceeded or other storage errors
    if (error instanceof Error && error.name === "QuotaExceededError") {
      console.error(
        `localStorage quota exceeded when saving ${key}. Consider clearing old data.`
      );
    } else {
      console.warn(`Failed to save ${key} to localStorage:`, error);
    }
  }
}

/**
 * Remove data from localStorage
 * @param key Storage key (will be prefixed automatically)
 */
export function removeFromStorage(key: string): void {
  if (typeof window === "undefined") {
    return;
  }

  try {
    const prefixedKey = STORAGE_PREFIX + key;
    localStorage.removeItem(prefixedKey);
  } catch (error) {
    console.warn(`Failed to remove ${key} from localStorage:`, error);
  }
}

/**
 * Clear all DeepTutor data from localStorage
 */
export function clearAllStorage(): void {
  if (typeof window === "undefined") {
    return;
  }

  try {
    const keysToRemove: string[] = [];

    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith(STORAGE_PREFIX)) {
        keysToRemove.push(key);
      }
    }

    keysToRemove.forEach((key) => localStorage.removeItem(key));
    console.info(`Cleared ${keysToRemove.length} DeepTutor storage items`);
  } catch (error) {
    console.warn("Failed to clear localStorage:", error);
  }
}

/**
 * Create a partial copy of state excluding specified fields
 * Useful for excluding runtime-only fields like isLoading, WebSocket refs, etc.
 * @param state The full state object
 * @param exclude Array of field names to exclude from persistence
 * @returns A new object without the excluded fields
 */
export function persistState<T extends Record<string, any>>(
  state: T,
  exclude: (keyof T)[]
): Partial<T> {
  const result: Partial<T> = {};

  for (const key of Object.keys(state) as (keyof T)[]) {
    if (!exclude.includes(key)) {
      result[key] = state[key];
    }
  }

  return result;
}

/**
 * Merge persisted state with default state
 * Ensures all required fields exist even if persisted data is incomplete
 * @param persistedState Partial state loaded from storage
 * @param defaultState Complete default state
 * @param exclude Fields that should always use default values (runtime-only fields)
 * @returns Merged state with all fields populated
 */
export function mergeWithDefaults<T extends Record<string, any>>(
  persistedState: Partial<T> | null | undefined,
  defaultState: T,
  exclude: (keyof T)[] = []
): T {
  if (!persistedState) {
    return defaultState;
  }

  const result = { ...defaultState };

  for (const key of Object.keys(persistedState) as (keyof T)[]) {
    // Skip excluded fields - always use defaults
    if (exclude.includes(key)) {
      continue;
    }

    // Only copy if value is not undefined
    if (persistedState[key] !== undefined) {
      result[key] = persistedState[key] as T[keyof T];
    }
  }

  return result;
}

/**
 * Get storage usage statistics
 * @returns Object with total size and per-key sizes
 */
export function getStorageStats(): {
  totalSize: number;
  items: { key: string; size: number }[];
} {
  if (typeof window === "undefined") {
    return { totalSize: 0, items: [] };
  }

  const items: { key: string; size: number }[] = [];
  let totalSize = 0;

  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith(STORAGE_PREFIX)) {
        const value = localStorage.getItem(key) || "";
        const size = new Blob([key + value]).size;
        items.push({ key: key.replace(STORAGE_PREFIX, ""), size });
        totalSize += size;
      }
    }
  } catch (error) {
    console.warn("Failed to get storage stats:", error);
  }

  return { totalSize, items };
}

/**
 * Storage keys for each module
 */
export const STORAGE_KEYS = {
  CHAT_STATE: "chat_state",
  SOLVER_STATE: "solver_state",
  QUESTION_STATE: "question_state",
  RESEARCH_STATE: "research_state",
  IDEAGEN_STATE: "ideagen_state",
  GUIDE_SESSION: "guide_session",
  COWRITER_CONTENT: "cowriter_content",
} as const;

/**
 * Fields to exclude from persistence for each module
 * These are runtime-only fields that shouldn't be saved
 */
export const EXCLUDE_FIELDS = {
  CHAT: ["isLoading", "currentStage"] as const,
  SOLVER: [
    "isSolving",
    "logs",
    "agentStatus",
    "tokenStats",
    "progress",
  ] as const,
  QUESTION: [
    "logs",
    "progress",
    "agentStatus",
    "tokenStats",
    "uploadedFile",
  ] as const,
  RESEARCH: ["status", "logs", "progress"] as const,
  IDEAGEN: ["isGenerating", "progress"] as const,
  GUIDE: ["isLoading", "loadingMessage"] as const,
} as const;
