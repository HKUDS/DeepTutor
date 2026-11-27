const root = document.documentElement;
const el = id => document.getElementById(id);

const tagline = el('tagline');
const loading = el('loading');
const progressTrack = el('progress-track');
const progressFill = el('progress-fill');
const step = el('step');
const slowHint = el('slow-hint');
const slowHintText = el('slow-hint-text');
const slowLogsBtn = el('slow-logs');
const problem = el('problem');
const problemTitle = el('problem-title');
const problemBody = el('problem-body');
const problemDetail = el('problem-detail');
const retryBtn = el('retry');
const logsBtn = el('logs');
const edition = el('edition');

root.dataset.platform = window.desktop.platform;

const STEP_PROGRESS = {
  opening: 8,
  starting: 16,
  recovering: 22,
  verifying: 28,
  firstLaunch: 32,
  updating: 36,
  checking: 44,
  preparingUi: 60,
  startingCore: 78,
  openingSpace: 92,
  attached: 100,
  ready: 100,
  stopping: 55,
};

const SLOW_START_MS = 15000;

let currentStep = '';
let currentProgress = 8;
let lastPhase = '';
let swapTimer;
let slowTimer;

function setProgress(percent) {
  const clamped = Math.max(6, Math.min(100, Math.round(percent)));
  currentProgress = clamped;
  progressFill.style.setProperty('--progress', `${clamped}%`);
  progressTrack.setAttribute('aria-valuenow', String(clamped));
}

function resetSlowTimer(isStarting) {
  if (!isStarting) {
    clearTimeout(slowTimer);
    slowTimer = undefined;
    slowHint.hidden = true;
    return;
  }
  if (slowTimer || !slowHint.hidden) return;
  slowTimer = setTimeout(() => {
    slowTimer = undefined;
    if (root.dataset.phase === 'starting' && root.dataset.content !== 'visible') {
      slowHint.hidden = false;
    }
  }, SLOW_START_MS);
}

function setStep(next) {
  if (next === currentStep) return;
  const firstStep = !currentStep;
  currentStep = next;
  clearTimeout(swapTimer);
  if (firstStep) {
    step.classList.remove('is-swapping');
    step.textContent = next;
    return;
  }
  step.classList.add('is-swapping');
  swapTimer = setTimeout(() => {
    step.textContent = next;
    step.classList.remove('is-swapping');
  }, 140);
}

function apply(state) {
  if (!state) return;
  const phase = state.phase || 'starting';
  root.lang = state.language || 'en';
  root.dataset.theme = state.theme || 'light';
  root.dataset.phase = phase;
  root.dataset.content = state.contentVisible ? 'visible' : 'hidden';

  tagline.textContent = state.tagline || '';
  edition.textContent = state.edition || '';
  retryBtn.textContent = state.retry || 'Retry';
  logsBtn.textContent = state.logs || 'Logs';
  slowHintText.textContent = state.slowHint || '';
  slowLogsBtn.textContent = state.logs || 'Logs';

  const hasProblem = phase === 'error' || phase === 'stopped';
  loading.hidden = hasProblem;
  problem.hidden = !hasProblem;

  if (hasProblem) {
    resetSlowTimer(false);
    problemTitle.textContent = state.title || '';
    problemBody.textContent = state.message || '';
    problemDetail.textContent = state.detail || '';
  } else {
    if (lastPhase !== phase && phase === 'starting') {
      currentProgress = 8;
      slowHint.hidden = true;
    }
    const target = state.contentVisible
      ? 100
      : (STEP_PROGRESS[state.step] ?? currentProgress);
    setProgress(phase === 'stopping' ? target : Math.max(currentProgress, target));
    setStep(state.message || '');
    resetSlowTimer(phase === 'starting' && !state.contentVisible);
  }

  lastPhase = phase;
}

retryBtn.addEventListener('click', () => {
  slowHint.hidden = true;
  currentProgress = 8;
  void window.desktop.restart();
});
logsBtn.addEventListener('click', () => void window.desktop.logs());
slowLogsBtn.addEventListener('click', () => void window.desktop.logs());

window.desktop.onStatus(apply);

// Synchronously hydrate before first paint so theme, language, and copy never flash.
try {
  const initial = window.desktop.initialStatus?.();
  if (initial) apply(initial);
  else void window.desktop.status().then(apply);
} catch {
  void window.desktop.status().then(apply);
}

requestAnimationFrame(() => {
  root.dataset.hydrated = 'true';
});
