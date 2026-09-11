import type { AttachmentLimits } from "@/lib/attachment-limits";
import { classifyFile, isSvgFilename } from "@/lib/doc-attachments";
import {
  extractBase64FromDataUrl,
  readFileAsDataUrl,
} from "@/lib/file-attachments";

export interface PendingAttachment {
  type: string;
  filename: string;
  base64?: string;
  previewUrl?: string;
  size?: number;
  mimeType?: string;
}

export type AttachmentRejectionReason =
  | "unsupported"
  | "too_large"
  | "quota";

export interface AttachmentRejection {
  name: string;
  reason: AttachmentRejectionReason;
}

export function selectAttachmentFiles(
  files: File[],
  existingBytes: number,
  limits: AttachmentLimits,
): { accepted: File[]; rejected: AttachmentRejection[] } {
  let runningTotal = existingBytes;
  const accepted: File[] = [];
  const rejected: AttachmentRejection[] = [];

  for (const file of files) {
    if (!classifyFile(file)) {
      rejected.push({ name: file.name, reason: "unsupported" });
      continue;
    }
    if (file.size > limits.maxFileBytes) {
      rejected.push({ name: file.name, reason: "too_large" });
      continue;
    }
    if (runningTotal + file.size > limits.maxTotalBytes) {
      rejected.push({ name: file.name, reason: "quota" });
      break;
    }
    runningTotal += file.size;
    accepted.push(file);
  }

  return { accepted, rejected };
}

export async function fileToPendingAttachment(
  file: File,
): Promise<PendingAttachment> {
  const raw = await readFileAsDataUrl(file);
  const svg = isSvgFilename(file.name) || file.type === "image/svg+xml";
  const isImage = !svg && file.type.startsWith("image/");
  return {
    type: isImage ? "image" : "file",
    filename: file.name,
    base64: extractBase64FromDataUrl(raw),
    previewUrl: isImage || svg ? raw : undefined,
    size: file.size,
    mimeType: file.type || undefined,
  };
}
