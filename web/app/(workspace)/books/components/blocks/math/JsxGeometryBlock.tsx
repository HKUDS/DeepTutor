"use client";

import { useEffect, useRef } from "react";
import JXG from "jsxgraph";
import "./jsxgraph.css";
import { useTranslation } from "react-i18next";
import type { MathBlockConfig } from "./mathBlockAdapter";

type Board = ReturnType<typeof JXG.JSXGraph.initBoard>;

const NAVY = "#0b2149";
const BRAND = "#14bf96";
const INK60 = "#666666";

const DEFAULT_TITLE = "三角形全等 · SSS（边边边）";
const DEFAULT_HINT = "拖动顶点 A/B/C，观察三边对应相等的两个三角形能否完全重合。";

/** payload 无 elements 时画默认 SSS 全等示例。 */
function drawDefaultBoard(board: Board): void {
  const mk = (coords: [number, number], name: string) =>
    board.create("point", coords, {
      name,
      size: 4,
      color: NAVY,
      strokeColor: "#ffffff",
      strokeWidth: 1,
      label: { fontSize: 16, offset: [6, 6] },
    });
  const A = mk([-4, -1], "A");
  const B = mk([-1.5, 2], "B");
  const C = mk([-2.5, -1], "C");
  board.create("polygon", [A, B, C], {
    name: "△ABC",
    fillColor: BRAND,
    fillOpacity: 0.16,
    strokeColor: NAVY,
    strokeWidth: 2,
    vertices: { visible: false },
    borders: { strokeColor: NAVY },
  });
  const A2 = mk([2.5, -1], "A'");
  const B2 = mk([5, 2], "B'");
  const C2 = mk([4, -1], "C'");
  board.create("polygon", [A2, B2, C2], {
    name: "△A'B'C'",
    fillColor: BRAND,
    fillOpacity: 0.28,
    strokeColor: BRAND,
    strokeWidth: 2,
    vertices: { visible: false },
    borders: { strokeColor: BRAND, dash: 0 },
  });
  board.create("text", [-4.5, 3.2, "AB = A'B'、BC = B'C'、CA = C'A' ⇒ △ABC ≌ △A'B'C'"], {
    fontSize: 13,
    color: INK60,
    anchorX: "left",
  });
}

/**
 * YuEdu fork: JSXGraph 几何画板 block。
 * 用 config.elements（{type, params, attrs}）逐个 board.create；为空时画默认示例。
 * 单个元素构造失败被吞掉，不影响其余元素。
 */
export default function JsxGeometryBlock({
  config,
}: {
  config: MathBlockConfig;
}) {
  const { t } = useTranslation();
  const hostRef = useRef<HTMLDivElement | null>(null);
  const boardRef = useRef<Board | null>(null);

  useEffect(() => {
    if (!hostRef.current) return;
    const board = JXG.JSXGraph.initBoard(hostRef.current, {
      boundingbox: config.boundingBox,
      axis: config.axis,
      grid: config.grid,
      showCopyright: false,
      showNavigation: false,
      keepaspectratio: true,
      pan: { enabled: true },
    });
    boardRef.current = board;

    if (config.elements.length > 0) {
      for (const el of config.elements) {
        try {
          board.create(
            el.type as Parameters<typeof board.create>[0],
            (el.params ?? []) as Parameters<typeof board.create>[1],
            (el.attrs ?? {}) as Parameters<typeof board.create>[2],
          );
        } catch {
          /* 脏元素跳过，不阻断其余绘制 */
        }
      }
    } else {
      drawDefaultBoard(board);
    }

    return () => {
      JXG.JSXGraph.freeBoard(board);
      boardRef.current = null;
    };
  }, [config]);

  const title = config.title || DEFAULT_TITLE;
  const hint = config.hint || DEFAULT_HINT;

  return (
    <div className="my-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="text-base font-bold text-[var(--foreground)]">{title}</h3>
        <span className="rounded-full bg-[var(--background)] px-2.5 py-0.5 text-xs font-medium text-[var(--foreground)]">
          {t("Geometry board")}
        </span>
      </div>
      <div
        ref={hostRef}
        className="h-[380px] w-full overflow-hidden rounded-lg bg-white"
        data-jsxgraph
      />
      <p className="mt-2 text-xs leading-relaxed text-[var(--muted-foreground)]">
        {hint}
      </p>
    </div>
  );
}
