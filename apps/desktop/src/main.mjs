import { app, BrowserWindow, WebContentsView, Menu, ipcMain, shell, dialog, session, nativeTheme, screen } from 'electron';
import { fork } from 'node:child_process';
import { watch } from 'node:fs';
import { mkdir, readFile, writeFile, rename, cp, appendFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { installBundle, bundleConfig, startupRuntime } from './bundles.mjs';
import { externalURL } from './config.mjs';
import { resolveLanguage, translate } from './i18n.mjs';
import { WINDOWS, agentMarker, edition, targetId } from './platform.mjs';
import { killTree } from './processes.mjs';
import { minWindowSize, restoreWindowBounds } from './window-bounds.mjs';

app.setName('Open DeepTutor');
if (WINDOWS) app.setAppUserModelId('org.deeptutor.open-desktop');
const EDITION = edition();
const sourceDirectory = path.dirname(fileURLToPath(import.meta.url));
const shellURL = pathToFileURL(path.join(sourceDirectory, 'index.html')).href;
// Runtimes are large and machine-specific, so Windows keeps them out of the roaming profile.
const userRoot = process.env.OPEN_DEEPTUTOR_TEST_HOME
  || path.join(WINDOWS ? process.env.LOCALAPPDATA ?? app.getPath('appData') : app.getPath('appData'), 'Open DeepTutor');
app.setPath('userData', userRoot);
const runtimeHome = path.join(userRoot, 'workspace');
const logPath = path.join(userRoot, 'logs/runtime.log');
const activeFile = path.join(userRoot, 'active.json');
const transactionFile = path.join(userRoot, 'upgrade.json');
const windowStateFile = path.join(userRoot, 'window-state.json');
// DeepTutor's own Settings page writes the interface language and theme here.
const interfaceFile = path.join(runtimeHome, 'data/user/settings/interface.json');
const seed = app.isPackaged ? path.join(process.resourcesPath, 'seed/runtime.json') : path.join(sourceDirectory, '../.local', targetId(), 'seed/runtime.json');
const publicKey = await readFile(path.join(sourceDirectory, '../assets/runtime-public.pem'), 'utf8');

// macOS draws its 44px bar under the traffic lights; Windows uses a 38px WCO bar matching the sidebar tone.
const HEADER_HEIGHT = WINDOWS ? 38 : 44;
// Once loaded, solid themes use the sampled sidebar color. The glass gradient
// keeps the fallback color for the window chrome.
const PALETTE_BACKGROUND = WINDOWS
  ? { snow: '#f7f7f8', light: '#f5f2ea', dark: '#171719', glass: '#0e0d1a' }
  : { snow: '#ffffff', light: '#faf8f5', dark: '#161618', glass: '#0e0d1a' };
const OVERLAY_SYMBOL = { light: '#27272a', dark: '#e4e4e7', glass: '#e9e7f5' };

let window;
let view;
let contentVisible = false;
let worker;
let state = { phase: 'starting', step: 'opening' };
const PRIMARY_LANGUAGES = [
  { code: 'zh', label: '简体中文' },
  { code: 'en', label: 'English' },
];

const MORE_LANGUAGES = [
  { code: 'fr', label: 'Français' },
  { code: 'de', label: 'Deutsch' },
  { code: 'ja', label: '日本語' },
  { code: 'ko', label: '한국어' },
  { code: 'uk', label: 'Українська' },
  { code: 'pl', label: 'Polski' },
  { code: 'pt', label: 'Português' },
  { code: 'vi', label: 'Tiếng Việt' },
  { code: 'tr', label: 'Türkçe' },
  { code: 'it', label: 'Italiano' },
  { code: 'hu', label: 'Magyar' },
];

const SUPPORTED_LANGUAGES = new Set([
  ...PRIMARY_LANGUAGES.map(item => item.code),
  ...MORE_LANGUAGES.map(item => item.code),
]);

const THEME_PREFERENCES = ['system', 'snow', 'light', 'dark', 'glass'];
const VALID_THEME_SET = new Set(THEME_PREFERENCES);
const VALID_LAYOUT_SET = new Set(['modern', 'classic']);

let ui = {
  language: 'en',
  theme: 'light',
  themePreference: 'system',
  palette: 'snow',
  chromeBg: null,
  uiLayout: 'modern',
};
let chromeSyncTimer;
let interfaceWatcher;
let interfaceTimer;
let windowStateTimer;
let windowStateWrite = Promise.resolve();
// Crisp zoom stops avoid blurry 1px borders caused by fractional zoomLevel steps (1.2^0.5).
const ZOOM_STEPS = [0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75];
let zoomFactor = 1;
let layoutTimer;
let menuPopups;
let busy = false;
let quitting = false;
let exitAllowed = false;
let active;

const t = (key, values) => translate(ui.language, key, values);

async function writeJSON(file, data) {
  await mkdir(path.dirname(file), { recursive: true, mode: 0o700 });
  await writeFile(`${file}.tmp`, JSON.stringify(data, null, 2), { mode: 0o600 });
  await rename(`${file}.tmp`, file);
}

async function readJSON(file) {
  try { return JSON.parse(await readFile(file, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return null; throw error; }
}

function coreVersion() {
  return active?.manifest.coreVersion ?? app.getVersion();
}

function currentChromeBackground() {
  return ui.chromeBg || PALETTE_BACKGROUND[ui.palette] || PALETTE_BACKGROUND.snow;
}

function titleBarOverlayOptions(theme, color = currentChromeBackground()) {
  return {
    color,
    symbolColor: ui.palette === 'glass' ? OVERLAY_SYMBOL.glass : OVERLAY_SYMBOL[theme],
    height: HEADER_HEIGHT,
  };
}

function clampZoomFactor(value) {
  if (!Number.isFinite(value)) return 1;
  return Math.min(ZOOM_STEPS[ZOOM_STEPS.length - 1], Math.max(ZOOM_STEPS[0], value));
}

function nearestZoomIndex(value) {
  let best = 0;
  let minDiff = Infinity;
  for (let i = 0; i < ZOOM_STEPS.length; i += 1) {
    const diff = Math.abs(ZOOM_STEPS[i] - value);
    if (diff < minDiff) {
      minDiff = diff;
      best = i;
    }
  }
  return best;
}

function applyContentZoom(nextFactor, { persist = true } = {}) {
  zoomFactor = clampZoomFactor(nextFactor);
  if (view && !view.webContents.isDestroyed()) {
    view.webContents.setZoomFactor(zoomFactor);
  }
  if (persist) persistWindowState();
}

function stepContentZoom(direction) {
  if (!view || state.phase !== 'ready' || view.webContents.isDestroyed()) return;
  const current = view.webContents.getZoomFactor();
  const idx = nearestZoomIndex(current);
  const nextIdx = Math.max(0, Math.min(ZOOM_STEPS.length - 1, idx + direction));
  applyContentZoom(ZOOM_STEPS[nextIdx]);
}

function resetContentZoom() {
  if (!view || state.phase !== 'ready' || view.webContents.isDestroyed()) return;
  applyContentZoom(1);
}

function defaultWindowBounds() {
  const { workArea } = screen.getPrimaryDisplay();
  const { minWidth, minHeight } = minWindowSize(workArea);
  const width = Math.min(1360, Math.max(minWidth, Math.round(workArea.width * 0.86)), workArea.width);
  const height = Math.min(900, Math.max(minHeight, Math.round(workArea.height * 0.86)), workArea.height);
  return {
    x: Math.round(workArea.x + (workArea.width - width) / 2),
    y: Math.round(workArea.y + (workArea.height - height) / 2),
    width,
    height,
    maximized: false,
    zoomFactor: 1,
  };
}

function resolveWindowBounds(saved) {
  const savedZoom = clampZoomFactor(saved?.zoomFactor ?? 1);
  if (!saved || ![saved.x, saved.y, saved.width, saved.height].every(Number.isFinite)) {
    return { ...defaultWindowBounds(), zoomFactor: savedZoom };
  }
  const restored = restoreWindowBounds(saved, screen.getAllDisplays());
  if (!restored) return { ...defaultWindowBounds(), zoomFactor: savedZoom };
  return { ...restored, maximized: Boolean(saved.maximized), zoomFactor: savedZoom };
}

function persistWindowState(immediate = false) {
  clearTimeout(windowStateTimer);
  if (!window || window.isDestroyed()) return windowStateWrite;
  // Never overwrite maximized/normal bounds while minimized or in fullscreen.
  if (window.isMinimized() || window.isFullScreen()) return windowStateWrite;
  const payload = {
    ...window.getNormalBounds(),
    maximized: window.isMaximized(),
    zoomFactor,
  };
  const write = () => {
    windowStateWrite = windowStateWrite.then(() => writeJSON(windowStateFile, payload)).catch(console.error);
  };
  if (immediate) write();
  else windowStateTimer = setTimeout(write, 300);
  return windowStateWrite;
}

/** What the shell page shows, already in the user's language. */
function snapshot() {
  const failed = state.phase === 'error';
  return {
    phase: state.phase, step: state.step ?? null, theme: ui.theme, palette: ui.palette, chromeBg: currentChromeBackground(), language: ui.language,
    contentVisible,
    title: failed ? t('errorTitle') : state.phase === 'stopped' ? t('stoppedTitle') : '',
    message: failed ? t('errorBody') : state.step ? t(state.step) : '',
    detail: failed ? state.message ?? '' : '',
    tagline: t('tagline'), slowHint: t('slowHint'), retry: t('retry'), logs: t('logs'),
    edition: `${EDITION.full} v${coreVersion()}`,
    menus: [
      { id: 'app', label: 'Open DeepTutor' },
      { id: 'preferences', label: t('preferences') },
      { id: 'view', label: t('view') },
      { id: 'core', label: t('core') },
    ],
  };
}

function publish() {
  if (window && !window.isDestroyed()) window.webContents.send('desktop:status', snapshot());
}

function status(next) {
  state = { ...state, ...next };
  if (next.phase && next.phase !== 'ready') hideContent();
  publish();
}

function normalizeAppLanguage(value) {
  const code = String(value ?? '').trim().toLowerCase().replaceAll('_', '-');
  const base = code.split('-', 1)[0];
  if (base === 'cn') return 'zh';
  if (base === 'ua') return 'uk';
  if (base === 'jp') return 'ja';
  return SUPPORTED_LANGUAGES.has(base) ? base : resolveLanguage(value);
}

function normalizeThemePreference(value) {
  return VALID_THEME_SET.has(value) ? value : 'system';
}

function resolvePalette(preference) {
  if (preference === 'system') return nativeTheme.shouldUseDarkColors ? 'dark' : 'snow';
  return VALID_THEME_SET.has(preference) ? preference : 'snow';
}

function resolveChromeTheme(preference) {
  const palette = resolvePalette(preference);
  return palette === 'dark' || palette === 'glass' ? 'dark' : 'light';
}

async function readInterface() {
  let saved;
  try { saved = await readJSON(interfaceFile) ?? {}; }
  catch { return ui; } // A half-written or hand-edited file keeps the current choice.
  const language = normalizeAppLanguage(saved.language);
  const themePreference = normalizeThemePreference(saved.theme);
  const palette = resolvePalette(themePreference);
  return {
    ...ui,
    language,
    themePreference,
    palette,
    theme: resolveChromeTheme(themePreference),
    chromeBg: palette === ui.palette ? ui.chromeBg : null,
  };
}

function applyThemeChrome() {
  const bg = currentChromeBackground();
  if (window && !window.isDestroyed()) {
    window.setBackgroundColor(bg);
    if (WINDOWS) window.setTitleBarOverlay(titleBarOverlayOptions(ui.theme, bg));
  }
  if (view && !view.webContents.isDestroyed()) {
    view.setBackgroundColor(bg);
  }
}

async function refreshInterface() {
  const next = await readInterface();
  const paletteChanged = next.palette !== ui.palette;
  if (
    next.language === ui.language
    && next.theme === ui.theme
    && next.themePreference === ui.themePreference
    && !paletteChanged
  ) return;
  ui = next;
  buildMenu();
  applyThemeChrome();
  publish();
  if (paletteChanged) scheduleChromeColorSync(120);
}

/** 采样 WebContentsView 左上角（紧贴标题栏下方侧边栏）的实际合成色，消除顶栏与侧边栏色差。 */
async function syncChromeColorFromView() {
  if (!WINDOWS || !webViewReady()) return;
  try {
    const hex = await view.webContents.executeJavaScript(`(() => {
      const parse = value => {
        const m = /^rgba?\\(\\s*(\\d+)\\s*,\\s*(\\d+)\\s*,\\s*(\\d+)(?:\\s*,\\s*([\\d.]+))?\\s*\\)/.exec(value || '');
        if (!m) return null;
        return [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]];
      };
      const stack = document.elementsFromPoint(8, 8).reverse();
      let acc = null;
      for (const el of stack) {
        if (el.matches?.('button, a, input, svg, img, span, p')) continue;
        const style = getComputedStyle(el);
        if (style.backgroundImage && style.backgroundImage !== 'none' && style.backgroundImage.includes('gradient')) {
          return null; // 琉璃等渐变背景交给预设色处理，避免取到透明底
        }
        const rgba = parse(style.backgroundColor);
        if (!rgba || rgba[3] <= 0.01) continue;
        if (!acc || rgba[3] >= 0.99) {
          acc = [rgba[0], rgba[1], rgba[2]];
        } else {
          const a = rgba[3];
          acc = [
            Math.round(rgba[0] * a + acc[0] * (1 - a)),
            Math.round(rgba[1] * a + acc[1] * (1 - a)),
            Math.round(rgba[2] * a + acc[2] * (1 - a)),
          ];
        }
      }
      if (!acc) return null;
      return '#' + acc.map(v => v.toString(16).padStart(2, '0')).join('');
    })()`);
    const nextBg = typeof hex === 'string' && /^#[0-9a-f]{6}$/i.test(hex) ? hex : null;
    if (nextBg === ui.chromeBg) return;
    ui = { ...ui, chromeBg: nextBg };
    applyThemeChrome();
    publish();
  } catch { /* 页面切换中忽略 */ }
}

function scheduleChromeColorSync(delay = 80) {
  clearTimeout(chromeSyncTimer);
  chromeSyncTimer = setTimeout(() => void syncChromeColorFromView(), delay);
}

function webViewReady() {
  return Boolean(view && state.phase === 'ready' && !view.webContents.isDestroyed());
}

/** 弹出「偏好」菜单前，从页面 localStorage 拉取实时状态，保证勾选态 100% 准确。 */
async function syncPreferencesFromView() {
  if (!webViewReady()) return;
  try {
    const live = await view.webContents.executeJavaScript(`(() => {
      try {
        return {
          language: localStorage.getItem('deeptutor-language'),
          theme: localStorage.getItem('deeptutor-theme'),
          uiLayout: localStorage.getItem('deeptutor.ui-layout'),
        };
      } catch {
        return null;
      }
    })()`);
    if (!live) return;
    const nextLanguage = live.language ? normalizeAppLanguage(live.language) : ui.language;
    const nextThemePref = live.theme ? normalizeThemePreference(live.theme) : ui.themePreference;
    const nextPalette = resolvePalette(nextThemePref);
    const nextTheme = resolveChromeTheme(nextThemePref);
    const nextLayout = VALID_LAYOUT_SET.has(live.uiLayout) ? live.uiLayout : ui.uiLayout;

    const paletteChanged = nextPalette !== ui.palette;
    const shellChanged = nextLanguage !== ui.language || nextTheme !== ui.theme || paletteChanged;
    const menuChanged = shellChanged || nextThemePref !== ui.themePreference || nextLayout !== ui.uiLayout;
    if (!menuChanged) return;

    const prevTheme = ui.theme;
    ui = {
      language: nextLanguage,
      theme: nextTheme,
      themePreference: nextThemePref,
      palette: nextPalette,
      chromeBg: paletteChanged ? null : ui.chromeBg,
      uiLayout: nextLayout,
    };
    buildMenu();
    if (paletteChanged || nextTheme !== prevTheme) applyThemeChrome();
    if (shellChanged) publish();
    if (paletteChanged) scheduleChromeColorSync(60);
  } catch { /* 页面切换中或未就绪时保留现有状态 */ }
}

/** 优先走后端 /api/settings/ui 持久化，后端未就绪或请求失败时原子写回 interface.json。 */
async function persistInterfacePatch(patch) {
  if (state.backendURL && state.phase === 'ready') {
    try {
      const response = await fetch(`${state.backendURL}/api/settings/ui`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      });
      if (response.ok) return;
    } catch { /* 回退到直接写文件 */ }
  }
  try {
    const current = await readJSON(interfaceFile) ?? {};
    await writeJSON(interfaceFile, { ...current, ...patch });
  } catch (error) {
    console.error('Failed to persist interface preference:', error);
  }
}

async function applyLanguagePreference(nextLanguage) {
  const language = normalizeAppLanguage(nextLanguage);
  if (ui.language !== language) {
    ui = { ...ui, language };
    buildMenu();
    publish();
  }
  if (webViewReady()) {
    await view.webContents.executeJavaScript(`(() => {
      const language = ${JSON.stringify(language)};
      try { localStorage.setItem('deeptutor-language', language); } catch {}
      window.dispatchEvent(new CustomEvent('deeptutor:language', { detail: { language, source: 'desktop' } }));
    })()`).catch(console.error);
  }
  await persistInterfacePatch({ language });
}

async function applyThemePreference(nextPreference) {
  const themePreference = normalizeThemePreference(nextPreference);
  const palette = resolvePalette(themePreference);
  const theme = resolveChromeTheme(themePreference);
  ui = { ...ui, themePreference, palette, theme, chromeBg: null };
  buildMenu();
  applyThemeChrome();
  publish();

  if (webViewReady()) {
    // 直接按 web/lib/theme.ts 的规则改 <html> class，即使页面没有事件监听器也 100% 立刻切换。
    await view.webContents.executeJavaScript(`(() => {
      const pref = ${JSON.stringify(themePreference)};
      const resolved = pref === 'system'
        ? (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'snow')
        : pref;
      const html = document.documentElement;
      html.classList.remove('dark', 'theme-glass', 'theme-snow');
      if (resolved === 'dark') html.classList.add('dark');
      else if (resolved === 'glass') html.classList.add('dark', 'theme-glass');
      else if (resolved === 'snow') html.classList.add('theme-snow');
      try { localStorage.setItem('deeptutor-theme', pref); } catch {}
      window.dispatchEvent(new CustomEvent('deeptutor:theme', { detail: { theme: pref } }));
    })()`).catch(console.error);
    // 等页面按新 class 重绘一帧后，同步真实侧边栏颜色到顶部栏
    scheduleChromeColorSync(80);
  }
  await persistInterfacePatch({ theme: themePreference });
}

async function applyUiLayoutPreference(nextLayout) {
  if (!VALID_LAYOUT_SET.has(nextLayout) || !webViewReady()) return;
  if (ui.uiLayout !== nextLayout) {
    ui = { ...ui, uiLayout: nextLayout };
    buildMenu();
  }
  await view.webContents.executeJavaScript(`(() => {
    const layout = ${JSON.stringify(nextLayout)};
    try { localStorage.setItem('deeptutor.ui-layout', layout); } catch {}
    document.documentElement.setAttribute('data-ui-layout', layout);
    window.dispatchEvent(new CustomEvent('deeptutor:ui-layout', { detail: { layout } }));
  })()`).catch(console.error);
  scheduleChromeColorSync(120);
}

function openSettingsPage() {
  if (!webViewReady() || !state.url) return;
  const target = new URL('/settings', state.url).href;
  if (!view.webContents.getURL().startsWith(target)) {
    void view.webContents.loadURL(target);
  }
  view.webContents.focus();
}

function toggleAlwaysOnTop() {
  if (!window || window.isDestroyed()) return;
  window.setAlwaysOnTop(!window.isAlwaysOnTop());
  buildMenu();
}

function watchInterface() {
  if (interfaceWatcher) return;
  try {
    // Settings are replaced atomically, so watch the folder rather than the file.
    interfaceWatcher = watch(path.dirname(interfaceFile), () => {
      clearTimeout(interfaceTimer);
      interfaceTimer = setTimeout(() => void refreshInterface(), 150);
    });
    interfaceWatcher.on('error', () => { interfaceWatcher?.close(); interfaceWatcher = undefined; });
  } catch { /* The folder appears after the core's first init; boot() tries again. */ }
}

function hideContent() {
  clearTimeout(chromeSyncTimer);
  contentVisible = false;
  const current = view;
  view = undefined;
  if (!current) return;
  if (window && !window.isDestroyed()) {
    try { window.contentView.removeChildView(current); } catch { /* ignore */ }
  }
  if (!current.webContents.isDestroyed()) {
    current.webContents.close();
  }
}

function layout() {
  if (!view || !window || window.isDestroyed() || window.isMinimized()) return;
  const bounds = window.getContentBounds();
  if (bounds.width <= 0 || bounds.height <= HEADER_HEIGHT) return;
  view.setBounds({
    x: 0,
    y: HEADER_HEIGHT,
    width: bounds.width,
    height: bounds.height - HEADER_HEIGHT,
  });
}

function scheduleLayout() {
  layout();
  clearTimeout(layoutTimer);
  // Catch post-animation / post-DPI-change final bounds on Windows.
  layoutTimer = setTimeout(layout, 60);
}

function syncDisplayConstraints({ clampPosition = false } = {}) {
  if (!window || window.isDestroyed() || window.isMinimized()) return;
  const currentBounds = window.getBounds();
  const display = screen.getDisplayMatching(currentBounds);
  const { workArea } = display;
  const { minWidth, minHeight } = minWindowSize(workArea);
  window.setMinimumSize(minWidth, minHeight);

  if (clampPosition && !window.isMaximized() && !window.isFullScreen()) {
    const width = Math.min(workArea.width, Math.max(minWidth, currentBounds.width));
    const height = Math.min(workArea.height, Math.max(minHeight, currentBounds.height));
    const x = Math.min(Math.max(currentBounds.x, workArea.x), workArea.x + workArea.width - width);
    const y = Math.min(Math.max(currentBounds.y, workArea.y), workArea.y + workArea.height - height);
    if (x !== currentBounds.x || y !== currentBounds.y || width !== currentBounds.width || height !== currentBounds.height) {
      window.setBounds({ x, y, width, height });
    }
  }
  scheduleLayout();
}

async function openContent(ready) {
  hideContent();
  const origin = new URL(ready.url).origin;
  const nextView = new WebContentsView({ webPreferences: {
    contextIsolation: true, sandbox: true, nodeIntegration: false, webSecurity: true,
    partition: 'persist:deeptutor',
  } });
  view = nextView;
  nextView.setBackgroundColor(currentChromeBackground());
  nextView.setVisible(false);
  const content = nextView.webContents;
  content.setWindowOpenHandler(({ url: target }) => {
    if (target.startsWith(origin + '/') || target.startsWith(`blob:${origin}/`)) {
      return { action: 'allow', overrideBrowserWindowOptions: {
        webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false, webSecurity: true },
      } };
    }
    if (externalURL(target)) void shell.openExternal(target);
    return { action: 'deny' };
  });
  const restrict = (event, target) => {
    if (new URL(target).origin !== origin) {
      event.preventDefault();
      if (externalURL(target)) void shell.openExternal(target);
    }
  };
  content.on('will-navigate', restrict);
  content.on('will-redirect', restrict);
  content.on('will-attach-webview', event => event.preventDefault());
  content.on('render-process-gone', () => status({ phase: 'error', step: null, message: t('pageGone') }));
  // 页面每次加载/站内跳转后重新采样侧边栏色，让顶栏贴合当前页面。
  // Zoom is per-origin and resets on navigation: re-assert the user's factor on
  // every finished load (initial load, reload, full navigation).
  content.on('did-finish-load', () => {
    content.setZoomFactor(zoomFactor);
    scheduleChromeColorSync(120);
  });
  content.on('did-navigate-in-page', () => scheduleChromeColorSync(120));
  // Take full ownership of zoom: automatic Ctrl+wheel zoom is disabled so it cannot
  // fight the snapped stops below ('manual' still dispatches 'zoom-changed').
  content.setZoomMode('manual');
  content.setZoomFactor(zoomFactor);
  content.on('zoom-changed', (_event, direction) => {
    stepContentZoom(direction === 'in' ? 1 : -1);
  });
  content.on('before-input-event', (event, input) => {
    if (input.type !== 'keyDown' || !(input.control || input.meta) || input.alt) return;
    if (input.code === 'NumpadAdd' || (input.key === '+' && input.shift)) {
      event.preventDefault();
      stepContentZoom(1);
    } else if (input.code === 'NumpadSubtract') {
      event.preventDefault();
      stepContentZoom(-1);
    } else if (input.code === 'Numpad0') {
      event.preventDefault();
      resetContentZoom();
    }
  });
  // Mount and size while hidden so Next.js hydrates at the real viewport width without flashing white.
  window.contentView.addChildView(nextView);
  layout();
  // Load the canonical chat route directly; the Next.js root redirects to it.
  await content.loadURL(new URL('/chat', ready.url).href);
  // The pre-load setZoomFactor applied to about:blank; re-assert on the real origin.
  content.setZoomFactor(zoomFactor);
  // Disable mobile-style pinch visual zoom; needs a live frame (rejects before first load).
  void content.setVisualZoomLevelLimits(1, 1).catch(() => {});
  if (view === nextView && !quitting) {
    layout();
    nextView.setVisible(true);
    contentVisible = true;
    status(ready);
    buildMenu();
    scheduleChromeColorSync(120);
    content.focus();
  }
}

function trustedShell(event) {
  if (event.sender !== window?.webContents || event.senderFrame !== window.webContents.mainFrame
    || event.senderFrame.url !== shellURL) throw new Error('Untrusted desktop IPC caller');
}

async function stopWorker() {
  const previous = worker;
  worker = undefined;
  if (!previous || previous.exitCode !== null) return;
  await new Promise(resolve => {
    // Windows cannot signal the worker, so a stuck worker is ended with its services.
    const force = () => { if (WINDOWS) killTree(previous.pid); else previous.kill('SIGTERM'); };
    const timer = setTimeout(force, 12000);
    previous.once('exit', () => { clearTimeout(timer); resolve(); });
    if (previous.connected) previous.send({ type: 'stop' });
    else force();
  });
}

async function launchRuntime(installed) {
  const config = bundleConfig(installed.destination, runtimeHome, installed.manifest.runtimeId);
  const child = fork(path.join(sourceDirectory, 'supervisor.mjs'), [], {
    execPath: config.nodePath, stdio: ['ignore', 'ignore', 'pipe', 'ipc'],
    env: { ...process.env, ELECTRON_RUN_AS_NODE: '' },
  });
  worker = child;
  child.stderr.on('data', chunk => console.error(chunk.toString()));
  return new Promise((resolve, reject) => {
    let ready = false;
    child.on('message', next => {
      if (worker !== child || quitting) return;
      if (next.phase === 'ready') {
        if (!ready) { ready = true; resolve(next); }
        return;
      }
      status(next);
      if (next.phase === 'error' && !ready) reject(new Error(next.message));
    });
    child.once('error', reject);
    child.once('exit', code => {
      if (worker !== child || quitting) return;
      status({ phase: 'error', step: null, message: t('workerExited', { code }) });
      if (!ready) reject(new Error(state.message));
    });
    child.send({ type: 'start', config, logPath, cachePath: path.join(userRoot, 'cache', installed.manifest.runtimeId) });
  });
}

async function recoverInterruptedUpgrade() {
  const transaction = await readJSON(transactionFile);
  if (!transaction || transaction.phase !== 'testing') return;
  status({ phase: 'starting', step: 'recovering' });
  if (transaction.backup) {
    try { await rename(runtimeHome, `${runtimeHome}.interrupted-${Date.now()}`); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    await cp(transaction.backup, runtimeHome, { recursive: true });
  }
  await writeJSON(activeFile, transaction.previous);
  await writeJSON(transactionFile, { ...transaction, phase: 'recovered' });
}

async function logStartupFailure(error) {
  // Bundle extraction can fail before the supervisor creates the runtime log.
  console.error(error);
  try {
    await mkdir(path.dirname(logPath), { recursive: true });
    await appendFile(logPath, `\nDesktop startup failed: ${error.stack ?? error}\n`);
  } catch (logError) { console.error(logError); }
}

async function startupManifest() {
  const saved = await readJSON(activeFile);
  if (!saved) return { manifestFile: seed };
  // A missing or unreadable seed must not stop the installed core from starting.
  const bundled = await readJSON(seed).catch(error => { console.error(error); return null; });
  const { current, upgrade, seedError, replaceUntrusted } = startupRuntime({
    saved, seed: bundled, transaction: await readJSON(transactionFile), publicKey,
  });
  if (replaceUntrusted) return { manifestFile: seed, replaceUntrusted: true };
  if (seedError) console.error(seedError);
  const installed = path.join(userRoot, 'runtimes', current.runtimeId, 'installed.json');
  return upgrade ? { manifestFile: seed, previous: current, installed } : { manifestFile: installed };
}

async function boot() {
  if (busy || quitting) return;
  busy = true;
  let transaction;
  try {
    status({ phase: 'starting', step: 'starting' });
    await stopWorker();
    await recoverInterruptedUpgrade();
    const { manifestFile, previous, installed, replaceUntrusted } = await startupManifest();
    try { active = await installBundle(manifestFile, userRoot, publicKey, step => status({ step })); }
    catch (error) {
      if (!previous) throw error;
      // The bundled core could not be unpacked; keep starting the installed one.
      await logStartupFailure(error);
      active = await installBundle(installed, userRoot, publicKey, step => status({ step }));
    }
    if (quitting) return;
    if (replaceUntrusted || (previous && active.manifest.runtimeId !== previous.runtimeId)) {
      // The app was installed over an older core: switch to the bundled one with the
      // same backup and rollback as a manual update.
      status({ phase: 'starting', step: 'updating' });
      let backup = path.join(userRoot, 'backups', `before-${active.manifest.runtimeId}-${Date.now()}`);
      await mkdir(path.dirname(backup), { recursive: true });
      try { await cp(runtimeHome, backup, { recursive: true }); }
      catch (error) {
        // No workspace yet means nothing to restore on rollback.
        if (error.code !== 'ENOENT') throw error;
        backup = undefined;
      }
      transaction = { phase: 'testing', previous: previous ?? null, candidate: active.manifest, backup };
      await writeJSON(transactionFile, transaction);
    }
    const ready = await launchRuntime(active);
    if (quitting) return;
    await writeJSON(activeFile, active.manifest);
    if (transaction) await writeJSON(transactionFile, { ...transaction, phase: 'complete' });
    watchInterface();
    await refreshInterface();
    await openContent(ready);
  } catch (error) {
    await logStartupFailure(error);
    if (transaction) {
      // Restore the previous core and workspace; the next start uses them again.
      await stopWorker();
      try {
        await writeJSON(transactionFile, { ...transaction, failed: true });
        await recoverInterruptedUpgrade();
      }
      catch (recoveryError) { await logStartupFailure(recoveryError); }
    }
    status({ phase: 'error', step: null, message: error.message });
    await stopWorker();
  } finally { busy = false; }
}

async function installUpdate() {
  if (busy || quitting || !active) return;
  const choice = await dialog.showOpenDialog(window, { title: t('updateTitle'), properties: ['openFile'], filters: [{ name: t('updateFilter'), extensions: ['json'] }] });
  if (choice.canceled) return;
  const confirmation = await dialog.showMessageBox(window, {
    type: 'question', buttons: [t('cancel'), t('updateConfirm')], defaultId: 0, cancelId: 0,
    message: t('updateMessage'), detail: t('updateDetail'),
  });
  if (confirmation.response !== 1) return;
  busy = true;
  let transaction;
  try {
    const next = await installBundle(choice.filePaths[0], userRoot, publicKey);
    if (next.manifest.runtimeId === active.manifest.runtimeId) return;
    status({ phase: 'starting', step: 'updating' });
    await stopWorker();
    const backup = path.join(userRoot, 'backups', `before-${next.manifest.runtimeId}-${Date.now()}`);
    await mkdir(path.dirname(backup), { recursive: true });
    await cp(runtimeHome, backup, { recursive: true });
    transaction = { phase: 'testing', previous: active.manifest, candidate: next.manifest, backup };
    await writeJSON(transactionFile, transaction);
    const ready = await launchRuntime(next);
    await openContent(ready);
    await writeJSON(activeFile, next.manifest);
    await writeJSON(transactionFile, { ...transaction, phase: 'complete' });
    active = next;
    buildMenu();
    publish();
  } catch (error) {
    await stopWorker();
    if (transaction) await recoverInterruptedUpgrade();
    await dialog.showMessageBox(window, { type: 'error', message: t('updateFailed'), detail: error.message, buttons: [t('reopen')] });
    busy = false;
    await boot();
  } finally { busy = false; }
}

function buildMenu() {
  const ready = webViewReady();
  const about = {
    label: t('about'),
    click: () => dialog.showMessageBox(window, {
      message: `${EDITION.full} v${coreVersion()}`,
      detail: t('aboutDetail', { core: active?.manifest.coreVersion ?? '—', runtime: active?.manifest.runtimeId ?? '—' }),
    }),
  };

  const settingsItem = {
    label: t('settings'),
    accelerator: 'CmdOrCtrl+,',
    enabled: ready,
    click: () => openSettingsPage(),
  };

  const appSubmenu = WINDOWS
    ? [
        settingsItem,
        { type: 'separator' },
        about,
        { type: 'separator' },
        { role: 'quit', label: t('quit') },
      ]
    : [
        about,
        { type: 'separator' },
        settingsItem,
        { type: 'separator' },
        { role: 'hide', label: t('hide') }, { role: 'hideOthers', label: t('hideOthers') }, { role: 'unhide', label: t('showAll') },
        { type: 'separator' },
        { role: 'quit', label: t('quit') },
      ];

  const activeMoreLang = MORE_LANGUAGES.find(item => item.code === ui.language);
  const preferencesSubmenu = [
    // 常用语言直接平铺在最上方，使用 checkbox 避免与子菜单跨组产生 Win32 radio 冲突
    ...PRIMARY_LANGUAGES.map(item => ({
      label: item.label,
      type: 'checkbox',
      checked: ui.language === item.code,
      click: () => void applyLanguagePreference(item.code),
    })),
    {
      label: activeMoreLang ? `${t('moreLanguages')} (${activeMoreLang.label})` : t('moreLanguages'),
      submenu: MORE_LANGUAGES.map(item => ({
        label: item.label,
        type: 'checkbox',
        checked: ui.language === item.code,
        click: () => void applyLanguagePreference(item.code),
      })),
    },
    { type: 'separator' },
    {
      label: t('theme'),
      submenu: [
        { id: 'system', key: 'themeSystem' },
        { id: 'snow', key: 'themeDefault' },
        { id: 'light', key: 'themeCream' },
        { id: 'dark', key: 'themeDark' },
        { id: 'glass', key: 'themeGlass' },
      ].map(({ id, key }) => ({
        label: t(key),
        type: 'radio',
        checked: ui.themePreference === id,
        click: () => void applyThemePreference(id),
      })),
    },
    {
      label: t('layout'),
      submenu: [
        { id: 'modern', key: 'layoutModern' },
        { id: 'classic', key: 'layoutClassic' },
      ].map(({ id, key }) => ({
        label: t(key),
        type: 'radio',
        enabled: ready,
        checked: ui.uiLayout === id,
        click: () => void applyUiLayoutPreference(id),
      })),
    },
  ];

  const viewSubmenu = [
    ...(WINDOWS ? [
      {
        label: t('alwaysOnTop'),
        type: 'checkbox',
        checked: Boolean(window && !window.isDestroyed() && window.isAlwaysOnTop()),
        click: () => toggleAlwaysOnTop(),
      },
      { type: 'separator' },
    ] : []),
    { label: t('reload'), accelerator: 'CmdOrCtrl+R', enabled: ready, click: () => view?.webContents.reload() },
    ...(WINDOWS ? [
      { label: t('forceReload'), accelerator: 'CmdOrCtrl+Shift+R', enabled: ready, click: () => view?.webContents.reloadIgnoringCache() },
    ] : []),
    { type: 'separator' },
    { label: t('actualSize'), accelerator: 'CmdOrCtrl+0', click: () => resetContentZoom() },
    { label: t('zoomIn'), accelerator: 'CmdOrCtrl+=', click: () => stepContentZoom(1) },
    { label: t('zoomOut'), accelerator: 'CmdOrCtrl+-', click: () => stepContentZoom(-1) },
    { type: 'separator' },
    { role: 'togglefullscreen', label: t('fullscreen') },
  ];

  const coreSubmenu = [
    { label: t('restartCore'), click: async () => {
      const choice = await dialog.showMessageBox(window, { message: t('restartConfirm'), buttons: [t('cancel'), t('restart')], defaultId: 0, cancelId: 0 });
      if (choice.response === 1) void boot();
    } },
    { label: t('installUpdate'), click: () => void installUpdate() }, { type: 'separator' },
    { label: t('openData'), click: () => void shell.openPath(runtimeHome) },
    { label: t('openLogs'), click: () => void shell.openPath(path.dirname(logPath)) },
  ];

  if (WINDOWS) {
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      { label: 'Open DeepTutor', submenu: appSubmenu },
      { label: t('preferences'), submenu: preferencesSubmenu },
      { label: t('view'), submenu: viewSubmenu },
      { label: t('core'), submenu: coreSubmenu },
    ]));

    menuPopups = new Map([
      ['app', Menu.buildFromTemplate(appSubmenu)],
      ['preferences', Menu.buildFromTemplate(preferencesSubmenu)],
      ['view', Menu.buildFromTemplate(viewSubmenu)],
      ['core', Menu.buildFromTemplate(coreSubmenu)],
    ]);

    // Keep native Win32 menu bar permanently hidden while retaining global shortcuts.
    if (window && !window.isDestroyed()) {
      window.setAutoHideMenuBar(false);
      window.setMenuBarVisibility(false);
    }
  } else {
    const editSubmenu = [
      { role: 'undo', label: t('undo') }, { role: 'redo', label: t('redo') }, { type: 'separator' },
      { role: 'cut', label: t('cut') }, { role: 'copy', label: t('copy') }, { role: 'paste', label: t('paste') },
      { role: 'selectAll', label: t('selectAll') },
    ];
    const windowSubmenu = [
      { role: 'minimize', label: t('minimize') }, { role: 'zoom', label: t('zoom') },
      { type: 'separator' }, { role: 'front', label: t('front') },
    ];
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      { label: 'Open DeepTutor', submenu: appSubmenu },
      { label: t('edit'), submenu: editSubmenu },
      { label: t('view'), submenu: viewSubmenu },
      { label: t('core'), submenu: coreSubmenu },
      { role: 'windowMenu', label: t('window'), submenu: windowSubmenu },
    ]));
  }
}

if (!app.requestSingleInstanceLock()) { app.quit(); }
else {
  app.on('second-instance', () => {
    if (!window || window.isDestroyed()) return;
    if (window.isMinimized()) window.restore();
    window.show();
    window.focus();
  });
  app.on('before-quit', event => {
    if (exitAllowed) return;
    event.preventDefault();
    if (quitting) return;
    quitting = true;
    status({ phase: 'stopping', step: 'stopping' });
    void Promise.all([persistWindowState(true), stopWorker()]).finally(() => { exitAllowed = true; app.quit(); });
  });
  app.on('window-all-closed', () => app.quit());
  // Electron waits for ESM evaluation before emitting ready; do not await ready
  // at module scope or the packaged application deadlocks before its first window.
  app.whenReady().then(async () => {
    ui = await readInterface();
    nativeTheme.on('updated', () => void refreshInterface());
    const coreSession = session.fromPartition('persist:deeptutor');
    // The web UI reads this marker to name the client, e.g. "Open DeepTutor for MacOS with Apple Silicon".
    coreSession.setUserAgent(`${coreSession.getUserAgent()} ${agentMarker(app.getVersion())}`);
    coreSession.setPermissionCheckHandler((_contents, permission) => permission === 'clipboard-sanitized-write');
    coreSession.setPermissionRequestHandler(async (contents, permission, callback, details) => {
      if (permission === 'clipboard-sanitized-write') return callback(true);
      if (permission !== 'media' || contents !== view?.webContents || details.requestingUrl && !details.requestingUrl.startsWith(state.url + '/')) return callback(false);
      const result = await dialog.showMessageBox(window, { type: 'question', message: t('mediaPrompt'), buttons: [t('deny'), t('allow')], defaultId: 0, cancelId: 0 });
      callback(result.response === 1);
    });

    // Window memory and adaptive first-run sizing work on every platform.
    const initialBounds = resolveWindowBounds(await readJSON(windowStateFile).catch(() => null));
    zoomFactor = initialBounds.zoomFactor;
    const size = {
      x: initialBounds.x,
      y: initialBounds.y,
      width: initialBounds.width,
      height: initialBounds.height,
      ...minWindowSize(screen.getDisplayMatching(initialBounds).workArea),
    };

    window = new BrowserWindow({
      title: 'Open DeepTutor',
      ...size,
      show: false,
      backgroundColor: currentChromeBackground(),
      ...(WINDOWS
        ? { titleBarStyle: 'hidden', titleBarOverlay: titleBarOverlayOptions(ui.theme) }
        : { titleBarStyle: 'hiddenInset', trafficLightPosition: { x: 18, y: 16 } }),
      webPreferences: { preload: path.join(sourceDirectory, 'preload.cjs'), contextIsolation: true, sandbox: true, nodeIntegration: false },
    });

    if (WINDOWS) {
      window.setAutoHideMenuBar(false);
      window.setMenuBarVisibility(false);
    }

    // Lock shell chrome zoom to 100% so the custom titlebar stays aligned with WCO controls.
    window.webContents.setZoomFactor(1);
    window.webContents.setZoomMode('disabled');
    window.webContents.on('zoom-changed', () => window.webContents.setZoomFactor(1));
    window.webContents.on('will-navigate', event => event.preventDefault());
    window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));

    window.once('ready-to-show', () => {
      if (initialBounds?.maximized) window.maximize();
      window.show();
    });

    const syncLayoutAndState = () => {
      scheduleLayout();
      persistWindowState();
    };
    window.on('resize', syncLayoutAndState);
    window.on('move', () => persistWindowState());
    window.on('moved', () => syncDisplayConstraints());
    window.on('maximize', syncLayoutAndState);
    window.on('unmaximize', syncLayoutAndState);
    window.on('restore', () => syncDisplayConstraints());
    window.on('enter-full-screen', scheduleLayout);
    window.on('leave-full-screen', scheduleLayout);

    const onDisplayChanged = () => syncDisplayConstraints({ clampPosition: true });
    screen.on('display-metrics-changed', onDisplayChanged);
    screen.on('display-removed', onDisplayChanged);
    window.on('close', event => {
      if (!exitAllowed) { event.preventDefault(); app.quit(); }
    });
    window.on('closed', () => { window = undefined; });

    // Synchronous first-frame hydration: the shell reads its state during page
    // load so theme, language and copy are correct before the first paint.
    ipcMain.on('desktop:status-sync', event => {
      trustedShell(event);
      event.returnValue = snapshot();
    });

    for (const [channel, handler] of Object.entries({
      status: () => snapshot(),
      restart: () => { void boot(); },
      logs: async () => { await mkdir(path.dirname(logPath), { recursive: true }); await shell.openPath(path.dirname(logPath)); },
      popupMenu: async (id, position) => {
        if (id === 'preferences') await syncPreferencesFromView();
        return new Promise(resolve => {
          const menu = menuPopups?.get(id);
          if (!menu || !window || window.isDestroyed()) return resolve();
          const x = Number.isFinite(position?.x) ? Math.max(0, Math.round(position.x)) : 8;
          const y = Number.isFinite(position?.y) ? Math.max(0, Math.round(position.y)) : HEADER_HEIGHT;
          menu.popup({ window, x, y, callback: resolve });
        });
      },
    })) ipcMain.handle(`desktop:${channel}`, (event, ...args) => { trustedShell(event); return handler(...args); });

    buildMenu();
    watchInterface();
    await window.loadURL(shellURL);
    // Pinch visual zoom off for the chrome; needs the loaded frame to accept the limits.
    void window.webContents.setVisualZoomLevelLimits(1, 1).catch(() => {});
    void boot();
  }).catch(async error => {
    await logStartupFailure(error);
    dialog.showErrorBox('Open DeepTutor', error.message);
    exitAllowed = true;
    app.quit();
  });
}
