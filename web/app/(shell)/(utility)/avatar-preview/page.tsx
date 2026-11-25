"use client";

// TEMPORARY harness for the session-avatar states. Delete once signed off.

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  SessionAvatar,
  type SessionMark,
} from "@/components/sidebar/SessionAvatar";

const TITLES = [
  "DeepTutor 模型配置工作台",
  "DeepTutor 侧边栏聊天历史重组",
  "Thinking-orbs 集成到 DeepTutor",
  "DeepTutor 模型配置集成逻辑",
  "deeptutor.info 文档审查",
  "New session",
];

/**
 * The lifecycle a session actually walks: it runs, it finishes while you are
 * elsewhere, then you open it. Cycling through that is the only way to judge
 * both transitions without clicking at exactly the right moment.
 */
const CYCLE: SessionMark[] = [
  "idle",
  "running",
  "unread",
  "idle",
  "running",
  "failed",
];

function SidebarMock({
  marks,
  size,
}: {
  marks: SessionMark[];
  size: number;
}) {
  return (
    <div className="w-[268px] rounded-xl border border-[var(--border)]/60 bg-[var(--card)]/40 p-2">
      {TITLES.map((title, i) => (
        <div
          key={title}
          className="group/session flex items-center gap-2.5 rounded-lg px-2 py-[7px] text-[13.5px] text-[var(--foreground)] transition-colors hover:bg-[var(--muted)]/50"
        >
          <SessionAvatar sessionId={title} mark={marks[i]} size={size} />
          <span className="min-w-0 truncate">{title}</span>
        </div>
      ))}
    </div>
  );
}

export default function AvatarPreview() {
  const { t } = useTranslation();
  const [phase, setPhase] = useState(0);
  const [auto, setAuto] = useState(true);
  const [size, setSize] = useState(12);

  useEffect(() => {
    if (!auto) return;
    const id = window.setInterval(() => setPhase((p) => p + 1), 1800);
    return () => window.clearInterval(id);
  }, [auto]);

  // Each row sits at a different point in the cycle, so every state and both
  // transitions are on screen at once.
  const marks = TITLES.map(
    (_, i) => CYCLE[(phase + i) % CYCLE.length] ?? "idle",
  );

  return (
    <div className="h-full overflow-y-auto bg-[var(--background)] p-8 text-[var(--foreground)]">
      <h1 className="text-[15px] font-semibold">{t("Session avatars — states")}</h1>
      <p className="mt-1 max-w-[720px] text-[12.5px] leading-[1.7] text-[var(--muted-foreground)]">
        {t("Avatar state preview description")}
      </p>

      <div className="mt-5 flex items-center gap-3 text-[12.5px]">
        <button
          type="button"
          onClick={() => setAuto((v) => !v)}
          className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
        >
          {auto ? t("Pause") : t("Play")}
        </button>
        <button
          type="button"
          onClick={() => setPhase((p) => p + 1)}
          className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
        >
          {t("Step forward")}
        </button>
        <span className="ml-2 text-[var(--muted-foreground)]/60">{t("Size")}</span>
        {[11, 12, 13, 14].map((px) => (
          <button
            key={px}
            type="button"
            onClick={() => setSize(px)}
            className={`rounded-lg border px-2.5 py-1.5 tabular-nums ${
              size === px
                ? "border-[var(--primary)] text-[var(--primary)]"
                : "border-[var(--border)] text-[var(--muted-foreground)]"
            }`}
          >
            {px}px
          </button>
        ))}
      </div>

      <div className="mt-7 flex flex-wrap items-start gap-10">
        <div>
          <div className="mb-2 text-[11px] uppercase tracking-[0.08em] text-[var(--muted-foreground)]/50">
            {t("Sidebar 1:1")}
          </div>
          <SidebarMock marks={marks} size={size} />
        </div>

        <div>
          <div className="mb-2 text-[11px] uppercase tracking-[0.08em] text-[var(--muted-foreground)]/50">
            {t("State snapshots · 4× zoom")}
          </div>
          <div className="flex gap-7 rounded-xl border border-[var(--border)]/60 p-5">
            {(
              ["running", "unread", "failed", "idle"] as SessionMark[]
            ).map((mark) => (
              <div key={mark} className="flex flex-col items-center gap-3">
                <span style={{ zoom: 4 }}>
                  <SessionAvatar sessionId={mark} mark={mark} size={size} />
                </span>
                <span className="text-[11px] text-[var(--muted-foreground)]/60">
                  {t({ running: "Running", unread: "Unread", failed: "Failed", idle: "Idle" }[mark])}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
