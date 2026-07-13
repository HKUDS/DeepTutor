// Memory graph data layer: fetch L1/L2/L3 from the workbench APIs,
// parse markdown citations, build nodes + edges, compute a concentric
// layout. Pure TypeScript so the React component stays thin.

import { apiFetch, apiUrl } from "@/lib/api";

export type Surface =
  | "chat"
  | "notebook"
  | "quiz"
  | "kb"
  | "book"
  | "partner"
  | "cowriter";

export const SURFACES: Surface[] = [
  "chat",
  "notebook",
  "quiz",
  "kb",
  "book",
  "partner",
  "cowriter",
];

export type L3Slot = "profile" | "recent" | "scope";
export const L3_SLOTS: L3Slot[] = ["profile", "recent", "scope"];

export type Layer = "L1" | "L2" | "L3";

export interface L1Entity {
  id: string;
  label: string;
  ts: string;
  content: string;
}

export interface ParsedEntry {
  // entry ULID like ``m_01KS...``
  id: string;
  section: string;
  text: string;
  // raw ref strings as they appear in the footnote table
  refs: string[];
}

export interface ParsedDoc {
  title: string;
  entries: ParsedEntry[];
}

// ── Node + edge schema ────────────────────────────────────────────────

export interface GraphNode {
  id: string; // unique key across all layers
  layer: Layer;
  // L1: surface; L2: surface; L3: slot
  cluster: string;
  // For L2/L3 entries: section heading within the doc
  section?: string;
  label: string; // tooltip header
  preview: string; // hover body
  // Click navigation target
  href: string;
  // Layout (filled in by layoutGraph)
  x: number;
  y: number;
  r: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  // ``strong`` when the target is a specific entry; ``soft`` when only
  // the surface was cited (L3 → L2 cluster).
  kind: "strong" | "soft";
}

export interface MemoryGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  clusters: ClusterMeta[];
  // Adjacency lookup keyed by node id
  adjacency: Map<string, string[]>;
  // Maps node id → its cluster id
  nodeCluster: Map<string, string>;
}

export interface ClusterMeta {
  id: string;
  layer: Layer;
  key: string; // surface or slot name
  label: string;
  // Center of the cluster's bounding pie slice (used for soft edges
  // and the cluster halo).
  cx: number;
  cy: number;
  // Pie slice geometry
  startAngle: number;
  endAngle: number;
  innerRadius: number;
  outerRadius: number;
  count: number;
}

// ── Parsing ───────────────────────────────────────────────────────────

// Bullet shapes accepted by the consolidator (see services/memory/document.py):
//   - "- text [^1], [^3] <!--m_xxx-->"   (new layout)
//   - "- text [^m_xxx]"                  (legacy)
const ENTRY_ID = "m_[0-9A-HJKMNP-TV-Z]{26}";
const NEW_BULLET_RE = new RegExp(
  String.raw`^\s*-\s+(.*?)((?:\s*,?\s*\[\^[^\]]+\])*)\s*<!--\s*(` +
    ENTRY_ID +
    String.raw`)\s*-->\s*$`,
);
const OLD_BULLET_RE = new RegExp(
  String.raw`^\s*-\s+(.*?)\[\^(` + ENTRY_ID + String.raw`)\]\s*$`,
);
const NEW_FOOTNOTE_RE = /^\[\^([^\]]+)\]:\s*(.*?)\s*$/;
const OLD_FOOTNOTE_RE = new RegExp(
  String.raw`^\[\^(` + ENTRY_ID + String.raw`)\]:\s*(.*?)\s*$`,
);
const MARKER_RE = /\[\^([^\]]+)\]/g;

export function parseDoc(content: string): ParsedDoc {
  const lines = content.split(/\r?\n/);
  let title = "";
  let section = "";
  const entries: ParsedEntry[] = [];
  // Map label → ref(s). Legacy footnotes can carry a comma-separated
  // list, new ones carry a single ref.
  const footnotes = new Map<string, string[]>();

  for (const raw of lines) {
    const line = raw.trimEnd();
    if (!line) continue;
    if (line.startsWith("# ") && !title) {
      title = line.slice(2).trim();
      continue;
    }
    if (line.startsWith("## ")) {
      section = line.slice(3).trim();
      continue;
    }
    if (line === "---") continue;

    const mNew = NEW_BULLET_RE.exec(line);
    if (mNew) {
      const [, text, markersBlock, id] = mNew;
      const markerIds = Array.from(
        markersBlock.matchAll(MARKER_RE),
        (m) => m[1],
      );
      entries.push({
        id,
        section,
        text: text.trim(),
        // Defer ref resolution until we've finished collecting footnotes.
        refs: markerIds,
      });
      continue;
    }

    const mOld = OLD_BULLET_RE.exec(line);
    if (mOld) {
      const [, text, id] = mOld;
      entries.push({ id, section, text: text.trim(), refs: [id] });
      continue;
    }

    const mOldFn = OLD_FOOTNOTE_RE.exec(line);
    if (mOldFn) {
      const [, id, payload] = mOldFn;
      footnotes.set(
        id,
        payload
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      );
      continue;
    }

    const mNewFn = NEW_FOOTNOTE_RE.exec(line);
    if (mNewFn) {
      const [, label, ref] = mNewFn;
      const cur = footnotes.get(label) ?? [];
      cur.push(ref.trim());
      footnotes.set(label, cur);
      continue;
    }
  }

  // Resolve marker labels → actual ref strings.
  for (const entry of entries) {
    const resolved: string[] = [];
    for (const marker of entry.refs) {
      const refs = footnotes.get(marker);
      if (refs && refs.length) {
        for (const r of refs) if (r && !resolved.includes(r)) resolved.push(r);
      } else if (marker.startsWith("m_")) {
        // Legacy bullet where the marker *is* the entry id; refs come
        // from a separate footnote we may already have stored.
      } else {
        // Unknown label — keep it so the graph at least shows a stub.
        resolved.push(marker);
      }
    }
    entry.refs = resolved;
  }

  return { title, entries };
}

// Split a footnote ref like "chat:unified_xxx" into surface + id.
// The id is allowed to contain colons (e.g. ``quiz:unified_xxx:q_1`` →
// surface=quiz, id=unified_xxx:q_1).
export function splitRef(ref: string): { surface: string; entityId: string } {
  const idx = ref.indexOf(":");
  if (idx < 0) return { surface: ref, entityId: "" };
  return { surface: ref.slice(0, idx), entityId: ref.slice(idx + 1) };
}

// ── Fetching ──────────────────────────────────────────────────────────

interface SnapshotResponse {
  entities: L1Entity[];
}

interface DocResponse {
  content: string;
}

export interface RawMemorySnapshot {
  l1: Record<Surface, L1Entity[]>;
  l2: Record<Surface, ParsedDoc>;
  l3: Record<L3Slot, ParsedDoc>;
}

export async function fetchMemorySnapshot(): Promise<RawMemorySnapshot> {
  const l1Promises = SURFACES.map(async (s): Promise<[Surface, L1Entity[]]> => {
    try {
      const res = await apiFetch(apiUrl(`/api/v1/memory/snapshot/${s}`));
      const data = (await res.json()) as SnapshotResponse;
      return [s, data?.entities ?? []];
    } catch {
      return [s, []];
    }
  });

  const l2Promises = SURFACES.map(async (s): Promise<[Surface, ParsedDoc]> => {
    try {
      const res = await apiFetch(apiUrl(`/api/v1/memory/doc/L2/${s}`));
      const data = (await res.json()) as DocResponse;
      return [s, parseDoc(data?.content ?? "")];
    } catch {
      return [s, { title: "", entries: [] }];
    }
  });

  const l3Promises = L3_SLOTS.map(
    async (slot): Promise<[L3Slot, ParsedDoc]> => {
      try {
        const res = await apiFetch(apiUrl(`/api/v1/memory/doc/L3/${slot}`));
        const data = (await res.json()) as DocResponse;
        return [slot, parseDoc(data?.content ?? "")];
      } catch {
        return [slot, { title: "", entries: [] }];
      }
    },
  );

  const [l1Entries, l2Entries, l3Entries] = await Promise.all([
    Promise.all(l1Promises),
    Promise.all(l2Promises),
    Promise.all(l3Promises),
  ]);

  const l1 = Object.fromEntries(l1Entries) as Record<Surface, L1Entity[]>;
  const l2 = Object.fromEntries(l2Entries) as Record<Surface, ParsedDoc>;
  const l3 = Object.fromEntries(l3Entries) as Record<L3Slot, ParsedDoc>;
  return { l1, l2, l3 };
}

// ── Layout (concentric clusters) ─────────────────────────────────────

export interface LayoutOptions {
  // Display size (the layout is centered at width/2, height/2).
  width: number;
  height: number;
  // Inner ring (L3) radius range.
  l3InnerRadius: number;
  l3OuterRadius: number;
  // Middle ring (L2) radius range.
  l2InnerRadius: number;
  l2OuterRadius: number;
  // Outer ring (L1) radius range.
  l1InnerRadius: number;
  l1OuterRadius: number;
  // Padding between adjacent cluster slices, in radians. ``clusterGap``
  // applies to L1/L2 (7-way split, narrow gaps look right); the L3 ring
  // only has three clusters, so it gets its own (larger) gap.
  clusterGap: number;
  l3ClusterGap: number;
}

export const DEFAULT_LAYOUT: LayoutOptions = {
  width: 1200,
  height: 1200,
  l3InnerRadius: 70,
  l3OuterRadius: 190,
  l2InnerRadius: 240,
  l2OuterRadius: 360,
  l1InnerRadius: 400,
  l1OuterRadius: 570,
  clusterGap: 0.05,
  l3ClusterGap: 0.22,
};

// Build nodes + edges + cluster metadata + layout coordinates.
export function buildGraph(
  snap: RawMemorySnapshot,
  opts: LayoutOptions = DEFAULT_LAYOUT,
): MemoryGraph {
  const { width, height } = opts;
  const cx = width / 2;
  const cy = height / 2;

  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];
  const clusters: ClusterMeta[] = [];
  const adjacency = new Map<string, string[]>();
  const nodeCluster = new Map<string, string>();

  // Pre-dedupe per surface / slot so React keys stay unique AND the
  // cluster counts driving angular allocation match what we actually
  // render. Quiz L1 is the offender today — one row per question
  // variant, with the same composite ``unified_xxx:q_N`` id appearing
  // twice or more in the same snapshot.
  const dedupedL1: Record<Surface, L1Entity[]> = {} as Record<
    Surface,
    L1Entity[]
  >;
  for (const s of SURFACES) {
    const seen = new Set<string>();
    dedupedL1[s] = snap.l1[s].filter((e) => {
      if (seen.has(e.id)) return false;
      seen.add(e.id);
      return true;
    });
  }
  const dedupedL2: Record<Surface, ParsedEntry[]> = {} as Record<
    Surface,
    ParsedEntry[]
  >;
  for (const s of SURFACES) {
    const seen = new Set<string>();
    dedupedL2[s] = snap.l2[s].entries.filter((e) => {
      if (seen.has(e.id)) return false;
      seen.add(e.id);
      return true;
    });
  }
  const dedupedL3: Record<L3Slot, ParsedEntry[]> = {} as Record<
    L3Slot,
    ParsedEntry[]
  >;
  for (const slot of L3_SLOTS) {
    const seen = new Set<string>();
    dedupedL3[slot] = snap.l3[slot].entries.filter((e) => {
      if (seen.has(e.id)) return false;
      seen.add(e.id);
      return true;
    });
  }

  // ── Build L3 cluster geometry: slot arcs proportional to count.
  // Place ``profile`` first so the most-meaningful summary sits at
  // 12 o'clock when the canvas first renders.
  const l3Counts = L3_SLOTS.map((s) => dedupedL3[s].length);
  const l3Total = l3Counts.reduce((a, b) => a + b, 0) || 1;
  const l3MinFrac = 0.12; // 43° floor — keeps even empty slots labelable
  const l3MinPool = l3MinFrac * L3_SLOTS.length;
  const l3ElasticPool = Math.max(0, 1 - l3MinPool);
  const l3Frac = l3Counts.map((c) => l3MinFrac + (c / l3Total) * l3ElasticPool);
  const l3FracSum = l3Frac.reduce((a, b) => a + b, 0);
  for (let i = 0; i < l3Frac.length; i++) l3Frac[i] /= l3FracSum;

  const l3ClusterMap = new Map<string, ClusterMeta>();
  let l3Cursor = -Math.PI / 2;
  L3_SLOTS.forEach((slot, idx) => {
    const span = l3Frac[idx] * 2 * Math.PI;
    const start = l3Cursor + opts.l3ClusterGap / 2;
    const end = l3Cursor + span - opts.l3ClusterGap / 2;
    l3Cursor += span;
    const mid = (start + end) / 2;
    const r = (opts.l3InnerRadius + opts.l3OuterRadius) / 2;
    const cluster: ClusterMeta = {
      id: `L3:${slot}`,
      layer: "L3",
      key: slot,
      label: L3_LABEL[slot],
      cx: cx + Math.cos(mid) * r,
      cy: cy + Math.sin(mid) * r,
      startAngle: start,
      endAngle: end,
      innerRadius: opts.l3InnerRadius,
      outerRadius: opts.l3OuterRadius,
      count: dedupedL3[slot].length,
    };
    clusters.push(cluster);
    l3ClusterMap.set(slot, cluster);
  });

  // ── Build L2 + L1 cluster geometry: angular share per surface is
  // proportional to the *combined* L1+L2 count so dense surfaces own
  // a bigger arc and the whole outer ring stays uniformly dense.
  // Each surface gets a minimum slice so tiny ones (book, partner)
  // still register visually.
  const minSliceFraction = 0.025; // ≈ 9° floor
  const rawWeights = SURFACES.map(
    (s) => dedupedL1[s].length + dedupedL2[s].length,
  );
  const totalRaw = rawWeights.reduce((a, b) => a + b, 0) || 1;
  const minPool = minSliceFraction * SURFACES.length;
  const elasticPool = Math.max(0, 1 - minPool);
  const surfaceFraction = rawWeights.map(
    (w) => minSliceFraction + (w / totalRaw) * elasticPool,
  );
  // Renormalise (rounding can drift it off 1.0).
  const sumFrac = surfaceFraction.reduce((a, b) => a + b, 0);
  for (let i = 0; i < surfaceFraction.length; i++)
    surfaceFraction[i] /= sumFrac;

  const l2ClusterMap = new Map<string, ClusterMeta>();
  const l1ClusterMap = new Map<string, ClusterMeta>();
  let cursor = -Math.PI / 2;
  SURFACES.forEach((surf, idx) => {
    const span = surfaceFraction[idx] * 2 * Math.PI;
    const start = cursor + opts.clusterGap / 2;
    const end = cursor + span - opts.clusterGap / 2;
    cursor += span;
    const mid = (start + end) / 2;
    const r2 = (opts.l2InnerRadius + opts.l2OuterRadius) / 2;
    const r1 = (opts.l1InnerRadius + opts.l1OuterRadius) / 2;
    const c2: ClusterMeta = {
      id: `L2:${surf}`,
      layer: "L2",
      key: surf,
      label: SURFACE_LABEL[surf],
      cx: cx + Math.cos(mid) * r2,
      cy: cy + Math.sin(mid) * r2,
      startAngle: start,
      endAngle: end,
      innerRadius: opts.l2InnerRadius,
      outerRadius: opts.l2OuterRadius,
      count: dedupedL2[surf].length,
    };
    const c1: ClusterMeta = {
      id: `L1:${surf}`,
      layer: "L1",
      key: surf,
      label: SURFACE_LABEL[surf],
      cx: cx + Math.cos(mid) * r1,
      cy: cy + Math.sin(mid) * r1,
      startAngle: start,
      endAngle: end,
      innerRadius: opts.l1InnerRadius,
      outerRadius: opts.l1OuterRadius,
      count: dedupedL1[surf].length,
    };
    clusters.push(c2);
    clusters.push(c1);
    l2ClusterMap.set(surf, c2);
    l1ClusterMap.set(surf, c1);
  });

  const center = { x: cx, y: cy };

  // ── Place L3 nodes inside their slice.
  L3_SLOTS.forEach((slot) => {
    const cluster = l3ClusterMap.get(slot)!;
    const entries = dedupedL3[slot];
    placeNodesInSlice(entries.length, cluster, center, (i) => {
      const entry = entries[i];
      const id = `L3:${slot}:${entry.id}`;
      nodeCluster.set(id, cluster.id);
      return {
        id,
        layer: "L3",
        cluster: cluster.id,
        section: entry.section,
        label: `${cluster.label} · ${entry.section || ""}`.trim(),
        preview: entry.text,
        href: `/memory/l3/${slot}`,
        x: 0,
        y: 0,
        r: 6,
      } satisfies Omit<GraphNode, "x" | "y" | "r"> & {
        x: number;
        y: number;
        r: number;
      };
    }).forEach((n) => nodes.push(n));
  });

  // ── Place L2 nodes inside their slice.
  // Track entry ULID → node id so L3 footnotes that cite specific
  // ``m_xxx`` entries (the future-proof path) can wire up cleanly.
  const l2EntryNodeIdx = new Map<string, string>();
  SURFACES.forEach((surf) => {
    const cluster = l2ClusterMap.get(surf)!;
    const entries = dedupedL2[surf];
    placeNodesInSlice(entries.length, cluster, center, (i) => {
      const entry = entries[i];
      const id = `L2:${surf}:${entry.id}`;
      l2EntryNodeIdx.set(entry.id, id);
      nodeCluster.set(id, cluster.id);
      return {
        id,
        layer: "L2",
        cluster: cluster.id,
        section: entry.section,
        label: `${cluster.label} · ${entry.section || ""}`.trim(),
        preview: entry.text,
        href: `/memory/l2/${surf}`,
        x: 0,
        y: 0,
        r: 4.5,
      } satisfies Omit<GraphNode, "x" | "y" | "r"> & {
        x: number;
        y: number;
        r: number;
      };
    }).forEach((n) => nodes.push(n));
  });

  // ── Place L1 nodes inside their slice.
  const l1EntityNodeIdx = new Map<string, string>(); // ``${surf}:${id}`` → node id
  SURFACES.forEach((surf) => {
    const cluster = l1ClusterMap.get(surf)!;
    const entities = dedupedL1[surf];
    placeNodesInSlice(entities.length, cluster, center, (i) => {
      const entity = entities[i];
      const id = `L1:${surf}:${entity.id}`;
      l1EntityNodeIdx.set(`${surf}:${entity.id}`, id);
      nodeCluster.set(id, cluster.id);
      return {
        id,
        layer: "L1",
        cluster: cluster.id,
        label: entity.label || entity.id,
        preview: entity.content?.slice(0, 280) ?? "",
        href: `/memory/l1?surface=${surf}&ref=${encodeURIComponent(
          `${surf}:${entity.id}`,
        )}`,
        x: 0,
        y: 0,
        r: 2.8,
      } satisfies Omit<GraphNode, "x" | "y" | "r"> & {
        x: number;
        y: number;
        r: number;
      };
    }).forEach((n) => nodes.push(n));
  });

  // ── Edges. L2 → L1 (specific entity), L3 → L2 (specific entry OR
  // soft to surface cluster centroid).
  const pushEdge = (e: GraphEdge) => {
    edges.push(e);
    if (!adjacency.has(e.source)) adjacency.set(e.source, []);
    if (!adjacency.has(e.target)) adjacency.set(e.target, []);
    adjacency.get(e.source)!.push(e.target);
    adjacency.get(e.target)!.push(e.source);
  };

  SURFACES.forEach((surf) => {
    for (const entry of dedupedL2[surf]) {
      const sourceId = `L2:${surf}:${entry.id}`;
      for (const ref of entry.refs) {
        const { surface: s, entityId } = splitRef(ref);
        if (!s || !entityId) continue;
        const targetId = l1EntityNodeIdx.get(`${s}:${entityId}`);
        if (targetId) {
          pushEdge({ source: sourceId, target: targetId, kind: "strong" });
        }
      }
    }
  });

  // Soft edges from L3 → L2 cluster centroid synthetic node. Real L3
  // citations today are surface-level ("chat"), so we add one synthetic
  // anchor per surface that lives at the cluster's geometric centroid.
  // Synthetic anchors are hidden from the user (rendered as a faint
  // halo) but appear in the adjacency map so hover highlighting can
  // light up the whole surface.
  const surfaceAnchors = new Map<string, string>();
  SURFACES.forEach((surf) => {
    const cluster = l2ClusterMap.get(surf)!;
    const id = `L2:${surf}:__anchor__`;
    surfaceAnchors.set(surf, id);
    nodeCluster.set(id, cluster.id);
    nodes.push({
      id,
      layer: "L2",
      cluster: cluster.id,
      label: cluster.label,
      preview: `${cluster.label} surface`,
      href: `/memory/l2/${surf}`,
      x: cluster.cx,
      y: cluster.cy,
      // Hidden — see GraphView. We keep ``r = 0`` so hit-testing skips it.
      r: 0,
    });
  });

  L3_SLOTS.forEach((slot) => {
    for (const entry of dedupedL3[slot]) {
      const sourceId = `L3:${slot}:${entry.id}`;
      // Track which surfaces this L3 entry cites so we don't draw
      // duplicate edges into the same cluster anchor.
      const cited = new Set<string>();
      for (const ref of entry.refs) {
        // ``ref`` here is the *resolved* footnote payload, e.g.
        //   ``chat``                        → surface-level
        //   ``chat:m_01KS...`` (future)      → specific L2 entry
        const { surface: s, entityId } = splitRef(ref);
        if (s && entityId.startsWith("m_")) {
          const targetId = l2EntryNodeIdx.get(entityId);
          if (targetId) {
            pushEdge({ source: sourceId, target: targetId, kind: "strong" });
            cited.add(s);
          }
        } else if (!s && (SURFACES as readonly string[]).includes(ref)) {
          if (cited.has(ref)) continue;
          const anchor = surfaceAnchors.get(ref);
          if (anchor) {
            pushEdge({ source: sourceId, target: anchor, kind: "soft" });
            cited.add(ref);
          }
        } else if (s && (SURFACES as readonly string[]).includes(s)) {
          if (cited.has(s)) continue;
          const anchor = surfaceAnchors.get(s);
          if (anchor) {
            pushEdge({ source: sourceId, target: anchor, kind: "soft" });
            cited.add(s);
          }
        }
      }
    }
  });

  return { nodes, edges, clusters, adjacency, nodeCluster };
}

// Spread ``count`` points across a pie-slice using a deterministic
// jittered-grid: divide the annular slice into a roughly hex-packed
// lattice, then perturb each lattice point with a stable hash so the
// cluster reads as a soft galaxy rather than a starburst.
function placeNodesInSlice<T extends { x: number; y: number; r: number }>(
  count: number,
  cluster: ClusterMeta,
  center: { x: number; y: number },
  factory: (i: number) => T,
): T[] {
  if (count === 0) return [];
  const out: T[] = [];
  const sliceSpan = cluster.endAngle - cluster.startAngle;
  const pad = 8;
  const inner = cluster.innerRadius + pad;
  const outer = cluster.outerRadius - pad;
  // Decide how many radial rows to use based on the cluster's area.
  // A thin sector with few items uses one row; a thick sector with
  // hundreds of items uses many.
  const sliceArea = ((outer * outer - inner * inner) * sliceSpan) / 2;
  // Target one point per ~sqrt(area/count) square area.
  const densityCell = Math.sqrt(sliceArea / Math.max(1, count));
  // Number of radial rows ≈ thickness / cell size.
  const thickness = outer - inner;
  const rows = Math.max(1, Math.round(thickness / densityCell));
  // Per-row capacity allocated by arc length (proportional to radius).
  const rowMidR = (r: number) => inner + (thickness * (r + 0.5)) / rows;
  const totalCapacity = (() => {
    let sum = 0;
    for (let r = 0; r < rows; r++) {
      sum += (rowMidR(r) * sliceSpan) / densityCell;
    }
    return sum;
  })();
  // Map item index i to (row, slot within row).
  type Slot = { row: number; col: number; cols: number };
  const slots: Slot[] = [];
  let acc = 0;
  for (let r = 0; r < rows; r++) {
    const rowCols = Math.max(
      1,
      Math.round(
        (count * (rowMidR(r) * sliceSpan)) / (densityCell * totalCapacity),
      ),
    );
    for (let c = 0; c < rowCols; c++) {
      slots.push({ row: r, col: c, cols: rowCols });
    }
    acc += rowCols;
    if (acc >= count) break;
  }
  // Fill remaining slots if rounding under-shot; pad by re-using the
  // outermost row.
  while (slots.length < count) {
    const r = rows - 1;
    slots.push({
      row: r,
      col: slots.length,
      cols: slots[slots.length - 1].cols + 1,
    });
  }
  // Deterministic pseudo-random for jitter, indexed by item id.
  const hash = (n: number) => {
    let x = (n + 1) * 2654435761;
    x = (x ^ (x >>> 13)) >>> 0;
    return ((x * 1597334677) >>> 0) / 4294967296;
  };
  for (let i = 0; i < count; i++) {
    const slot = slots[i];
    const rowMid = rowMidR(slot.row);
    const colFrac = (slot.col + 0.5) / slot.cols;
    // Hex offset: alternate rows shift by half a column.
    const colShift = slot.row % 2 === 0 ? 0 : 0.5 / slot.cols;
    const a =
      cluster.startAngle +
      sliceSpan * (colFrac + colShift) +
      (hash(i) - 0.5) * (sliceSpan / slot.cols) * 0.45;
    const r =
      rowMid +
      (hash(i + 9311) - 0.5) * Math.min(densityCell * 0.85, thickness / rows);
    const node = factory(i);
    node.x = center.x + Math.cos(a) * r;
    node.y = center.y + Math.sin(a) * r;
    out.push(node);
  }
  return out;
}

// ── Display labels ───────────────────────────────────────────────────

export const SURFACE_LABEL: Record<Surface, string> = {
  chat: "Chat",
  notebook: "Notebook",
  quiz: "Quiz",
  kb: "Knowledge base",
  book: "Book",
  partner: "Partner",
  cowriter: "Co-writer",
};

export const L3_LABEL: Record<L3Slot, string> = {
  profile: "Profile",
  recent: "Recent",
  scope: "Scope",
};
