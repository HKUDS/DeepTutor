"use client";
import { OutputFileActions } from "@/components/files/OutputFileActions";

interface GeneratedOutputAttachment {
  generated?: boolean
  relative_path?: string
  url?: string
}

export function supportsGeneratedOutputActions(attachment: GeneratedOutputAttachment): boolean {
  const parts = (attachment.relative_path || '').split('/')
  const directChatOutput =
    parts.length === 5 &&
    parts[0] === 'outputs' &&
    parts[1] === 'chat' &&
    parts[3].startsWith('turn_')
  return Boolean(
    attachment.generated &&
    /^\/files\/workspace-items\/ws_[0-9a-f]{32}\/wsi_[0-9a-f]{32}(?:\?[^#]*)?$/.test(
      attachment.url || ''
    ) &&
    (directChatOutput ||
      (parts.length >= 10 &&
        parts[0] === 'outputs' &&
        parts[1] === 'chat' &&
        parts[3].startsWith('turn_') &&
        parts[4] === 'exec' &&
        parts[5] === 'outputs' &&
        parts[6] === 'chat' &&
        parts[8].startsWith('turn_')))
  )
}

export function GeneratedOutputFileActions({ url }: { url: string }) {
  return <OutputFileActions key={url} url={url} kind="generated" />;
}
