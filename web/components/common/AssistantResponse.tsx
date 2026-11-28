"use client";

import { Fragment, memo, useMemo } from "react";

import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import ModelThinkingCard from "@/components/common/ModelThinkingCard";
import { useReading } from "@/context/ReadingContext";
import { contentLang } from "@/lib/content-lang";
import type { StreamEvent } from "@/features/chat/model/protocol";
import {
  hasVisibleMarkdownContent,
  repairChineseEmphasis,
  repairMalformedStrongEmphasis,
  stripArtifactAnnotations,
} from "@/lib/markdown-display";
import {
  linkifyLocatorCitations,
  verifiedReadingLocators,
} from "@/lib/reading-citations";
import { linkifyMediaTimestamps } from "@/lib/reading-media-citations";
import { parseModelThinkingSegments } from "@/lib/think-segments";
import { useSmoothStreamText } from "@/hooks/useSmoothStreamText";
import { AnswerCard } from "@/features/chat/inline-answers/AnswerCard";
import { splitAnswerMarkers } from "@/features/chat/inline-answers/markers";

interface AssistantResponseProps {
  content: string;
  className?: string;
  /**
   * When true, the renderer drives the visible text through a rAF
   * typewriter (``useSmoothStreamText``) so the markdown grows at a
   * steady, frame-aligned pace even when the upstream LLM emits
   * uneven chunks. Pass ``false`` for completed turns and any non-
   * streaming surface — the hook short-circuits to a pass-through
   * in that case.
   */
  isStreaming?: boolean;
  readingMaterialId?: string;
  readingMaterialRevision?: number;
  events?: StreamEvent[];
  language?: string;
  /** Assistant message id, used to anchor inline answer cards and their chips. */
  messageId?: number;
}

function AssistantResponseImpl({
  content,
  className = "text-[16px] leading-[1.75]",
  isStreaming = false,
  readingMaterialId,
  readingMaterialRevision,
  events,
  language,
  messageId,
}: AssistantResponseProps) {
  const displayContent = useSmoothStreamText(content, isStreaming);
  // A locator becomes interactive only when this turn's persisted reading-tool
  // events prove it belongs to the material that was open for the turn. The
  // currently open material is used only for an extra range check; it never
  // supplies identity for a historical answer.
  const { material } = useReading();
  const verifiedLocators = useMemo(
    () =>
      verifiedReadingLocators(
        events,
        readingMaterialId,
        readingMaterialRevision,
      ),
    [events, readingMaterialId, readingMaterialRevision],
  );
  const citedContent = useMemo(() => {
    if (
      material?.unit === "segment" &&
      (!readingMaterialId || material.material_id === readingMaterialId) &&
      (!readingMaterialRevision ||
        material.revision === readingMaterialRevision)
    ) {
      return linkifyMediaTimestamps(displayContent);
    }
    return readingMaterialId && verifiedLocators.size > 0
      ? linkifyLocatorCitations(displayContent, {
          materialId: readingMaterialId,
          materialRevision: readingMaterialRevision,
          allowedLocators: verifiedLocators,
          ...(material?.material_id === readingMaterialId &&
          (!readingMaterialRevision ||
            material.revision === readingMaterialRevision)
            ? { maxLocator: material.unit_count }
            : {}),
        })
      : displayContent;
  }, [
    displayContent,
    material,
    readingMaterialId,
    readingMaterialRevision,
    verifiedLocators,
  ]);
  const segments = useMemo(
    () => parseModelThinkingSegments(stripArtifactAnnotations(citedContent)),
    [citedContent],
  );

  // Decide whether the message has anything worth rendering. We consider both
  // ordinary markdown segments and model-thinking blocks: a turn that only
  // ever produced a <think> scratchpad should still render the collapsed card
  // instead of dropping the assistant bubble entirely.
  const hasRenderableSegment = useMemo(() => {
    return segments.some((segment) => {
      if (segment.kind === "think") return segment.content.trim().length > 0;
      return splitAnswerMarkers(segment.content).some(
        (part) => part.type === "answer" || hasVisibleMarkdownContent(part.content),
      );
    });
  }, [segments]);

  if (!hasRenderableSegment) return null;

  // role="article" lets screen-reader users locate each assistant turn as a
  // structured landmark. aria-live="polite" + aria-atomic="false" announces
  // streamed-in content as the user pauses, without re-reading the whole
  // bubble each token. Together this is the minimal pattern that turns a
  // silent stream into an audible one. ``lang`` scopes the reply's language
  // to the message text so the ``:lang()`` CJK font stacks in globals.css
  // apply to chat prose without touching surrounding chrome.
  return (
    <div
      role="article"
      aria-live="polite"
      aria-atomic="false"
      className={className}
      lang={contentLang(language)}
    >
      {segments.map((segment, index) => {
        if (segment.kind === "think") {
          return (
            <ModelThinkingCard
              key={`think-${index}`}
              content={segment.content}
              closed={segment.closed}
            />
          );
        }
        const repairedContent = isStreaming
          ? repairMalformedStrongEmphasis(segment.content)
          : repairChineseEmphasis(
              repairMalformedStrongEmphasis(segment.content),
              language,
            );

        const parts = splitAnswerMarkers(repairedContent);
        if (
          !parts.some(
            (part) =>
              part.type === "answer" || hasVisibleMarkdownContent(part.content),
          )
        ) {
          return <Fragment key={`text-${index}`} />;
        }

        return (
          <Fragment key={`text-${index}`}>
            {parts.map((part, partIndex) =>
              part.type === "answer" ? (
                <AnswerCard
                  key={`answer-${index}-${partIndex}-${part.id}`}
                  messageId={messageId}
                  questionId={part.id}
                  disabled={isStreaming || messageId === undefined}
                />
              ) : hasVisibleMarkdownContent(part.content) ? (
                <MarkdownRenderer
                  key={`text-${index}-${partIndex}`}
                  content={part.content}
                  variant="prose"
                  learningTextSize={16}
                  className="text-[var(--foreground)]"
                />
              ) : null,
            )}
          </Fragment>
        );
      })}
    </div>
  );
}

// Memoize so completed messages don't re-parse markdown when an
// unrelated streaming sibling updates the parent — the streaming
// message gets a fresh ``msg.content`` per delta and re-renders
// naturally, but every other bubble keeps its previous render output.
const AssistantResponse = memo(AssistantResponseImpl);
AssistantResponse.displayName = "AssistantResponse";
export default AssistantResponse;
