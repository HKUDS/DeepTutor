import test, { after, before } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { SourceRuntime } from '../src/runtime.mjs';
import { probe } from '../src/processes.mjs';

let server;
let base;
let status = 200;
let responseDelay = 0;
before(async () => {
  server = http.createServer((request, response) => {
    const selectedStatus = status;
    setTimeout(() => { response.writeHead(selectedStatus); response.end('local test'); }, responseDelay);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  base = `http://127.0.0.1:${server.address().port}`;
});
after(async () => { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });

function runtime() {
  const logs = [];
  const instance = new SourceRuntime({ log: chunk => logs.push(String(chunk)) });
  instance.state.phase = 'ready';
  return { instance, logs };
}

test('a slow but healthy backend outlives the old 2.5 second deadline', async () => {
  status = 200;
  responseDelay = 2800;
  assert.equal(await probe(`${base}/health/ready`), false);
  const { instance } = runtime();
  await instance.checkHealth(base);
  assert.equal(instance.state.phase, 'ready');
  assert.equal(instance.unhealthySince, undefined);
  responseDelay = 0;
});

test('three readiness misses do not kill the backend; recovery resets the clock', async () => {
  status = 503;
  const { instance, logs } = runtime();
  const clock = Date.now;
  let now = 100000;
  Date.now = () => now;
  try {
    for (let index = 0; index < 3; index++) {
      await instance.checkHealth(base);
      now += 10000;
    }
    assert.equal(instance.state.phase, 'ready');
    assert.equal(instance.group.stopping, false);
    status = 200;
    await instance.checkHealth(base);
    assert.equal(instance.unhealthySince, undefined);
    assert.ok(logs.some(line => line.includes('recovered')));
    status = 503;
    await instance.checkHealth(base);
    assert.equal(instance.unhealthySince, now);
  } finally { Date.now = clock; }
});

test('persistent unresponsiveness still stops owned services after the grace period', async () => {
  status = 503;
  const { instance } = runtime();
  const clock = Date.now;
  let now = 100000;
  Date.now = () => now;
  try {
    await instance.checkHealth(base);
    now += 89000;
    await instance.checkHealth(base);
    assert.equal(instance.state.phase, 'ready');
    now += 1000;
    await instance.checkHealth(base);
    assert.equal(instance.state.phase, 'error');
    assert.equal(instance.group.stopping, true);
    assert.match(instance.state.message, /90 seconds/);
  } finally { Date.now = clock; }
});

test('an in-flight probe cannot overwrite a stop or error state', async () => {
  status = 503;
  responseDelay = 30;
  const { instance, logs } = runtime();
  const pending = instance.checkHealth(base);
  instance.state.phase = 'stopping';
  await pending;
  assert.equal(instance.state.phase, 'stopping');
  assert.equal(instance.unhealthySince, undefined);
  assert.equal(logs.length, 0);
  responseDelay = 0;
});

test('overlapping checks and checks outside ready are ignored', async () => {
  const { instance } = runtime();
  instance.checking = true;
  await instance.checkHealth('http://127.0.0.1:1');
  assert.equal(instance.unhealthySince, undefined);
  instance.checking = false;
  instance.state.phase = 'stopped';
  await instance.checkHealth('http://127.0.0.1:1');
  assert.equal(instance.unhealthySince, undefined);
});

test('a readiness error is recorded instead of silently ending the runtime', async () => {
  status = 503;
  const { instance, logs } = runtime();
  await instance.checkHealth(base);
  assert.equal(instance.state.phase, 'ready');
  assert.match(logs.join(''), /Core health probe failed/);
});
