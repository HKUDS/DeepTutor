"use client";

import { createContext, useContext } from "react";
import type { ReadingAgeMode } from "@/lib/reading-age-presentation";
import type {
  ReadingExtensionManifest,
  ReadingExtensionResult,
} from "@/lib/reading-api";

/** How read-along reaches the page it is reading. */
export interface ReadAlongSource {
  /** Word model + plain text of the page currently rendered. */
  getPage: () => { text: string; wordCount: number } | null;
  /** True when the reader can advance (there is a next unit). */
  hasNext: () => boolean;
  /** Turn to the next unit, keeping read-along going. */
  next: () => void;
}

/** One runnable extension action, with its label already resolved. */
export interface ReadingActionEntry {
  key: string;
  extension: ReadingExtensionManifest;
  action: ReadingExtensionManifest["actions"][number];
  label: string;
  /** Needs a text selection to mean anything (translate, explain, guide). */
  needsSelection: boolean;
}

/**
 * One run of an action, as the companion column shows it.
 *
 * A card exists from the moment the action starts, so the learner sees where
 * the answer is going to land before it arrives — the old toolbar spun a chip
 * and then dropped a result between the toolbar and the page, a place nothing
 * else on screen ever used.
 */
export interface ReadingActionCard {
  id: string;
  key: string;
  label: string;
  quote: string;
  locator: number;
  materialId: string;
  status: "running" | "done" | "error";
  result?: ReadingExtensionResult;
  error?: string;
}

export interface ReadingActionsValue {
  ageMode: ReadingAgeMode;
  /** Index into `readAlongWords` of the word being spoken, or -1. */
  activeWord: number;
  /** Word timeline for the passage currently being read aloud. */
  readAlongWords: { word: string; start: number; duration: number }[];
  actions: ReadingActionEntry[];
  cards: ReadingActionCard[];
  speaking: boolean;
  /**
   * Read-along is armed: the reader follows the voice with a cursor, and
   * clicking or selecting text starts speech from that point
   * (NaturalReader's interaction model, as opposed to a one-shot page play).
   */
  readAlongActive: boolean;
  /** Start read-along at a word index, or resume from where it stopped. */
  startReadAlong: (fromWord?: number) => void;
  /** Speak a selection once and stop (no advancing past it). */
  speakSelection: (text: string) => void;
  /** Toggle the read-along cursor on/off. */
  toggleReadAlong: () => void;
  /** The reader calls this once a newly turned page has rendered. */
  continueReadAlong: () => void;
  /** Key of the action currently running, or "". */
  busyKey: string;
  run: (
    entry: ReadingActionEntry,
    target?: { locator?: number; selection?: string },
  ) => Promise<void>;
  stopSpeaking: () => void;
  dismiss: (cardId: string) => void;
  /**
   * The reader registers how to obtain its current page and turn to the next
   * one. Held in the provider so read-along can walk a multi-unit document
   * without the toolbar knowing how the reader paginates.
   */
  registerReadAlongSource: (source: ReadAlongSource | null) => void;
}

export const ReadingActionsContext = createContext<ReadingActionsValue | null>(
  null,
);

/**
 * The workspace's shared reading actions, or `null` outside a workspace.
 *
 * `null` is a real state: the reader pane is also rendered on its own (tests,
 * and any host without a companion column), and there it keeps its own
 * toolbar with inline results.
 */
export function useReadingActions(): ReadingActionsValue | null {
  return useContext(ReadingActionsContext);
}

/**
 * Put the caret in the companion's composer, leaving its draft alone.
 *
 * The composer's own prefill hook *sets* the text, so using it with "" to
 * "just focus" wiped whatever the learner had half-typed.
 */
export function focusReadingComposer() {
  document
    .querySelector<HTMLTextAreaElement>("[data-reading-composer] textarea")
    ?.focus();
}
