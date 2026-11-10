"use client";

/**
 * NotebookGraphView — the notebook's cells as a connectable map.
 *
 * Each cell is a node; drawing between the handles links two cells, and a link
 * carries a Markdown label — which is what lets the line hold text, a formula
 * (`$...$`) or an image. Layout and links are handed back to the notebook,
 * which parks them in the hidden `dt-graph` block of the page.
 */

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { FileText, Shapes, SquareTerminal } from "lucide-react";
import {
  Background,
  BaseEdge,
  ConnectionMode,
  Controls,
  EdgeLabelRenderer,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  getSmoothStepPath,
  useNodesState,
  type Connection,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import RichMarkdownRenderer from "@/components/common/RichMarkdownRenderer";
import RichCodeBlock from "@/components/common/RichCodeBlock";
import NotebookCellEditor from "@/components/chat/home/NotebookCellEditor";
import {
  newNotebookEdgeId,
  type NotebookGraph,
  type NotebookTag,
} from "@/lib/notebook-graph";
import { normalizeCellLanguage, type NotebookCell } from "@/lib/notebook-cells";
import NotebookTagControl, {
  NotebookTagChip,
} from "@/components/chat/home/NotebookTagControl";

const Geogebra = dynamic(() => import("@/components/Geogebra"), { ssr: false });

type CellNode = Node<{ cell: NotebookCell; tag?: NotebookTag }, "cell">;
type LabeledEdge = Edge<{ label: string }, "labeled">;

const NODE_WIDTH = 264;
const NODE_GAP_X = 320;
const NODE_GAP_Y = 260;

const ADD_CELL_OPTIONS = [
  { kind: "markdown" as const, icon: FileText, label: "Note cell" },
  { kind: "code" as const, icon: SquareTerminal, label: "Code cell" },
  { kind: "geogebra" as const, icon: Shapes, label: "Board cell" },
];

function defaultPosition(index: number) {
  return {
    x: 60 + (index % 3) * NODE_GAP_X,
    y: 60 + Math.floor(index / 3) * NODE_GAP_Y,
  };
}

function CellNodeView({ data }: NodeProps<CellNode>) {
  const { t } = useTranslation();
  const cell = data.cell;
  const empty = t("(empty)");
  const kindLabel =
    cell.kind === "code"
      ? t("Code")
      : cell.kind === "geogebra"
        ? t("GeoGebra board")
        : t("Note");
  const name = cell.name?.trim() ?? "";
  return (
    <div
      style={{
        width: NODE_WIDTH,
        ...(data.tag ? { borderTop: `3px solid ${data.tag.color}` } : {}),
      }}
      className="overflow-hidden rounded-2xl border border-[color-mix(in_srgb,var(--border)_65%,transparent)] bg-[var(--card)] shadow-sm"
    >
      <div className="flex items-center justify-between gap-1 border-b border-[color-mix(in_srgb,var(--border)_35%,transparent)] px-2.5 py-1.5">
        <div className="min-w-0 flex-1">
          <div className="truncate text-[12.5px] font-medium text-[var(--foreground)]">
            {name || kindLabel}
          </div>
          {name ? (
            <div className="truncate text-[10px] text-[var(--muted-foreground)]">
              {kindLabel}
            </div>
          ) : null}
        </div>
        {data.tag ? <NotebookTagChip tag={data.tag} /> : null}
      </div>
      <div className="max-h-[240px] overflow-auto px-2.5 py-2 text-[12px]">
        {cell.kind === "code" ? (
          cell.source.trim() ? (
            <RichCodeBlock raw={cell.source} lang={normalizeCellLanguage(cell.language)} />
          ) : (
            <span className="text-[var(--muted-foreground)]">{empty}</span>
          )
        ) : cell.kind === "geogebra" ? (
          <Geogebra
            script={cell.source}
            editable={false}
            width={NODE_WIDTH - 24}
            height={168}
          />
        ) : cell.source.trim() ? (
          <RichMarkdownRenderer content={cell.source} enableMath enableCode enableMermaid />
        ) : (
          <span className="text-[var(--muted-foreground)]">{empty}</span>
        )}
      </div>
      <Handle
        type="target"
        position={Position.Left}
        className="!h-3 !w-3 !border-2 !border-[var(--card)] !bg-[var(--primary)]"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!h-3 !w-3 !border-2 !border-[var(--card)] !bg-[var(--primary)]"
      />
    </div>
  );
}

function LabeledEdgeView({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  data,
  selected,
}: EdgeProps<LabeledEdge>) {
  const [path, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });
  const label = data?.label ?? "";
  return (
    <>
      {/* A light halo keeps the line legible over the dotted canvas. */}
      <path
        d={path}
        fill="none"
        stroke="var(--background)"
        strokeWidth={6}
        strokeLinecap="round"
      />
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        style={{
          stroke: selected ? "var(--primary)" : "#64748b",
          strokeWidth: selected ? 3 : 2,
        }}
      />
      {label ? (
        <EdgeLabelRenderer>
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%,-50%) translate(${labelX}px,${labelY}px)`,
              pointerEvents: "all",
            }}
            className="nodrag nopan max-w-[200px] rounded-md border border-[color-mix(in_srgb,var(--border)_60%,transparent)] bg-[var(--card)] px-1.5 py-0.5 text-[11px] leading-snug text-[var(--foreground)]"
          >
            <RichMarkdownRenderer content={label} enableMath enableImages />
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}

const NODE_TYPES = { cell: CellNodeView };
const EDGE_TYPES = { labeled: LabeledEdgeView };

export default function NotebookGraphView({
  cells,
  graph,
  onGraphChange,
  onCellChange,
  onUploadImage,
  onTagChange,
  onAddCell,
}: {
  cells: NotebookCell[];
  graph: NotebookGraph;
  onGraphChange: (graph: NotebookGraph) => void;
  onCellChange?: (id: string, patch: Partial<NotebookCell>) => void;
  /** Upload an image and return its URL, for a link label. */
  onUploadImage?: (file: File) => Promise<string>;
  onTagChange?: (id: string, tag: NotebookTag | null) => void;
  /** Add a new cell; the list appends it after the current cells. */
  onAddCell?: (kind: NotebookCell["kind"]) => void;
}) {
  const { t } = useTranslation();
  const [nodes, setNodes, onNodesChange] = useNodesState<CellNode>(
    cells.map((cell, index) => ({
      id: cell.id,
      type: "cell" as const,
      position: graph.positions[cell.id] ?? defaultPosition(index),
      data: { cell, tag: graph.tags[cell.id] },
    })),
  );
  const [editing, setEditing] = useState<{ id: string; label: string } | null>(
    null,
  );
  const [editingCellId, setEditingCellId] = useState<string | null>(null);
  // Keep nodes aligned with the cell list: edits update their data, new cells
  // appear as cards after the previous cell in the list, and deleted cells drop
  // out. Existing nodes keep the position the learner dragged them to.
  useEffect(() => {
    setNodes((prev) => {
      const current = new Map(prev.map((node) => [node.id, node]));
      let previous: { x: number; y: number } | null = null;
      return cells.map((cell, index) => {
        const existing = current.get(cell.id);
        if (existing) {
          previous = existing.position;
          return {
            ...existing,
            data: {
              ...existing.data,
              cell,
              tag: graph.tags[cell.id],
            },
          };
        }
        const position =
          graph.positions[cell.id] ??
          (previous
            ? { x: previous.x, y: previous.y + NODE_GAP_Y }
            : defaultPosition(index));
        previous = position;
        return {
          id: cell.id,
          type: "cell" as const,
          position,
          data: { cell, tag: graph.tags[cell.id] },
        };
      });
    });
  }, [cells, graph.tags, graph.positions, setNodes]);
  const labelRef = useRef<HTMLTextAreaElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);

  const insertLabelSnippet = useCallback((snippet: string) => {
    setEditing((current) => {
      if (!current) return current;
      const element = labelRef.current;
      const start = element?.selectionStart ?? current.label.length;
      const end = element?.selectionEnd ?? current.label.length;
      return {
        ...current,
        label:
          current.label.slice(0, start) + snippet + current.label.slice(end),
      };
    });
  }, []);

  const uploadIntoLabel = useCallback(
    async (file: File) => {
      if (!onUploadImage) return;
      try {
        const url = await onUploadImage(file);
        insertLabelSnippet(`\n![](${url})\n`);
      } catch {
        // A failed upload leaves the label as it was.
      }
    },
    [insertLabelSnippet, onUploadImage],
  );

  const edges: LabeledEdge[] = useMemo(
    () =>
      graph.edges.map((edge) => ({
        id: edge.id,
        source: edge.from,
        target: edge.to,
        type: "labeled" as const,
        data: { label: edge.label },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 22,
          height: 22,
          color: "#64748b",
        },
      })),
    [graph.edges],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return;
      const id = newNotebookEdgeId();
      onGraphChange({
        ...graph,
        edges: [
          ...graph.edges,
          { id, from: connection.source, to: connection.target, label: "" },
        ],
      });
      setEditing({ id, label: "" });
    },
    [graph, onGraphChange],
  );

  const onNodeDragStop = useCallback(
    (_event: unknown, node: CellNode) => {
      onGraphChange({
        ...graph,
        positions: { ...graph.positions, [node.id]: node.position },
      });
    },
    [graph, onGraphChange],
  );

  const onEdgesDelete = useCallback(
    (deleted: LabeledEdge[]) => {
      const ids = new Set(deleted.map((edge) => edge.id));
      onGraphChange({
        ...graph,
        edges: graph.edges.filter((edge) => !ids.has(edge.id)),
      });
    },
    [graph, onGraphChange],
  );

  const connectInOrder = useCallback(() => {
    const next = [...graph.edges];
    for (let i = 0; i < cells.length - 1; i += 1) {
      const from = cells[i].id;
      const to = cells[i + 1].id;
      if (next.some((edge) => edge.from === from && edge.to === to)) continue;
      next.push({ id: newNotebookEdgeId(), from, to, label: "" });
    }
    onGraphChange({ ...graph, edges: next });
  }, [cells, graph, onGraphChange]);

  const saveLabel = useCallback(() => {
    if (!editing) return;
    onGraphChange({
      ...graph,
      edges: graph.edges.map((edge) =>
        edge.id === editing.id ? { ...edge, label: editing.label } : edge,
      ),
    });
    setEditing(null);
  }, [editing, graph, onGraphChange]);

  const deleteEdge = useCallback(() => {
    if (!editing) return;
    onGraphChange({
      ...graph,
      edges: graph.edges.filter((edge) => edge.id !== editing.id),
    });
    setEditing(null);
  }, [editing, graph, onGraphChange]);

  const editingCell = editingCellId
    ? cells.find((cell) => cell.id === editingCellId)
    : undefined;

  return (
    <div className="relative h-full w-full">
      <div className="pointer-events-none absolute left-3 top-3 z-10 max-w-[330px] rounded-lg border border-[color-mix(in_srgb,var(--border)_55%,transparent)] bg-[color-mix(in_srgb,var(--card)_92%,transparent)] px-3 py-2 text-[11.5px] leading-snug text-[var(--muted-foreground)] shadow-sm">
        <p>
          {t("Drag a dot on a cell onto another cell to link them; click a line to label it.")}
        </p>
        <button
          type="button"
          onClick={connectInOrder}
          className="pointer-events-auto mt-1.5 rounded-md border border-[color-mix(in_srgb,var(--border)_60%,transparent)] px-2 py-1 text-[11px] text-[var(--foreground)] transition-colors hover:bg-[color-mix(in_srgb,var(--muted)_60%,transparent)]"
        >
          {t("Connect in order")}
        </button>
      </div>
      <ReactFlowProvider>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onConnect={onConnect}
          onNodeDragStop={onNodeDragStop}
          onEdgesDelete={onEdgesDelete}
          onEdgeClick={(_event, edge) =>
            setEditing({ id: edge.id, label: String(edge.data?.label ?? "") })
          }
          nodeTypes={NODE_TYPES}
          edgeTypes={EDGE_TYPES}
          deleteKeyCode={null}
          connectionMode={ConnectionMode.Loose}
          connectionLineStyle={{ stroke: "#64748b", strokeWidth: 2 }}
          onNodeDoubleClick={(_event, node) => {
            if (onCellChange) setEditingCellId(node.id);
          }}
          zoomOnDoubleClick={false}
          fitView
          minZoom={0.2}
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
      </ReactFlowProvider>

      {onAddCell ? (
        <div className="pointer-events-none absolute bottom-4 left-1/2 z-10 flex -translate-x-1/2 items-center gap-0.5 rounded-full border border-[color-mix(in_srgb,var(--border)_65%,transparent)] bg-[color-mix(in_srgb,var(--card)_94%,transparent)] p-1 shadow-lg backdrop-blur">
          {ADD_CELL_OPTIONS.map(({ kind, icon: Icon, label }) => (
            <button
              key={kind}
              type="button"
              onClick={() => onAddCell(kind)}
              className="pointer-events-auto inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[11.5px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[color-mix(in_srgb,var(--muted)_70%,transparent)] hover:text-[var(--foreground)]"
            >
              <Icon size={13} strokeWidth={1.8} aria-hidden />
              {t(label)}
            </button>
          ))}
        </div>
      ) : null}

      {editingCell ? (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/30 p-4"
          onClick={() => setEditingCellId(null)}
        >
          <div
            className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-xl border border-[var(--border)] bg-[var(--card)] shadow-xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex shrink-0 items-center justify-between border-b border-[color-mix(in_srgb,var(--border)_45%,transparent)] px-4 py-2.5">
              <div className="min-w-0">
                <h2 className="truncate text-[13px] font-semibold text-[var(--foreground)]">
                  {editingCell.name?.trim() ||
                    t(
                      editingCell.kind === "code"
                        ? "Code"
                        : editingCell.kind === "geogebra"
                          ? "GeoGebra board"
                          : "Note",
                    )}
                </h2>
                {editingCell.name?.trim() ? (
                  <p className="truncate text-[10px] text-[var(--muted-foreground)]">
                    {t(
                      editingCell.kind === "code"
                        ? "Code"
                        : editingCell.kind === "geogebra"
                          ? "GeoGebra board"
                          : "Note",
                    )}
                  </p>
                ) : null}
              </div>
              <button
                type="button"
                onClick={() => setEditingCellId(null)}
                className="rounded-md px-2 py-1 text-[12px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
              >
                {t("Close")}
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-3">
              <NotebookCellEditor
                cell={editingCell}
                onChange={(patch) => onCellChange?.(editingCell.id, patch)}
                tag={graph.tags[editingCell.id]}
                onTagChange={(next) => onTagChange?.(editingCell.id, next)}
              />
            </div>
          </div>
        </div>
      ) : null}

      {editing ? (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/30 p-4"
          onClick={() => setEditing(null)}
        >
          <div
            className="w-full max-w-md rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-xl"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 className="text-[13px] font-semibold text-[var(--foreground)]">
              {t("Link label")}
            </h2>
            <p className="mt-0.5 text-[11.5px] text-[var(--muted-foreground)]">
              {t("Text, a $formula$ or an image — Markdown shown on the line.")}
            </p>
            <textarea
              ref={labelRef}
              autoFocus
              value={editing.label}
              rows={3}
              onChange={(event) =>
                setEditing({ ...editing, label: event.target.value })
              }
              onPaste={(event) => {
                const file = Array.from(event.clipboardData?.files ?? []).find(
                  (item) => item.type.startsWith("image/"),
                );
                if (file && onUploadImage) {
                  event.preventDefault();
                  void uploadIntoLabel(file);
                }
              }}
              placeholder={t("e.g. if $a>0$ then …")}
              className="mt-2 block w-full resize-y rounded-lg border border-[var(--border)] bg-transparent px-2.5 py-2 font-mono text-[12.5px] text-[var(--foreground)] outline-none"
            />
            {editing.label.trim() ? (
              <div className="mt-2 rounded-lg border border-[color-mix(in_srgb,var(--border)_45%,transparent)] px-2.5 py-2 text-[12.5px]">
                <RichMarkdownRenderer content={editing.label} enableMath enableImages />
              </div>
            ) : null}
            <div className="mt-3 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={deleteEdge}
                  className="text-[12px] text-[var(--muted-foreground)] underline hover:text-[var(--foreground)]"
                >
                  {t("Delete link")}
                </button>
                {onUploadImage ? (
                  <>
                    <input
                      ref={imageInputRef}
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        event.target.value = "";
                        if (file) void uploadIntoLabel(file);
                      }}
                    />
                    <button
                      type="button"
                      onClick={() => imageInputRef.current?.click()}
                      className="text-[12px] text-[var(--muted-foreground)] underline hover:text-[var(--foreground)]"
                    >
                      {t("Add image")}
                    </button>
                  </>
                ) : null}
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setEditing(null)}
                  className="rounded-md px-3 py-1.5 text-[12px] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                >
                  {t("Cancel")}
                </button>
                <button
                  type="button"
                  onClick={saveLabel}
                  className="rounded-md bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-[var(--primary-foreground)]"
                >
                  {t("Save")}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
