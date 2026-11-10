"use client";

/**
 * ReadAlongArticle — 专注跟读。
 *
 * 导师的回复不再“一次铺开”：这一层把它按句（或按块）拆成可跟读的单元，
 * 由一条移动的高亮带路；全篇最多只有一个“必须记住”的信号句，用唯一的高对比标出。
 *
 * 规则（对应 v5–v8 的设计）：
 * - 正文/列表：逐句朗读 + 高亮
 * - 代码块、公式、表格：整块“停靠”，不朗读符号，停留更久
 * - 无 TTS 或有“静默推进”时：按句长自动推进，暂停/选句照常
 * - 点击任意一句可从句开始；学习者可把某一句设为“重点”
 */

import { memo, useCallback, useEffect, useRef, useState } from "react";
import { Pause, Play, SkipBack, SkipForward, Star, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import RichMarkdownRenderer from "@/components/common/RichMarkdownRenderer";
import { apiFetch, apiUrl } from "@/lib/api";
import { useTtsReadiness } from "@/hooks/useTtsReadiness";

/**
 * The markdown body is rendered once and never re-rendered: the read-along
 * annotates its DOM (sentence spans, unit classes), and a re-render would make
 * React reconcile against a tree it no longer recognises. The content is fixed
 * for the lifetime of the overlay, so memoising it is enough to keep React out.
 */
const ArticleBody = memo(function ArticleBody({ content }: { content: string }) {
  return (
    <RichMarkdownRenderer content={content} enableMath enableCode enableMermaid />
  );
});

type UnitKind = "prose" | "listitem" | "code" | "formula" | "table";

const READ_ALONG_CSS = `
.ra-article .ra-sentence { border-radius: 5px; padding: 2px 3px; margin: 0 -3px; cursor: pointer;
  transition: background-color .22s ease, box-shadow .22s ease; }
.ra-article .ra-sentence:hover { background: color-mix(in srgb, var(--muted) 70%, transparent); }
.ra-article .ra-sentence.ra-active { background: #f1ece0; }
.ra-article .ra-unit[data-kind="code"].ra-active { background: #efe7d8; box-shadow: inset 3px 0 0 var(--primary); }
.ra-article .ra-unit[data-kind="formula"].ra-active,
.ra-article .ra-unit[data-kind="table"].ra-active { background: #f6efe0; box-shadow: inset 3px 0 0 var(--primary); }
.ra-article .ra-signal { font-weight: 650;
  background: color-mix(in srgb, var(--primary) 9%, transparent);
  box-shadow: -2px 0 0 var(--primary), 2px 0 0 color-mix(in srgb, var(--primary) 9%, transparent); }
.ra-article .ra-signal.ra-active { background: color-mix(in srgb, var(--primary) 16%, transparent); }
@media (prefers-reduced-motion: reduce) {
  .ra-article .ra-sentence, .ra-article .ra-unit { transition: none !important; }
}
`;

/** Split a block's text nodes into per-sentence spans, leaving code/math alone. */
function wrapSentences(block: HTMLElement): void {
  const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const parent = node.parentElement;
      if (!parent) return NodeFilter.FILTER_REJECT;
      if (parent.closest("code, pre, .katex, .katex-display, script, style"))
        return NodeFilter.FILTER_REJECT;
      if (!node.nodeValue || !node.nodeValue.trim())
        return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const nodes: Text[] = [];
  while (walker.nextNode()) nodes.push(walker.currentNode as Text);

  for (const node of nodes) {
    const text = node.nodeValue ?? "";
    const parts = text.split(/(?<=[。！？!?])/).filter((part) => part.length > 0);
    const fragment = document.createDocumentFragment();
    for (const part of parts) {
      const span = document.createElement("span");
      span.className = "ra-sentence";
      span.textContent = part;
      fragment.appendChild(span);
    }
    node.parentNode?.replaceChild(fragment, node);
  }
}

/** Walk the rendered markdown and tag every read-along unit, in document order. */
function tagUnits(root: HTMLElement): void {
  const blocks = root.querySelectorAll<HTMLElement>(
    "p, li, pre, .katex-display, table, blockquote, h1, h2, h3, h4",
  );
  blocks.forEach((block) => {
    if (block.closest("pre") && block.tagName !== "PRE") return;
    if (block.closest("table") && block.tagName !== "TABLE") return;
    if (block.tagName === "LI" && block.querySelector("p, pre, .katex-display, table"))
      return;

    let kind: UnitKind = "prose";
    if (block.tagName === "PRE") kind = "code";
    else if (block.classList.contains("katex-display")) kind = "formula";
    else if (block.tagName === "TABLE") kind = "table";
    else if (block.tagName === "LI") kind = "listitem";

    block.classList.add("ra-unit");
    block.dataset.kind = kind;
    if (kind === "prose" || kind === "listitem") wrapSentences(block);
  });
}

function unitText(el: HTMLElement): string {
  return (el.textContent ?? "").replace(/\s+/g, " ").trim();
}

export default function ReadAlongArticle({
  content,
  title,
  onClose,
}: {
  content: string;
  title: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const articleRef = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);
  const [index, setIndex] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [silent, setSilent] = useState(false);
  const [skipBlocks, setSkipBlocks] = useState(false);
  const [signalText, setSignalText] = useState<string | null>(null);

  const synth = typeof window !== "undefined" ? window.speechSynthesis : null;
  const ttsAvailable =
    typeof window !== "undefined" &&
    typeof SpeechSynthesisUtterance !== "undefined" &&
    !!synth;

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const unitsRef = useRef<HTMLElement[]>([]);
  const goRef = useRef<(i: number) => void>(() => {});
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlRef = useRef<string | null>(null);
  const playingRef = useRef(false);
  // Set after the first backend TTS failure so we stop asking and fall back to
  // the browser voice for the rest of the overlay instead of logging 400s.
  const backendFailedRef = useRef(false);
  const ttsReady = useTtsReadiness();

  const [units, setUnits] = useState<HTMLElement[]>([]);

  const clearActive = useCallback(() => {
    unitsRef.current.forEach((el) => el.classList.remove("ra-active"));
  }, []);

  const highlight = useCallback(
    (i: number, center = true) => {
      clearActive();
      const el = unitsRef.current[i];
      if (!el) return;
      el.classList.add("ra-active");
      if (center) el.scrollIntoView({ block: "center", behavior: "smooth" });
    },
    [clearActive],
  );

  const stop = useCallback(() => {
    playingRef.current = false;
    setPlaying(false);
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    }
    if (synth) synth.cancel();
  }, [synth]);

  const kindOf = (el: HTMLElement): UnitKind =>
    (el.dataset.kind as UnitKind) || (el.classList.contains("ra-sentence") ? "prose" : "code");

  const dwell = useCallback(
    (el: HTMLElement) => {
      const kind = kindOf(el);
      if (kind === "code") return 3400 / rate;
      if (kind === "formula" || kind === "table") return 2600 / rate;
      return Math.max(1150, unitText(el).length * 150 / rate);
    },
    [rate],
  );

  // Backend TTS plays a whole unit as audio; the read-along advances when it ends.
  const speakBackend = useCallback(async (text: string) => {
    const resp = await apiFetch(apiUrl("/api/voice/tts"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!resp.ok) throw new Error(`tts ${resp.status}`);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    urlRef.current = url;
    await new Promise<void>((resolve, reject) => {
      const audio = new Audio(url);
      audioRef.current = audio;
      const release = () => {
        if (urlRef.current === url) {
          URL.revokeObjectURL(url);
          urlRef.current = null;
        }
        if (audioRef.current === audio) audioRef.current = null;
      };
      audio.onended = () => {
        release();
        resolve();
      };
      audio.onerror = () => {
        release();
        reject(new Error("audio"));
      };
      void audio.play().catch((error) => {
        release();
        reject(error);
      });
    });
  }, []);

  // The browser voice is the fallback: code/formula blocks only announce a
  // short label, never the symbols themselves.
  const speakWithBrowser = useCallback(
    (i: number, el: HTMLElement, speakable: boolean) => {
      const kind = kindOf(el);
      if (ttsAvailable) {
        const utter = new SpeechSynthesisUtterance(
          speakable
            ? unitText(el)
            : kind === "code"
              ? t("Code · pause")
              : t("Formula · pause"),
        );
        utter.lang = "zh-CN";
        utter.rate = rate;
        utter.onend = () => {
          if (!playingRef.current) return;
          if (speakable) goRef.current(i + 1);
          else timerRef.current = setTimeout(() => goRef.current(i + 1), dwell(el));
        };
        utter.onerror = () => {
          if (playingRef.current)
            timerRef.current = setTimeout(() => goRef.current(i + 1), dwell(el));
        };
        synth?.speak(utter);
        return;
      }
      timerRef.current = setTimeout(() => goRef.current(i + 1), dwell(el));
    },
    [dwell, rate, synth, t, ttsAvailable],
  );

  // The read-along engine: one step per unit, prose read aloud, blocks paused.
  const go = useCallback(
    (i: number) => {
      const list = unitsRef.current;
      if (i >= list.length) {
        setPlaying(false);
        return;
      }
      const el = list[i];
      const kind = kindOf(el);
      setIndex(i);

      if (skipBlocks && (kind === "code" || kind === "formula" || kind === "table")) {
        highlight(i, false);
        timerRef.current = setTimeout(() => goRef.current(i + 1), 220);
        return;
      }
      highlight(i);

      const speakable = kind === "prose" || kind === "listitem";
      if (!silent) {
        // Prefer the configured backend voice; on the first failure stop asking
        // and use the browser voice for the rest of the overlay.
        if (speakable && ttsReady === true && !backendFailedRef.current) {
          speakBackend(unitText(el))
            .then(() => {
              if (playingRef.current) goRef.current(i + 1);
            })
            .catch(() => {
              backendFailedRef.current = true;
              speakWithBrowser(i, el, true);
            });
          return;
        }
        speakWithBrowser(i, el, speakable);
        return;
      }
      timerRef.current = setTimeout(() => goRef.current(i + 1), dwell(el));
    },
    [dwell, highlight, silent, skipBlocks, speakBackend, speakWithBrowser, ttsReady],
  );

  useEffect(() => {
    goRef.current = go;
  }, [go]);

  const play = useCallback(
    (from: number) => {
      stop();
      playingRef.current = true;
      setPlaying(true);
      go(Math.max(0, from));
    },
    [go, stop],
  );

  const togglePlay = useCallback(() => {
    if (playing) {
      stop();
      return;
    }
    play(index < 0 ? 0 : index);
  }, [index, play, playing, stop]);

  const step = useCallback(
    (delta: number) => {
      const list = unitsRef.current;
      const next = Math.min(list.length - 1, Math.max(0, (index < 0 ? 0 : index) + delta));
      if (playing) play(next);
      else {
        setIndex(next);
        highlight(next);
      }
    },
    [highlight, index, play, playing],
  );

  // Tag units once the markdown renderer has produced its DOM.
  useEffect(() => {
    const root = articleRef.current;
    if (!root) return;
    tagUnits(root);
    unitsRef.current = Array.from(
      root.querySelectorAll<HTMLElement>(".ra-sentence, .ra-unit[data-kind='code'], .ra-unit[data-kind='formula'], .ra-unit[data-kind='table']"),
    );
    setUnits(unitsRef.current);
    setReady(true);
  }, [content]);

  // Click a unit: start there (playing) or just position it.
  useEffect(() => {
    const root = articleRef.current;
    if (!root || !ready) return;
    const onClick = (event: Event) => {
      const target = (event.target as HTMLElement | null)?.closest<HTMLElement>(
        ".ra-sentence, .ra-unit",
      );
      if (!target) return;
      const i = unitsRef.current.indexOf(target);
      if (i < 0) return;
      const isActive = target.classList.contains("ra-active");
      // A second click on the current sentence marks it as the one to remember.
      if (isActive) {
        unitsRef.current.forEach((el) => el.classList.remove("ra-signal"));
        target.classList.add("ra-signal");
        setSignalText(unitText(target).slice(0, 120));
        if (playing) stop();
        setIndex(i);
        return;
      }
      if (playing) play(i);
      else {
        setIndex(i);
        highlight(i);
      }
    };
    root.addEventListener("click", onClick);
    return () => root.removeEventListener("click", onClick);
  }, [highlight, play, playing, ready, stop]);

  // Clean up speech and timers when the overlay closes.
  useEffect(() => () => stop(), [stop]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/35 p-4"
      onClick={onClose}
    >
      <style>{READ_ALONG_CSS}</style>
      <div
        className="flex max-h-[88vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex shrink-0 items-center gap-2 border-b border-[color-mix(in_srgb,var(--border)_50%,transparent)] px-4 py-2.5">
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-[13.5px] font-semibold text-[var(--foreground)]">
              {t("Focus reading")}
            </h2>
            {title ? (
              <p className="truncate text-[11px] text-[var(--muted-foreground)]">{title}</p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("Close")}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-colors hover:bg-[var(--accent)] hover:text-[var(--foreground)]"
          >
            <X size={16} strokeWidth={1.9} />
          </button>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-1.5 border-b border-[color-mix(in_srgb,var(--border)_45%,transparent)] px-4 py-2">
          <button
            type="button"
            onClick={togglePlay}
            className="inline-flex h-8 min-w-[104px] items-center justify-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 text-[12.5px] font-medium text-[var(--primary-foreground)] transition hover:opacity-90"
          >
            {playing ? <Pause size={13} /> : <Play size={13} />}
            {playing ? t("Pause") : t("Start read-along")}
          </button>
          <button
            type="button"
            onClick={() => step(-1)}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            aria-label={t("Previous sentence")}
          >
            <SkipBack size={14} />
          </button>
          <button
            type="button"
            onClick={() => step(1)}
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            aria-label={t("Next sentence")}
          >
            <SkipForward size={14} />
          </button>
          <div className="ml-auto flex items-center gap-1 rounded-lg border border-[var(--border)] p-0.5">
            {[0.8, 1, 1.3].map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setRate(value)}
                className={`rounded-md px-2 py-1 text-[11px] ${
                  rate === value
                    ? "bg-[var(--muted)] text-[var(--foreground)]"
                    : "text-[var(--muted-foreground)]"
                }`}
              >
                {value}×
              </button>
            ))}
          </div>
          <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-[11.5px] text-[var(--muted-foreground)]">
            <input
              type="checkbox"
              checked={silent}
              onChange={(event) => setSilent(event.target.checked)}
            />
            {t("Silent")}
          </label>
          <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-[11.5px] text-[var(--muted-foreground)]">
            <input
              type="checkbox"
              checked={skipBlocks}
              onChange={(event) => setSkipBlocks(event.target.checked)}
            />
            {t("Skip code & formulas")}
          </label>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6">
          <div ref={articleRef} className="ra-article mx-auto max-w-[680px]">
            <ArticleBody content={content} />
          </div>
        </div>

        <div className="flex shrink-0 items-center justify-between gap-3 border-t border-[color-mix(in_srgb,var(--border)_45%,transparent)] px-4 py-2 text-[11.5px] text-[var(--muted-foreground)]">
          <span className="truncate">
            {signalText ? (
              <span className="inline-flex items-center gap-1.5">
                <Star size={12} className="text-[var(--primary)]" />
                {t("Key point")}：{signalText}
              </span>
            ) : (
              t("Click a sentence to start; click the current one again to mark it as the key point.")
            )}
          </span>
          {units.length > 0 && index >= 0 ? (
            <span className="shrink-0 tabular-nums">
              {index + 1} / {units.length}
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );
}
