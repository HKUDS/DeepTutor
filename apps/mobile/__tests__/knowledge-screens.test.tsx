import { Alert } from 'react-native';
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react-native';

import { KnowledgeDetailScreen } from '../src/screens/knowledge/KnowledgeDetailScreen';
import { KnowledgeListScreen } from '../src/screens/knowledge/KnowledgeListScreen';
import { KnowledgePicker } from '../src/screens/knowledge/KnowledgePicker';
import type { UploadItem } from '../src/features/knowledge/useUploads';
import type {
  KnowledgeBaseSummary,
  KnowledgeFileEntry,
  KnowledgeProgress,
} from '../src/services/knowledgeApi';

afterEach(() => {
  cleanup();
  jest.restoreAllMocks();
});

function button(label: string) {
  const match = screen.getAllByRole('button').find(node => node.props.accessibilityLabel === label);
  if (!match) throw new Error(`No button labelled "${label}"`);
  return match;
}

function base(overrides: Partial<KnowledgeBaseSummary> = {}): KnowledgeBaseSummary {
  return {
    ref: 'user:kb:physics',
    id: 'user:kb:physics',
    name: 'physics',
    description: 'Mechanics',
    status: 'ready',
    isDefault: false,
    documentCount: 2,
    imageCount: 0,
    chunkCount: 0,
    ragInitialized: true,
    needsReindex: false,
    provider: 'llamaindex',
    assigned: false,
    readOnly: false,
    available: true,
    progress: null,
    lastError: '',
    updatedAt: '',
    ...overrides,
  };
}

function file(name: string, overrides: Partial<KnowledgeFileEntry> = {}): KnowledgeFileEntry {
  return {
    name,
    type: 'file',
    size: 1024,
    modified: 1_700_000_000,
    mimeType: 'application/pdf',
    ...overrides,
  };
}

function progress(overrides: Partial<KnowledgeProgress> = {}): KnowledgeProgress {
  return {
    stage: 'processing_file',
    message: 'Parsing',
    current: 1,
    total: 2,
    percent: 50,
    fileName: 'a.pdf',
    error: '',
    retryable: true,
    updatedAt: '',
    ...overrides,
  };
}

function list(overrides: Partial<React.ComponentProps<typeof KnowledgeListScreen>> = {}) {
  return render(
    <KnowledgeListScreen
      bases={[]}
      status="ready"
      refreshing={false}
      error={null}
      creating={false}
      onCreate={jest.fn(async () => null)}
      onOpen={jest.fn()}
      onRefresh={jest.fn()}
      onRetry={jest.fn()}
      onBack={jest.fn()}
      {...overrides}
    />,
  );
}

test('the list says it is loading rather than showing an empty catalogue', () => {
  list({ status: 'loading' });
  expect(screen.getByText('Loading knowledge bases…')).toBeTruthy();
});

test('an empty catalogue invites the first base instead of looking broken', () => {
  list();
  expect(screen.getByText('No knowledge bases yet')).toBeTruthy();
});

test('a failed first load offers a retry and keeps the reason', () => {
  const onRetry = jest.fn();
  list({
    status: 'failed',
    error: 'Could not reach the server. Check your connection.',
    onRetry,
  });
  expect(
    screen.getByText('Could not reach the server. Check your connection.'),
  ).toBeTruthy();
  fireEvent.press(button('Try again'));
  expect(onRetry).toHaveBeenCalledTimes(1);
});

test('a row says how much is in the base and whether it is shared or read-only', () => {
  list({
    bases: [
      base(),
      base({
        ref: 'admin:kb:shared',
        id: 'admin:kb:shared',
        name: 'shared',
        assigned: true,
        readOnly: true,
        documentCount: 1,
      }),
    ],
  });
  expect(screen.getByText('2 documents')).toBeTruthy();
  expect(screen.getByText('1 document · shared with you · read-only')).toBeTruthy();
});

test('opening a row passes the handle the server routes on', () => {
  const onOpen = jest.fn();
  list({ bases: [base({ ref: 'admin:kb:shared', name: 'shared', assigned: true })], onOpen });
  fireEvent.press(button('shared'));
  expect(onOpen).toHaveBeenCalledWith('admin:kb:shared');
});

test('creating a base needs a name and keeps the sheet open when refused', async () => {
  const onCreate = jest.fn(async () => 'This knowledge base already exists.');
  list({ onCreate });

  fireEvent.press(button('New'));
  expect(button('Create').props.accessibilityState.disabled).toBe(true);

  fireEvent.changeText(screen.getByLabelText('Name'), '  biology  ');
  await act(async () => {
    fireEvent.press(button('Create'));
  });
  expect(onCreate).toHaveBeenCalledWith('biology');
  // The name is kept so it can be corrected rather than retyped.
  expect(screen.getByText('This knowledge base already exists.')).toBeTruthy();
  expect(screen.getByLabelText('Name')).toBeTruthy();
});

test('a created base closes the sheet', async () => {
  const onCreate = jest.fn(async () => null);
  list({ onCreate });

  fireEvent.press(button('New'));
  fireEvent.changeText(screen.getByLabelText('Name'), 'biology');
  await act(async () => {
    fireEvent.press(button('Create'));
  });
  expect(onCreate).toHaveBeenCalledWith('biology');
  expect(screen.queryByLabelText('Name')).toBeNull();
});

function detail(
  overrides: Partial<React.ComponentProps<typeof KnowledgeDetailScreen>> = {},
) {
  const uploads = {
    items: [] as UploadItem[],
    cancel: jest.fn(),
    retry: jest.fn(),
    dismiss: jest.fn(),
  };
  const props: React.ComponentProps<typeof KnowledgeDetailScreen> = {
    kb: base(),
    files: [file('a.pdf')],
    status: 'ready',
    error: null,
    refreshing: false,
    retrying: false,
    saving: false,
    policy: {
      extensions: ['.pdf'],
      accept: '.pdf',
      maxFileSizeBytes: 1024 * 1024,
      allowAnyExtension: false,
    },
    uploads,
    onBack: jest.fn(),
    onRefresh: jest.fn(),
    onRetry: jest.fn(),
    onPickFiles: jest.fn(),
    onDeleteFile: jest.fn(async () => true),
    onSaveDescription: jest.fn(async () => true),
    onDeleteBase: jest.fn(),
    ...overrides,
  };
  render(<KnowledgeDetailScreen {...props} />);
  // The caller's overrides are what the screen actually received.
  return { props, uploads: props.uploads };
}

test('the detail header names the base and what it holds', () => {
  detail();
  expect(screen.getByText('physics')).toBeTruthy();
  expect(screen.getByText('2 documents · llamaindex')).toBeTruthy();
  expect(screen.getByText('a.pdf')).toBeTruthy();
});

test('removing a document asks first and warns that vectors remain', async () => {
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
  const onDeleteFile = jest.fn(async () => true);
  detail({ onDeleteFile });

  fireEvent.press(screen.getByLabelText('Remove a.pdf'));
  expect(alert).toHaveBeenCalledTimes(1);
  const [title, message, actions] = alert.mock.calls[0];
  expect(title).toBe('Remove this document?');
  expect(message).toContain('vectors are not pruned');
  expect(onDeleteFile).not.toHaveBeenCalled();

  const confirm = actions?.find(action => action.text === 'Remove');
  confirm?.onPress?.();
  await waitFor(() => expect(onDeleteFile).toHaveBeenCalledWith('a.pdf'));
});

test('deleting the base asks first and then leaves it to the caller', () => {
  const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
  const onDeleteBase = jest.fn();
  detail({ onDeleteBase });
  fireEvent.press(button('Delete'));
  expect(alert.mock.calls[0][0]).toBe('Delete this knowledge base?');
  alert.mock.calls[0][2]?.find(action => action.text === 'Delete')?.onPress?.();
  expect(onDeleteBase).toHaveBeenCalledTimes(1);
});

test('a read-only base hides every write action and says why', () => {
  detail({
    kb: base({ readOnly: true, assigned: true }),
    policy: null,
  });
  expect(screen.queryByText('Upload files')).toBeNull();
  expect(screen.queryByText('Delete')).toBeNull();
  expect(screen.queryByText('Edit description')).toBeNull();
  expect(screen.getByText('This base is read-only for your account.')).toBeTruthy();
});

test('a failed run shows the parser’s reason and offers a retry', () => {
  const onRetry = jest.fn();
  detail({
    kb: base({
      status: 'error',
      progress: progress({ stage: 'error', error: 'No text layer in this PDF' }),
    }),
    files: [file('scan.pdf')],
    onRetry,
  });
  expect(screen.getByText('No text layer in this PDF')).toBeTruthy();
  fireEvent.press(button('Retry processing'));
  expect(onRetry).toHaveBeenCalledTimes(1);
});

test('a live run shows the server’s own percentage and file', () => {
  detail({
    kb: base({ status: 'processing', progress: progress() }),
  });
  const bar = screen.getByRole('progressbar');
  expect(bar.props.accessibilityValue).toEqual({ min: 0, max: 100, now: 50 });
  expect(screen.getByText('1 of 2 · a.pdf')).toBeTruthy();
});

test('an index older than its documents says so instead of claiming work', () => {
  detail({ kb: base({ status: 'needs_reindex' }) });
  expect(
    screen.getByText(
      'The index is older than its documents. Rebuild it from the web app to cite them.',
    ),
  ).toBeTruthy();
});

test('upload rows describe their own progress, cancel and retry', async () => {
  const items: UploadItem[] = [
    {
      id: 'u1',
      name: 'big.pdf',
      size: 200,
      status: 'uploading',
      loaded: 50,
      total: 200,
      error: null,
      retryable: true,
      uri: 'file:///big.pdf',
      mimeType: 'application/pdf',
    },
    {
      id: 'u2',
      name: 'bad.pdf',
      size: 10,
      status: 'failed',
      loaded: 0,
      total: 10,
      error: 'The server rejected this file as too large.',
      retryable: true,
      uri: 'file:///bad.pdf',
      mimeType: 'application/pdf',
    },
    {
      id: 'u3',
      name: 'done.pdf',
      size: 10,
      status: 'done',
      loaded: 10,
      total: 10,
      error: null,
      retryable: true,
      uri: 'file:///done.pdf',
      mimeType: 'application/pdf',
    },
  ];
  const { uploads } = detail({ uploads: { items, cancel: jest.fn(), retry: jest.fn(), dismiss: jest.fn() } });

  expect(screen.getByText('25% · 50 B of 200 B')).toBeTruthy();
  expect(screen.getByText('The server rejected this file as too large.')).toBeTruthy();
  expect(screen.getByText('Uploaded. The server is processing it.')).toBeTruthy();

  fireEvent.press(button('Cancel big.pdf'));
  expect(uploads.cancel).toHaveBeenCalledWith('u1');
  fireEvent.press(button('Retry bad.pdf'));
  expect(uploads.retry).toHaveBeenCalledWith('u2');
  fireEvent.press(button('Dismiss done.pdf'));
  expect(uploads.dismiss).toHaveBeenCalledWith('u3');
});

test('the description is edited in a sheet and saved to the server', async () => {
  const onSaveDescription = jest.fn(async () => true);
  detail({ onSaveDescription });
  fireEvent.press(button('Edit description'));
  fireEvent.changeText(screen.getByLabelText('Description'), '  Waves  ');
  fireEvent.press(button('Save'));
  await waitFor(() => expect(onSaveDescription).toHaveBeenCalledWith('Waves'));
  expect(screen.queryByLabelText('Description')).toBeNull();
});

test('the picker refuses a base whose index is not ready and explains it', () => {
  const onToggle = jest.fn();
  render(
    <KnowledgePicker
      visible
      bases={[
        base(),
        base({ ref: 'user:kb:bio', name: 'bio', status: 'processing' }),
        base({ ref: 'account:kb:gone', name: 'gone', available: false }),
      ]}
      selected={['user:kb:physics']}
      status="ready"
      error={null}
      onToggle={onToggle}
      onClose={jest.fn()}
      onRefresh={jest.fn()}
      onManage={jest.fn()}
    />,
  );

  const ready = screen.getByLabelText('physics');
  expect(ready.props.accessibilityState).toEqual({ checked: true, disabled: false });

  const busy = screen.getByLabelText('bio');
  expect(busy.props.accessibilityState).toEqual({ checked: false, disabled: true });
  expect(screen.getByText('Not ready — queued.')).toBeTruthy();

  expect(screen.getByText('This base is no longer available to you.')).toBeTruthy();

  fireEvent.press(ready);
  expect(onToggle).toHaveBeenCalledWith('user:kb:physics');
});

test('a selection the server no longer lists can still be removed', () => {
  const onToggle = jest.fn();
  render(
    <KnowledgePicker
      visible
      bases={[base()]}
      selected={['user:kb:physics', 'user:kb:deleted']}
      status="ready"
      error={null}
      onToggle={onToggle}
      onClose={jest.fn()}
      onRefresh={jest.fn()}
      onManage={jest.fn()}
    />,
  );

  // The handle is shown as a name, and the row stays pressable so the stale
  // choice can be dropped instead of riding along with every question.
  const stale = screen.getByLabelText('deleted');
  expect(stale.props.accessibilityState).toEqual({ checked: true, disabled: false });
  expect(
    screen.getByText('This base is no longer on the server. Tap to remove it.'),
  ).toBeTruthy();
  fireEvent.press(stale);
  expect(onToggle).toHaveBeenCalledWith('user:kb:deleted');
});

test('the picker offers management and a retry only when loading failed', () => {
  const onManage = jest.fn();
  const onRefresh = jest.fn();
  render(
    <KnowledgePicker
      visible
      bases={[]}
      selected={[]}
      status="failed"
      error="Could not reach the server."
      onToggle={jest.fn()}
      onClose={jest.fn()}
      onRefresh={onRefresh}
      onManage={onManage}
    />,
  );
  expect(screen.getByText('Could not reach the server.')).toBeTruthy();
  fireEvent.press(button('Manage'));
  fireEvent.press(button('Retry'));
  expect(onManage).toHaveBeenCalledTimes(1);
  expect(onRefresh).toHaveBeenCalledTimes(1);
});
