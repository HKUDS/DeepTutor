"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useReading } from "@/context/ReadingContext";
import { useChatStateAdapter } from "@/features/chat/ChatStateAdapter";
import { courseSessionConfiguration } from "@/lib/course-session-scope";
import {
  addBookmark,
  deleteBookmark,
  getMaterial,
  getReadingTranscript,
  listBookmarks,
  type ReadingBookmark,
} from "@/lib/reading-api";
import {
  READER_ACTION_EVENT,
  type ReaderActionPayload,
} from "@/lib/reading-reader-action";
import { setReadingWorkspace } from "@/lib/reading-turn-state";
import { READING_WORKSPACE_MODE } from "@/lib/workspace-mode";
import {
  activateReadingMaterial,
  deleteReadingConversation,
  generateMasteryPathFromReading,
  getReadingWorkspace,
  listReadingConversations,
  organizeReadingNotes,
  renameReadingConversation,
  removeReadingWorkspaceMaterial,
  updateReadingWorkspace,
  type OrganizedReadingNotes,
  type ReadingConversation,
  type ReadingLibraryMaterial,
  type ReadingWorkspace,
} from "@/lib/reading-workspace-api";
import type { TranscriptRow } from "./types";

/**
 * Everything the reading workspace needs from the network, in one place.
 *
 * The page component owns only what the reader touches directly — selection,
 * composer text, which panels are open. Hydration, polling, conversation
 * bootstrapping and the source lifecycle live here so the view stays readable
 * and each effect has one obvious owner.
 */
/** Stable empty list, so a material with no bookmarks is not a new array
 *  identity on every render. */
const NO_BOOKMARKS: ReadingBookmark[] = [];

export function useReadingWorkspace(
  workspaceId: string,
  sessionIdParam: string | null,
  courseId = "",
) {
  const router = useRouter();
  const { t } = useTranslation();
  const { material, annotations, openMaterial, closeMaterial, reportViewport } =
    useReading();
  const {
    state,
    configureSession,
    loadSession,
    newSession,
    cancelStreamingTurn,
  } = useChatStateAdapter();

  const [workspace, setWorkspace] = useState<ReadingWorkspace | null>(null);
  const [conversations, setConversations] = useState<ReadingConversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [activeLocator, setActiveLocator] = useState(1);
  const [transcript, setTranscript] = useState<TranscriptRow[]>([]);
  const [organizedNotes, setOrganizedNotes] =
    useState<OrganizedReadingNotes | null>(null);
  const sessionBootRef = useRef("");
  const transcriptRequestRef = useRef(0);

  const refresh = useCallback(async () => {
    const result = await getReadingWorkspace(workspaceId);
    const sessionRows = await listReadingConversations(workspaceId);
    setWorkspace(result.workspace);
    setConversations(sessionRows);
    return { workspace: result.workspace, sessions: sessionRows };
  }, [workspaceId]);

  useEffect(() => {
    let cancelled = false;
    // The async refresh owns the initial network hydration for this route.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh()
      .catch((caught) => {
        if (!cancelled)
          setError(
            caught instanceof Error
              ? caught.message
              : t("This collection could not be opened."),
          );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [refresh, t]);

  useEffect(() => {
    setReadingWorkspace(workspaceId);
    return () => {
      setReadingWorkspace(null);
      closeMaterial();
    };
  }, [closeMaterial, workspaceId]);

  const sessionConfiguration = useMemo(
    () => ({ workspaceMode: READING_WORKSPACE_MODE }),
    [],
  );

  const activeTab = useMemo(
    () =>
      workspace?.tabs.find(
        (tab) => tab.material.material_id === workspace.active_material_id,
      ) ??
      workspace?.tabs[0] ??
      null,
    [workspace],
  );

  useEffect(() => {
    const active = activeTab?.material;
    if (!active || active.status !== "ready") {
      closeMaterial();
      return;
    }
    let cancelled = false;
    void getMaterial(active.material_id)
      .then((detail) => {
        if (!cancelled) return openMaterial(detail);
      })
      .catch((caught) => {
        if (!cancelled)
          setError(
            caught instanceof Error ? caught.message : t("Open failed."),
          );
      });
    return () => {
      cancelled = true;
    };
  }, [activeTab?.material, closeMaterial, openMaterial, t]);

  // Poll while anything is still being processed, backing off as the wait
  // grows. A flat 2.5s forever means a source wedged in "processing" quietly
  // hammers the API for as long as the tab stays open.
  useEffect(() => {
    if (
      !workspace?.tabs.some(
        (tab) =>
          tab.material.status === "processing" ||
          tab.material.status === "queued",
      )
    )
      return;
    let attempt = 0;
    let timer = 0;
    const tick = () => {
      attempt += 1;
      void refresh().finally(() => {
        timer = window.setTimeout(
          tick,
          Math.min(2500 * 2 ** Math.floor(attempt / 4), 30_000),
        );
      });
    };
    timer = window.setTimeout(tick, 2500);
    return () => window.clearTimeout(timer);
  }, [refresh, workspace]);

  useEffect(() => {
    if (!workspace || loading) return;
    const bootKey = `${workspaceId}:${sessionIdParam ?? "new"}:${courseId.trim()}`;
    if (sessionBootRef.current === bootKey) return;
    sessionBootRef.current = bootKey;

    // The URL catching up with the session the first turn just created is not
    // a request to open a different conversation — the transcript on screen
    // already IS that conversation. Reloading it here would swap a streaming
    // answer for whatever partial row the backend has written so far.
    if (sessionIdParam && sessionIdParam === state.sessionId) return;

    void (async () => {
      try {
        // The URL is the truth about which conversation is open, the same
        // rule /chat follows: `/reading/<ws>/sessions/<id>` opens that conversation,
        // `/reading/<ws>` is a *new* one. This used to reopen the most recent
        // conversation instead, so arriving from the library — which links to
        // the bare collection URL — dropped the reader into an old transcript
        // they had not asked for.
        //
        // A conversation with nothing in it is a local draft, never a row:
        // the backend attaches the session to this workspace when the first
        // turn runs (see `turn_runtime`), so opening a collection and walking
        // away no longer litters it with empty conversations.
        const scopedSessionConfiguration = courseSessionConfiguration(
          sessionConfiguration,
          courseId,
        );
        if (sessionIdParam) {
          await loadSession(sessionIdParam);
          configureSession(scopedSessionConfiguration, sessionIdParam);
        } else {
          newSession({ ...scopedSessionConfiguration, capability: null });
        }
      } catch (caught) {
        setError(
          caught instanceof Error
            ? caught.message
            : t("The reading conversation could not be loaded."),
        );
      }
    })();
  }, [
    configureSession,
    courseId,
    loadSession,
    loading,
    newSession,
    sessionIdParam,
    sessionConfiguration,
    state.sessionId,
    t,
    workspace,
    workspaceId,
  ]);

  useEffect(() => {
    if (!material || material.unit !== "segment") return;
    const requestId = ++transcriptRequestRef.current;
    // One request for the whole transcript. Segments follow the speaker's
    // sentences, so a lecture has hundreds of them and fetching each on its own
    // meant hundreds of round trips before the panel could draw anything.
    void getReadingTranscript(material.material_id)
      .then((payload) => {
        if (transcriptRequestRef.current !== requestId) return;
        const rows: TranscriptRow[] = payload.segments
          .filter(
            (row) => row.text !== "[Transcript unavailable for this video.]",
          )
          .map((row) => ({
            locator: row.locator,
            title: row.title || `${row.locator}`,
            text: row.text,
            sourceHref: row.source_href,
          }));
        setTranscript(rows);
      })
      .catch(() => {
        if (transcriptRequestRef.current !== requestId) return;
        setTranscript([]);
        setNotice(t("This transcript could not be loaded."));
      });
  }, [material, t]);

  const activeConversation = useMemo(
    () =>
      conversations.find((row) => row.session_id === state.sessionId) ??
      conversations.find((row) => row.session_id === sessionIdParam) ??
      null,
    [conversations, sessionIdParam, state.sessionId],
  );

  const linkedSessionIds = useMemo(
    () => activeConversation?.linked_session_ids ?? [],
    [activeConversation],
  );

  /* ── Bookmarks ────────────────────────────────────────────────────────
     Kept here rather than inside the reader because two surfaces read them:
     the reader's own toolbar (is *this* page kept?) and the outline panel
     (the list, and jumping to one). Two copies would drift the moment either
     one added a bookmark. */
  const materialId = material?.material_id ?? "";
  const [loadedBookmarks, setLoadedBookmarks] = useState<{
    materialId: string;
    rows: ReadingBookmark[];
  }>({ materialId: "", rows: [] });
  // Derived rather than stored: switching material has to drop the previous
  // one's bookmarks in the same render it switches, and an effect that called
  // setState to clear them would both show the wrong list for a frame and
  // trip the compiler's set-state-in-effect rule.
  const bookmarks =
    loadedBookmarks.materialId === materialId
      ? loadedBookmarks.rows
      : NO_BOOKMARKS;

  useEffect(() => {
    if (!materialId) return;
    let cancelled = false;
    void listBookmarks(materialId)
      .then((rows) => {
        if (!cancelled) setLoadedBookmarks({ materialId, rows });
      })
      .catch(() => {
        if (!cancelled) setLoadedBookmarks({ materialId, rows: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [materialId]);

  // One control, both directions: the toolbar button reads "is this page
  // kept?" off the same list it writes to, so pressing it again removes what
  // the last press added.
  const toggleBookmark = useCallback(
    async (locator: number, label = "") => {
      if (!materialId) return;
      const existing = bookmarks.find((row) => row.locator === locator);
      try {
        if (existing) {
          await deleteBookmark(materialId, existing.bookmark_id);
        } else {
          await addBookmark(materialId, locator, label);
        }
        setLoadedBookmarks({
          materialId,
          rows: await listBookmarks(materialId),
        });
      } catch (caught) {
        setNotice(
          caught instanceof Error
            ? caught.message
            : t("That bookmark could not be saved."),
        );
      }
    },
    [bookmarks, materialId, t],
  );

  const removeBookmark = useCallback(
    async (bookmarkId: string) => {
      if (!materialId) return;
      try {
        await deleteBookmark(materialId, bookmarkId);
        setLoadedBookmarks({
          materialId,
          rows: await listBookmarks(materialId),
        });
      } catch (caught) {
        setNotice(
          caught instanceof Error
            ? caught.message
            : t("That bookmark could not be removed."),
        );
      }
    },
    [materialId, t],
  );

  const switchMaterial = useCallback(
    async (candidate: ReadingLibraryMaterial) => {
      if (!workspace || candidate.material_id === workspace.active_material_id)
        return;
      try {
        const updated = await activateReadingMaterial(
          workspace.workspace_id,
          candidate.material_id,
        );
        setWorkspace(updated);
        setActiveLocator(1);
        reportViewport({ locator: 1, selection: "" });
      } catch (caught) {
        // Without this the tab click is a no-op with no explanation, which is
        // indistinguishable from the click not registering at all.
        setNotice(
          caught instanceof Error
            ? caught.message
            : t("This material could not be opened."),
        );
      }
    },
    [reportViewport, t, workspace],
  );

  useEffect(() => {
    const onReaderAction = (event: Event) => {
      const detail = (event as CustomEvent<ReaderActionPayload>).detail;
      if (detail?.reader_action !== "switch_tab" || !detail.material_id) return;
      const candidate = workspace?.tabs.find(
        (tab) => tab.material.material_id === detail.material_id,
      )?.material;
      if (candidate) void switchMaterial(candidate);
    };
    window.addEventListener(READER_ACTION_EVENT, onReaderAction);
    return () =>
      window.removeEventListener(READER_ACTION_EVENT, onReaderAction);
  }, [switchMaterial, workspace?.tabs]);

  const removeMaterial = useCallback(
    async (candidate: ReadingLibraryMaterial) => {
      if (!workspace) return;
      setWorkspace(
        await removeReadingWorkspaceMaterial(
          workspace.workspace_id,
          candidate.material_id,
        ),
      );
    },
    [workspace],
  );

  // The same gesture /chat's "new chat" makes: reset to a local draft and
  // navigate to the URL that *means* "new". No row is written until the
  // learner actually says something, and the title is then the one the model
  // writes from that first turn rather than a placeholder every conversation
  // shares.
  //
  // Deliberately does not cancel the streaming turn. It used to, copying
  // /chat — and copying its bug: the turn being cancelled belongs to the
  // conversation being navigated *away* from, so starting a new one killed
  // the previous answer mid-flight.
  const newConversation = useCallback(() => {
    if (!workspace) return;
    newSession({ ...sessionConfiguration, capability: null });
    router.push(`/reading/${workspace.workspace_id}`);
  }, [
    newSession,
    router,
    sessionConfiguration,
    workspace,
  ]);

  // When the first turn assigns a session id, put it in the URL and let the
  // conversation menu see the row the backend just attached. Without it a
  // draft conversation would stay on the bare collection URL and a refresh
  // would silently start over.
  //
  // The URL is written with the native history API rather than `router.replace`
  // on purpose. `/reading/<ws>` and `/reading/<ws>/sessions/<id>` are different
  // route matches, and App Router treats moving between them — even within one
  // catch-all segment, which was tried — as a navigation: it unmounted the
  // whole workspace and mounted it again mid-answer. Measured, that meant the
  // reader's subtree left the DOM, "Opening collection…" painted for a frame,
  // the material was re-fetched and the page the learner was on reset to 1.
  // Asking the first question of a conversation blinked the entire screen.
  //
  // Nothing about that navigation was real: the learner stayed exactly where
  // they were and the conversation they are watching stream is the one being
  // named. So the address bar is corrected in place and `usePathname` — which
  // does follow the native API — keeps `sessionIdParam` honest for refreshes,
  // links and the back button.
  useEffect(() => {
    if (!state.sessionId || sessionIdParam) return;
    window.history.replaceState(
      null,
      "",
      `/reading/${encodeURIComponent(workspaceId)}/sessions/${encodeURIComponent(state.sessionId)}`,
    );
    void listReadingConversations(workspaceId)
      .then(setConversations)
      .catch(() => {});
  }, [sessionIdParam, state.sessionId, workspaceId]);

  const renameConversation = useCallback(
    async (sessionId: string, title: string) => {
      await renameReadingConversation(workspaceId, sessionId, title);
      setConversations(await listReadingConversations(workspaceId));
    },
    [workspaceId],
  );

  // Mirrors /chat's delete: drop the row, and if it was the conversation on
  // screen, fall back to a fresh draft rather than leaving the reader looking
  // at a transcript that no longer exists.
  const deleteConversation = useCallback(
    async (sessionId: string) => {
      await deleteReadingConversation(workspaceId, sessionId);
      setConversations(await listReadingConversations(workspaceId));
      if (sessionId === sessionIdParam) {
        cancelStreamingTurn();
        newSession({ ...sessionConfiguration, capability: null });
        router.push(`/reading/${workspaceId}`);
      }
    },
    [
      cancelStreamingTurn,
      newSession,
      router,
      sessionConfiguration,
      sessionIdParam,
      workspaceId,
    ],
  );

  const openConversation = useCallback(
    async (sessionId: string) => {
      router.push(`/reading/${workspaceId}/sessions/${sessionId}`);
      await loadSession(sessionId);
      configureSession(sessionConfiguration, sessionId);
    },
    [configureSession, loadSession, router, sessionConfiguration, workspaceId],
  );

  const organizeNotes = useCallback(async () => {
    if (!workspace) return;
    try {
      setNotice(t("Organizing notes…"));
      const notes = await organizeReadingNotes(workspace.workspace_id);
      setOrganizedNotes(notes);
      setNotice(t("Notes organized, each one citing where it came from."));
    } catch (caught) {
      setNotice(
        caught instanceof Error
          ? caught.message
          : t("Could not organize notes."),
      );
    }
  }, [t, workspace]);

  const buildMasteryPath = useCallback(
    async (bookId: string) => {
      if (!workspace) return;
      try {
        setNotice(t("Building Mastery Path…"));
        await generateMasteryPathFromReading(
          workspace.workspace_id,
          bookId.trim(),
        );
        setNotice(t("Mastery Path created. Open Learning Space to begin."));
      } catch (caught) {
        setNotice(
          caught instanceof Error
            ? caught.message
            : t("Mastery Path creation failed."),
        );
        throw caught;
      }
    },
    [t, workspace],
  );

  const renameWorkspace = useCallback(
    async (title: string) => {
      if (!workspace) return;
      if (!title?.trim() || title.trim() === workspace.title) return;
      setWorkspace(
        await updateReadingWorkspace(workspace.workspace_id, {
          title: title.trim(),
        }),
      );
    },
    [workspace],
  );

  return {
    workspace,
    setWorkspace,
    conversations,
    setConversations,
    loading,
    error,
    notice,
    setNotice,
    material,
    annotations,
    activeTab,
    activeConversation,
    linkedSessionIds,
    activeLocator,
    setActiveLocator,
    bookmarks,
    toggleBookmark,
    removeBookmark,
    transcript,
    organizedNotes,
    setOrganizedNotes,
    refresh,
    switchMaterial,
    removeMaterial,
    newConversation,
    openConversation,
    renameConversation,
    deleteConversation,
    organizeNotes,
    buildMasteryPath,
    renameWorkspace,
    reportViewport,
  };
}
