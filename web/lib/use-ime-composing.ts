/**
 * Shared IME composition guard for chat textareas. While the user is
 * composing (e.g. picking CJK candidates), Enter confirms a candidate
 * rather than submitting — keydown handlers read ``isComposingRef.current``
 * (typically via ``shouldSubmitOnEnter``) to tell the two apart. Sharing
 * one hook keeps the deferred reset below from being "simplified" away
 * at individual call sites, which would break CJK input.
 */

import { useCallback, useRef } from "react";

export function useImeComposing() {
  const isComposingRef = useRef(false);

  const onCompositionStart = useCallback(() => {
    isComposingRef.current = true;
  }, []);

  const onCompositionEnd = useCallback(() => {
    // Some IMEs fire compositionend before the Enter keydown that confirms
    // a candidate, so keep the guard through the current event turn.
    setTimeout(() => {
      isComposingRef.current = false;
    }, 0);
  }, []);

  return { isComposingRef, onCompositionStart, onCompositionEnd };
}
