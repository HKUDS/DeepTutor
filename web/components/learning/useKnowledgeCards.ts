"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useReducer } from "react";
import { fetchMediaArtifacts } from "@/lib/media-api";
import { listKnowledgeBases } from "@/lib/knowledge-api";
import {
  discardKnowledgeCard,
  editKnowledgeCard,
  ensureKnowledgeCard,
  fetchKnowledgeCards,
  publishKnowledgeCard,
  reconcileCardPublication,
  reconcileCardRetraction,
  retractKnowledgeCard,
  retryCardGeneration,
  retryPublishKnowledgeCard,
  type EditCardBody,
} from "@/lib/knowledge-card-api";
import { toContractError } from "./contract";
import { classifyKbs } from "./knowledgeCard";
import { createPathEpoch, type PathSnapshot } from "./pathGuard";
import {
  initialKnowledgeCardState,
  knowledgeCardReducer,
  type CardConfirmation,
  type KnowledgeCardAction,
  type KnowledgeCardState,
} from "./knowledgeCardReducer";

/**
 * Isomorphic commit-phase effect. Client components are also rendered on the
 * server during SSR, where ``useLayoutEffect`` is a no-op and logs a warning;
 * resolve to the passive effect there. In the browser this is the layout
 * effect, which React runs synchronously after committing the DOM and before
 * paint. Synchronizing the path epoch there means the guard is advanced before
 * any paint or user input can observe the new path — closing the gap between
 * commit and the passive-effects flush where an old path's in-flight promise
 * could still see its snapshot as current and dispatch into the new path's UI.
 */
const useCommitLayoutEffect =
  typeof window === "undefined" ? useEffect : useLayoutEffect;

/**
 * Knowledge-card review/publication state (UI-02). Loads the owner-scoped card
 * collection plus the real KB list and the current user's durable artifacts,
 * and exposes every approved mutation guarded by the server's version /
 * idempotency contract. After a mutation the authoritative persisted card is
 * reloaded (KB-03/KB-04 projections are partial; edit/retry/discard already
 * return the full reloaded card view).
 *
 * Cross-path safety (round-1): the path can change while an old path's load or
 * mutation is still awaiting the server. An epoch guard (see ``pathGuard``) is
 * advanced for the rendered path in a commit-phase layout effect — before the
 * browser paints — so it can never lag behind the committed UI into the
 * passive-effects window. Every dispatch that originates from asynchronous work
 * carries the snapshot captured when that work started. A stale snapshot — a
 * different path or an advanced epoch — drops the dispatch, so an old path's
 * cards, errors, busy keys and post-mutation refreshes can never mutate the new
 * path's state.
 */
export function useKnowledgeCards(pathId: string) {
  const [state, dispatch] = useReducer(knowledgeCardReducer, initialKnowledgeCardState);

  const pathEpoch = useMemo(() => createPathEpoch(), []);

  // Keep the epoch guard in sync with the rendered path at commit, before
  // paint. A passive effect would leave the guard on the old path until after
  // the browser paints, letting an old path's promise that resolves in that
  // window see its snapshot as current and dispatch into the new path's UI.
  // Declared before the load effect below so the initial load captures a fresh
  // snapshot.
  useCommitLayoutEffect(() => {
    pathEpoch.set(pathId);
  }, [pathId, pathEpoch]);

  const isCurrent = useCallback(
    (snapshot: PathSnapshot) => pathEpoch.isCurrent(snapshot),
    [pathEpoch],
  );

  /** Fetch the cards for a snapshot's path and dispatch only if still current. */
  const fetchCards = useCallback(
    async (captured?: PathSnapshot) => {
      const snapshot = captured ?? pathEpoch.snapshot();
      const result = await fetchKnowledgeCards(snapshot.pathId);
      if (isCurrent(snapshot)) {
        dispatch({ type: "CARDS_LOADED", cards: result.cards });
      }
      return result.cards;
    },
    [isCurrent, pathEpoch],
  );

  const refreshCards = useCallback(async () => {
    const captured = pathEpoch.snapshot();
    if (isCurrent(captured)) {
      dispatch({ type: "CARDS_LOADING" });
    }
    try {
      await fetchCards(captured);
    } catch (e: unknown) {
      if (isCurrent(captured)) {
        dispatch({ type: "CARDS_LOAD_FAILED", error: toContractError(e) });
      }
    }
  }, [isCurrent, fetchCards, pathEpoch]);

  useEffect(() => {
    if (!pathId) return;
    const captured = pathEpoch.snapshot();
    let cancelled = false;
    // Reset transient state scoped to any previous path, then start the fresh
    // load. The card collection is authoritative; the KB list and media
    // artifacts are read-only supplements that degrade to empty without failing
    // the surface (the server revalidates the KB on publish regardless).
    dispatch({ type: "RESET_FOR_PATH" });
    dispatch({ type: "CARDS_LOADING" });
    Promise.all([
      fetchKnowledgeCards(pathId),
      listKnowledgeBases({ force: true }).catch(() => []),
      fetchMediaArtifacts().catch(() => ({ artifacts: [], quota: null })),
    ])
      .then(([result, kbs, media]) => {
        if (cancelled || !isCurrent(captured)) return;
        dispatch({ type: "CARDS_LOADED", cards: result.cards });
        dispatch({ type: "KBS_LOADED", kbs: classifyKbs(kbs) });
        dispatch({ type: "ARTIFACTS_LOADED", artifacts: media.artifacts });
      })
      .catch((e: unknown) => {
        if (cancelled || !isCurrent(captured)) return;
        dispatch({ type: "CARDS_LOAD_FAILED", error: toContractError(e) });
      });
    return () => {
      cancelled = true;
    };
  }, [pathId, isCurrent, pathEpoch]);

  /**
   * Run a mutation with a guarded dispatch. ``intendedPathId`` is the path the
   * closure was created for; if a stale closure fires after the path changed we
   * reject it before it can dispatch a busy key onto the new path. Every
   * subsequent dispatch (start is synchronous and only when current; merge,
   * end, failed) is dropped once the captured snapshot goes stale.
   */
  const mutate = useCallback(
    async <T>(
      intendedPathId: string,
      key: string,
      fn: (captured: PathSnapshot, guarded: <A extends KnowledgeCardAction>(action: A) => void) => Promise<T>,
    ): Promise<T | null> => {
      const captured = pathEpoch.snapshot();
      if (intendedPathId !== captured.pathId || !isCurrent(captured)) return null;
      const guarded = <A extends KnowledgeCardAction>(action: A) => {
        if (isCurrent(captured)) dispatch(action);
      };
      dispatch({ type: "MUTATION_START", key });
      try {
        const result = await fn(captured, guarded);
        guarded({ type: "MUTATION_END", key });
        return result;
      } catch (e: unknown) {
        guarded({ type: "MUTATION_FAILED", key, error: toContractError(e) });
        return null;
      }
    },
    [isCurrent, pathEpoch],
  );

  const ensure = useCallback(
    (kpId: string) =>
      mutate(pathId, `ensure:${kpId}`, async (_captured, guarded) => {
        const card = await ensureKnowledgeCard(pathId, kpId);
        guarded({ type: "CARD_UPSERT", card });
        return card;
      }),
    [pathId, mutate],
  );

  const saveDraft = useCallback(
    (cardId: string, changes: Omit<EditCardBody, "expected_card_revision" | "request_id">) =>
      mutate(pathId, `edit:${cardId}`, async (_captured, guarded) => {
        const card = state.cards.find((c) => c.card_id === cardId);
        if (!card) throw new Error("card not loaded");
        const updated = await editKnowledgeCard(pathId, cardId, {
          ...changes,
          expected_card_revision: card.revision,
          request_id: `ui-edit-${Date.now()}`,
        });
        guarded({ type: "CARD_UPSERT", card: updated });
        return updated;
      }),
    [pathId, state.cards, mutate],
  );

  const retryGeneration = useCallback(
    (cardId: string) =>
      mutate(pathId, `retry:${cardId}`, async (_captured, guarded) => {
        const card = state.cards.find((c) => c.card_id === cardId);
        if (!card) throw new Error("card not loaded");
        const attempt = card.latest_generation_attempt;
        if (!attempt) throw new Error("no generation attempt to retry");
        const updated = await retryCardGeneration(pathId, cardId, {
          expected_card_revision: card.revision,
          request_id: `ui-retry-${Date.now()}`,
          latest_generation_attempt_id: attempt.id,
        });
        guarded({ type: "CARD_UPSERT", card: updated });
        return updated;
      }),
    [pathId, state.cards, mutate],
  );

  const discard = useCallback(
    (cardId: string) =>
      mutate(pathId, `discard:${cardId}`, async (_captured, guarded) => {
        const card = state.cards.find((c) => c.card_id === cardId);
        if (!card) throw new Error("card not loaded");
        const updated = await discardKnowledgeCard(pathId, cardId, {
          expected_card_revision: card.revision,
          request_id: `ui-discard-${Date.now()}`,
        });
        guarded({ type: "CARD_UPSERT", card: updated });
        return updated;
      }),
    [pathId, state.cards, mutate],
  );

  const publish = useCallback(
    (cardId: string, targetKbName: string) =>
      mutate(pathId, `publish:${cardId}`, async (captured, guarded) => {
        const card = state.cards.find((c) => c.card_id === cardId);
        if (!card) throw new Error("card not loaded");
        const result = await publishKnowledgeCard(pathId, cardId, {
          target_kb_name: targetKbName,
          expected_card_revision: card.revision,
          request_id: `ui-publish-${Date.now()}`,
        });
        guarded({ type: "CARD_MUTATION_MERGE", cardId, result });
        // Publication projections are partial; reload the authoritative card
        // (guarded so a path change mid-flight never overwrites the new path).
        await fetchCards(captured);
        return result;
      }),
    [pathId, state.cards, mutate, fetchCards],
  );

  const retryPublish = useCallback(
    (cardId: string) =>
      mutate(pathId, `retry-publish:${cardId}`, async (captured, guarded) => {
        const card = state.cards.find((c) => c.card_id === cardId);
        if (!card) throw new Error("card not loaded");
        const result = await retryPublishKnowledgeCard(pathId, cardId, {
          expected_card_revision: card.revision,
          request_id: `ui-retry-publish-${Date.now()}`,
        });
        guarded({ type: "CARD_MUTATION_MERGE", cardId, result });
        await fetchCards(captured);
        return result;
      }),
    [pathId, state.cards, mutate, fetchCards],
  );

  const reconcilePublication = useCallback(
    (cardId: string) =>
      mutate(pathId, `reconcile-pub:${cardId}`, async (captured, guarded) => {
        const result = await reconcileCardPublication(pathId, cardId);
        guarded({ type: "CARD_MUTATION_MERGE", cardId, result });
        await fetchCards(captured);
        return result;
      }),
    [pathId, mutate, fetchCards],
  );

  const retract = useCallback(
    (cardId: string) =>
      mutate(pathId, `retract:${cardId}`, async (captured, guarded) => {
        const card = state.cards.find((c) => c.card_id === cardId);
        if (!card) throw new Error("card not loaded");
        const result = await retractKnowledgeCard(pathId, cardId, {
          expected_card_revision: card.revision,
          request_id: `ui-retract-${Date.now()}`,
        });
        guarded({ type: "CARD_MUTATION_MERGE", cardId, result });
        await fetchCards(captured);
        return result;
      }),
    [pathId, state.cards, mutate, fetchCards],
  );

  const reconcileRetraction = useCallback(
    (cardId: string) =>
      mutate(pathId, `reconcile-retract:${cardId}`, async (captured, guarded) => {
        const result = await reconcileCardRetraction(pathId, cardId);
        guarded({ type: "CARD_MUTATION_MERGE", cardId, result });
        await fetchCards(captured);
        return result;
      }),
    [pathId, mutate, fetchCards],
  );

  const dispatchAction = useCallback((action: KnowledgeCardAction) => dispatch(action), []);

  return {
    state,
    dispatch: dispatchAction,
    refreshCards,
    ensure,
    saveDraft,
    retryGeneration,
    discard,
    publish,
    retryPublish,
    reconcilePublication,
    retract,
    reconcileRetraction,
  };
}

export type KnowledgeCardsApi = ReturnType<typeof useKnowledgeCards>;
export type { CardConfirmation, KnowledgeCardState };
