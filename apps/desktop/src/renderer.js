const $ = id => document.getElementById(id);
const platform = window.desktop.platform;
document.documentElement.dataset.platform = platform;
const step = $('step');
let shownStep = '';
let swapTimer;

function showStep(text) {
  if (text === shownStep) return;
  shownStep = text;
  if (platform === 'darwin') {
    step.textContent = text;
    return;
  }
  clearTimeout(swapTimer);
  step.classList.add('is-swapping');
  swapTimer = setTimeout(() => { step.textContent = text; step.classList.remove('is-swapping'); }, 180);
}

function render(view) {
  const root = document.documentElement;
  root.lang = view.language;
  root.dataset.theme = view.theme;
  root.dataset.phase = view.phase;
  $('tagline').textContent = view.tagline;
  $('edition').textContent = view.edition;
  $('retry').textContent = view.retry;
  $('logs').textContent = view.logs;
  const problem = view.phase === 'error' || view.phase === 'stopped';
  $('loading').hidden = problem;
  $('problem').hidden = !problem;
  $('problem-title').textContent = view.title;
  $('problem-body').textContent = view.message;
  $('problem-detail').textContent = view.detail;
  if (!problem) showStep(view.message);
}

let receivedStatus = false;
window.desktop.onStatus(view => {
  receivedStatus = true;
  render(view);
});
window.desktop.status().then(view => {
  if (!receivedStatus) render(view);
});
$('retry').addEventListener('click', () => window.desktop.restart());
$('logs').addEventListener('click', () => window.desktop.logs());
