/**
 * MediaRecorder reports ``audio/webm;codecs=opus``. OpenAI-compatible STT
 * endpoints treat the codec parameter as an unknown format and return 400.
 */
export function stripAudioMimeParameters(
  mimeType: string | undefined | null,
): string {
  const mediaType = (mimeType || "").split(";", 1)[0].trim();
  return mediaType || "audio/webm";
}
