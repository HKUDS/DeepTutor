import * as DocumentPicker from 'expo-document-picker';
import { File, Paths } from 'expo-file-system';

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
 * closes. Both platforms copy into their app cache directory
 * (`cacheDir/DocumentPicker/…` on Android, `Caches/DocumentPicker/…` on iOS).
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

function cachePrefix(): string | null {
  try {
    const uri = Paths.cache.uri;
    if (!uri) return null;
    return uri.endsWith('/') ? uri : `${uri}/`;
  } catch {
    // The native module is unavailable (for example in a plain Node test
    // environment); ownership cannot be proven, so nothing is deleted.
    return null;
  }
}

/**
 * Whether a URI is a copy the picker made inside this app's cache.
 *
 * Ownership is decided by the directory the file lives in, not by the `file://`
 * scheme: any URI on the device uses that scheme, including the learner's own
 * documents and the app's private database. Only paths strictly below
 * `Paths.cache` qualify, and no path segment may be `.` or `..` — a crafted
 * URI must not be able to walk out of the cache.
 */
export function isOwnedCacheCopy(uri: string): boolean {
  if (!uri.startsWith('file://')) return false;
  const prefix = cachePrefix();
  if (!prefix) return false;
  const candidate = uri.split(/[?#]/, 1)[0];
  const base = prefix.split(/[?#]/, 1)[0];
  if (!candidate.startsWith(base)) return false;
  const relative = candidate.slice(base.length);
  // An empty remainder is the cache directory itself, never a picked file.
  if (!relative) return false;
  return relative
    .split('/')
    .every(segment => segment !== '' && segment !== '.' && segment !== '..');
}

/**
 * Delete the copy the picker made in the app's own cache once it is no longer
 * needed.
 *
 * Only copies the app provably owns are touched: on Android a `content://` URI
 * belongs to the document provider, and a `file://` URI outside the cache may
 * be the learner's original document. Deleting either would destroy their file
 * rather than our copy. A failure here is not worth reporting — the cache is
 * the operating system's to reclaim anyway.
 */
export async function discardPickedCopy(uri: string): Promise<void> {
  if (!isOwnedCacheCopy(uri)) return;
  try {
    const copy = new File(uri);
    if (copy.exists) copy.delete();
  } catch {
    // Nothing to clean up, or the platform refused; neither blocks the upload.
  }
}

/** Release every copy in a pick that will not be uploaded. */
export async function discardPickedCopies(
  files: readonly PickedFile[],
): Promise<void> {
  await Promise.all(files.map(file => discardPickedCopy(file.uri)));
}
