import { act, renderHook, waitFor } from '@testing-library/react-native';

import { discardPickedCopy } from '../src/features/knowledge/pickFiles';
import { useUploads } from '../src/features/knowledge/useUploads';
import { ApiError } from '../src/services/apiClient';
import type { UploadPolicy } from '../src/services/knowledgeApi';
import {
  uploadKnowledgeFiles,
  type UploadHandle,
  type UploadResult,
} from '../src/services/knowledgeUpload';

jest.mock('../src/services/knowledgeUpload', () => {
  const actual = jest.requireActual('../src/services/knowledgeUpload');
  return { ...actual, uploadKnowledgeFiles: jest.fn() };
});
jest.mock('../src/features/knowledge/pickFiles', () => ({
  discardPickedCopy: jest.fn(async () => {}),
}));

const send = jest.mocked(uploadKnowledgeFiles);
const discard = jest.mocked(discardPickedCopy);

const policy: UploadPolicy = {
  extensions: ['.pdf'],
  accept: '.pdf',
  maxFileSizeBytes: 5_000,
  allowAnyExtension: false,
};

function picked(name: string, size = 100) {
  return {
    uri: `file:///cache/${name}`,
    name,
    size,
    mimeType: 'application/pdf',
  };
}

function transfer() {
  let resolve: (value: UploadResult) => void = () => {};
  let reject: (reason: unknown) => void = () => {};
  const promise = new Promise<UploadResult>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  const abort = jest.fn(() => reject(new ApiError('aborted', 'cancelled')));
  const handle: UploadHandle = { promise, abort };
  return { handle, resolve, reject, abort };
}

function setup(options: {
  origin?: string | null;
  ref?: string | null;
  policy?: UploadPolicy | null;
  onUploaded?: () => void;
} = {}) {
  const onUploaded = options.onUploaded ?? jest.fn();
  const hook = renderHook(
    ({ origin, ref }: { origin: string | null; ref: string | null }) =>
      useUploads({
        origin,
        ref,
        policy: options.policy === undefined ? policy : options.policy,
        onUploaded,
      }),
    {
      initialProps: {
        origin: options.origin === undefined ? 'https://tutor.test' : options.origin,
        ref: options.ref === undefined ? 'user:kb:physics' : options.ref,
      },
    },
  );
  return { ...hook, onUploaded };
}

beforeEach(() => {
  send.mockReset();
  discard.mockClear();
});

test('a refused file never reaches the network and says why', async () => {
  const { result } = setup();
  await act(async () => {
    result.current.upload([picked('notes.pdf'), picked('malware.exe')]);
  });
  expect(send).toHaveBeenCalledTimes(1);
  const refused = result.current.items.find(item => item.name === 'malware.exe');
  expect(refused).toMatchObject({
    status: 'failed',
    retryable: false,
    error: 'This server does not accept .exe files.',
  });

  // A file refused before any bytes moved cannot be retried on its own.
  act(() => result.current.retry(refused!.id));
  expect(send).toHaveBeenCalledTimes(1);
});

test('files go one at a time, each with the bytes the platform reported', async () => {
  const first = transfer();
  const second = transfer();
  send.mockReturnValueOnce(first.handle).mockReturnValueOnce(second.handle);
  const { result, onUploaded } = setup();

  await act(async () => {
    result.current.upload([picked('a.pdf'), picked('b.pdf', 300)]);
  });
  // Only one request is in flight, so each row can be described honestly.
  expect(send).toHaveBeenCalledTimes(1);
  expect(send.mock.calls[0][0]).toMatchObject({
    origin: 'https://tutor.test',
    ref: 'user:kb:physics',
    files: [
      {
        uri: 'file:///cache/a.pdf',
        name: 'a.pdf',
        size: 100,
        mimeType: 'application/pdf',
      },
    ],
  });
  expect(result.current.items[0].status).toBe('uploading');
  expect(result.current.items[1].status).toBe('queued');
  expect(result.current.busy).toBe(true);

  act(() => send.mock.calls[0][0].onProgress?.(50, 100));
  expect(result.current.items[0]).toMatchObject({ loaded: 50, total: 100 });

  await act(async () => {
    first.resolve({ taskId: 't1', files: ['a.pdf'], message: '' });
    await first.handle.promise;
  });
  expect(result.current.items[0].status).toBe('done');
  // The list is re-read from the server rather than guessed at.
  expect(onUploaded).toHaveBeenCalledTimes(1);
  // The server has the bytes, so the picker's cache copy is removed.
  expect(discard).toHaveBeenCalledWith('file:///cache/a.pdf');
  expect(send).toHaveBeenCalledTimes(2);

  await act(async () => {
    second.resolve({ taskId: 't2', files: ['b.pdf'], message: '' });
    await second.handle.promise;
  });
  expect(result.current.items.map(item => item.status)).toEqual(['done', 'done']);
  expect(result.current.busy).toBe(false);
  expect(onUploaded).toHaveBeenCalledTimes(2);
});

test('a failed transfer keeps the file so it can be retried', async () => {
  const failed = transfer();
  const retried = transfer();
  send.mockReturnValueOnce(failed.handle).mockReturnValueOnce(retried.handle);
  const { result } = setup();

  await act(async () => {
    result.current.upload([picked('a.pdf')]);
  });
  await act(async () => {
    failed.reject(new ApiError('http', 'too large', 413));
  });
  expect(result.current.items[0]).toMatchObject({
    status: 'failed',
    retryable: true,
    error: 'The server rejected this file as too large.',
  });
  // The copy is kept: retrying must not need the learner to pick it again.
  expect(discard).not.toHaveBeenCalled();

  await act(async () => {
    result.current.retry(result.current.items[0].id);
  });
  expect(send).toHaveBeenCalledTimes(2);
  expect(result.current.items[0].status).toBe('uploading');
  await act(async () => {
    retried.resolve({ taskId: 't2', files: ['a.pdf'], message: '' });
    await retried.handle.promise;
  });
  expect(result.current.items[0].status).toBe('done');
  expect(discard).toHaveBeenCalledWith('file:///cache/a.pdf');
});

test('cancelling aborts this transfer and says the server keeps what it has', async () => {
  const running = transfer();
  send.mockReturnValueOnce(running.handle);
  const { result, onUploaded } = setup();

  await act(async () => {
    result.current.upload([picked('a.pdf')]);
  });
  await act(async () => {
    result.current.cancel(result.current.items[0].id);
    expect(running.abort).toHaveBeenCalledTimes(1);
  });
  expect(result.current.items[0].status).toBe('cancelled');
  expect(result.current.items[0].error).toBeNull();
  // Nothing landed, so the document list is not re-read.
  expect(onUploaded).not.toHaveBeenCalled();
  // A cancelled row cannot be retried, so its copy is removed at once.
  expect(discard).toHaveBeenCalledWith('file:///cache/a.pdf');
});

test('a queued file can be withdrawn before it starts', async () => {
  const running = transfer();
  send.mockReturnValueOnce(running.handle);
  const { result } = setup();

  await act(async () => {
    result.current.upload([picked('a.pdf'), picked('b.pdf')]);
  });
  const queued = result.current.items[1];
  await act(async () => {
    result.current.cancel(queued.id);
  });
  expect(result.current.items[1].status).toBe('cancelled');

  await act(async () => {
    running.resolve({ taskId: 't1', files: ['a.pdf'], message: '' });
    await running.handle.promise;
  });
  // The cancelled file is never picked up by the queue.
  expect(send).toHaveBeenCalledTimes(1);
});

test('a finished row can be dismissed', async () => {
  const running = transfer();
  send.mockReturnValueOnce(running.handle);
  const { result } = setup();
  await act(async () => {
    result.current.upload([picked('a.pdf')]);
  });
  await act(async () => {
    running.resolve({ taskId: 't1', files: ['a.pdf'], message: '' });
    await running.handle.promise;
  });
  act(() => result.current.dismiss(result.current.items[0].id));
  expect(result.current.items).toEqual([]);
  expect(discard).toHaveBeenCalledWith('file:///cache/a.pdf');
});

test('leaving the screen aborts the transfer in flight', async () => {
  const running = transfer();
  send.mockReturnValueOnce(running.handle);
  const { result, unmount } = setup();
  await act(async () => {
    result.current.upload([picked('a.pdf')]);
  });
  unmount();
  expect(running.abort).toHaveBeenCalledTimes(1);
});

test('a file picked before the destination is known waits for it', async () => {
  const running = transfer();
  send.mockReturnValueOnce(running.handle);
  const { result, rerender } = setup({ origin: null });

  await act(async () => {
    result.current.upload([picked('a.pdf')]);
  });
  expect(send).not.toHaveBeenCalled();
  expect(result.current.items[0].status).toBe('queued');

  rerender({ origin: 'https://tutor.test', ref: 'user:kb:physics' });
  await act(async () => {});
  expect(send).toHaveBeenCalledTimes(1);
  await act(async () => {
    running.resolve({ taskId: 't1', files: ['a.pdf'], message: '' });
    await running.handle.promise;
  });
  await waitFor(() => expect(result.current.items[0].status).toBe('done'));
});
