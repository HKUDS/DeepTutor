"use client";

import { useCallback, useMemo, useState } from "react";

import type { OutgoingAttachment } from "@/contracts/generated/turn-protocol";

export function filterOutgoingAttachments(
  attachments: OutgoingAttachment[],
  maximum: number,
): OutgoingAttachment[] {
  return attachments
    .filter(
      (attachment) =>
        Boolean(attachment.type.trim()) &&
        Boolean(attachment.url || attachment.base64) &&
        !attachment.filename?.toLowerCase().endsWith(".svg"),
    )
    .slice(0, Math.max(0, maximum));
}

export function useChatAttachments(maximum = 10) {
  const [attachments, setAttachments] = useState<OutgoingAttachment[]>([]);
  const payload = useMemo(
    () => filterOutgoingAttachments(attachments, maximum),
    [attachments, maximum],
  );
  const clear = useCallback(() => setAttachments([]), []);
  return { attachments, clear, payload, setAttachments };
}
