"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { fetchAuthStatus } from "@/lib/auth";
import { getOwnLearnerProfile } from "@/lib/profile-api";
import {
  primaryReadingActionRank,
  resolveReadingAgeMode,
  type ReadingAgeMode,
} from "@/lib/reading-age-presentation";
import {
  listReadingExtensions,
  runReadingExtension,
  type ReadingExtensionManifest,
} from "@/lib/reading-api";
import { CHAT_ROUTED_READING_ACTIONS } from "@/lib/reading-passage-prompts";
import { builtInActionLabel } from "./ReadingExtensionBar";
import {
  ReadingActionsContext,
  type ReadingActionCard,
  type ReadingActionEntry,
  type ReadingActionsValue,
} from "./reading-actions-context";

const MAX_CARDS = 6;

/**
 * Reading actions for a whole workspace: one catalog, one place results land.
 *
 * The reader's selection popover starts them, the companion column shows
 * them, the header's read-aloud button speaks through them. Before this they
 * were a strip of chips above the page that owned its own results, and a
 * learner had two different places an AI answer could appear depending on
 * which button they had pressed.
 */
export function ReadingActionsProvider({
  materialId,
  locator,
  onStart,
  children,
}: {
  /** The material open in the reader; actions run against it. */
  materialId: string | null;
  /** The viewport locator, used when an action has no selection of its own. */
  locator: number;
  /** A result is on its way — the workspace opens the companion for it. */
  onStart?: () => void;
  children: React.ReactNode;
}) {
  const { i18n, t } = useTranslation();
  const [extensions, setExtensions] = useState<ReadingExtensionManifest[]>([]);
  const [ageMode, setAgeMode] = useState<ReadingAgeMode>("default");
  const [cards, setCards] = useState<ReadingActionCard[]>([]);
  const [busyKey, setBusyKey] = useState("");
  const [speaking, setSpeaking] = useState(false);
  const onStartRef = useRef(onStart);
  onStartRef.current = onStart;

  useEffect(() => {
    let active = true;
    void listReadingExtensions()
      .then((rows) => {
        if (active) setExtensions(rows);
      })
      .catch(() => {
        // No catalog means no actions; reading and chat still work.
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    void fetchAuthStatus().then(async (status) => {
      const learnerMode =
        status?.preset === "learner" || Boolean(status?.learning_policy);
      if (!learnerMode) return;
      const profile = await getOwnLearnerProfile().catch(() => null);
      if (active) {
        setAgeMode(
          resolveReadingAgeMode({
            learnerMode,
            profileAge: profile?.age,
            policyAgeBand: status?.learning_policy?.age_band,
          }),
        );
      }
    });
    return () => {
      active = false;
    };
  }, []);

  const stopSpeaking = useCallback(() => {
    window.speechSynthesis?.cancel();
    setSpeaking(false);
  }, []);

  // A card answers a question about one document; switching documents leaves
  // it describing a page that is no longer on screen.
  useEffect(() => {
    setCards([]);
  }, [materialId]);

  // Speech stops the moment the reader leaves the passage being read, the
  // same promise the standalone toolbar makes.
  useEffect(
    () => () => {
      window.speechSynthesis?.cancel();
      setSpeaking(false);
    },
    [locator, materialId],
  );

  const actions = useMemo<ReadingActionEntry[]>(
    () =>
      extensions
        .flatMap((extension) =>
          extension.actions
            .filter(
              (action) =>
                !CHAT_ROUTED_READING_ACTIONS.has(
                  `${extension.id}:${action.id}`,
                ),
            )
            .map((action) => {
              const key = `${extension.id}:${action.id}`;
              const builtIn = builtInActionLabel(extension.id, action.id);
              return {
                key,
                extension,
                action,
                label: builtIn ? t(builtIn) : action.label,
                needsSelection: action.requires.includes("selection"),
              };
            }),
        )
        .sort((left, right) => {
          const leftRank = primaryReadingActionRank(left.key);
          const rightRank = primaryReadingActionRank(right.key);
          return (
            (leftRank < 0 ? 3 : leftRank) - (rightRank < 0 ? 3 : rightRank)
          );
        }),
    [extensions, t],
  );

  const run = useCallback<ReadingActionsValue["run"]>(
    async (entry, target = {}) => {
      if (!materialId) return;
      const selection = (target.selection || "").trim();
      const requestedLocator = target.locator ?? locator;
      const speech = entry.key === "read_aloud:read";
      const cardId = `${entry.key}-${Date.now()}`;
      const card: ReadingActionCard = {
        id: cardId,
        key: entry.key,
        label: entry.label,
        quote: selection,
        locator: requestedLocator,
        materialId,
        status: "running",
      };
      const open = (row: ReadingActionCard) => {
        onStartRef.current?.();
        setCards((current) => [...current, row].slice(-MAX_CARDS));
      };
      setBusyKey(entry.key);
      // Read-aloud has nothing to show but the header's stop button, so it
      // only gets a card when it fails — silence would read as "it worked".
      if (!speech) open(card);
      const settle = (patch: Partial<ReadingActionCard>) => {
        if (speech) {
          if (patch.status === "error") open({ ...card, ...patch });
          return;
        }
        setCards((current) =>
          current.map((row) => (row.id === cardId ? { ...row, ...patch } : row)),
        );
      };
      try {
        const next = await runReadingExtension(
          materialId,
          entry.extension.id,
          entry.action.id,
          {
            locator: requestedLocator,
            selection,
            locale: i18n.language,
          },
        );
        if (next.type === "browser_speech") {
          const text = String(next.payload.text || "");
          if (!("speechSynthesis" in window) || !text) {
            settle({
              status: "error",
              error: t("No speech voice is available in this browser."),
            });
            return;
          }
          window.speechSynthesis.cancel();
          const utterance = new SpeechSynthesisUtterance(text);
          utterance.lang = String(next.payload.locale || i18n.language);
          utterance.onend = () => setSpeaking(false);
          utterance.onerror = () => setSpeaking(false);
          window.speechSynthesis.speak(utterance);
          setSpeaking(true);
          return;
        }
        settle({ status: "done", result: next });
      } catch (error) {
        settle({
          status: "error",
          error: error instanceof Error ? error.message : String(error),
        });
      } finally {
        setBusyKey((current) => (current === entry.key ? "" : current));
      }
    },
    [i18n.language, locator, materialId, t],
  );

  const dismiss = useCallback((cardId: string) => {
    setCards((current) => current.filter((card) => card.id !== cardId));
  }, []);

  const value = useMemo<ReadingActionsValue>(
    () => ({
      ageMode,
      actions,
      cards,
      speaking,
      busyKey,
      run,
      stopSpeaking,
      dismiss,
    }),
    [actions, ageMode, busyKey, cards, dismiss, run, speaking, stopSpeaking],
  );

  return (
    <ReadingActionsContext.Provider value={value}>
      {children}
    </ReadingActionsContext.Provider>
  );
}
