export function minWindowSize({ width, height }) {
  return {
    minWidth: Math.min(820, width),
    minHeight: Math.min(560, height),
  };
}

export function restoreWindowBounds(saved, displays) {
  let bestWorkArea = null;
  let bestOverlap = 0;
  for (const { workArea } of displays) {
    const right = workArea.x + workArea.width;
    const bottom = workArea.y + workArea.height;
    const overlapX = Math.min(saved.x + saved.width, right) - Math.max(saved.x, workArea.x);
    const titleVisible = saved.y >= workArea.y - 8 && saved.y <= bottom - 60;
    if (overlapX < 120 || !titleVisible) continue;
    const overlapY = Math.min(saved.y + saved.height, bottom) - Math.max(saved.y, workArea.y);
    const overlap = overlapX * overlapY;
    if (overlap > bestOverlap) {
      bestWorkArea = workArea;
      bestOverlap = overlap;
    }
  }
  if (!bestWorkArea) return null;

  const { minWidth, minHeight } = minWindowSize(bestWorkArea);
  const width = Math.min(bestWorkArea.width, Math.max(minWidth, Math.round(saved.width)));
  const height = Math.min(bestWorkArea.height, Math.max(minHeight, Math.round(saved.height)));
  const x = Math.min(Math.max(Math.round(saved.x), bestWorkArea.x), bestWorkArea.x + bestWorkArea.width - width);
  const y = Math.min(Math.max(Math.round(saved.y), bestWorkArea.y), bestWorkArea.y + bestWorkArea.height - height);
  return { x, y, width, height };
}
