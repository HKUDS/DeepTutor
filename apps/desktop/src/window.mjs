/**
 * Bring the already running window forward when the app is launched again.
 *
 * Electron's single-instance lock keeps the second launch from opening a second
 * window, so this handler is the only feedback the user gets. `show()` on a
 * minimized window leaves it minimized, which reads as "the icon does nothing",
 * so it has to be restored first (#2721).
 */
export function focusWindow(win) {
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

/** Becoming visible again is what re-paints content added while hidden. */
export const REPAINT_EVENTS = ['restore', 'show', 'focus', 'maximize'];

/**
 * Lay the content view out whenever the window comes back on screen.
 *
 * A `WebContentsView` added while the window was minimized or occluded is never
 * painted, and restoring the window does not repaint it; only a resize did,
 * which is why maximizing appeared to fix the blank page in #2721.
 */
export function repaintOnShow(win, layout, invalidate) {
  if (!win) return;
  for (const event of REPAINT_EVENTS) {
    win.on(event, () => {
      layout();
      // Unchanged bounds give the compositor nothing to redo, so an occluded
      // window needs an outright repaint. `focus` is the event that fires when
      // a covered window comes forward; `invalidate` is absent on some Electron
      // versions, hence the guard.
      if (event === 'focus' && typeof invalidate === 'function') invalidate();
    });
  }
}
