import * as DocumentPicker from 'expo-document-picker';

import {
  discardPickedCopy,
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
  return { File: FakeFile, __removed: removed };
});

const picker = jest.mocked(DocumentPicker.getDocumentAsync);
const removed = (
  jest.requireMock('expo-file-system') as { __removed: string[] }
).__removed;

beforeEach(() => {
  picker.mockReset();
  removed.length = 0;
});

test('the picker asks for any format and for a readable copy on iOS', async () => {
  picker.mockResolvedValue({
    canceled: false,
    assets: [
      {
        uri: 'file:///cache/report.pdf',
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
      uri: 'file:///cache/report.pdf',
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

test('only the app’s own cached copy is deleted', async () => {
  await discardPickedCopy('file:///cache/report.pdf');
  expect(removed).toEqual(['file:///cache/report.pdf']);

  // A content:// URI belongs to the document provider, not to the app.
  await discardPickedCopy('content://downloads/report.pdf');
  expect(removed).toEqual(['file:///cache/report.pdf']);
});
