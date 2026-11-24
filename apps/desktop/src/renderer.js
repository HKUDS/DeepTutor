const root = document.documentElement;
const el = id => document.getElementById(id);

const menusNav = el('titlebar-menus');
const tagline = el('tagline');
const loading = el('loading');
const step = el('step');
const problem = el('problem');
const problemTitle = el('problem-title');
const problemBody = el('problem-body');
const problemDetail = el('problem-detail');
const retryBtn = el('retry');
const logsBtn = el('logs');
const edition = el('edition');

root.dataset.platform = window.desktop.platform;

let currentStep = '';
let swapTimer;
let menuSignature = '';
let activeMenuId = null;

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

function renderMenus(menus) {
  if (window.desktop.platform !== 'win32' || !Array.isArray(menus) || !menusNav) return;
  const sig = menus.map(m => `${m.id}:${m.label}`).join('|');
  if (sig === menuSignature) return;
  menuSignature = sig;
  menusNav.textContent = '';

  for (const item of menus) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = item.id === 'app' ? 'titlebar-menu-btn is-brand' : 'titlebar-menu-btn';
    btn.dataset.menuId = item.id;
    btn.setAttribute('aria-haspopup', 'menu');
    btn.setAttribute('aria-expanded', 'false');

    if (item.id === 'app') {
      const icon = document.createElement('img');
      icon.src = '../assets/mark.png';
      icon.alt = '';
      btn.appendChild(icon);
    }
    const label = document.createElement('span');
    label.textContent = item.label;
    btn.appendChild(label);

    // Prevent stealing focus from WebContentsView on click so Edit actions target the web page.
    btn.addEventListener('mousedown', event => event.preventDefault());
    btn.addEventListener('click', async () => {
      if (activeMenuId === item.id) return;
      activeMenuId = item.id;
      btn.setAttribute('aria-expanded', 'true');
      const rect = btn.getBoundingClientRect();
      try {
        await window.desktop.popupMenu(item.id, { x: rect.left, y: rect.bottom + 2 });
      } finally {
        btn.setAttribute('aria-expanded', 'false');
        if (activeMenuId === item.id) activeMenuId = null;
      }
    });

    menusNav.appendChild(btn);
  }
}

function apply(state) {
  if (!state) return;
  root.lang = state.language || 'en';
  root.dataset.theme = state.theme || 'light';
  root.dataset.phase = state.phase || 'starting';
  root.dataset.content = state.contentVisible ? 'visible' : 'hidden';

  renderMenus(state.menus);
  tagline.textContent = state.tagline || '';
  edition.textContent = state.edition || '';
  retryBtn.textContent = state.retry || 'Retry';
  logsBtn.textContent = state.logs || 'Logs';

  const hasProblem = state.phase === 'error' || state.phase === 'stopped';
  loading.hidden = hasProblem;
  problem.hidden = !hasProblem;

  if (hasProblem) {
    problemTitle.textContent = state.title || '';
    problemBody.textContent = state.message || '';
    problemDetail.textContent = state.detail || '';
  } else {
    setStep(state.message || '');
  }
}

retryBtn.addEventListener('click', () => void window.desktop.restart());
logsBtn.addEventListener('click', () => void window.desktop.logs());
window.desktop.onStatus(apply);
void window.desktop.status().then(apply);
