import type {
  AnnotationItem,
  ReadingTextSelector,
} from "@/lib/reading-api";

export interface W3CTextAnnotation {
  "@context": "http://www.w3.org/ns/anno.jsonld";
  id: string;
  type: "Annotation";
  body: Array<{
    type: "TextualBody";
    purpose: "commenting" | "highlighting";
    value: string;
  }>;
  target: {
    source: string;
    selector: ReadingTextSelector[];
  };
}

export interface RecogitoTextAnnotation {
  id: string;
  bodies: [];
  target: {
    annotation: string;
    selector: Array<{ quote: string; start: number; end: number }>;
  };
  properties: {
    annotationId: string;
    color: string;
    kind: AnnotationItem["kind"];
  };
}

/**
 * Resolve a persisted W3C quote/position pair against the currently rendered
 * text. Position is accepted only when it still covers the quote; otherwise a
 * unique quote plus prefix/suffix context is used to re-anchor it.
 */
export function resolveTextSelectors(
  text: string,
  annotation: Pick<AnnotationItem, "quote" | "selectors">,
): ReadingTextSelector[] | null {
  const stored = annotation.selectors ?? [];
  const quoteSelector = stored.find(
    (selector) => selector.type === "TextQuoteSelector",
  );
  const positionSelector = stored.find(
    (selector) => selector.type === "TextPositionSelector",
  );
  const exact =
    quoteSelector?.type === "TextQuoteSelector"
      ? quoteSelector.exact
      : annotation.quote;
  if (!exact) return null;

  if (
    positionSelector?.type === "TextPositionSelector" &&
    positionSelector.start >= 0 &&
    positionSelector.end <= text.length &&
    text.slice(positionSelector.start, positionSelector.end) === exact
  ) {
    return [
      quoteSelector?.type === "TextQuoteSelector"
        ? quoteSelector
        : quoteAt(text, exact, positionSelector.start),
      positionSelector,
    ];
  }

  const candidates = occurrences(text, exact);
  const contextual = candidates.filter((start) => {
    if (quoteSelector?.type !== "TextQuoteSelector") return true;
    const prefixMatches =
      !quoteSelector.prefix || text.slice(0, start).endsWith(quoteSelector.prefix);
    const suffixMatches =
      !quoteSelector.suffix ||
      text.slice(start + exact.length).startsWith(quoteSelector.suffix);
    return prefixMatches && suffixMatches;
  });
  const matches = contextual.length ? contextual : candidates;
  if (matches.length !== 1) return null;
  const start = matches[0];
  return [
    quoteAt(text, exact, start),
    { type: "TextPositionSelector", start, end: start + exact.length },
  ];
}

export function toW3CTextAnnotation(
  annotation: AnnotationItem,
  renderedText: string,
  source: string,
): W3CTextAnnotation | null {
  const selector = resolveTextSelectors(renderedText, annotation);
  if (!selector) return null;
  return {
    "@context": "http://www.w3.org/ns/anno.jsonld",
    id: annotation.annotation_id,
    type: "Annotation",
    body: [
      {
        type: "TextualBody",
        purpose: annotation.note ? "commenting" : "highlighting",
        value: annotation.note,
      },
    ],
    target: { source, selector },
  };
}

export function toRecogitoTextAnnotation(
  annotation: AnnotationItem,
  renderedText: string,
): RecogitoTextAnnotation | null {
  const selectors = resolveTextSelectors(renderedText, annotation);
  const quote = selectors?.find(
    (selector) => selector.type === "TextQuoteSelector",
  );
  const position = selectors?.find(
    (selector) => selector.type === "TextPositionSelector",
  );
  if (
    quote?.type !== "TextQuoteSelector" ||
    position?.type !== "TextPositionSelector"
  ) {
    return null;
  }
  return {
    id: annotation.annotation_id,
    bodies: [],
    target: {
      annotation: annotation.annotation_id,
      selector: [
        { quote: quote.exact, start: position.start, end: position.end },
      ],
    },
    properties: {
      annotationId: annotation.annotation_id,
      color: annotation.color,
      kind: annotation.kind,
    },
  };
}

function quoteAt(text: string, exact: string, start: number): ReadingTextSelector {
  return {
    type: "TextQuoteSelector",
    exact,
    prefix: text.slice(Math.max(0, start - 10), start),
    suffix: text.slice(start + exact.length, start + exact.length + 10),
  };
}

function occurrences(text: string, quote: string): number[] {
  const found: number[] = [];
  let start = 0;
  while (start <= text.length - quote.length) {
    const match = text.indexOf(quote, start);
    if (match < 0) break;
    found.push(match);
    start = match + Math.max(1, quote.length);
  }
  return found;
}
