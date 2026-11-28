"use client";

import type { ReactNode } from "react";
import type { MessageAttachment } from "@/features/chat/ChatStateAdapter";
import { isChatFileLink } from "@/lib/chat-file-link";
import { scopedUrl } from "@/lib/workspace-scope";

export function ChatFileLink({
  attachment,
  onOpen,
  className,
  children,
  ariaLabel,
  unavailableReference,
}: {
  attachment: MessageAttachment;
  onOpen?: (attachment: MessageAttachment) => void;
  className: string;
  children: ReactNode;
  ariaLabel?: string;
  unavailableReference?: string;
}) {
  const href = attachment.url && isChatFileLink(attachment.url)
    ? scopedUrl(attachment.url)
    : unavailableReference
      ? `#chat-file-unavailable-${encodeURIComponent(unavailableReference)}`
      : null;
  if (href && onOpen) {
    return (
      <a
        href={href}
        data-chat-file-link=""
        onClick={(event) => {
          event.preventDefault();
          onOpen(attachment);
        }}
        className={className}
        aria-label={ariaLabel}
      >
        {children}
      </a>
    );
  }
  return (
    <button
      type="button"
      onClick={onOpen ? () => onOpen(attachment) : undefined}
      className={className}
      aria-label={ariaLabel}
    >
      {children}
    </button>
  );
}
