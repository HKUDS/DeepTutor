export type KidsPageTurnDirection = "previous" | "next";

export const KIDS_PAGE_TURN_MIN_DRAG_PX = 48;
export const KIDS_PAGE_TURN_HORIZONTAL_RATIO = 1.25;

interface KidsPageTurnGesture {
  pointerId: number;
  startX: number;
  startY: number;
}

const INTERACTIVE_PAGE_TURN_SELECTOR = [
  "a",
  "button",
  "input",
  "textarea",
  "select",
  "video",
  "iframe",
  "svg",
  "pre",
  "[contenteditable='true']",
  "[data-kids-no-page-swipe]",
].join(",");

export function shouldAllowKidsPageTurnGesture(target: EventTarget | null): boolean {
  const element = target as Element | null;
  if (!element || typeof element.closest !== "function") return false;
  return !element.closest(INTERACTIVE_PAGE_TURN_SELECTOR);
}

const KEYBOARD_PAGE_TURN_SELECTOR = [
  "input",
  "textarea",
  "select",
  "[contenteditable='true']",
  "[data-kids-no-page-swipe]",
].join(",");

export function shouldAllowKidsPageTurnKeyboard(target: EventTarget | null): boolean {
  const element = target as Element | null;
  if (!element || typeof element.closest !== "function") return false;
  return !element.closest(KEYBOARD_PAGE_TURN_SELECTOR);
}

export function resolveKidsPageTurnSwipe(
  startX: number,
  startY: number,
  endX: number,
  endY: number,
): KidsPageTurnDirection | null {
  const dx = endX - startX;
  const dy = endY - startY;
  if (Math.abs(dx) < KIDS_PAGE_TURN_MIN_DRAG_PX) return null;
  if (Math.abs(dx) <= Math.abs(dy) * KIDS_PAGE_TURN_HORIZONTAL_RATIO) return null;
  return dx < 0 ? "next" : "previous";
}

export function getKidsPageTurnDirectionForLayout(
  direction: KidsPageTurnDirection,
  isRTL: boolean,
): KidsPageTurnDirection {
  if (!isRTL) return direction;
  return direction === "next" ? "previous" : "next";
}

export function createKidsPageTurnGestureTracker() {
  let gesture: KidsPageTurnGesture | null = null;
  let swipeHandled = false;

  return {
    begin(pointerId: number, startX: number, startY: number) {
      gesture = { pointerId, startX, startY };
      swipeHandled = false;
    },
    end(
      pointerId: number,
      endX: number,
      endY: number,
    ): KidsPageTurnDirection | null {
      if (!gesture || gesture.pointerId !== pointerId) return null;
      const direction = resolveKidsPageTurnSwipe(
        gesture.startX,
        gesture.startY,
        endX,
        endY,
      );
      swipeHandled = direction !== null;
      gesture = null;
      return direction;
    },
    cancel() {
      gesture = null;
    },
    consumeClick(): boolean {
      const handled = swipeHandled;
      swipeHandled = false;
      return handled;
    },
  };
}
