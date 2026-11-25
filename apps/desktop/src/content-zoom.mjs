const stops = [0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75];

function nearest(value) {
  return stops.reduce((best, stop, index) =>
    Math.abs(stop - value) < Math.abs(stops[best] - value) ? index : best, 0);
}

/** Own zoom on the application page only; the private shell has a separate view. */
export function createContentZoom(saved, persist) {
  let factor = Number.isFinite(saved) ? stops[nearest(saved)] : 1;
  let current;
  let loaded = false;
  const ready = () => loaded && current && !current.isDestroyed();
  function apply(next) {
    if (!ready()) return;
    current.setZoomFactor(next);
    factor = next;
    persist(next);
  }
  function step(direction) {
    if (!ready()) return;
    apply(stops[Math.max(0, Math.min(stops.length - 1, nearest(current.getZoomFactor()) + direction))]);
  }
  return {
    get factor() { return factor; }, step, reset: () => apply(1),
    attach(contents) {
      current = contents;
      loaded = false;
      contents.setZoomMode('manual');
      contents.on('did-finish-load', () => {
        if (contents !== current || contents.isDestroyed()) return;
        loaded = true;
        contents.setZoomFactor(factor);
      });
      contents.on('zoom-changed', (_event, direction) => {
        if (contents === current) step(direction === 'in' ? 1 : -1);
      });
      contents.on('before-input-event', (event, input) => {
        if (contents !== current || !ready() || input.type !== 'keyDown' || !(input.control || input.meta) || input.alt) return;
        if (input.code === 'NumpadAdd' || (input.key === '+' && input.shift)) {
          event.preventDefault(); step(1);
        } else if (input.code === 'NumpadSubtract') {
          event.preventDefault(); step(-1);
        } else if (input.code === 'Numpad0') {
          event.preventDefault(); apply(1);
        }
      });
    },
  };
}
