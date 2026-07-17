"use client";

import { useRef, useState } from "react";
import { ReactSketchCanvas, type ReactSketchCanvasRef } from "react-sketch-canvas";
import { Eraser, Pencil, RotateCcw, Trash2, X } from "lucide-react";
import { useTranslation } from "react-i18next";

interface DrawingModalProps {
  open: boolean;
  onClose: () => void;
  onInsert: (dataUrl: string) => void;
}

export default function DrawingModal({ open, onClose, onInsert }: DrawingModalProps) {
  const { t } = useTranslation();
  const canvasRef = useRef<ReactSketchCanvasRef>(null);
  const [isEraser, setIsEraser] = useState(false);
  // Default to black stroke for now, as agreed.
  const [strokeColor] = useState("#000000");

  if (!open) return null;

  const handleClear = () => {
    canvasRef.current?.clearCanvas();
  };

  const handleUndo = () => {
    canvasRef.current?.undo();
  };

  const handleInsert = async () => {
    if (!canvasRef.current) return;
    try {
      // Export as a base64 encoded PNG
      const dataUrl = await canvasRef.current.exportImage("png");
      onInsert(dataUrl);
      onClose();
    } catch (e) {
      console.error("Failed to export drawing", e);
    }
  };

  const handleModeToggle = () => {
    const nextEraser = !isEraser;
    setIsEraser(nextEraser);
    canvasRef.current?.eraseMode(nextEraser);
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 p-4 sm:p-8 animate-in fade-in duration-200">
      <div className="flex h-full w-full max-w-5xl flex-col overflow-hidden rounded-2xl bg-[var(--card)] shadow-2xl animate-in zoom-in-95 duration-200">
        
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
          <h2 className="text-lg font-semibold">{t("Drawing Board")}</h2>
          <button
            onClick={onClose}
            className="rounded-full p-2 hover:bg-[var(--muted)]/80 text-[var(--muted-foreground)] transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        {/* Toolbar */}
        <div className="flex items-center justify-between border-b border-[var(--border)]/50 bg-[var(--muted)]/30 px-4 py-2">
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => {
                setIsEraser(false);
                canvasRef.current?.eraseMode(false);
              }}
              className={`flex h-9 items-center gap-2 rounded-lg px-3 text-sm font-medium transition-colors ${
                !isEraser ? "bg-[var(--primary)] text-[var(--primary-foreground)]" : "bg-[var(--card)] hover:bg-[var(--muted)] border border-[var(--border)]"
              }`}
            >
              <Pencil size={16} />
              {t("Pen")}
            </button>
            <button
              onClick={() => {
                setIsEraser(true);
                canvasRef.current?.eraseMode(true);
              }}
              className={`flex h-9 items-center gap-2 rounded-lg px-3 text-sm font-medium transition-colors ${
                isEraser ? "bg-[var(--primary)] text-[var(--primary-foreground)]" : "bg-[var(--card)] hover:bg-[var(--muted)] border border-[var(--border)]"
              }`}
            >
              <Eraser size={16} />
              {t("Eraser")}
            </button>
            <div className="mx-2 h-6 w-px bg-[var(--border)] hidden sm:block" />
            <button
              onClick={handleUndo}
              className="flex h-9 items-center gap-2 rounded-lg bg-[var(--card)] px-3 text-sm font-medium border border-[var(--border)] hover:bg-[var(--muted)] transition-colors"
            >
              <RotateCcw size={16} />
              <span className="hidden sm:inline">{t("Undo")}</span>
            </button>
            <button
              onClick={handleClear}
              className="flex h-9 items-center gap-2 rounded-lg bg-[var(--card)] px-3 text-sm font-medium border border-[var(--border)] hover:bg-[var(--muted)] text-red-500 hover:text-red-600 transition-colors"
            >
              <Trash2 size={16} />
              <span className="hidden sm:inline">{t("Clear")}</span>
            </button>
          </div>
          
          <button
            onClick={handleInsert}
            className="rounded-lg bg-[var(--primary)] px-5 py-2 text-sm font-medium text-[var(--primary-foreground)] hover:bg-[var(--primary)]/90 transition-colors shrink-0"
          >
            {t("Insert Drawing")}
          </button>
        </div>

        {/* Canvas Area */}
        <div className="relative flex-1 bg-white">
          <ReactSketchCanvas
            ref={canvasRef}
            strokeWidth={isEraser ? 20 : 3}
            strokeColor={strokeColor}
            canvasColor="transparent"
            className="h-full w-full"
          />
        </div>
      </div>
    </div>
  );
}
