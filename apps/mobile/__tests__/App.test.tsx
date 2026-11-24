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

test('connects to a DeepTutor server and displays streamed content', async () => {
  const fetchSpy = jest.spyOn(globalThis, 'fetch').mockResolvedValue({
    ok: true,
    json: async () => ({ enabled: false, authenticated: true }),
  } as Response);
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
  const socketSpy = jest
    .spyOn(globalThis, 'WebSocket')
    .mockImplementation(() => socket as unknown as WebSocket);
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

    await ReactTestRenderer.act(async () => {
      for (const [seq, content] of ['A function ', 'calls itself.'].entries()) {
        listeners.get('message')?.({
          data: JSON.stringify({
            type: 'content',
            protocol_version: '2.0',
            turn_id: 'turn-1',
            session_id: 'session-1',
            seq: seq + 1,
            timestamp: 1,
            content,
          }),
        });
      }
    });
    expect(JSON.stringify(app.toJSON())).toContain('A function calls itself.');
  } finally {
    await ReactTestRenderer.act(async () => app?.unmount());
    fetchSpy.mockRestore();
    socketSpy.mockRestore();
  }
});
