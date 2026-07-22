"use client";

import { Fragment, memo, useMemo } from "react";

import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import ModelThinkingCard from "@/components/common/ModelThinkingCard";
import {
  hasVisibleMarkdownContent,
  stripArtifactAnnotations,
} from "@/lib/markdown-display";
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
}

function AssistantResponseImpl({
  content,
  className = "text-[16px] leading-[1.75]",
  isStreaming = false,
}: AssistantResponseProps) {
  const displayContent = useSmoothStreamText(content, isStreaming);
  const segments = useMemo(
    () => parseModelThinkingSegments(stripArtifactAnnotations(displayContent)),
    [displayContent],
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

        if (!hasVisibleMarkdownContent(segment.content)) {
          return <Fragment key={`text-${index}`} />;
        }

        return (
          <MarkdownRenderer
            key={`text-${index}`}
            content={segment.content}
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
