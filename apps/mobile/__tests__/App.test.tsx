/**
 * @format
 */

import React from 'react';
import ReactTestRenderer from 'react-test-renderer';
import { Button, TextInput } from 'react-native';
import App from '../App';

jest.mock(
  'react-native-safe-area-context',
  () => jest.requireActual('react-native-safe-area-context/jest/mock').default,
);

function createSocket() {
  const listeners = new Map<string, (event: { data?: string }) => void>();
  const socket = {
    readyState: 0,
    send: jest.fn(),
    close: jest.fn(),
    addEventListener: (
      type: string,
      listener: (event: { data?: string }) => void,
    ) => listeners.set(type, listener),
  };
  return { socket, listeners };
}

test('streams two turns in one session and resumes without duplicate text', async () => {
  const fetchSpy = jest.spyOn(globalThis, 'fetch').mockResolvedValue({
    ok: true,
    json: async () => ({ enabled: false, authenticated: true }),
  } as Response);
  const { socket, listeners } = createSocket();
  const recovered = createSocket();
  const socketSpy = jest
    .spyOn(globalThis, 'WebSocket')
    .mockReturnValueOnce(socket as unknown as WebSocket)
    .mockReturnValueOnce(recovered.socket as unknown as WebSocket);
  let app!: ReactTestRenderer.ReactTestRenderer;
  try {
    await ReactTestRenderer.act(async () => {
      app = ReactTestRenderer.create(<App />);
    });
    await ReactTestRenderer.act(async () => {
      app.root.findByType(Button).props.onPress();
    });
    expect(fetchSpy.mock.calls[0][0]).toMatch(/\/api\/auth\/status$/);
    expect(socketSpy.mock.calls[0][0]).toMatch(/\/ws\?dt_workspace=$/);

    await ReactTestRenderer.act(async () => {
      socket.readyState = 1;
      listeners.get('open')?.({});
      app.root.findByType(TextInput).props.onChangeText('Explain recursion');
    });
    await ReactTestRenderer.act(async () => {
      app.root
        .findAllByType(Button)
        .find(button => button.props.title === 'Send')!
        .props.onPress();
    });
    const commands = socket.send.mock.calls.map(([command]) =>
      JSON.parse(command),
    );
    expect(commands).toContainEqual(
      expect.objectContaining({
        type: 'start_turn',
        content: 'Explain recursion',
        protocol_version: '2.0',
      }),
    );

    const firstChunk = {
      type: 'content',
      protocol_version: '2.0',
      turn_id: 'turn-1',
      session_id: 'session-1',
      seq: 1,
      timestamp: 1,
      content: 'A function ',
    };
    const emit = (target: typeof listeners, event: object) =>
      target.get('message')?.({ data: JSON.stringify(event) });
    await ReactTestRenderer.act(async () => {
      emit(listeners, firstChunk);
      listeners.get('close')?.({});
    });
    expect(JSON.stringify(app.toJSON())).toContain('Reconnecting');
    await ReactTestRenderer.act(async () => {
      await new Promise<void>(resolve => setTimeout(() => resolve(), 350));
      recovered.socket.readyState = 1;
      recovered.listeners.get('open')?.({});
    });
    expect(recovered.socket.send).toHaveBeenCalledWith(
      JSON.stringify({
        type: 'resume_from',
        turn_id: 'turn-1',
        seq: 1,
        protocol_version: '2.0',
      }),
    );
    await ReactTestRenderer.act(async () => {
      emit(recovered.listeners, firstChunk);
      emit(recovered.listeners, {
        ...firstChunk,
        seq: 2,
        content: 'calls itself.',
      });
      emit(recovered.listeners, { ...firstChunk, seq: 3, type: 'done' });
    });
    expect(JSON.stringify(app.toJSON())).not.toContain('A function A function');
    expect(JSON.stringify(app.toJSON())).toContain('A function calls itself.');

    await ReactTestRenderer.act(async () => {
      app.root.findByType(TextInput).props.onChangeText('Give an example');
    });
    await ReactTestRenderer.act(async () => {
      app.root
        .findAllByType(Button)
        .find(button => button.props.title === 'Send')!
        .props.onPress();
    });
    expect(
      recovered.socket.send.mock.calls.map(([command]) => JSON.parse(command)),
    ).toContainEqual(
      expect.objectContaining({
        type: 'start_turn',
        content: 'Give an example',
        session_id: 'session-1',
      }),
    );
    await ReactTestRenderer.act(async () => {
      emit(recovered.listeners, {
        ...firstChunk,
        turn_id: 'turn-2',
        content: 'For example, a factorial function.',
      });
      emit(recovered.listeners, {
        ...firstChunk,
        turn_id: 'turn-2',
        seq: 2,
        type: 'error',
        content: 'The model is unavailable.',
      });
      emit(recovered.listeners, {
        ...firstChunk,
        turn_id: 'turn-2',
        seq: 3,
        type: 'done',
      });
    });
    expect(JSON.stringify(app.toJSON())).toContain(
      'For example, a factorial function.',
    );
    expect(JSON.stringify(app.toJSON())).toContain('The model is unavailable.');
    expect(
      app.root
        .findAllByType(Button)
        .some(button => button.props.title === 'Send'),
    ).toBe(true);
  } finally {
    await ReactTestRenderer.act(async () => app?.unmount());
    fetchSpy.mockRestore();
    socketSpy.mockRestore();
  }
}, 15_000);

test('shows a rejected login and connects after retrying', async () => {
  const fetchSpy = jest
    .spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ enabled: true, authenticated: false }),
    } as Response)
    .mockResolvedValueOnce({ status: 401, ok: false } as Response)
    .mockResolvedValueOnce({ status: 200, ok: true } as Response)
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ enabled: true, authenticated: true }),
    } as Response);
  const { socket } = createSocket();
  const socketSpy = jest
    .spyOn(globalThis, 'WebSocket')
    .mockReturnValue(socket as unknown as WebSocket);
  let app!: ReactTestRenderer.ReactTestRenderer;
  try {
    await ReactTestRenderer.act(async () => {
      app = ReactTestRenderer.create(<App />);
    });
    await ReactTestRenderer.act(async () => {
      app.root.findByType(Button).props.onPress();
    });
    const input = (label: string) =>
      app.root
        .findAllByType(TextInput)
        .find(item => item.props.accessibilityLabel === label)!;
    await ReactTestRenderer.act(async () => {
      input('Username').props.onChangeText('learner');
      input('Password').props.onChangeText('incorrect');
    });
    await ReactTestRenderer.act(async () => {
      app.root.findByType(Button).props.onPress();
    });
    expect(JSON.stringify(app.toJSON())).toContain(
      'Check your username and password.',
    );
    expect(socketSpy).not.toHaveBeenCalled();

    await ReactTestRenderer.act(async () => {
      input('Password').props.onChangeText('correct');
    });
    await ReactTestRenderer.act(async () => {
      app.root.findByType(Button).props.onPress();
    });
    expect(fetchSpy.mock.calls[2]).toEqual([
      expect.stringMatching(/\/api\/auth\/login$/),
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
        body: JSON.stringify({ username: 'learner', password: 'correct' }),
      }),
    ]);
    expect(socketSpy).toHaveBeenCalledTimes(1);
  } finally {
    await ReactTestRenderer.act(async () => app?.unmount());
    fetchSpy.mockRestore();
    socketSpy.mockRestore();
  }
});
