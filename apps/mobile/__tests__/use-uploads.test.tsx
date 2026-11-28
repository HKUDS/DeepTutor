import { act, renderHook, waitFor } from '@testing-library/react-native';

import { discardPickedCopy } from '../src/features/knowledge/pickFiles';
import {
  useUploads,
  type UploadDestination,
} from '../src/features/knowledge/useUploads';
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

const BASE: UploadDestination = {
  origin: 'https://tutor.test',
  ref: 'user:kb:physics',
  accountId: 'account-1',
};

function destination(overrides: Partial<UploadDestination> = {}): UploadDestination {
  return { ...BASE, ...overrides };
}

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

function setup(
  options: {
    destination?: UploadDestination | null;
    policy?: UploadPolicy | null;
    onUploaded?: () => void;
  } = {},
) {
  const onUploaded = options.onUploaded ?? jest.fn();
  const hook = renderHook(
    ({ destination: target }: { destination: UploadDestination | null }) =>
      useUploads({
        destination: target,
        policy: options.policy === undefined ? policy : options.policy,
        onUploaded,
      }),
    {
      initialProps: {
        destination:
          options.destination === undefined
            ? destination()
            : options.destination,
      },
    },
  );
  return { ...hook, onUploaded };
}

beforeEach(() => {
  send.mockReset();
  discard.mockClear();
});

test('a refused file never reaches the network, says why and releases its copy', async () => {
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
  // A refused file is never sent, so its cache copy has no further use.
  expect(discard).toHaveBeenCalledWith('file:///cache/malware.exe');

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

test('a refusal the server explained is shown in its own words', async () => {
  // A 409 from this backend can mean a missing embedding model, a read-only
  // base or a run that already finished. Only the server knows which.
  const failed = transfer();
  send.mockReturnValueOnce(failed.handle);
  const { result } = setup();

  await act(async () => {
    result.current.upload([picked('a.pdf')]);
  });
  const reason =
    'The bound embedding model is unavailable or changed. Check the model settings or select a model to re-index this knowledge base.';
  await act(async () => {
    failed.reject(new ApiError('http', 'refused', 409, reason));
  });
  expect(result.current.items[0]).toMatchObject({
    status: 'failed',
    retryable: true,
    error: reason,
  });
});

test('cancelling aborts this transfer and releases the copy', async () => {
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
  expect(discard).toHaveBeenCalledWith('file:///cache/a.pdf');
});

test('a queued file can be withdrawn before it starts, and its copy goes too', async () => {
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
  expect(discard).toHaveBeenCalledWith('file:///cache/b.pdf');

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

test('leaving the screen aborts the transfer and releases every copy', async () => {
  const running = transfer();
  send.mockReturnValueOnce(running.handle);
  const { result, unmount } = setup();
  await act(async () => {
    result.current.upload([picked('a.pdf'), picked('b.pdf')]);
  });
  unmount();
  expect(running.abort).toHaveBeenCalledTimes(1);
  // Both the in-flight file and the one still waiting are released; nobody can
  // retry them from a screen that no longer exists.
  expect(discard).toHaveBeenCalledWith('file:///cache/a.pdf');
  expect(discard).toHaveBeenCalledWith('file:///cache/b.pdf');
});

test('a pick that resolves after the screen closed is released, not queued', async () => {
  const { result, unmount } = setup();
  unmount();
  await act(async () => {
    result.current.upload([picked('a.pdf'), picked('b.pdf')]);
  });
  expect(send).not.toHaveBeenCalled();
  expect(discard).toHaveBeenCalledWith('file:///cache/a.pdf');
  expect(discard).toHaveBeenCalledWith('file:///cache/b.pdf');
});

test('without a destination nothing is queued and no copy is kept', async () => {
  const { result } = setup({ destination: null });
  await act(async () => {
    result.current.upload([picked('a.pdf')]);
  });
  expect(send).not.toHaveBeenCalled();
  expect(result.current.items).toHaveLength(1);
  expect(result.current.items[0]).toMatchObject({
    status: 'failed',
    retryable: false,
    error: 'This screen is not connected to a server.',
  });
  expect(discard).toHaveBeenCalledWith('file:///cache/a.pdf');
});

test('changing the base retires the queue instead of re-addressing it', async () => {
  const first = transfer();
  send.mockReturnValueOnce(first.handle);
  const { result, rerender } = setup({ destination: destination({ ref: 'kb-a' }) });

  await act(async () => {
    result.current.upload([picked('a.pdf'), picked('b.pdf')]);
  });
  expect(send).toHaveBeenCalledTimes(1);
  expect(send.mock.calls[0][0]).toMatchObject({ ref: 'kb-a' });

  rerender({ destination: destination({ ref: 'kb-b' }) });
  await act(async () => {});

  // The transfer in flight is stopped and the queued file is never started.
  expect(first.abort).toHaveBeenCalledTimes(1);
  expect(send).toHaveBeenCalledTimes(1);
  expect(result.current.items.map(item => item.status)).toEqual([
    'cancelled',
    'cancelled',
  ]);
  expect(result.current.items[0].error).toContain('destination changed');
  expect(discard).toHaveBeenCalledWith('file:///cache/a.pdf');
  expect(discard).toHaveBeenCalledWith('file:///cache/b.pdf');

  // A new pick goes to the new base and nowhere else.
  const second = transfer();
  send.mockReturnValueOnce(second.handle);
  await act(async () => {
    result.current.upload([picked('c.pdf')]);
  });
  expect(send.mock.calls[1][0]).toMatchObject({ ref: 'kb-b' });
});

test('switching account on the same base retires the queue', async () => {
  const running = transfer();
  send.mockReturnValueOnce(running.handle);
  const { result, rerender } = setup();

  await act(async () => {
    result.current.upload([picked('a.pdf')]);
  });
  rerender({ destination: destination({ accountId: 'account-2' }) });
  await act(async () => {});

  expect(running.abort).toHaveBeenCalledTimes(1);
  expect(result.current.items[0].status).toBe('cancelled');
  expect(send).toHaveBeenCalledTimes(1);
});

test('signing out retires the queue', async () => {
  const running = transfer();
  send.mockReturnValueOnce(running.handle);
  const { result, rerender } = setup();

  await act(async () => {
    result.current.upload([picked('a.pdf')]);
  });
  rerender({ destination: null });
  await act(async () => {});

  expect(running.abort).toHaveBeenCalledTimes(1);
  expect(result.current.items[0].status).toBe('cancelled');
  expect(discard).toHaveBeenCalledWith('file:///cache/a.pdf');
});

test('a failed row from another destination cannot be retried here', async () => {
  const failed = transfer();
  const other = transfer();
  send.mockReturnValueOnce(failed.handle).mockReturnValueOnce(other.handle);
  const { result, rerender } = setup();

  await act(async () => {
    result.current.upload([picked('a.pdf')]);
  });
  await act(async () => {
    failed.reject(new ApiError('network', 'offline'));
  });
  const id = result.current.items[0].id;

  rerender({ destination: destination({ origin: 'https://other.test' }) });
  await act(async () => {});
  // The retry offer is withdrawn with the destination.
  expect(result.current.items[0]).toMatchObject({
    status: 'cancelled',
    retryable: true,
  });
  await act(async () => {
    result.current.retry(id);
  });
  expect(send).toHaveBeenCalledTimes(1);
  expect(discard).toHaveBeenCalledWith('file:///cache/a.pdf');
});

test('a file picked before the destination exists is not inherited later', async () => {
  const { result, rerender } = setup({ destination: null });
  await act(async () => {
    result.current.upload([picked('a.pdf')]);
  });
  expect(send).not.toHaveBeenCalled();

  rerender({ destination: destination() });
  await act(async () => {});
  // Nothing was waiting to be sent once a server appeared.
  expect(send).not.toHaveBeenCalled();
  await waitFor(() => expect(result.current.items[0].status).toBe('failed'));
});
