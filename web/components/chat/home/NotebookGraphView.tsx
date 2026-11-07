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
import { useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Background,
  BaseEdge,
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
import {
  newNotebookEdgeId,
  type NotebookGraph,
} from "@/lib/notebook-graph";
import type { NotebookCell } from "@/lib/notebook-cells";

const Geogebra = dynamic(() => import("@/components/Geogebra"), { ssr: false });

type CellNode = Node<{ cell: NotebookCell }, "cell">;
type LabeledEdge = Edge<{ label: string }, "labeled">;

const NODE_WIDTH = 264;
const NODE_GAP_X = 320;
const NODE_GAP_Y = 260;

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
  const label =
    cell.kind === "code"
      ? t("Code")
      : cell.kind === "geogebra"
        ? t("GeoGebra board")
        : t("Note");
  return (
    <div
      style={{ width: NODE_WIDTH }}
      className="overflow-hidden rounded-xl border border-[color-mix(in_srgb,var(--border)_65%,transparent)] bg-[var(--card)] shadow-sm"
    >
      <div className="border-b border-[color-mix(in_srgb,var(--border)_35%,transparent)] px-2.5 py-1 text-[10.5px] font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
        {label}
      </div>
      <div className="max-h-[240px] overflow-auto px-2.5 py-2 text-[12px]">
        {cell.kind === "code" ? (
          <pre className="m-0 whitespace-pre-wrap font-mono text-[11px] text-[var(--foreground)]">
            {cell.source || empty}
          </pre>
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
      <Handle type="target" position={Position.Left} className="!bg-[var(--primary)]" />
      <Handle type="source" position={Position.Right} className="!bg-[var(--primary)]" />
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
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        style={selected ? { strokeWidth: 2.5 } : undefined}
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
}: {
  cells: NotebookCell[];
  graph: NotebookGraph;
  onGraphChange: (graph: NotebookGraph) => void;
}) {
  const { t } = useTranslation();
  const [nodes, setNodes, onNodesChange] = useNodesState<CellNode>(
    cells.map((cell, index) => ({
      id: cell.id,
      type: "cell" as const,
      position: graph.positions[cell.id] ?? defaultPosition(index),
      data: { cell },
    })),
  );
  const [editing, setEditing] = useState<{ id: string; label: string } | null>(
    null,
  );

  const edges: LabeledEdge[] = useMemo(
    () =>
      graph.edges.map((edge) => ({
        id: edge.id,
        source: edge.from,
        target: edge.to,
        type: "labeled" as const,
        data: { label: edge.label },
        markerEnd: { type: MarkerType.ArrowClosed },
      })),
    [graph.edges],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return;
      const id = newNotebookEdgeId();
      onGraphChange({
        positions: graph.positions,
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
        positions: { ...graph.positions, [node.id]: node.position },
        edges: graph.edges,
      });
    },
    [graph, onGraphChange],
  );

  const onEdgesDelete = useCallback(
    (deleted: LabeledEdge[]) => {
      const ids = new Set(deleted.map((edge) => edge.id));
      onGraphChange({
        positions: graph.positions,
        edges: graph.edges.filter((edge) => !ids.has(edge.id)),
      });
    },
    [graph, onGraphChange],
  );

  const saveLabel = useCallback(() => {
    if (!editing) return;
    onGraphChange({
      positions: graph.positions,
      edges: graph.edges.map((edge) =>
        edge.id === editing.id ? { ...edge, label: editing.label } : edge,
      ),
    });
    setEditing(null);
  }, [editing, graph, onGraphChange]);

  const deleteEdge = useCallback(() => {
    if (!editing) return;
    onGraphChange({
      positions: graph.positions,
      edges: graph.edges.filter((edge) => edge.id !== editing.id),
    });
    setEditing(null);
  }, [editing, graph, onGraphChange]);

  return (
    <div className="h-full w-full">
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
          fitView
          minZoom={0.2}
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
      </ReactFlowProvider>

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
              autoFocus
              value={editing.label}
              rows={3}
              onChange={(event) =>
                setEditing({ ...editing, label: event.target.value })
              }
              placeholder={t("e.g. if $a>0$ then …")}
              className="mt-2 block w-full resize-y rounded-lg border border-[var(--border)] bg-transparent px-2.5 py-2 font-mono text-[12.5px] text-[var(--foreground)] outline-none"
            />
            {editing.label.trim() ? (
              <div className="mt-2 rounded-lg border border-[color-mix(in_srgb,var(--border)_45%,transparent)] px-2.5 py-2 text-[12.5px]">
                <RichMarkdownRenderer content={editing.label} enableMath enableImages />
              </div>
            ) : null}
            <div className="mt-3 flex items-center justify-between">
              <button
                type="button"
                onClick={deleteEdge}
                className="text-[12px] text-[var(--muted-foreground)] underline hover:text-[var(--foreground)]"
              >
                {t("Delete link")}
              </button>
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
