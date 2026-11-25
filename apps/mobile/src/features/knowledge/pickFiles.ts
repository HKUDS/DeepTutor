import * as DocumentPicker from 'expo-document-picker';
import { File } from 'expo-file-system';

import type { PickedFile } from '../../services/knowledgeApi';

/**
 * System file picker.
 *
 * The OS picker is opened for every file type on purpose: the server's accepted
 * formats are decided by whichever parser engine is active, and mapping an
 * arbitrary extension to a MIME type would hide files the server would happily
 * take (and, on Android, filter by a guess). The policy is enforced after
 * picking, against the list the server itself advertises.
 *
 * `copyToCacheDirectory` makes iOS hand back a readable file URL; without it the
 * URI can point into a provider that revokes access as soon as the picker
 * closes.
 */
export async function pickDocuments(): Promise<PickedFile[]> {
  const result = await DocumentPicker.getDocumentAsync({
    multiple: true,
    copyToCacheDirectory: true,
    type: '*/*',
  });
  if (result.canceled) return [];
  return result.assets.map(asset => ({
    uri: asset.uri,
    name: asset.name,
    ...(typeof asset.size === 'number' ? { size: asset.size } : {}),
    mimeType: asset.mimeType ?? '',
  }));
}

/**
 * Delete the copy the picker made in the app's own cache once it is no longer
 * needed.
 *
 * Only `file://` URIs are touched: on Android a `content://` URI belongs to the
 * document provider, and deleting it would destroy the learner's document
 * rather than our copy of it. A failure here is not worth reporting — the cache
 * is the operating system's to reclaim anyway.
 */
export async function discardPickedCopy(uri: string): Promise<void> {
  if (!uri.startsWith('file://')) return;
  try {
    const copy = new File(uri);
    if (copy.exists) copy.delete();
  } catch {
    // Nothing to clean up, or the platform refused; neither blocks the upload.
  }
}
