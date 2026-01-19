import { useState, useEffect, useCallback, useRef } from "react";
import {
  loadFromStorage,
  saveToStorage,
  persistState,
  mergeWithDefaults,
} from "@/lib/persistence";
import { debounce } from "@/lib/debounce";

/**
 * Options for usePersistentState hook
 */
interface PersistentStateOptions<T> {
  /** Fields to exclude from persistence (runtime-only fields) */
  exclude?: (keyof T)[];
  /** Debounce delay in milliseconds for save operations (default: 500ms) */
  debounceMs?: number;
  /** Whether persistence is enabled (default: true) */
  enabled?: boolean;
}

/**
 * Custom hook that provides useState-like functionality with automatic localStorage persistence
 *
 * @param key Storage key for this state
 * @param initialValue Default/initial value
 * @param options Configuration options
 * @returns Tuple of [state, setState] similar to useState
 *
 * @example
 * ```tsx
 * const [state, setState] = usePersistentState(
 *   'my_state',
 *   { count: 0, isLoading: false },
 *   { exclude: ['isLoading'], debounceMs: 300 }
 * );
 * ```
 */
export function usePersistentState<T extends Record<string, any>>(
  key: string,
  initialValue: T,
  options: PersistentStateOptions<T> = {}
): [T, React.Dispatch<React.SetStateAction<T>>] {
  const { exclude = [], debounceMs = 500, enabled = true } = options;

  // Use ref to track if we've done initial load
  const isInitialized = useRef(false);

  // Initialize state with persisted value or default
  const [state, setStateInternal] = useState<T>(() => {
    if (typeof window === "undefined" || !enabled) {
      return initialValue;
    }

    // Load persisted state and merge with defaults
    const persisted = loadFromStorage<Partial<T>>(key, {});
    return mergeWithDefaults(persisted, initialValue, exclude as (keyof T)[]);
  });

  // Create debounced save function
  const debouncedSave = useCallback(
    debounce((value: T) => {
      if (!enabled) return;

      // Filter out excluded fields before saving
      const toSave = persistState(value, exclude as (keyof T)[]);
      saveToStorage(key, toSave);
    }, debounceMs),
    [key, exclude, debounceMs, enabled]
  );

  // Save state whenever it changes (after initial load)
  useEffect(() => {
    // Skip the first render (initial load from storage)
    if (!isInitialized.current) {
      isInitialized.current = true;
      return;
    }

    debouncedSave(state);
  }, [state, debouncedSave]);

  // Custom setState that wraps the internal setter
  const setState: React.Dispatch<React.SetStateAction<T>> = useCallback(
    (action) => {
      setStateInternal(action);
    },
    []
  );

  return [state, setState];
}

/**
 * Hook for simple value persistence (not objects)
 * Useful for primitive values like strings, numbers, booleans
 *
 * @param key Storage key
 * @param initialValue Default value
 * @param debounceMs Debounce delay (default: 300ms)
 */
export function usePersistentValue<T>(
  key: string,
  initialValue: T,
  debounceMs: number = 300
): [T, React.Dispatch<React.SetStateAction<T>>] {
  const isInitialized = useRef(false);

  const [value, setValueInternal] = useState<T>(() => {
    if (typeof window === "undefined") {
      return initialValue;
    }
    return loadFromStorage<T>(key, initialValue);
  });

  const debouncedSave = useCallback(
    debounce((val: T) => {
      saveToStorage(key, val);
    }, debounceMs),
    [key, debounceMs]
  );

  useEffect(() => {
    if (!isInitialized.current) {
      isInitialized.current = true;
      return;
    }
    debouncedSave(value);
  }, [value, debouncedSave]);

  return [value, setValueInternal];
}

/**
 * Hook to restore and auto-save state for GlobalContext modules
 * This is a more specific version for use in GlobalContext
 *
 * @param key Storage key
 * @param defaultState Default state object
 * @param excludeFields Fields to exclude from persistence
 * @param setState The setState function from GlobalContext
 */
export function useStatePersistence<T extends Record<string, any>>(
  key: string,
  state: T,
  defaultState: T,
  excludeFields: readonly (keyof T)[],
  debounceMs: number = 500
): {
  loadPersistedState: () => T;
  saveState: (state: T) => void;
} {
  // Create debounced save function
  const saveState = useCallback(
    debounce((currentState: T) => {
      const toSave = persistState(currentState, excludeFields as (keyof T)[]);
      saveToStorage(key, toSave);
    }, debounceMs),
    [key, excludeFields, debounceMs]
  );

  // Load persisted state
  const loadPersistedState = useCallback((): T => {
    if (typeof window === "undefined") {
      return defaultState;
    }
    const persisted = loadFromStorage<Partial<T>>(key, {});
    return mergeWithDefaults(
      persisted,
      defaultState,
      excludeFields as (keyof T)[]
    );
  }, [key, defaultState, excludeFields]);

  return { loadPersistedState, saveState };
}

export default usePersistentState;
