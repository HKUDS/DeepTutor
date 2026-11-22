import assert from 'node:assert/strict';
import test from 'node:test';
import { planRequestHeaders } from '../src/chatgpt-plan-request.mjs';

const frontendURL = 'http://127.0.0.1:18802';
const frame = { url: frontendURL + '/settings' };
const context = { sessionToken: 'fixture', frontendURL, contentsId: 1, mainFrame: frame };
const header = 'x-deeptutor-desktop-session';
const request = {
  url: frontendURL + '/api/settings/providers/chatgpt-plan/status',
  webContentsId: 1, frame, initiatorOrigin: frontendURL,
  resourceType: 'xhr', method: 'GET', requestHeaders: {},
};

test('only the Desktop view receives the plan authentication header', () => {
  assert.deepEqual(planRequestHeaders(request, context), { [header]: 'fixture' });
  const socket = {
    ...request, url: 'ws://127.0.0.1:18802/ws?dt_workspace=',
    frame: null, resourceType: 'webSocket', requestHeaders: { Origin: frontendURL },
  };
  assert.equal(planRequestHeaders(socket, context)[header], 'fixture');
  for (const changed of [
    { webContentsId: 2 },
    { frame: { url: frame.url } },
    { initiatorOrigin: 'https://example.test' },
    { url: 'https://example.test/api/settings/providers/chatgpt-plan/status' },
    { url: frontendURL + '/api/settings' },
    { method: 'OPTIONS' },
  ]) {
    const supplied = { 'X-DeepTutor-Desktop-Session': 'untrusted', Accept: 'application/json' };
    assert.deepEqual(
      planRequestHeaders({ ...request, ...changed, requestHeaders: supplied }, context),
      { Accept: 'application/json' },
    );
  }
});
