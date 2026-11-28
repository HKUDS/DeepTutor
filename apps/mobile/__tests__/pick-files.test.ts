import * as DocumentPicker from 'expo-document-picker';

import {
  discardPickedCopy,
  discardPickedCopies,
  isOwnedCacheCopy,
  pickDocuments,
} from '../src/features/knowledge/pickFiles';

jest.mock('expo-document-picker', () => ({ getDocumentAsync: jest.fn() }));
jest.mock('expo-file-system', () => {
  const removed: string[] = [];
  class FakeFile {
    exists = true;
    path: string;
    constructor(path: string) {
      this.path = path;
    }
    delete() {
      removed.push(this.path);
    }
  }
  return {
    File: FakeFile,
    Paths: { cache: { uri: 'file:///data/app/cache/' } },
    __removed: removed,
  };
});

const picker = jest.mocked(DocumentPicker.getDocumentAsync);
const removed = (
  jest.requireMock('expo-file-system') as { __removed: string[] }
).__removed;

const cacheCopy = 'file:///data/app/cache/DocumentPicker/x/report.pdf';

beforeEach(() => {
  picker.mockReset();
  removed.length = 0;
});

test('the picker asks for any format and for a readable copy on iOS', async () => {
  picker.mockResolvedValue({
    canceled: false,
    assets: [
      {
        uri: cacheCopy,
        name: 'report.pdf',
        size: 2048,
        mimeType: 'application/pdf',
        lastModified: 0,
      },
      // Android providers often report neither a size nor a type.
      { uri: 'content://downloads/scan', name: 'scan', mimeType: null },
    ],
  } as unknown as DocumentPicker.DocumentPickerResult);

  await expect(pickDocuments()).resolves.toEqual([
    {
      uri: cacheCopy,
      name: 'report.pdf',
      size: 2048,
      mimeType: 'application/pdf',
    },
    { uri: 'content://downloads/scan', name: 'scan', mimeType: '' },
  ]);
  expect(picker).toHaveBeenCalledWith({
    multiple: true,
    copyToCacheDirectory: true,
    type: '*/*',
  });
});

test('closing the picker is not an error', async () => {
  picker.mockResolvedValue({ canceled: true, assets: null });
  await expect(pickDocuments()).resolves.toEqual([]);
});

test('ownership is decided by the cache directory, not the file scheme', () => {
  expect(isOwnedCacheCopy(cacheCopy)).toBe(true);

  // The learner's own document, reachable through the same file:// scheme.
  expect(isOwnedCacheCopy('file:///data/app/files/report.pdf')).toBe(false);
  // A provider URI is not ours to delete.
  expect(isOwnedCacheCopy('content://downloads/report.pdf')).toBe(false);
  // A path that walks out of the cache is not a cache copy.
  expect(isOwnedCacheCopy('file:///data/app/cache/../files/report.pdf')).toBe(false);
  expect(isOwnedCacheCopy('file:///data/app/cache/DocumentPicker/../../files/a.pdf')).toBe(
    false,
  );
  // The cache directory itself must never be removed.
  expect(isOwnedCacheCopy('file:///data/app/cache/')).toBe(false);
  expect(isOwnedCacheCopy('')).toBe(false);
});

test('only the app’s own cached copy is deleted', async () => {
  await discardPickedCopy(cacheCopy);
  expect(removed).toEqual([cacheCopy]);

  // A content:// URI belongs to the document provider, not to the app.
  await discardPickedCopy('content://downloads/report.pdf');
  // Neither does a file:// path outside the cache.
  await discardPickedCopy('file:///data/app/files/report.pdf');
  expect(removed).toEqual([cacheCopy]);
});

test('a whole refused pick is released', async () => {
  await discardPickedCopies([
    { uri: cacheCopy, name: 'report.pdf', size: 10, mimeType: 'application/pdf' },
    {
      uri: 'file:///data/app/cache/DocumentPicker/x/other.pdf',
      name: 'other.pdf',
      size: 10,
      mimeType: 'application/pdf',
    },
    { uri: 'content://downloads/scan', name: 'scan', size: 10, mimeType: '' },
  ]);
  expect(removed).toEqual([
    cacheCopy,
    'file:///data/app/cache/DocumentPicker/x/other.pdf',
  ]);
});
