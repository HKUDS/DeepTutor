import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createServer } from 'node:http';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { app, BrowserWindow, WebContentsView } from 'electron';
import { createContentZoom } from '../../src/content-zoom.mjs';

const root = process.env.OPEN_DEEPTUTOR_ZOOM_TEST_ROOT;
const phase = process.env.OPEN_DEEPTUTOR_ZOOM_TEST_PHASE;
// A fresh Chromium profile prevents its origin cache from masking broken restoration.
app.setPath('userData', path.join(root, `chromium-${phase}`));
const deadline = setTimeout(() => { console.error('Native zoom test timed out'); app.exit(1); }, 45_000);

async function viewport(contents) {
  return contents.executeJavaScript('({ width: innerWidth, height: innerHeight, dpr: devicePixelRatio })');
}

app.whenReady().then(async () => {
  const server = createServer((_req, res) => {
    res.setHeader('Content-Type', 'text/html');
    res.end('<!doctype html><title>Content zoom regression</title><h1>Learning space</h1><input autofocus>');
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const url = `http://127.0.0.1:${server.address().port}/chat`;
  const preferences = { contextIsolation: true, sandbox: true, nodeIntegration: false, backgroundThrottling: false };
  const window = new BrowserWindow({ width: 1000, height: 700, useContentSize: true, webPreferences: preferences });
  window.setMenu(null);
  window.webContents.setZoomMode('disabled');
  window.webContents.setZoomFactor(1);
  await window.loadURL('data:text/html,<!doctype html><title>Private shell</title>');
  const shell = await viewport(window.webContents);
  const bounds = window.getBounds();
  const size = window.getContentBounds();
  let writes = Promise.resolve();
  const zoomFile = path.join(root, 'content-zoom.json');
  const saved = phase === 'restore' ? JSON.parse(await readFile(zoomFile, 'utf8')).factor : undefined;
  const zoom = createContentZoom(saved, factor => {
    writes = writes.then(() => writeFile(zoomFile, JSON.stringify({ factor })));
  });
  const view = new WebContentsView({ webPreferences: { ...preferences, partition: 'persist:content' } });
  window.contentView.addChildView(view);
  view.setBounds({ x: 0, y: 0, width: size.width, height: size.height });
  zoom.attach(view.webContents);
  await view.webContents.loadURL(url);
  await view.webContents.setVisualZoomLevelLimits(1, 1);
  window.show();
  window.focus();
  view.webContents.focus();
  const measurements = [];

  async function expectScale(label, factor) {
    let actual;
    const end = Date.now() + 5000;
    do {
      actual = await viewport(view.webContents);
      if (Math.abs(actual.width - size.width / factor) <= 1 && Math.abs(actual.dpr - shell.dpr * factor) < 0.01) break;
      await delay(25);
    } while (Date.now() < end);
    const measured = { label, factor: view.webContents.getZoomFactor(), ...actual };
    console.log(JSON.stringify(measured));
    assert.ok(Math.abs(actual.width - size.width / factor) <= 1,
      `${label}: viewport width ${actual.width} should be ${size.width / factor} at ${factor}x`);
    assert.ok(Math.abs(actual.dpr - shell.dpr * factor) < 0.01,
      `${label}: DPR ${actual.dpr} should be ${shell.dpr * factor}`);
    assert.ok(Math.abs(view.webContents.getZoomFactor() - factor) < 0.001);
    assert.equal(window.webContents.getZoomFactor(), 1);
    assert.deepEqual(await viewport(window.webContents), shell, `${label}: private shell changed`);
    assert.deepEqual(window.getBounds(), bounds, `${label}: native window changed`);
    measurements.push(measured);
  }

  await expectScale(phase === 'restore' ? 'cold restart' : 'initial', phase === 'restore' ? 1.25 : 1);
  if (phase === 'exercise') {
    zoom.step(1);
    await expectScale('zoom in', 1.1);
    zoom.step(-1);
    await expectScale('zoom out', 1);
    zoom.step(1);
    zoom.step(1);
    await expectScale('125 percent', 1.25);

    const peer = new WebContentsView({ webPreferences: { ...preferences, partition: 'persist:content' } });
    await peer.webContents.loadURL(url);
    assert.equal(peer.webContents.getZoomFactor(), 1, 'same-origin view must not inherit content zoom');
    assert.equal((await viewport(peer.webContents)).dpr, shell.dpr);
    peer.webContents.close();

    const reloaded = once(view.webContents, 'did-finish-load');
    view.webContents.reload();
    await reloaded;
    await expectScale('reload', 1.25);
    zoom.reset();
    await expectScale('reset', 1);

    view.webContents.sendInputEvent({ type: 'keyDown', keyCode: '+', modifiers: ['control', 'shift'] });
    view.webContents.sendInputEvent({ type: 'keyUp', keyCode: '+', modifiers: ['control', 'shift'] });
    await expectScale('Ctrl Shift Plus', 1.1);
    view.webContents.emit('zoom-changed', {}, 'in');
    await expectScale('wheel zoom request', 1.25);
    await delay(100);
    await expectScale('settled zoom', 1.25);
    await writes;
  }
  await writeFile(path.join(root, `${phase}.json`), JSON.stringify({ electron: process.versions.electron, url, shell, bounds, measurements }));
  view.webContents.close();
  window.destroy();
  server.close();
  clearTimeout(deadline);
  app.exit(0);
}).catch(error => {
  console.error(error.stack);
  clearTimeout(deadline);
  app.exit(1);
});
