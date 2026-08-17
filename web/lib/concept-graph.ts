import type { ConceptGraph } from "@/lib/book-types";

function safeNodeId(nodeId: string, used: Set<string>): string {
  const cleaned =
    (nodeId || "n").replace(/[^\p{L}\p{N}]/gu, "_").replace(/^_+|_+$/g, "") ||
    "n";
  let candidate = cleaned.slice(0, 32);
  let suffix = 1;
  while (used.has(candidate)) {
    suffix += 1;
    candidate = `${cleaned.slice(0, 30)}_${suffix}`;
  }
  used.add(candidate);
  return candidate;
}

function safeLabel(label: string): string {
  return label.trim().replace(/\s+/g, " ").replaceAll('"', "'") || "concept";
}

/**
 * Rebuild the deterministic Mermaid source from structured graph data.
 *
 * Stored books created by older releases may carry already-truncated Mermaid
 * labels even though their structured nodes retain the complete titles.
 * Rendering from the structured source repairs those books in place.
 */
export function renderConceptGraphMermaid(graph: ConceptGraph): string {
  if (graph.nodes.length === 0) {
    return 'graph TD\n  empty["(no concepts yet)"]';
  }

  const chapterMode = graph.nodes.some((node) => Boolean(node.chapter_id));
  const used = new Set<string>();
  const idMap = new Map<string, string>();
  const lines = ["graph TD"];
  let chapterSequence = 0;

  for (const node of graph.nodes) {
    const id = safeNodeId(node.id || node.label, used);
    idMap.set(node.id, id);
    const label = safeLabel(node.label);
    if (chapterMode && node.chapter_id) {
      chapterSequence += 1;
      lines.push(
        `  ${id}["${String(chapterSequence).padStart(2, "0")} · ${label}"]`,
      );
    } else if (chapterMode) {
      lines.push(`  ${id}(["${label}"])`);
    } else {
      lines.push(`  ${id}["${label}"]`);
    }
  }

  const arrows = new Map([
    ["depends_on", "-->"],
    ["extends", "==>"],
    ["related", "-.->"],
  ]);
  for (const edge of graph.edges) {
    const source = idMap.get(edge.src);
    const target = idMap.get(edge.dst);
    if (source && target) {
      lines.push(`  ${source} ${arrows.get(edge.relation) || "-->"} ${target}`);
    }
  }
  return lines.join("\n");
}
