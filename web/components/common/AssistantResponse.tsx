"use client";

import { Fragment, memo, useMemo } from "react";

import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import ModelThinkingCard from "@/components/common/ModelThinkingCard";
import { useReading } from "@/context/ReadingContext";
import type { StreamEvent } from "@/features/chat/model/protocol";
import { useWatching } from "@/context/WatchingContext";
import {
  hasVisibleMarkdownContent,
  repairMalformedStrongEmphasis,
  stripArtifactAnnotations,
} from "@/lib/markdown-display";
import {
  linkifyLocatorCitations,
  verifiedReadingLocators,
} from "@/lib/reading-citations";
import { linkifyMediaTimestamps } from "@/lib/reading-media-citations";
import { linkifyVideoTimestamps } from "@/lib/watching-citations";
import { parseModelThinkingSegments } from "@/lib/think-segments";
import { useSmoothStreamText } from "@/hooks/useSmoothStreamText";

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
}

function AssistantResponseImpl({
  content,
  className = "text-[16px] leading-[1.75]",
  isStreaming = false,
  readingMaterialId,
  readingMaterialRevision,
  events,
}: AssistantResponseProps) {
  const displayContent = useSmoothStreamText(content, isStreaming);
  // A locator becomes interactive only when this turn's persisted reading-tool
  // events prove it belongs to the material that was open for the turn. The
  // currently open material is used only for an extra range check; it never
  // supplies identity for a historical answer.
  const { material } = useReading();
  const watching = useWatching();
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
    if (watching.active && watching.material) {
      return linkifyVideoTimestamps(displayContent);
    }
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
    watching.active,
    watching.material,
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
      return hasVisibleMarkdownContent(segment.content);
    });
  }, [segments]);

  if (!hasRenderableSegment) return null;

  // role="article" lets screen-reader users locate each assistant turn as a
  // structured landmark. aria-live="polite" + aria-atomic="false" announces
  // streamed-in content as the user pauses, without re-reading the whole
  // bubble each token. Together this is the minimal pattern that turns a
  // silent stream into an audible one.
  return (
    <div
      role="article"
      aria-live="polite"
      aria-atomic="false"
      className={className}
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
        const repairedContent = repairMalformedStrongEmphasis(segment.content);

        if (!hasVisibleMarkdownContent(repairedContent)) {
          return <Fragment key={`text-${index}`} />;
        }

        return (
          <MarkdownRenderer
            key={`text-${index}`}
            content={repairedContent}
            variant="prose"
            className="text-[var(--foreground)]"
          />
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
