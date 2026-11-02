/**
 * Where calendar items sit: side-by-side columns for overlapping timed
 * events in a day, and stacked lanes for spans across a week row.
 */

export interface TimedBox {
  id: string
  /** Minutes since the day's midnight, already clipped to [0, 1440]. */
  start: number
  end: number
}

export interface PlacedBox extends TimedBox {
  /** Fractions of the column width. */
  left: number
  width: number
  column: number
  columns: number
}

/**
 * Google-style packing. Events that overlap, directly or through a chain,
 * form a cluster sharing one column count; each takes the first free
 * column, then widens rightwards over columns it does not collide with.
 * A box shorter than `minLength` collides as if it had that length, so
 * a five-minute event never hides under its neighbour's text.
 */
export function layoutDay(boxes: TimedBox[], minLength = 20): PlacedBox[] {
  const sorted = [...boxes].sort(
    (a, b) => a.start - b.start || b.end - a.end || a.id.localeCompare(b.id)
  )
  const visualEnd = (box: TimedBox) => Math.max(box.end, box.start + minLength)
  const placed: PlacedBox[] = []
  let cluster: { box: TimedBox; column: number }[] = []
  let columnEnds: number[] = []
  let clusterEnd = -Infinity

  const flush = () => {
    const columns = columnEnds.length
    for (const { box, column } of cluster) {
      let span = 1
      while (
        column + span < columns &&
        !cluster.some(
          other =>
            other.column === column + span &&
            other.box.start < visualEnd(box) &&
            box.start < visualEnd(other.box)
        )
      )
        span++
      placed.push({ ...box, column, columns, left: column / columns, width: span / columns })
    }
    cluster = []
    columnEnds = []
  }

  for (const box of sorted) {
    if (box.start >= clusterEnd) {
      flush()
      clusterEnd = -Infinity
    }
    let column = columnEnds.findIndex(end => end <= box.start)
    if (column === -1) {
      column = columnEnds.length
      columnEnds.push(visualEnd(box))
    } else columnEnds[column] = visualEnd(box)
    cluster.push({ box, column })
    clusterEnd = Math.max(clusterEnd, visualEnd(box))
  }
  flush()
  return placed
}

export interface SpanItem {
  id: string
  /** Inclusive day indexes inside the row. */
  first: number
  last: number
  /** Ties order shorter-first-after-longer, then by this. */
  order?: number
}

export interface PlacedSpan extends SpanItem {
  lane: number
}

/** Lowest free lane for each span; earlier and longer spans go first. */
export function packLanes(items: SpanItem[]): PlacedSpan[] {
  const sorted = [...items].sort(
    (a, b) =>
      a.first - b.first ||
      b.last - b.first - (a.last - a.first) ||
      (a.order ?? 0) - (b.order ?? 0) ||
      a.id.localeCompare(b.id)
  )
  const lanes: number[] = []
  return sorted.map(item => {
    let lane = lanes.findIndex(lastDay => lastDay < item.first)
    if (lane === -1) {
      lane = lanes.length
      lanes.push(item.last)
    } else lanes[lane] = item.last
    return { ...item, lane }
  })
}
