import { useCallback, useRef } from 'react';
import { useFocusEffect } from 'expo-router';

/**
 * Re-read a list when its screen comes back into view.
 *
 * A screen stays mounted while another is pushed on top of it, so a catalogue
 * loaded on mount would keep showing a base that was deleted from its detail
 * page — or miss one created in Settings — until the app restarted. The first
 * focus is skipped because the caller's own mount effect has already loaded.
 */
export function useRefreshOnFocus(refresh: () => Promise<unknown>) {
  const first = useRef(true);
  useFocusEffect(
    useCallback(() => {
      if (first.current) {
        first.current = false;
        return;
      }
      refresh().catch(() => {});
    }, [refresh]),
  );
}
