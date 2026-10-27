"use client";

import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { consumePendingPrompt } from "@/lib/pending-prompt";
import {
  MASTERY_OPENING_SCOPE,
  masteryOpeningMessage,
  type MasteryMode,
} from "@/lib/mastery-mode";

/** Keep the opening pending until the route's session can accept a turn. */
export function useMasteryOpening({
  pathId,
  topicReady,
  hasMessages,
  hasOutline,
  sessionLoading,
  sessionError,
  sessionMode,
  isStreaming,
  submit,
}: {
  pathId: string;
  topicReady: boolean;
  hasMessages: boolean;
  /** An outline already exists, so the outline sitting is an edit, not a draft. */
  hasOutline: boolean;
  sessionLoading: boolean;
  sessionError: string | null;
  sessionMode: MasteryMode;
  isStreaming: boolean;
  submit: (content: string) => boolean;
}) {
  const { t } = useTranslation();
  const openingSentRef = useRef("");
  useEffect(() => {
    if (!topicReady || hasMessages || sessionLoading || sessionError)
      return;
    if (isStreaming || openingSentRef.current === pathId) return;
    const pending = consumePendingPrompt(MASTERY_OPENING_SCOPE).trim();
    // A review conversation opened from the outline stays empty. The review
    // plan and the topic-page button leave a pending prompt when they want
    // one spoken. Outline drafts still open themselves.
    //
    // An outline that already exists is the one exception among outlines.
    // "Design the outline with me" is a request to build one, and sending it
    // over a map the learner has been studying invites a rebuild they did not
    // ask for; 修改大纲 means *edit this, keep the rest*. Nothing needs to be
    // said for that: the tutor reads `mastery_status`, sees an active outline,
    // and the screen offers the edits to pick from.
    const opening =
      pending ||
      (sessionMode === "review" || (sessionMode === "outline" && hasOutline)
        ? ""
        : masteryOpeningMessage(sessionMode, t));
    if (opening && submit(opening)) openingSentRef.current = pathId;
  }, [
    hasMessages,
    hasOutline,
    pathId,
    sessionError,
    sessionLoading,
    sessionMode,
    isStreaming,
    submit,
    t,
    topicReady,
  ]);
}
