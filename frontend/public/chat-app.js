const messagesEl = document.getElementById('messages');
const inputEl = document.getElementById('chat-input');

// Show initial empty state
function showEmptyChat() {
  messagesEl.textContent = '';
  const div = document.createElement('div');
  div.className = 'empty-state';
  const icon = document.createElement('p');
  icon.className = 'empty-state-icon';
  icon.textContent = '\u25C9';
  div.appendChild(icon);
  const line1 = document.createElement('p');
  line1.textContent = 'Send a message to start. The agent has persistent memory.';
  div.appendChild(line1);
  const line2 = document.createElement('p');
  line2.style.cssText = 'margin-top:4px; font-size:11px; color:var(--text-dim)';
  line2.textContent = 'Try: "What database are we using and why?"';
  div.appendChild(line2);
  messagesEl.appendChild(div);
}
showEmptyChat();

let firstMessage = true;
let lastBenchmarkReport = null;
let lastBenchmarkSummary = null;
let lastBenchmarkHistory = [];
let selectedClaimSlot = null;
let claimsAsOf = '';
let claimsDetailOpen = false;
const AUTO_FLUSH_THRESHOLD_PCT = 80;
const PREF_SEED_RESET_KEY = 'cm_seed_reset_before_run';
const PREF_SEED_WIPE_KEY = 'cm_seed_wipe_memory';
const PREF_SEED_CONTINUE_STORY_KEY = 'cm_seed_continue_story';
const PREF_STORY_CURSOR_TURN_KEY = 'cm_story_pack_last_turn';
const PREF_GRAPH_VIEW_MODE_KEY = 'cm_graph_view_mode';
const PREF_GRAPH_REL_FILTER_KEY = 'cm_graph_rel_filter';
const PREF_GRAPH_CONF_FILTER_KEY = 'cm_graph_conf_filter';
const PREF_GRAPH_SEARCH_FILTER_KEY = 'cm_graph_search_filter';

let graphViewMode = 'list';
const graphFilters = {
  relation: 'all',
  minConfidence: 0,
  search: '',
};
let rollingPaneRenderer = null;
let claimsPaneRenderer = null;
let entitiesPaneRenderer = null;
let runtimePaneRenderer = null;
let benchmarkPaneRenderer = null;
let beadsPaneRenderer = null;
let associationsPaneRenderer = null;
let graphListPaneRenderer = null;
let graphControlsPaneRenderer = null;
let graphEdgeDetailPaneRenderer = null;
let graphSummaryPaneRenderer = null;
let graphCanvasHostFactory = null;
let graphSvgCanvasRenderer = null;
let graph3dRuntimeRenderer = null;
let graphDataBuilder = null;
let graphUtilsModule = null;
const sliceLoadState = Object.create(null);

function lazyLoadSlice(path, pick, assign, opts) {
  const cfg = opts || {};
  return import(path)
    .then((mod) => {
      const value = typeof pick === 'function' ? pick(mod || {}) : null;
      if (value !== null && value !== undefined) {
        if (typeof assign === 'function') assign(value);
        return value;
      }
      if (typeof assign === 'function') assign(null);
      if (cfg.throwOnMissing) {
        throw new Error(String(cfg.missingError || 'slice_missing_export'));
      }
      return null;
    })
    .catch((err) => {
      if (typeof assign === 'function') assign(null);
      if (cfg.throwOnMissing) throw err;
      return null;
    });
}

function renderViaSlice(renderer, renderAttempt, fallbackRender, ensureLoad) {
  if (renderer) {
    try {
      renderAttempt(renderer);
      return true;
    } catch (_) {
      // fallback below
    }
  }

  if (typeof fallbackRender === 'function') fallbackRender();
  if (typeof ensureLoad === 'function') ensureLoad();
  return false;
}

function callSliceWithFallback(binding, invoke, fallback, ensureLoad, isValid) {
  if (binding) {
    try {
      const out = invoke(binding);
      if (!isValid || isValid(out)) return out;
    } catch (_) {
      // fallback below
    }
  }

  if (typeof ensureLoad === 'function') ensureLoad();
  return fallback();
}

function ensureSliceLoad(key, beginLoad) {
  const k = String(key || '').trim();
  if (!k) return Promise.resolve(null);
  if (sliceLoadState[k]) return sliceLoadState[k];

  sliceLoadState[k] = Promise.resolve()
    .then(() => (typeof beginLoad === 'function' ? beginLoad() : null))
    .finally(() => {
      delete sliceLoadState[k];
      refreshMemory();
    });

  return sliceLoadState[k];
}

function ensureSliceBinding(currentValue, key, path, pick, assign, opts) {
  if (currentValue) return Promise.resolve(currentValue);
  if (sliceLoadState[key]) return sliceLoadState[key];
  return ensureSliceLoad(key, () => lazyLoadSlice(path, pick, assign, opts));
}

function arrayOrEmpty(value) {
  return Array.isArray(value) ? value : [];
}

function arrayOr(value, fallback) {
  return Array.isArray(value) ? value : fallback;
}

function firstPayloadError(data) {
  const errors = arrayOrEmpty((data || {}).errors);
  if (!errors.length) return '';
  const first = errors[0] || {};
  return String(first.error || JSON.stringify(first));
}

function loadGraphPrefs() {
  try {
    const mode = String(localStorage.getItem(PREF_GRAPH_VIEW_MODE_KEY) || 'list').toLowerCase();
    if (mode === 'graph' || mode === 'list') graphViewMode = mode;

    const rel = String(localStorage.getItem(PREF_GRAPH_REL_FILTER_KEY) || 'all').trim();
    graphFilters.relation = rel || 'all';

    const conf = Number(localStorage.getItem(PREF_GRAPH_CONF_FILTER_KEY) || 0);
    graphFilters.minConfidence = Number.isFinite(conf) ? Math.max(0, Math.min(1, conf)) : 0;

    graphFilters.search = String(localStorage.getItem(PREF_GRAPH_SEARCH_FILTER_KEY) || '').trim();
  } catch (_) {
    // best effort only
  }
}

function saveGraphPrefs() {
  try {
    localStorage.setItem(PREF_GRAPH_VIEW_MODE_KEY, String(graphViewMode || 'list'));
    localStorage.setItem(PREF_GRAPH_REL_FILTER_KEY, String(graphFilters.relation || 'all'));
    localStorage.setItem(PREF_GRAPH_CONF_FILTER_KEY, String(graphFilters.minConfidence || 0));
    localStorage.setItem(PREF_GRAPH_SEARCH_FILTER_KEY, String(graphFilters.search || ''));
  } catch (_) {
    // best effort only
  }
}

loadGraphPrefs();

const authBtnEl = document.getElementById('auth-btn');
const authStatusEl = document.getElementById('auth-status');
const modelSelectEl = document.getElementById('model-select');
let authEnabled = false;
let authReady = false;
let authClient = null;
let authRequestedScope = 'openid profile email';
let refreshTimerId = null;
let refreshErrorStreak = 0;
let authRedirecting = false;
const AUTH_LOOP_GUARD_KEY = 'CM_AUTH_LOOP_GUARD';
let modelOptionsHydrated = false;

function renderDemoModelOptions(payload) {
  if (!modelSelectEl) return;
  modelOptionsHydrated = true;
  const rows = arrayOrEmpty((payload || {}).options);
  const selected = String((payload || {}).override_model || '').trim();
  modelSelectEl.innerHTML = '';

  const autoOpt = document.createElement('option');
  autoOpt.value = '';
  const autoModel = String((payload || {}).auto_model || '').trim();
  autoOpt.textContent = autoModel ? ('auto (' + autoModel + ')') : 'auto';
  modelSelectEl.appendChild(autoOpt);

  rows.forEach((row) => {
    const modelId = String((row || {}).model_id || '').trim();
    if (!modelId) return;
    const label = String((row || {}).label || modelId).trim();
    const available = !!(row || {}).available;
    const requiredEnv = String((row || {}).required_env || '').trim();
    const opt = document.createElement('option');
    opt.value = modelId;
    opt.textContent = available ? label : (label + ' (missing creds: ' + requiredEnv + ')');
    opt.disabled = !available;
    modelSelectEl.appendChild(opt);
  });

  modelSelectEl.value = selected;
}

async function loadDemoModels() {
  if (!modelSelectEl) return;
  try {
    const res = await fetch('/api/demo/models');
    const data = await res.json();
    if (!res.ok || !data || !data.ok) return;
    renderDemoModelOptions(data);
  } catch (_) {
    // best effort only
  }
}

async function changeDemoModel(modelId) {
  const nextModel = String(modelId || '').trim();
  if (!modelSelectEl) return;
  modelSelectEl.disabled = true;
  try {
    const res = await fetch('/api/demo/model', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ model_id: nextModel }),
    });
    const data = await res.json();
    if (!res.ok || !data || !data.ok) {
      throw new Error(String((data || {}).error || ('HTTP ' + res.status)));
    }
    renderDemoModelOptions(data);
    const selected = String((data || {}).selected_model || '').trim();
    addMsg('system', nextModel ? ('Model selected: ' + selected) : ('Model selection reset to auto (' + selected + ')'));
  } catch (err) {
    alert('Model selection failed: ' + String((err && err.message) || err || 'unknown_error'));
    loadDemoModels();
  } finally {
    modelSelectEl.disabled = false;
  }
}

function readAuthLoopGuard() {
  try {
    const raw = sessionStorage.getItem(AUTH_LOOP_GUARD_KEY) || '{}';
    const row = JSON.parse(raw);
    return {
      count: Number(row.count || 0),
      ts: Number(row.ts || 0),
      lastError: String(row.lastError || ''),
    };
  } catch (_) {
    return { count: 0, ts: 0, lastError: '' };
  }
}

function writeAuthLoopGuard(next) {
  try {
    sessionStorage.setItem(AUTH_LOOP_GUARD_KEY, JSON.stringify(next || {}));
  } catch (_) {
    // best effort only
  }
}

function clearAuthLoopGuard() {
  writeAuthLoopGuard({ count: 0, ts: 0, lastError: '' });
}

function setAuthStatus(text) {
  if (!authStatusEl) return;
  authStatusEl.style.display = authEnabled ? 'inline' : 'none';
  authStatusEl.textContent = String(text || '');
}

function setAuthButton(label, onClick) {
  if (!authBtnEl) return;
  if (!authEnabled) {
    authBtnEl.style.display = 'none';
    return;
  }
  authBtnEl.style.display = 'inline-block';
  authBtnEl.textContent = String(label || 'Sign in');
  authBtnEl.onclick = typeof onClick === 'function' ? onClick : null;
}

function mergeAuthScopes(baseScopes, extraScopes) {
  const out = [];
  const seen = new Set();
  const add = (raw) => {
    String(raw || '')
      .split(/\s+/)
      .map(s => s.trim())
      .filter(Boolean)
      .forEach((s) => {
        if (seen.has(s)) return;
        seen.add(s);
        out.push(s);
      });
  };
  add(baseScopes);
  add(extraScopes);
  return out.join(' ');
}

async function redirectToLogin(forcePrompt) {
  if (!authClient) return;
  const guard = readAuthLoopGuard();
  writeAuthLoopGuard({ count: guard.count + 1, ts: Date.now(), lastError: guard.lastError || '' });
  const qp = new URLSearchParams(window.location.search);
  const next = String(qp.get('next') || (window.location.pathname + window.location.search) || '/').trim();
  const loginOpts = {
    appState: { returnTo: next },
    authorizationParams: forcePrompt ? { prompt: 'login', scope: authRequestedScope } : { scope: authRequestedScope },
  };
  if (window.self !== window.top) {
    loginOpts.openUrl = (url) => {
      window.top.location.assign(url);
    };
  }
  await authClient.loginWithRedirect(loginOpts);
}

async function initAuthGate() {
  let callbackReturnTo = '';
  let requestedNext = '';
  const directBase = String(window.__CORE_MEMORY_HOSTED_DIRECT_BASE || '').trim();
  const rawFetch = typeof window.__CORE_MEMORY_NATIVE_FETCH === 'function'
    ? window.__CORE_MEMORY_NATIVE_FETCH
    : window.fetch.bind(window);
  let meta = null;
  try {
    const res = await rawFetch('/api/meta');
    if (res.ok) {
      meta = await res.json();
    }
  } catch (_) {
    meta = null;
  }
  if ((!meta || !meta.auth) && directBase) {
    try {
      const res = await rawFetch(directBase + '/api/meta');
      if (res.ok) {
        meta = await res.json();
      }
    } catch (_) {
      // ignore fallback errors
    }
  }
  if (!meta || !meta.auth) {
    authEnabled = true;
    authReady = false;
    setAuthStatus('Auth configuration unavailable. Retry in a moment.');
    setAuthButton('Retry', () => window.location.reload());
    return false;
  }

  const auth = (meta && meta.auth) || {};
  authEnabled = !!auth.enabled;
  if (!authEnabled) {
    authReady = true;
    return true;
  }

  const domain = String(auth.domain || '').trim();
  const clientId = String(auth.client_id || '').trim();
  const audience = String(auth.audience || '').trim();
  const audienceScope = String(auth.scope || '').trim();
  authRequestedScope = mergeAuthScopes('openid profile email', audienceScope);
  if (!domain || !clientId || !window.auth0 || typeof window.auth0.createAuth0Client !== 'function') {
    setAuthStatus('Auth is enabled but not fully configured.');
    setAuthButton('Sign in', null);
    return false;
  }

  try {
    const authRedirectUri = window.location.origin.replace(/\/$/, '') + '/';
    authClient = await window.auth0.createAuth0Client({
      domain,
      clientId,
      authorizationParams: {
        audience,
        scope: authRequestedScope,
        redirect_uri: authRedirectUri,
      },
      cacheLocation: 'localstorage',
      useRefreshTokens: true,
    });
    window.__CORE_MEMORY_REFRESH_TOKEN = async () => {
      if (!authClient) return '';
      try {
        const fresh = await authClient.getTokenSilently();
        window.__CORE_MEMORY_SET_TOKEN(fresh || '');
        return String(fresh || '').trim();
      } catch (_) {
        window.__CORE_MEMORY_SET_TOKEN('');
        return '';
      }
    };

    const qp = new URLSearchParams(window.location.search);
    if (String(qp.get('login') || '').trim() === '1') {
      requestedNext = String(qp.get('next') || '').trim();
    }
    if (qp.get('error')) {
      const err = String(qp.get('error') || 'auth_error');
      const desc = String(qp.get('error_description') || '').trim();
      writeAuthLoopGuard({ count: 2, ts: Date.now(), lastError: desc || err });
      setAuthStatus('Auth error: ' + err + (desc ? (' (' + desc + ')') : ''));
      setAuthButton('Sign in', () => redirectToLogin(true));
      return false;
    }

    if (qp.get('code') && qp.get('state')) {
      const cb = await authClient.handleRedirectCallback();
      callbackReturnTo = String(((cb || {}).appState || {}).returnTo || '').trim();
      window.history.replaceState({}, document.title, window.location.pathname);
      try {
        if (window.self !== window.top && window.top.location.origin === window.location.origin) {
          window.top.history.replaceState({}, document.title, window.top.location.pathname);
        }
      } catch (_) {
        // ignore
      }
    }

    const isAuthenticated = await authClient.isAuthenticated();
    if (!isAuthenticated) {
      const guard = readAuthLoopGuard();
      const recent = (Date.now() - Number(guard.ts || 0)) < 90000;
      const tooMany = recent && Number(guard.count || 0) >= 2;
      window.__CORE_MEMORY_SET_TOKEN('');
      if (tooMany) {
        const hasCachedToken = !!window.__CORE_MEMORY_GET_TOKEN();
        const explicitLogin = String(qp.get('login') || '').trim() === '1';
        if (explicitLogin || !hasCachedToken) {
          clearAuthLoopGuard();
        } else {
          const msg = guard.lastError || 'Repeated login redirects detected.';
          setAuthStatus('Auth paused: ' + msg);
          setAuthButton('Retry login', () => {
            clearAuthLoopGuard();
            redirectToLogin(true);
          });
          return false;
        }
      }

      setAuthStatus('Redirecting to login...');
      setAuthButton('Sign in', () => redirectToLogin(true));
      if (!authRedirecting) {
        authRedirecting = true;
        await redirectToLogin(true);
      }
      return false;
    }

    const token = await window.__CORE_MEMORY_REFRESH_TOKEN();
    window.__CORE_MEMORY_SET_TOKEN(token || '');
    if (!token) {
      setAuthStatus('Session expired. Redirecting to login...');
      setAuthButton('Sign in', () => redirectToLogin(true));
      if (!authRedirecting) {
        authRedirecting = true;
        clearAuthLoopGuard();
        await redirectToLogin(true);
      }
      return false;
    }
    clearAuthLoopGuard();

    if (!callbackReturnTo && requestedNext) {
      callbackReturnTo = requestedNext;
    }

    if (callbackReturnTo) {
      try {
        const target = new URL(callbackReturnTo, window.location.origin);
        if (target.origin === window.location.origin) {
          const currentPath = window.self !== window.top ? String(window.top.location.pathname || '/') : String(window.location.pathname || '/');
          const currentSearch = window.self !== window.top ? String(window.top.location.search || '') : String(window.location.search || '');
          if (String(target.pathname || '/') !== currentPath || String(target.search || '') !== currentSearch) {
            if (window.self !== window.top) {
              window.top.location.assign(target.toString());
            } else {
              window.location.assign(target.toString());
            }
            return false;
          }
        }
      } catch (_) {
        // ignore invalid return targets
      }
    }

    const user = await authClient.getUser();
    const email = String((user && user.email) || '').trim();
    setAuthStatus(email ? ('Signed in: ' + email) : 'Signed in');
    setAuthButton('Sign out', () => {
      window.__CORE_MEMORY_SET_TOKEN('');
      window.__CORE_MEMORY_REFRESH_TOKEN = async () => '';
      authClient.logout({
        logoutParams: { returnTo: authRedirectUri },
      });
    });
    authReady = true;
    return true;
  } catch (err) {
    window.__CORE_MEMORY_SET_TOKEN('');
    window.__CORE_MEMORY_REFRESH_TOKEN = async () => '';
    const emsg = String((err && err.message) || err || 'unknown');
    if (/login_required|consent_required|interaction_required/i.test(emsg)) {
      setAuthStatus('Session expired. Redirecting to login...');
      setAuthButton('Sign in', () => redirectToLogin(true));
      if (!authRedirecting) {
        authRedirecting = true;
        clearAuthLoopGuard();
        try { await redirectToLogin(true); } catch (_) {}
      }
      return false;
    }
    setAuthStatus('Auth error: ' + emsg);
    setAuthButton('Sign in', () => redirectToLogin(true));
    return false;
  }
}

function getStoryCursorTurn() {
  try {
    const raw = Number(localStorage.getItem(PREF_STORY_CURSOR_TURN_KEY) || 0);
    return Number.isFinite(raw) ? Math.max(0, Math.floor(raw)) : 0;
  } catch (_) {
    return 0;
  }
}

function setStoryCursorTurn(turnNo) {
  const n = Number(turnNo || 0);
  const v = Number.isFinite(n) ? Math.max(0, Math.floor(n)) : 0;
  try {
    localStorage.setItem(PREF_STORY_CURSOR_TURN_KEY, String(v));
  } catch (_) {
    // best effort only
  }
  refreshStoryCursorLabel();
}

function refreshStoryCursorLabel() {
  const label = document.getElementById('story-cursor-label');
  if (!label) return;
  label.textContent = 'Story cursor: turn ' + String(getStoryCursorTurn());
}

function openReagraphArchive() {
  const overlay = document.getElementById('graph-overlay');
  const frame = document.getElementById('graph-overlay-frame');
  if (!overlay || !frame) {
    const rel = './graph';
    const url = new URL(rel, window.location.href).toString();
    window.location.assign(url);
    return;
  }

  const qp = new URLSearchParams(window.location.search);
  const graphUrl = new URL('./graph', window.location.href);
  const apiBase = String(qp.get('api_base') || '').trim();
  if (apiBase) graphUrl.searchParams.set('api_base', apiBase);
  graphUrl.searchParams.set('overlay', '1');

  if (!frame.getAttribute('src')) {
    frame.setAttribute('src', graphUrl.toString());
  }

  overlay.classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeGraphOverlay() {
  const overlay = document.getElementById('graph-overlay');
  if (overlay) overlay.classList.remove('open');
  document.body.style.overflow = '';
}

document.addEventListener('keydown', (evt) => {
  if (evt.key !== 'Escape') return;
  const overlay = document.getElementById('graph-overlay');
  if (!overlay || !overlay.classList.contains('open')) return;
  closeGraphOverlay();
});

function resetStoryCursor(silent) {
  setStoryCursorTurn(0);
  if (!silent) {
    addMsg('system', 'Story-pack cursor reset. Next Seed starts at turn 1.');
  }
}

function loadSeedResetPrefs() {
  let resetBeforeRun = false;
  let wipeMemory = false;
  let continueStory = true;
  try {
    const resetRaw = localStorage.getItem(PREF_SEED_RESET_KEY);
    if (resetRaw === '0' || resetRaw === 'false') resetBeforeRun = false;
    const wipeRaw = localStorage.getItem(PREF_SEED_WIPE_KEY);
    if (wipeRaw === '1' || wipeRaw === 'true') wipeMemory = true;
    const continueRaw = localStorage.getItem(PREF_SEED_CONTINUE_STORY_KEY);
    if (continueRaw === '0' || continueRaw === 'false') continueStory = false;
  } catch (_) {
    // best effort only
  }
  const resetEl = document.getElementById('seed-reset-before-run');
  const wipeEl = document.getElementById('seed-wipe-memory');
  const continueEl = document.getElementById('seed-continue-story');
  if (resetEl) resetEl.checked = !!resetBeforeRun;
  if (wipeEl) wipeEl.checked = !!wipeMemory;
  if (continueEl) continueEl.checked = !!continueStory;
  refreshStoryCursorLabel();
}

function saveSeedResetPrefs() {
  const resetEl = document.getElementById('seed-reset-before-run');
  const wipeEl = document.getElementById('seed-wipe-memory');
  const continueEl = document.getElementById('seed-continue-story');
  try {
    localStorage.setItem(PREF_SEED_RESET_KEY, resetEl && resetEl.checked ? '1' : '0');
    localStorage.setItem(PREF_SEED_WIPE_KEY, wipeEl && wipeEl.checked ? '1' : '0');
    localStorage.setItem(PREF_SEED_CONTINUE_STORY_KEY, continueEl && continueEl.checked ? '1' : '0');
  } catch (_) {
    // best effort only
  }
}

function closeSessionPopover() {
  const pop = document.getElementById('session-popover');
  if (pop) pop.classList.remove('open');
}

function toggleSessionPopover(evt) {
  if (evt) evt.stopPropagation();
  const pop = document.getElementById('session-popover');
  if (!pop) return;
  pop.classList.toggle('open');
}

function bindSessionPopoverControls() {
  const badge = document.getElementById('session-badge');
  if (!badge) return;
  badge.style.cursor = 'pointer';
  badge.style.userSelect = 'none';
  badge.setAttribute('role', 'button');
  badge.setAttribute('tabindex', '0');
  if (badge.__cmPopoverBound) return;
  badge.addEventListener('click', (e) => toggleSessionPopover(e));
  badge.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      toggleSessionPopover(e);
    }
  });
  badge.__cmPopoverBound = true;
}

function bindUiEventHandlers() {
  if (document.body.__cmUiHandlersBound) return;

  const pop = document.getElementById('session-popover');
  if (pop) {
    pop.addEventListener('click', (event) => event.stopPropagation());
  }

  const resetBeforeRunEl = document.getElementById('seed-reset-before-run');
  const wipeMemoryEl = document.getElementById('seed-wipe-memory');
  const continueStoryEl = document.getElementById('seed-continue-story');
  if (resetBeforeRunEl) resetBeforeRunEl.addEventListener('change', saveSeedResetPrefs);
  if (wipeMemoryEl) wipeMemoryEl.addEventListener('change', saveSeedResetPrefs);
  if (continueStoryEl) continueStoryEl.addEventListener('change', saveSeedResetPrefs);

  const modelSelect = document.getElementById('model-select');
  if (modelSelect) {
    modelSelect.addEventListener('change', (event) => {
      const next = String((event && event.target && event.target.value) || '').trim();
      changeDemoModel(next);
    });
  }

  const flushBtn = document.getElementById('btn-flush-session');
  if (flushBtn) flushBtn.addEventListener('click', flushSession);

  const openGraphBtn = document.getElementById('btn-open-graph');
  if (openGraphBtn) openGraphBtn.addEventListener('click', openReagraphArchive);

  const chatInput = document.getElementById('chat-input');
  if (chatInput) {
    chatInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') sendMessage();
    });
  }

  const sendBtn = document.getElementById('btn-send-message');
  if (sendBtn) sendBtn.addEventListener('click', sendMessage);

  const tabSelect = document.getElementById('tab-selector');
  if (tabSelect) {
    tabSelect.addEventListener('change', (event) => {
      const next = String((event && event.target && event.target.value) || '').trim();
      if (next) switchTab(next);
    });
  }

  const seedBtn = document.getElementById('btn-seed');
  if (seedBtn) seedBtn.addEventListener('click', seedMemory);

  const benchmarkBtn = document.getElementById('btn-benchmark');
  if (benchmarkBtn) benchmarkBtn.addEventListener('click', runBenchmark);

  const modal = document.getElementById('modal');
  if (modal) {
    modal.addEventListener('click', (event) => {
      if (event.target === modal) closeModal();
    });
  }

  const modalCloseBtn = document.getElementById('btn-modal-close');
  if (modalCloseBtn) modalCloseBtn.addEventListener('click', closeModal);

  const graphOverlay = document.getElementById('graph-overlay');
  if (graphOverlay) {
    graphOverlay.addEventListener('click', (event) => {
      if (event.target === graphOverlay) closeGraphOverlay();
    });
  }

  const closeGraphBtn = document.getElementById('btn-close-graph-overlay');
  if (closeGraphBtn) closeGraphBtn.addEventListener('click', closeGraphOverlay);

  const newSessionBtn = document.getElementById('btn-session-new');
  if (newSessionBtn) newSessionBtn.addEventListener('click', () => startFreshSessionNow(false));

  const hardResetBtn = document.getElementById('btn-session-hard-reset');
  if (hardResetBtn) hardResetBtn.addEventListener('click', () => startFreshSessionNow(true));

  const resetCursorBtn = document.getElementById('btn-story-cursor-reset');
  if (resetCursorBtn) resetCursorBtn.addEventListener('click', () => resetStoryCursor(false));

  document.body.__cmUiHandlersBound = true;
}

async function resetSessionForSeed(opts = {}) {
  const wipeMemory = !!opts.wipeMemory;
  if (wipeMemory) {
    const ok = window.confirm('Hard reset will clear demo memory data before creating a new session. Continue?');
    if (!ok) {
      throw new Error('Hard reset canceled');
    }
  }
  const res = await fetch('/api/session/reset', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({wipe_memory: !!wipeMemory}),
  });
  const data = await res.json();
  if (!res.ok || !data.ok) {
    throw new Error(data.error || ('HTTP ' + res.status));
  }
  return data;
}

async function startFreshSessionNow(wipeMemory) {
  try {
    const out = await resetSessionForSeed({wipeMemory: !!wipeMemory});
    if (wipeMemory) {
      setStoryCursorTurn(0);
    }
    addMsg(
      'system',
      'Fresh session started: ' + String(out.new_session || 'n/a') +
      (out.wiped_memory ? ' (memory cleared)' : '')
    );
    closeSessionPopover();
    refreshMemory();
  } catch (err) {
    if (String(err && err.message || '') === 'Hard reset canceled') return;
    alert('Failed to reset session: ' + err.message);
  }
}

function loadClaimsStateFromUrl() {
  try {
    const u = new URL(window.location.href);
    const slot = (u.searchParams.get('cm_slot') || '').trim();
    const asof = (u.searchParams.get('cm_as_of') || '').trim();
    if (slot) selectedClaimSlot = slot;
    if (asof) claimsAsOf = asof;
  } catch (_) {
    // best effort only
  }
}

function syncClaimsStateToUrl() {
  try {
    const u = new URL(window.location.href);
    if (selectedClaimSlot) u.searchParams.set('cm_slot', selectedClaimSlot);
    else u.searchParams.delete('cm_slot');
    if (claimsAsOf) u.searchParams.set('cm_as_of', claimsAsOf);
    else u.searchParams.delete('cm_as_of');
    window.history.replaceState({}, '', u.toString());
  } catch (_) {
    // best effort only
  }
}

function addMsg(role, text, turnId) {
  if (firstMessage && role !== 'init') {
    messagesEl.textContent = '';
    firstMessage = false;
  }
  const div = document.createElement('div');
  div.className = 'msg msg-' + role;
  div.textContent = text;
  if (turnId) {
    const meta = document.createElement('div');
    meta.className = 'msg-meta';
    meta.textContent = turnId;
    div.appendChild(meta);
  }
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

async function parseApiJsonResponse(res, label) {
  const status = Number(res && res.status || 0);
  const raw = await res.text();
  let data = null;
  try {
    data = raw ? JSON.parse(raw) : {};
  } catch (_) {
    const snippet = String(raw || '').slice(0, 120).replace(/\s+/g, ' ');
    throw new Error((label || 'request') + ' returned non-JSON (HTTP ' + status + '): ' + snippet);
  }
  if (!res.ok || (data && data.ok === false)) {
    const detail = String((data && (data.error || data.detail || data.message)) || ('HTTP ' + status));
    throw new Error(detail);
  }
  return data || {};
}

async function sendMessage() {
  if (authEnabled && !authReady) {
    addMsg('system', 'Sign in required before sending messages.');
    return;
  }
  const text = inputEl.value.trim();
  if (!text) return;
  inputEl.value = '';
  addMsg('user', text);
  const progressMsg = addMsg('system', 'Chat pipeline: queued');
  inputEl.disabled = true;

  try {
    const startRes = await fetch('/api/chat/start', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: text}),
    });
    const start = await parseApiJsonResponse(startRes, 'chat start');
    const jobId = String(start.job_id || '').trim();
    if (!jobId) throw new Error('chat_job_missing_id');

    let cursor = 0;
    let data = null;
    const deadline = Date.now() + 180000;

    while (Date.now() < deadline) {
      const statusRes = await fetch('/api/chat/status/' + encodeURIComponent(jobId) + '?cursor=' + String(cursor));
      const status = await parseApiJsonResponse(statusRes, 'chat status');
      const events = arrayOrEmpty(status.events);
      if (events.length > 0) {
        cursor = Number(status.cursor_next || cursor || 0);
        const lastEvt = events[events.length - 1] || {};
        const msg = String(lastEvt.message || lastEvt.stage || status.stage || 'running').trim();
        if (msg) {
          progressMsg.textContent = 'Chat pipeline: ' + msg;
        }
      }

      if (status.done) {
        if (status.error) throw new Error(String(status.error));
        data = status.result || null;
        break;
      }

      const waitMs = Math.max(200, Math.min(1200, Number(status.poll_after_ms || 450)));
      await new Promise((resolve) => setTimeout(resolve, waitMs));
    }

    if (!data) {
      throw new Error('chat_status_timeout');
    }

    progressMsg.remove();
    addMsg('assistant', (data.assistant || data.response || ''), data.turn_id);
    if (data.last_answer) {
      const d = (data.last_answer && data.last_answer.diagnostics) ? data.last_answer.diagnostics : data.last_answer;
      const gLevel = String(d.grounding_level || 'n/a');
      addMsg(
        'system',
        'Answer diagnostics: outcome=' + (d.answer_outcome || 'n/a') +
        ', surface=' + (d.source_surface || 'n/a') +
        ', anchor=' + (d.anchor_reason || 'n/a') +
        ', mode=' + (d.retrieval_mode || 'n/a') +
        ', grounding=' + gLevel
      );
    }
    if (data.auto_flushed) {
      addMsg('system', 'Auto-flush triggered. Session reset, rolling window rebuilt.');
    }
  } catch (err) {
    progressMsg.remove();
    addMsg('assistant', 'Error: ' + err.message);
  }

  inputEl.disabled = false;
  inputEl.focus();
  refreshMemory();
}

function beadTypeClass(type) {
  const known = ['decision','lesson','goal','evidence','context','outcome','checkpoint','process_flush','session_start','session_end'];
  return known.includes(type) ? 'bead-type-' + type : 'bead-type-default';
}

function statusClass(status) {
  const known = ['open','default','candidate','promoted','archived','conflict'];
  return known.includes(status) ? 'status-' + status : 'status-default';
}

function renderBeadsFallback(beads) {
  const el = document.getElementById('tab-beads');
  el.textContent = '';
  if (!beads.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = 'No beads yet';
    el.appendChild(empty);
    return;
  }
  beads.forEach(b => {
    const card = document.createElement('div');
    card.className = 'bead-card';
    card.addEventListener('click', () => showBead(b.id));

    const header = document.createElement('div');
    header.className = 'bead-header';

    const typeSpan = document.createElement('span');
    typeSpan.className = 'bead-type ' + beadTypeClass(b.type);
    typeSpan.textContent = b.type;
    header.appendChild(typeSpan);

    const titleSpan = document.createElement('span');
    titleSpan.className = 'bead-title';
    titleSpan.textContent = b.title;
    header.appendChild(titleSpan);

    const statusSpan = document.createElement('span');
    statusSpan.className = 'bead-status ' + statusClass(b.status);
    statusSpan.textContent = b.status;
    header.appendChild(statusSpan);

    card.appendChild(header);

    if (b.summary && b.summary.length) {
      const sumDiv = document.createElement('div');
      sumDiv.className = 'bead-summary';
      sumDiv.textContent = b.summary.join(' \u00B7 ');
      card.appendChild(sumDiv);
    }

    const idDiv = document.createElement('div');
    idDiv.className = 'bead-id';
    idDiv.textContent = b.id + ' \u00B7 ' + (b.source_turn_ids.join(', ') || 'no turn') + (b.hydrate_available ? ' \u00B7 hydrate\u2713' : '');
    card.appendChild(idDiv);

    el.appendChild(card);
  });
}

function ensureBeadsPaneRenderer() {
  return ensureSliceBinding(
    beadsPaneRenderer,
    'beadsPaneRenderer',
    '/chat-slices/beads-pane.js',
    (mod) => (mod && typeof mod.renderBeadsPane === 'function' ? mod.renderBeadsPane : null),
    (value) => { beadsPaneRenderer = value; }
  );
}

function renderBeads(beads) {
  const safeBeads = arrayOrEmpty(beads);
  const el = document.getElementById('tab-beads');
  if (!el) return;

  renderViaSlice(
    beadsPaneRenderer,
    (renderer) => renderer(el, {
      beads: safeBeads,
      beadTypeClass,
      statusClass,
      onOpenBead: showBead,
    }),
    () => renderBeadsFallback(safeBeads),
    ensureBeadsPaneRenderer
  );
}

function renderAssociationsFallback(assocs) {
  const el = document.getElementById('tab-associations');
  el.textContent = '';
  if (!assocs.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = 'No associations yet';
    el.appendChild(empty);
    return;
  }
  assocs.forEach(a => {
    const card = document.createElement('div');
    card.className = 'assoc-card';

    const rel = document.createElement('div');
    rel.className = 'assoc-rel';
    rel.textContent = a.relationship;
    card.appendChild(rel);

    const beads = document.createElement('div');
    beads.className = 'assoc-beads';
    beads.textContent = a.source_bead.slice(0, 16) + ' \u2192 ' + a.target_bead.slice(0, 16);
    card.appendChild(beads);

    if (a.explanation) {
      const expl = document.createElement('div');
      expl.className = 'assoc-expl';
      expl.textContent = a.explanation;
      card.appendChild(expl);
    }

    el.appendChild(card);
  });
}

function ensureAssociationsPaneRenderer() {
  return ensureSliceBinding(
    associationsPaneRenderer,
    'associationsPaneRenderer',
    '/chat-slices/associations-pane.js',
    (mod) => (mod && typeof mod.renderAssociationsPane === 'function' ? mod.renderAssociationsPane : null),
    (value) => { associationsPaneRenderer = value; }
  );
}

function renderAssociations(assocs) {
  const safeAssocs = arrayOrEmpty(assocs);
  const el = document.getElementById('tab-associations');
  if (!el) return;

  renderViaSlice(
    associationsPaneRenderer,
    (renderer) => renderer(el, { assocs: safeAssocs }),
    () => renderAssociationsFallback(safeAssocs),
    ensureAssociationsPaneRenderer
  );
}

function normalizeGraphEdgesFallback(assocs) {
  const out = [];
  function numConfidence(v) {
    const n = Number(v);
    return Number.isFinite(n) ? Math.max(0, Math.min(1, n)) : null;
  }
  (assocs || []).forEach((a, idx) => {
    const src = String((a || {}).source_bead || (a || {}).source_bead_id || '').trim();
    const dst = String((a || {}).target_bead || (a || {}).target_bead_id || '').trim();
    if (!src || !dst) return;
    out.push({
      id: String((a || {}).id || ('edge-' + idx + '-' + src.slice(0, 6) + '-' + dst.slice(0, 6))),
      source: src,
      target: dst,
      relationship: String((a || {}).relationship || 'associated_with'),
      confidence: numConfidence((a || {}).confidence),
      reason_text: String((a || {}).reason_text || (a || {}).explanation || ''),
    });
  });
  return out;
}

function applyGraphFiltersFallback(edges, beadMap, filters) {
  const rel = String((filters || {}).relation || 'all');
  const minConfidence = Number((filters || {}).minConfidence || 0);
  const search = String((filters || {}).search || '').trim().toLowerCase();
  const titleFor = (id) => {
    const bead = (beadMap || {})[String(id || '')] || {};
    return String(bead.title || id || 'n/a');
  };

  return (edges || []).filter(e => {
    if (rel !== 'all' && String((e || {}).relationship || '') !== rel) return false;
    if ((e || {}).confidence !== null && Number.isFinite(minConfidence) && Number(e.confidence) < minConfidence) return false;
    if (!search) return true;
    const srcTitle = titleFor((e || {}).source).toLowerCase();
    const dstTitle = titleFor((e || {}).target).toLowerCase();
    const hay = [
      srcTitle,
      dstTitle,
      String((e || {}).relationship || '').toLowerCase(),
      String((e || {}).reason_text || '').toLowerCase(),
      String((e || {}).source || '').toLowerCase(),
      String((e || {}).target || '').toLowerCase(),
    ].join(' ');
    return hay.includes(search);
  });
}

function ensureGraphUtilsModule() {
  return ensureSliceBinding(
    graphUtilsModule,
    'graphUtilsModule',
    '/chat-slices/graph-utils.js',
    (mod) => (mod && typeof mod.graphNodeTitle === 'function' ? mod : null),
    (value) => { graphUtilsModule = value; }
  );
}

function callGraphUtils(methodName, invoke, fallback) {
  const fn = graphUtilsModule && graphUtilsModule[methodName];
  if (typeof fn === 'function') {
    try {
      return invoke(fn);
    } catch (_) {
      // fallback below
    }
  }
  ensureGraphUtilsModule();
  return fallback();
}

function graphNumConfidence(v) {
  return callGraphUtils(
    'graphNumConfidence',
    (fn) => fn(v),
    () => {
      const n = Number(v);
      return Number.isFinite(n) ? Math.max(0, Math.min(1, n)) : null;
    }
  );
}

function graphNodeTitle(beadMap, id) {
  return callGraphUtils(
    'graphNodeTitle',
    (fn) => fn(beadMap || {}, id),
    () => {
      const bead = (beadMap || {})[String(id || '')] || {};
      return String(bead.title || id || 'n/a');
    }
  );
}

function normalizeGraphEdges(assocs) {
  return callGraphUtils(
    'normalizeGraphEdges',
    (fn) => fn(assocs || []),
    () => normalizeGraphEdgesFallback(assocs || [])
  );
}

function applyGraphFilters(edges, beadMap) {
  const filters = {
    relation: String(graphFilters.relation || 'all'),
    minConfidence: Number(graphFilters.minConfidence || 0),
    search: String(graphFilters.search || ''),
  };
  return callGraphUtils(
    'applyGraphFilters',
    (fn) => fn(edges || [], beadMap || {}, filters),
    () => applyGraphFiltersFallback(edges || [], beadMap || {}, filters)
  );
}

function graphEntityId(v) {
  return callGraphUtils(
    'graphEntityId',
    (fn) => fn(v),
    () => {
      if (v && typeof v === 'object') return String(v.id || v.name || '');
      return String(v || '');
    }
  );
}

function ensureGraph3DRuntimeRenderer() {
  return ensureSliceBinding(
    graph3dRuntimeRenderer,
    'graph3dRuntimeRenderer',
    '/chat-slices/graph-3d-runtime.js',
    (mod) => (mod && typeof mod.renderGraph3DRuntimePane === 'function' ? mod.renderGraph3DRuntimePane : null),
    (value) => { graph3dRuntimeRenderer = value; },
    { throwOnMissing: true, missingError: 'graph_3d_runtime_missing_exports' }
  );
}

function renderGraph3DRuntime(opts) {
  const safe = opts || {};

  return ensureGraph3DRuntimeRenderer().then((renderer) => renderer(safe));
}

function reagraphDataFromEdgesFallback(edges, beadMap) {
  const nodeMap = {};
  const degree = {};
  const typeColor = (type) => {
    const t = String(type || '').toLowerCase();
    if (t === 'decision') return '#6ae276';
    if (t === 'evidence') return '#22d3ee';
    if (t === 'lesson') return '#4ade80';
    if (t === 'goal') return '#fbbf24';
    if (t === 'outcome') return '#f87171';
    if (t === 'context') return '#8b8fa3';
    return '#7ca0ab';
  };

  (edges || []).forEach((e) => {
    const s = String((e || {}).source || '');
    const t = String((e || {}).target || '');
    if (!s || !t) return;
    degree[s] = Number(degree[s] || 0) + 1;
    degree[t] = Number(degree[t] || 0) + 1;
    if (!nodeMap[s]) {
      const b = beadMap[s] || {};
      nodeMap[s] = { id: s, title: String(b.title || s), type: String(b.type || 'context') };
    }
    if (!nodeMap[t]) {
      const b = beadMap[t] || {};
      nodeMap[t] = { id: t, title: String(b.title || t), type: String(b.type || 'context') };
    }
  });

  const nodes = Object.values(nodeMap).map((n) => {
    const d = Number(degree[n.id] || 1);
    return {
      id: n.id,
      label: String(n.title || n.id || 'node'),
      size: Math.max(3, Math.min(14, 4 + (d * 1.1))),
      fill: typeColor(n.type),
      data: {
        id: n.id,
        title: n.title,
        type: n.type,
        degree: d,
      },
    };
  });

  const links = (edges || []).map((e) => ({
    id: String((e || {}).id || ''),
    source: String((e || {}).source || ''),
    target: String((e || {}).target || ''),
    label: String((e || {}).relationship || 'associated_with'),
    size: 0.5 + (Math.max(0, Math.min(1, Number((e || {}).confidence ?? 0))) * 2.2),
    data: {
      relationship: String((e || {}).relationship || 'associated_with'),
      confidence: Number((e || {}).confidence ?? 0),
      reason_text: String((e || {}).reason_text || ''),
    },
  })).filter((l) => l.source && l.target);

  return { nodes, edges: links };
}

function ensureGraphDataBuilder() {
  return ensureSliceBinding(
    graphDataBuilder,
    'graphDataBuilder',
    '/chat-slices/graph-reagraph-data.js',
    (mod) => (mod && typeof mod.buildReagraphData === 'function' ? mod.buildReagraphData : null),
    (value) => { graphDataBuilder = value; }
  );
}

function reagraphDataFromEdges(edges, beadMap) {
  const safeEdges = arrayOrEmpty(edges);
  const safeMap = beadMap || {};

  return callSliceWithFallback(
    graphDataBuilder,
    (builder) => builder(safeEdges, safeMap),
    () => reagraphDataFromEdgesFallback(safeEdges, safeMap),
    ensureGraphDataBuilder
  );
}

function createGraphCanvasHostFallback(el, opts) {
  const wrap = document.createElement('div');
  wrap.className = 'graph-3d-wrap';

  const canvasHost = document.createElement('div');
  canvasHost.className = 'graph-3d-canvas';
  wrap.appendChild(canvasHost);

  const loading = document.createElement('div');
  loading.className = 'graph-3d-note';
  loading.textContent = String((opts || {}).noteText || 'Loading 3D graph...');
  wrap.appendChild(loading);

  el.appendChild(wrap);

  return {
    wrap,
    canvasHost,
    setNote: (text) => {
      loading.textContent = String(text || '');
    },
    removeNote: () => {
      if (loading && loading.parentNode) loading.remove();
    },
    removeCanvasHost: () => {
      if (canvasHost && canvasHost.parentNode) canvasHost.remove();
    },
  };
}

function ensureGraphCanvasHostFactory() {
  return ensureSliceBinding(
    graphCanvasHostFactory,
    'graphCanvasHostFactory',
    '/chat-slices/graph-canvas-host.js',
    (mod) => (mod && typeof mod.createGraphCanvasHost === 'function' ? mod.createGraphCanvasHost : null),
    (value) => { graphCanvasHostFactory = value; }
  );
}

function createGraphCanvasHost(el, opts) {
  return callSliceWithFallback(
    graphCanvasHostFactory,
    (factory) => factory(el, opts || {}),
    () => createGraphCanvasHostFallback(el, opts || {}),
    ensureGraphCanvasHostFactory,
    (out) => !!(out && out.wrap && out.canvasHost)
  );
}

function renderGraph3DCanvas(el, edges, beadMap, onNodeClick, onEdgeClick) {
  const host = createGraphCanvasHost(el, { noteText: 'Loading 3D graph...' });
  const wrap = host.wrap;
  const canvasHost = host.canvasHost;

  const graph = reagraphDataFromEdges(edges, beadMap);
  const theme = {
    canvas: { background: '#060a16' },
    node: {
      fill: '#7ca0ab',
      activeFill: '#6ae276',
      opacity: 0.95,
      selectedOpacity: 1,
      inactiveOpacity: 0.2,
      label: { color: '#e1e4ed', stroke: '#060a16', activeColor: '#ffffff' },
      subLabel: { color: '#8b8fa3', stroke: 'transparent', activeColor: '#e1e4ed' },
    },
    edge: {
      fill: '#5b6a8a',
      activeFill: '#8ea2ff',
      opacity: 0.7,
      selectedOpacity: 1,
      inactiveOpacity: 0.2,
      label: { color: '#b8c0d8', stroke: '#060a16', activeColor: '#ffffff' },
    },
    lasso: { border: '1px solid #6ae276', background: 'rgba(106,226,118,0.15)' },
    ring: { fill: '#1f2838', activeFill: '#6ae276' },
  };

  renderGraph3DRuntime({
    el,
    wrap,
    canvasHost,
    graph,
    theme,
    onNodeClick,
    onEdgeClick,
  })
    .then(() => {
      if (host && typeof host.setNote === 'function') {
        host.setNote('Reagraph 3D: drag to orbit, right-drag to pan, wheel to zoom, drag nodes to reposition.');
      }
    })
    .catch(() => {
      if (typeof wrap.__cmUnmount === 'function') {
        try { wrap.__cmUnmount(); } catch (_) {}
      }
      if (!el.contains(canvasHost)) return;
      if (host && typeof host.removeCanvasHost === 'function') host.removeCanvasHost();
      if (host && typeof host.removeNote === 'function') host.removeNote();
      renderGraphSvgCanvas(el, edges, beadMap, onEdgeClick);
    });
}

function renderGraphSvgCanvasFallback(el, edges, beadMap, onEdgeClick) {
  const svgNs = 'http://www.w3.org/2000/svg';
  const wrap = document.createElement('div');
  wrap.className = 'graph-canvas-wrap';

  const nodesSet = new Set();
  (edges || []).forEach(e => {
    nodesSet.add(String(e.source || ''));
    nodesSet.add(String(e.target || ''));
  });
  let nodeIds = Array.from(nodesSet).filter(Boolean);

  const degree = {};
  (edges || []).forEach(e => {
    degree[String(e.source || '')] = Number(degree[String(e.source || '')] || 0) + 1;
    degree[String(e.target || '')] = Number(degree[String(e.target || '')] || 0) + 1;
  });

  const maxNodes = 64;
  if (nodeIds.length > maxNodes) {
    nodeIds.sort((a, b) => Number(degree[b] || 0) - Number(degree[a] || 0));
    nodeIds = nodeIds.slice(0, maxNodes);
  }
  const keep = new Set(nodeIds);
  const limitedEdges = (edges || []).filter(e => keep.has(String(e.source || '')) && keep.has(String(e.target || ''))).slice(0, 220);

  const width = Math.max(300, Number((el && el.clientWidth) || 0) - 20);
  const height = Math.max(380, Math.min(860, 220 + (nodeIds.length * 8)));
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.max(90, Math.min(width, height) / 2 - 52);

  const svg = document.createElementNS(svgNs, 'svg');
  svg.setAttribute('class', 'graph-canvas');
  const baseView = { x: 0, y: 0, w: width, h: height };
  const view = { x: baseView.x, y: baseView.y, w: baseView.w, h: baseView.h };
  function applyView() {
    svg.setAttribute(
      'viewBox',
      String(view.x.toFixed(2)) + ' ' + String(view.y.toFixed(2)) + ' ' + String(view.w.toFixed(2)) + ' ' + String(view.h.toFixed(2))
    );
  }
  applyView();

  let panState = null;
  let dragged = false;
  let suppressClickUntil = 0;
  svg.style.cursor = 'grab';

  svg.addEventListener('pointerdown', (ev) => {
    if (ev.button !== 0) return;
    panState = {
      pointerId: ev.pointerId,
      sx: ev.clientX,
      sy: ev.clientY,
      ox: view.x,
      oy: view.y,
    };
    dragged = false;
    try { svg.setPointerCapture(ev.pointerId); } catch (_) {}
    svg.style.cursor = 'grabbing';
  });

  svg.addEventListener('pointermove', (ev) => {
    if (!panState || ev.pointerId !== panState.pointerId) return;
    const rect = svg.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const px = ev.clientX - panState.sx;
    const py = ev.clientY - panState.sy;
    if (Math.abs(px) > 2 || Math.abs(py) > 2) dragged = true;
    const dx = px * (view.w / rect.width);
    const dy = py * (view.h / rect.height);
    view.x = panState.ox - dx;
    view.y = panState.oy - dy;
    applyView();
  });

  function endPan(ev) {
    if (!panState || !ev || ev.pointerId !== panState.pointerId) return;
    if (dragged) suppressClickUntil = Date.now() + 180;
    try { svg.releasePointerCapture(ev.pointerId); } catch (_) {}
    panState = null;
    svg.style.cursor = 'grab';
  }
  svg.addEventListener('pointerup', endPan);
  svg.addEventListener('pointercancel', endPan);

  svg.addEventListener('wheel', (ev) => {
    ev.preventDefault();
    const rect = svg.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const mx = (ev.clientX - rect.left) / rect.width;
    const my = (ev.clientY - rect.top) / rect.height;
    const zoom = ev.deltaY < 0 ? 0.92 : 1.08;
    const worldX = view.x + (mx * view.w);
    const worldY = view.y + (my * view.h);
    view.w = Math.max(140, Math.min(6000, view.w * zoom));
    view.h = Math.max(140, Math.min(6000, view.h * zoom));
    view.x = worldX - (mx * view.w);
    view.y = worldY - (my * view.h);
    applyView();
  }, { passive: false });

  svg.addEventListener('dblclick', (ev) => {
    ev.preventDefault();
    view.x = baseView.x;
    view.y = baseView.y;
    view.w = baseView.w;
    view.h = baseView.h;
    applyView();
  });

  svg.addEventListener('click', (ev) => {
    if (Date.now() < suppressClickUntil) {
      ev.preventDefault();
      ev.stopPropagation();
    }
  }, true);

  const pos = {};
  nodeIds.forEach((id, idx) => {
    if (nodeIds.length === 1) {
      pos[id] = { x: cx, y: cy };
      return;
    }
    const angle = ((2 * Math.PI * idx) / nodeIds.length) - (Math.PI / 2);
    pos[id] = {
      x: cx + (radius * Math.cos(angle)),
      y: cy + (radius * Math.sin(angle)),
    };
  });

  limitedEdges.forEach(edge => {
    const s = pos[String(edge.source || '')];
    const t = pos[String(edge.target || '')];
    if (!s || !t) return;
    const line = document.createElementNS(svgNs, 'line');
    line.setAttribute('class', 'graph-edge');
    line.setAttribute('x1', String(s.x));
    line.setAttribute('y1', String(s.y));
    line.setAttribute('x2', String(t.x));
    line.setAttribute('y2', String(t.y));
    const sw = 0.9 + ((edge.confidence === null ? 0.2 : edge.confidence) * 2.1);
    line.setAttribute('stroke-width', String(sw.toFixed(2)));

    line.addEventListener('click', (ev) => {
      ev.stopPropagation();
      if (typeof onEdgeClick === 'function') onEdgeClick(edge);
    });

    const tt = document.createElementNS(svgNs, 'title');
    tt.textContent = String(edge.relationship || 'associated_with') +
      ' · conf=' + String(edge.confidence === null ? 'n/a' : Number(edge.confidence).toFixed(2)) +
      (edge.reason_text ? ('\n' + edge.reason_text) : '');
    line.appendChild(tt);
    svg.appendChild(line);
  });

  nodeIds.forEach(id => {
    const p = pos[id];
    if (!p) return;
    const g = document.createElementNS(svgNs, 'g');
    g.setAttribute('class', 'graph-node');
    g.setAttribute('transform', 'translate(' + String(p.x.toFixed(2)) + ' ' + String(p.y.toFixed(2)) + ')');

    const circle = document.createElementNS(svgNs, 'circle');
    const r = 6 + Math.min(6, Number(degree[id] || 0) * 0.5);
    circle.setAttribute('r', String(r.toFixed(1)));
    g.appendChild(circle);

    const label = document.createElementNS(svgNs, 'text');
    label.setAttribute('x', '0');
    label.setAttribute('y', String(-r - 5));
    label.setAttribute('text-anchor', 'middle');
    const raw = graphNodeTitle(beadMap, id);
    label.textContent = raw.length > 20 ? (raw.slice(0, 19) + '…') : raw;
    g.appendChild(label);

    const tt = document.createElementNS(svgNs, 'title');
    tt.textContent = raw + '\n' + id;
    g.appendChild(tt);

    g.addEventListener('click', (ev) => {
      ev.stopPropagation();
      showBead(id);
    });
    svg.appendChild(g);
  });

  wrap.appendChild(svg);
  el.appendChild(wrap);

  const note = document.createElement('div');
  note.className = 'runtime-card';
  note.innerHTML =
    '<div><strong>Graph view</strong></div>' +
    '<div style="margin-top:2px;color:var(--text-dim)">nodes=' + String(nodeIds.length) +
    ' · edges=' + String(limitedEdges.length) +
    ' · drag to pan · wheel to zoom · double-click to reset.</div>';
  el.appendChild(note);
}

function ensureGraphSvgCanvasRenderer() {
  return ensureSliceBinding(
    graphSvgCanvasRenderer,
    'graphSvgCanvasRenderer',
    '/chat-slices/graph-svg-canvas.js',
    (mod) => (mod && typeof mod.renderGraphSvgCanvasPane === 'function' ? mod.renderGraphSvgCanvasPane : null),
    (value) => { graphSvgCanvasRenderer = value; }
  );
}

function renderGraphSvgCanvas(el, edges, beadMap, onEdgeClick) {
  const safeEdges = arrayOrEmpty(edges);
  const safeMap = beadMap || {};

  renderViaSlice(
    graphSvgCanvasRenderer,
    (renderer) => renderer(el, {
      edges: safeEdges,
      beadMap: safeMap,
      graphNodeTitle,
      onOpenBead: showBead,
      onEdgeClick,
    }),
    () => renderGraphSvgCanvasFallback(el, safeEdges, safeMap, onEdgeClick),
    ensureGraphSvgCanvasRenderer
  );
}

function renderGraphListFallback(el, edges, beadMap) {
  (edges || []).slice(0, 140).forEach(a => {
    const src = String(a.source || '');
    const dst = String(a.target || '');
    const srcTitle = graphNodeTitle(beadMap, src);
    const dstTitle = graphNodeTitle(beadMap, dst);

    const row = document.createElement('div');
    row.className = 'bench-bucket';
    row.innerHTML =
      '<div><strong>' + escapeHtml(String(a.relationship || 'associated_with')) + '</strong></div>' +
      '<div style="margin-top:2px;color:var(--text-dim)">source: ' + escapeHtml(srcTitle) + '</div>' +
      '<div style="margin-top:2px;color:var(--text-dim)">target: ' + escapeHtml(dstTitle) + '</div>' +
      '<div style="margin-top:2px;color:var(--text-dim)">confidence: ' + String(a.confidence === null ? 'n/a' : Number(a.confidence).toFixed(2)) + '</div>' +
      '<div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap">' +
        (src ? '<button class="btn" data-bead-id="' + escapeHtml(src) + '">Open source</button>' : '') +
        (dst ? '<button class="btn" data-bead-id="' + escapeHtml(dst) + '">Open target</button>' : '') +
      '</div>';
    row.querySelectorAll('button[data-bead-id]').forEach(btn => {
      btn.addEventListener('click', ev => {
        ev.stopPropagation();
        const bid = btn.getAttribute('data-bead-id') || '';
        if (bid) showBead(bid);
      });
    });
    el.appendChild(row);
  });
}

function ensureGraphListPaneRenderer() {
  return ensureSliceBinding(
    graphListPaneRenderer,
    'graphListPaneRenderer',
    '/chat-slices/graph-list-pane.js',
    (mod) => (mod && typeof mod.renderGraphListPane === 'function' ? mod.renderGraphListPane : null),
    (value) => { graphListPaneRenderer = value; }
  );
}

function renderGraphList(el, edges, beadMap) {
  const safeEdges = arrayOrEmpty(edges);
  renderViaSlice(
    graphListPaneRenderer,
    (renderer) => renderer(el, {
      edges: safeEdges,
      beadMap: beadMap || {},
      graphNodeTitle,
      onOpenBead: showBead,
    }),
    () => renderGraphListFallback(el, safeEdges, beadMap || {}),
    ensureGraphListPaneRenderer
  );
}

function renderGraphControlsFallback(el, opts) {
  const beadCount = Number(opts.beadCount || 0);
  const edgeCount = Number(opts.edgeCount || 0);
  const viewMode = String(opts.viewMode || 'list');
  const showFilters = !!opts.showFilters;

  const toolbar = document.createElement('div');
  toolbar.className = 'graph-toolbar';

  const summary = document.createElement('div');
  summary.innerHTML =
    '<div><strong>Graph pane</strong></div>' +
    '<div style="margin-top:2px;color:var(--text-dim)">beads=' + String(beadCount) +
    ' · associations=' + String(edgeCount) + '</div>';
  toolbar.appendChild(summary);

  const toggle = document.createElement('div');
  toggle.className = 'graph-toggle';
  ['list', 'graph'].forEach(mode => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'graph-toggle-btn' + (viewMode === mode ? ' active' : '');
    btn.textContent = mode === 'list' ? 'List view' : 'Graph view';
    btn.addEventListener('click', () => {
      if (typeof opts.onSetMode === 'function') opts.onSetMode(mode);
    });
    toggle.appendChild(btn);
  });
  toolbar.appendChild(toggle);

  el.appendChild(toolbar);

  if (!showFilters) return;

  const filters = document.createElement('div');
  filters.className = 'graph-filters';
  filters.innerHTML =
    '<span class="graph-filter-label">Filters</span>' +
    '<select class="control-select" id="graph-filter-rel" style="width:160px"></select>' +
    '<input class="control-input" id="graph-filter-conf" type="number" min="0" max="1" step="0.05" style="width:90px" />' +
    '<input class="control-input" id="graph-filter-search" type="text" placeholder="search node/edge" style="flex:1;min-width:160px" />';
  el.appendChild(filters);

  const relSel = filters.querySelector('#graph-filter-rel');
  const confInput = filters.querySelector('#graph-filter-conf');
  const searchInput = filters.querySelector('#graph-filter-search');

  const relOptions = arrayOr(opts.relationOptions, ['all']);
  relOptions.forEach(rel => {
    const opt = document.createElement('option');
    opt.value = String(rel);
    opt.textContent = String(rel);
    if (String(rel) === String(opts.relationValue || 'all')) opt.selected = true;
    relSel.appendChild(opt);
  });

  confInput.value = String(Number(opts.minConfidence || 0).toFixed(2));
  searchInput.value = String(opts.search || '');

  relSel.addEventListener('change', () => {
    if (typeof opts.onSetRelation === 'function') {
      opts.onSetRelation(String(relSel.value || 'all'));
    }
  });
  confInput.addEventListener('change', () => {
    if (typeof opts.onSetMinConfidence === 'function') {
      opts.onSetMinConfidence(confInput.value);
    }
  });
  searchInput.addEventListener('input', () => {
    if (typeof opts.onSetSearch === 'function') {
      opts.onSetSearch(String(searchInput.value || '').trim());
    }
  });
}

function ensureGraphControlsPaneRenderer() {
  return ensureSliceBinding(
    graphControlsPaneRenderer,
    'graphControlsPaneRenderer',
    '/chat-slices/graph-controls-pane.js',
    (mod) => (mod && typeof mod.renderGraphControlsPane === 'function' ? mod.renderGraphControlsPane : null),
    (value) => { graphControlsPaneRenderer = value; }
  );
}

function renderGraphControls(el, opts) {
  renderViaSlice(
    graphControlsPaneRenderer,
    (renderer) => renderer(el, opts || {}),
    () => renderGraphControlsFallback(el, opts || {}),
    ensureGraphControlsPaneRenderer
  );
}

function renderGraphEdgeDetailFallback(el, opts) {
  const edge = (opts || {}).edge || null;
  const beadMap = (opts || {}).beadMap || {};
  const onOpenBead = typeof (opts || {}).onOpenBead === 'function' ? opts.onOpenBead : null;
  el.textContent = '';

  if (!edge) {
    el.innerHTML =
      '<div><strong>Edge details</strong></div>' +
      '<div style="margin-top:2px;color:var(--text-dim)">Click an edge in graph view to inspect and jump to source/target beads.</div>';
    return;
  }

  const src = graphEntityId((edge || {}).source);
  const dst = graphEntityId((edge || {}).target);
  const srcTitle = graphNodeTitle(beadMap, src);
  const dstTitle = graphNodeTitle(beadMap, dst);
  const conf = edge && edge.confidence !== null ? Number(edge.confidence).toFixed(2) : 'n/a';
  const reason = String((edge || {}).reason_text || '').trim();
  el.innerHTML =
    '<div><strong>' + escapeHtml(String((edge || {}).relationship || 'associated_with')) + '</strong></div>' +
    '<div style="margin-top:2px;color:var(--text-dim)">source: ' + escapeHtml(srcTitle) + '</div>' +
    '<div style="margin-top:2px;color:var(--text-dim)">target: ' + escapeHtml(dstTitle) + '</div>' +
    '<div style="margin-top:2px;color:var(--text-dim)">confidence: ' + escapeHtml(conf) + '</div>' +
    (reason ? ('<div style="margin-top:4px">' + escapeHtml(reason) + '</div>') : '') +
    '<div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">' +
      (src ? '<button class="btn" data-edge-open="src">Open source</button>' : '') +
      (dst ? '<button class="btn" data-edge-open="dst">Open target</button>' : '') +
    '</div>';

  el.querySelectorAll('button[data-edge-open]').forEach(btn => {
    btn.addEventListener('click', (ev) => {
      ev.stopPropagation();
      const which = btn.getAttribute('data-edge-open') || '';
      const id = which === 'src' ? src : (which === 'dst' ? dst : '');
      if (id && onOpenBead) onOpenBead(id);
    });
  });
}

function ensureGraphEdgeDetailPaneRenderer() {
  return ensureSliceBinding(
    graphEdgeDetailPaneRenderer,
    'graphEdgeDetailPaneRenderer',
    '/chat-slices/graph-edge-detail-pane.js',
    (mod) => (mod && typeof mod.renderGraphEdgeDetailPane === 'function' ? mod.renderGraphEdgeDetailPane : null),
    (value) => { graphEdgeDetailPaneRenderer = value; }
  );
}

function renderGraphEdgeDetail(el, opts) {
  renderViaSlice(
    graphEdgeDetailPaneRenderer,
    (renderer) => renderer(el, opts || {}),
    () => renderGraphEdgeDetailFallback(el, opts || {}),
    ensureGraphEdgeDetailPaneRenderer
  );
}

function renderGraphSummaryFallback(el, opts) {
  const filteredEdges = arrayOrEmpty((opts || {}).filteredEdges);
  const totalEdges = Number((opts || {}).totalEdges || 0);
  el.textContent = '';

  const meta = document.createElement('div');
  meta.className = 'runtime-card';
  meta.innerHTML =
    '<div><strong>Filtered graph</strong></div>' +
    '<div style="margin-top:2px;color:var(--text-dim)">showing ' + String(filteredEdges.length) +
    ' / ' + String(totalEdges) + ' edges</div>';
  el.appendChild(meta);

  if (!filteredEdges.length) return;

  const wrap = document.createElement('div');
  wrap.className = 'graph-legend';

  const counts = {};
  filteredEdges.forEach(e => {
    const rel = String((e || {}).relationship || 'associated_with');
    counts[rel] = Number(counts[rel] || 0) + 1;
  });

  const rows = Object.entries(counts).sort((a, b) => Number(b[1]) - Number(a[1]));
  rows.slice(0, 14).forEach(([rel, n]) => {
    const chip = document.createElement('span');
    chip.className = 'graph-chip';
    chip.innerHTML = escapeHtml(String(rel)) + ' <span class="graph-chip-count">' + String(n) + '</span>';
    wrap.appendChild(chip);
  });

  if (rows.length > 14) {
    const more = document.createElement('span');
    more.className = 'graph-chip';
    more.textContent = '+' + String(rows.length - 14) + ' more';
    wrap.appendChild(more);
  }

  el.appendChild(wrap);
}

function ensureGraphSummaryPaneRenderer() {
  return ensureSliceBinding(
    graphSummaryPaneRenderer,
    'graphSummaryPaneRenderer',
    '/chat-slices/graph-summary-pane.js',
    (mod) => (mod && typeof mod.renderGraphSummaryPane === 'function' ? mod.renderGraphSummaryPane : null),
    (value) => { graphSummaryPaneRenderer = value; }
  );
}

function renderGraphSummary(el, opts) {
  renderViaSlice(
    graphSummaryPaneRenderer,
    (renderer) => renderer(el, opts || {}),
    () => renderGraphSummaryFallback(el, opts || {}),
    ensureGraphSummaryPaneRenderer
  );
}

function renderGraph(beads, assocs) {
  const el = document.getElementById('tab-graph');
  const mounted3d = el && el.querySelectorAll ? el.querySelectorAll('.graph-3d-wrap') : [];
  if (mounted3d && mounted3d.length) {
    mounted3d.forEach((node) => {
      if (node && typeof node.__cmUnmount === 'function') {
        try { node.__cmUnmount(); } catch (_) {}
      }
    });
  }
  el.textContent = '';
  const beadMap = {};
  (beads || []).forEach(b => { beadMap[String(b.id || '')] = b; });
  const edges = normalizeGraphEdges(assocs || []);

  const rels = graphViewMode === 'graph'
    ? Array.from(new Set(edges.map(e => String(e.relationship || 'associated_with')))).sort()
    : [];
  if (graphViewMode === 'graph' && graphFilters.relation !== 'all' && !rels.includes(graphFilters.relation)) {
    graphFilters.relation = 'all';
    saveGraphPrefs();
  }

  renderGraphControls(el, {
    beadCount: (beads || []).length,
    edgeCount: edges.length,
    viewMode: graphViewMode,
    showFilters: graphViewMode === 'graph' && edges.length > 0,
    relationOptions: ['all'].concat(rels),
    relationValue: String(graphFilters.relation || 'all'),
    minConfidence: Number(graphFilters.minConfidence || 0),
    search: String(graphFilters.search || ''),
    onSetMode: (mode) => {
      graphViewMode = mode === 'graph' ? 'graph' : 'list';
      saveGraphPrefs();
      renderGraph(beads, assocs);
    },
    onSetRelation: (rel) => {
      graphFilters.relation = String(rel || 'all');
      saveGraphPrefs();
      renderGraph(beads, assocs);
    },
    onSetMinConfidence: (raw) => {
      const v = Number(raw || 0);
      graphFilters.minConfidence = Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 0;
      saveGraphPrefs();
      renderGraph(beads, assocs);
    },
    onSetSearch: (search) => {
      graphFilters.search = String(search || '').trim();
      saveGraphPrefs();
      renderGraph(beads, assocs);
    },
  });

  if (!edges.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = 'No graph edges yet';
    el.appendChild(empty);
    return;
  }

  if (graphViewMode === 'graph') {
    const filtered = applyGraphFilters(edges, beadMap);
    const summaryHost = document.createElement('div');
    el.appendChild(summaryHost);
    renderGraphSummary(summaryHost, { filteredEdges: filtered, totalEdges: edges.length });

    if (!filtered.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      empty.textContent = 'No edges match current filters';
      el.appendChild(empty);
      return;
    }

    const edgeDetail = document.createElement('div');
    edgeDetail.className = 'runtime-card';
    renderGraphEdgeDetail(edgeDetail, {
      edge: null,
      beadMap,
      onOpenBead: showBead,
    });

    renderGraph3DCanvas(el, filtered, beadMap, (nodeId) => {
      if (nodeId) showBead(nodeId);
    }, (edge) => {
      renderGraphEdgeDetail(edgeDetail, {
        edge,
        beadMap,
        onOpenBead: showBead,
      });
    });

    el.appendChild(edgeDetail);
    return;
  }

  renderGraphList(el, edges, beadMap);
}

function renderRollingFallback(el, items) {
  el.textContent = '';
  if (!items.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = 'Rolling window empty';
    el.appendChild(empty);
    return;
  }
  items.forEach(r => {
    const row = document.createElement('div');
    row.className = 'rolling-item';

    const typeSpan = document.createElement('span');
    typeSpan.className = 'bead-type ' + beadTypeClass(r.type);
    typeSpan.textContent = r.type;
    row.appendChild(typeSpan);

    const titleSpan = document.createElement('span');
    titleSpan.textContent = r.title;
    row.appendChild(titleSpan);

    el.appendChild(row);
  });
}

function ensureRollingPaneRenderer() {
  return ensureSliceBinding(
    rollingPaneRenderer,
    'rollingPaneRenderer',
    '/chat-slices/rolling-pane.js',
    (mod) => (mod && typeof mod.renderRollingPane === 'function' ? mod.renderRollingPane : null),
    (value) => { rollingPaneRenderer = value; }
  );
}

function renderRolling(items) {
  const el = document.getElementById('tab-rolling');
  if (!el) return;

  renderViaSlice(
    rollingPaneRenderer,
    (renderer) => renderer(el, items, beadTypeClass),
    () => renderRollingFallback(el, items),
    ensureRollingPaneRenderer
  );
}

function renderClaimsFallback(rows, claimsMeta) {
  const el = document.getElementById('tab-claims');
  el.textContent = '';

  const toolbar = document.createElement('div');
  toolbar.className = 'claims-toolbar';
  const asOfInput = document.createElement('input');
  asOfInput.type = 'datetime-local';
  asOfInput.className = 'control-input';
  asOfInput.style.width = '200px';
  asOfInput.title = 'As-of timestamp (UTC)';
  asOfInput.value = isoToDatetimeLocal(claimsAsOf || (claimsMeta || {}).as_of || '');

  const applyBtn = document.createElement('button');
  applyBtn.className = 'btn';
  applyBtn.textContent = 'Apply as-of';
  applyBtn.addEventListener('click', () => {
    claimsAsOf = datetimeLocalToIso(asOfInput.value);
    syncClaimsStateToUrl();
    refreshMemory();
  });

  const clearBtn = document.createElement('button');
  clearBtn.className = 'btn';
  clearBtn.textContent = 'Now';
  clearBtn.addEventListener('click', () => {
    claimsAsOf = '';
    syncClaimsStateToUrl();
    refreshMemory();
  });

  toolbar.appendChild(asOfInput);
  toolbar.appendChild(applyBtn);
  toolbar.appendChild(clearBtn);
  el.appendChild(toolbar);

  const counts = (claimsMeta || {}).counts || {};
  const countsWrap = document.createElement('div');
  countsWrap.style.marginBottom = '8px';
  countsWrap.innerHTML =
    '<span class="claims-pill">active ' + String(counts.active ?? 0) + '</span> ' +
    '<span class="claims-pill">conflict ' + String(counts.conflict ?? 0) + '</span> ' +
    '<span class="claims-pill">retracted ' + String(counts.retracted ?? 0) + '</span> ' +
    '<span class="claims-pill">other ' + String(counts.other ?? 0) + '</span>' +
    '<span style="margin-left:6px;color:var(--text-dim);font-size:11px">as_of: ' + escapeHtml((claimsMeta || {}).as_of || 'now') + '</span>';
  el.appendChild(countsWrap);

  if (!rows || !rows.length) {
    claimsDetailOpen = false;
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = 'No claim-state slots yet';
    el.appendChild(empty);
    return;
  }

  if (!selectedClaimSlot || !rows.some(r => (r.slot_key || '') === selectedClaimSlot)) {
    selectedClaimSlot = rows[0].slot_key;
    syncClaimsStateToUrl();
  }

  const wrap = document.createElement('div');
  wrap.className = 'claims-layout';
  const list = document.createElement('div');
  list.className = 'claims-list';
  const hint = document.createElement('div');
  hint.style.cssText = 'padding:8px 10px;border-bottom:1px solid var(--border);font-size:11px;color:var(--text-dim);';
  hint.textContent = 'Select a claim slot to open detail view.';
  list.appendChild(hint);

  rows.forEach(r => {
    const status = r.status || 'not_found';
    const row = document.createElement('div');
    row.className = 'claim-row' + ((r.slot_key || '') === selectedClaimSlot ? ' active' : '');
    row.innerHTML =
      '<div><strong>' + String(r.slot_key || '-') + '</strong> ' +
      '<span class="bead-status ' + statusClass(status) + '">' + status + '</span></div>' +
      '<div style="margin-top:2px;color:var(--text-dim)">value: ' + String(r.value ?? '—') +
      ' · conflicts: ' + String(r.conflict_count ?? 0) + '</div>';
    row.addEventListener('click', async () => {
      selectedClaimSlot = r.slot_key || null;
      claimsDetailOpen = true;
      syncClaimsStateToUrl();
      renderClaims(rows, claimsMeta);
    });
    list.appendChild(row);
  });

  wrap.appendChild(list);

  const overlay = document.createElement('div');
  overlay.className = 'claims-detail-overlay' + (claimsDetailOpen ? ' open' : '');

  const backdrop = document.createElement('button');
  backdrop.type = 'button';
  backdrop.className = 'claims-detail-backdrop';
  backdrop.setAttribute('aria-label', 'Close claim detail');
  backdrop.addEventListener('click', () => {
    claimsDetailOpen = false;
    renderClaims(rows, claimsMeta);
  });
  overlay.appendChild(backdrop);

  const panel = document.createElement('div');
  panel.className = 'claims-detail-panel';

  const panelHead = document.createElement('div');
  panelHead.className = 'claims-detail-head';
  panelHead.innerHTML = '<strong>Claim detail</strong><span style="color:var(--text-dim)">slot: ' + escapeHtml(String(selectedClaimSlot || 'n/a')) + '</span>';

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'claims-detail-close';
  closeBtn.setAttribute('aria-label', 'Close claim detail');
  closeBtn.textContent = '×';
  closeBtn.addEventListener('click', () => {
    claimsDetailOpen = false;
    renderClaims(rows, claimsMeta);
  });
  panelHead.appendChild(closeBtn);
  panel.appendChild(panelHead);

  const detailBodyWrap = document.createElement('div');
  detailBodyWrap.className = 'claims-detail-body';
  const detail = document.createElement('div');
  detail.className = 'claim-detail';
  detail.textContent = 'Loading slot detail...';
  detailBodyWrap.appendChild(detail);
  panel.appendChild(detailBodyWrap);

  overlay.appendChild(panel);
  wrap.appendChild(overlay);
  el.appendChild(wrap);

  if (claimsDetailOpen) {
    loadClaimSlotDetail(selectedClaimSlot, detail);
  }
}


function ensureClaimsPaneRenderer() {
  return ensureSliceBinding(
    claimsPaneRenderer,
    'claimsPaneRenderer',
    '/chat-slices/claims-pane.js',
    (mod) => (mod && typeof mod.renderClaimsPane === 'function' ? mod.renderClaimsPane : null),
    (value) => { claimsPaneRenderer = value; }
  );
}

function renderClaims(rows, claimsMeta) {
  const el = document.getElementById('tab-claims');
  if (!el) return;

  const safeRows = arrayOrEmpty(rows);
  if (!safeRows.length) {
    claimsDetailOpen = false;
  } else if (!selectedClaimSlot || !safeRows.some(r => (r && (r.slot_key || '')) === selectedClaimSlot)) {
    selectedClaimSlot = (safeRows[0] && safeRows[0].slot_key) || null;
    syncClaimsStateToUrl();
  }

  renderViaSlice(
    claimsPaneRenderer,
    (renderer) => renderer(el, {
      rows: safeRows,
      claimsMeta,
      selectedClaimSlot,
      claimsDetailOpen,
      asOfInputValue: isoToDatetimeLocal(claimsAsOf || (claimsMeta || {}).as_of || ''),
      asOfLabel: String((claimsMeta || {}).as_of || claimsAsOf || 'now'),
      statusClass,
      onApplyAsOfValue: (localValue) => {
        claimsAsOf = datetimeLocalToIso(localValue);
        syncClaimsStateToUrl();
        refreshMemory();
      },
      onClearAsOf: () => {
        claimsAsOf = '';
        syncClaimsStateToUrl();
        refreshMemory();
      },
      onSelectSlot: (slotKey) => {
        selectedClaimSlot = slotKey || null;
        claimsDetailOpen = true;
        syncClaimsStateToUrl();
        renderClaims(safeRows, claimsMeta);
      },
      onCloseDetail: () => {
        claimsDetailOpen = false;
        renderClaims(safeRows, claimsMeta);
      },
      loadDetail: (slotKey, detailEl) => loadClaimSlotDetail(slotKey, detailEl),
    }),
    () => renderClaimsFallback(safeRows, claimsMeta),
    ensureClaimsPaneRenderer
  );
}

function renderEntitiesFallback(entityMeta) {
  const el = document.getElementById('tab-entities');
  el.textContent = '';
  const rows = arrayOrEmpty((entityMeta || {}).rows);
  const counts = (entityMeta || {}).counts || {};
  const merges = arrayOrEmpty((entityMeta || {}).merge_proposals);

  const toolbar = document.createElement('div');
  toolbar.className = 'claims-toolbar';
  const suggestBtn = document.createElement('button');
  suggestBtn.className = 'btn';
  suggestBtn.textContent = 'Suggest merges';
  suggestBtn.addEventListener('click', entitySuggestMerges);
  const refreshBtn = document.createElement('button');
  refreshBtn.className = 'btn';
  refreshBtn.textContent = 'Refresh';
  refreshBtn.addEventListener('click', refreshMemory);
  toolbar.appendChild(suggestBtn);
  toolbar.appendChild(refreshBtn);
  el.appendChild(toolbar);

  const head = document.createElement('div');
  head.style.marginBottom = '8px';
  head.innerHTML =
    '<span class="claims-pill">total ' + String(counts.total ?? rows.length) + '</span> ' +
    '<span class="claims-pill">active ' + String(counts.active ?? 0) + '</span> ' +
    '<span class="claims-pill">merged ' + String(counts.merged ?? 0) + '</span> ' +
    '<span class="claims-pill">merge proposals ' + String(merges.length) + '</span>';
  el.appendChild(head);

  if (!rows.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = 'No entity registry rows yet';
    el.appendChild(empty);
  } else {
    rows.slice(0, 80).forEach(r => {
      const card = document.createElement('div');
      card.className = 'runtime-card';
      const status = String(r.status || 'active');
      card.innerHTML =
        '<div><strong>' + escapeHtml(String(r.label || r.id || 'entity')) + '</strong> ' +
        '<span class="runtime-badge ' + (status === 'active' ? 'runtime-badge-good' : 'runtime-badge-warn') + '">' + escapeHtml(status) + '</span></div>' +
        '<div style="margin-top:2px;color:var(--text-dim)">id: ' + escapeHtml(String(r.id || 'n/a')) + '</div>' +
        '<div style="margin-top:2px;color:var(--text-dim)">aliases: ' + String(r.aliases_count ?? 0) +
        ' · confidence: ' + String(r.confidence ?? 'n/a') +
        ' · provenance: ' + String(r.provenance_count ?? 0) + '</div>' +
        (r.merged_into
          ? ('<div style="margin-top:2px;color:var(--amber)">merged_into: ' + escapeHtml(String(r.merged_into)) + '</div>')
          : '') +
        '<div style="margin-top:2px;color:var(--text-dim)">updated: ' + escapeHtml(formatIsoShort(r.updated_at || '')) + '</div>';
      const aliases = arrayOrEmpty(r.aliases);
      if (aliases.length) {
        const aliasesLine = document.createElement('div');
        aliasesLine.style.cssText = 'margin-top:4px;color:var(--text-dim);font-size:11px';
        aliasesLine.textContent = 'aliases: ' + aliases.slice(0, 8).join(', ');
        card.appendChild(aliasesLine);
      }
      el.appendChild(card);
    });
  }

  if (merges.length) {
    const mh = document.createElement('div');
    mh.className = 'runtime-card';
    mh.innerHTML = '<strong>Entity merge proposals</strong><div style="margin-top:2px;color:var(--text-dim)">Pending proposals can be accepted/rejected directly from this panel.</div>';
    el.appendChild(mh);
    merges.slice(0, 20).forEach(m => {
      const row = document.createElement('div');
      row.className = 'bench-bucket';
      const status = String(m.status || 'n/a');
      row.innerHTML =
        '<div><strong>' + escapeHtml(String(m.id || 'proposal')) + '</strong> ' +
        '<span class="runtime-badge ' + (status === 'pending' ? 'runtime-badge-warn' : 'runtime-badge-good') + '">' + escapeHtml(status) + '</span></div>' +
        '<div style="margin-top:2px;color:var(--text-dim)">score=' + String(Number(m.score || 0).toFixed(3)) +
        ' · left=' + escapeHtml(String(m.left_entity_id || 'n/a')) +
        ' · right=' + escapeHtml(String(m.right_entity_id || 'n/a')) + '</div>' +
        '<div style="margin-top:2px;color:var(--text-dim)">reasons: ' + escapeHtml(String((m.reasons || []).join(', ') || 'n/a')) + '</div>';

      if (status === 'pending') {
        const actions = document.createElement('div');
        actions.style.cssText = 'margin-top:6px; display:flex; gap:6px; flex-wrap:wrap;';

        const acceptLeft = document.createElement('button');
        acceptLeft.className = 'btn';
        acceptLeft.textContent = 'Accept (keep left)';
        acceptLeft.addEventListener('click', (ev) => {
          ev.stopPropagation();
          entityDecideMerge(m, 'accept', String(m.left_entity_id || ''));
        });

        const acceptRight = document.createElement('button');
        acceptRight.className = 'btn';
        acceptRight.textContent = 'Accept (keep right)';
        acceptRight.addEventListener('click', (ev) => {
          ev.stopPropagation();
          entityDecideMerge(m, 'accept', String(m.right_entity_id || ''));
        });

        const reject = document.createElement('button');
        reject.className = 'btn btn-warn';
        reject.textContent = 'Reject';
        reject.addEventListener('click', (ev) => {
          ev.stopPropagation();
          entityDecideMerge(m, 'reject', null);
        });

        actions.appendChild(acceptLeft);
        actions.appendChild(acceptRight);
        actions.appendChild(reject);
        row.appendChild(actions);
      } else {
        const reviewed = document.createElement('div');
        reviewed.style.cssText = 'margin-top:4px;color:var(--text-dim);font-size:11px';
        reviewed.textContent = 'reviewer: ' + String(m.reviewer || 'n/a') + ' · reviewed_at: ' + formatIsoShort(String(m.reviewed_at || ''));
        row.appendChild(reviewed);
      }

      row.addEventListener('click', () => {
        openJsonModal('Entity merge proposal', m);
      });
      el.appendChild(row);
    });
  }
}

function ensureEntitiesPaneRenderer() {
  return ensureSliceBinding(
    entitiesPaneRenderer,
    'entitiesPaneRenderer',
    '/chat-slices/entities-pane.js',
    (mod) => (mod && typeof mod.renderEntitiesPane === 'function' ? mod.renderEntitiesPane : null),
    (value) => { entitiesPaneRenderer = value; }
  );
}

function renderEntities(entityMeta) {
  const safeMeta = entityMeta || {};
  const el = document.getElementById('tab-entities');
  if (!el) return;

  renderViaSlice(
    entitiesPaneRenderer,
    (renderer) => renderer(el, {
      entityMeta: safeMeta,
      formatIsoShort,
      onSuggestMerges: entitySuggestMerges,
      onRefresh: refreshMemory,
      onDecideMerge: entityDecideMerge,
      onOpenProposal: (proposal) => {
        openJsonModal('Entity merge proposal', proposal);
      },
    }),
    () => renderEntitiesFallback(safeMeta),
    ensureEntitiesPaneRenderer
  );
}

async function entitySuggestMerges() {
  try {
    const res = await fetch('/api/demo/entities/merge/suggest', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({min_score: 0.86, max_pairs: 40, source: 'demo-ui'}),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || ('HTTP ' + res.status));
    addMsg('system', 'Entity merge suggest completed: created=' + String(data.created ?? 0) + ', pending=' + String(data.pending ?? 0));
    refreshMemory();
  } catch (err) {
    addMsg('system', 'Entity merge suggest failed: ' + err.message);
  }
}

async function entityDecideMerge(proposal, decision, keepEntityId) {
  const pid = String((proposal || {}).id || '');
  if (!pid) return;
  try {
    const res = await fetch('/api/demo/entities/merge/decide', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        proposal_id: pid,
        decision: String(decision || '').toLowerCase(),
        keep_entity_id: keepEntityId || undefined,
        reviewer: 'demo-ui',
        notes: 'demo adjudication',
        apply: true,
      }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || ('HTTP ' + res.status));
    addMsg('system', 'Entity merge ' + String(decision) + ' for ' + pid + ' (status=' + String(data.status || 'n/a') + ')');
    refreshMemory();
  } catch (err) {
    addMsg('system', 'Entity merge decision failed: ' + err.message);
  }
}

async function loadClaimSlotDetail(slotKey, detailEl) {
  if (!slotKey || !detailEl) return;
  const requestId = String(Date.now()) + '-' + Math.random().toString(36).slice(2, 8);
  detailEl.dataset.req = requestId;
  const parts = String(slotKey).split(':');
  const subject = parts.shift() || '';
  const slot = parts.join(':');
  if (!subject || !slot) {
    detailEl.textContent = 'Invalid slot key: ' + String(slotKey);
    return;
  }
  detailEl.textContent = 'Loading slot detail...';
  try {
    let url = '/v1/memory/inspect/claim-slots/' + encodeURIComponent(subject) + '/' + encodeURIComponent(slot);
    if (claimsAsOf) url += '?as_of=' + encodeURIComponent(claimsAsOf);
    const res = await fetch(url);
    const data = await res.json();
    if (!res.ok || !data.ok) {
      throw new Error(data.error || ('HTTP ' + res.status));
    }
    if (detailEl.dataset.req !== requestId) return;
    const row = data.row || {};
    const current = row.current_claim || {};
    const conflicts = row.conflicts || [];
    const history = row.history || [];
    const timeline = row.timeline || [];
    const assertEvents = timeline.filter(t => String((t || {}).event_type || '').toLowerCase() === 'assert');
    const updateEvents = timeline.filter(t => String((t || {}).event_type || '').toLowerCase() !== 'assert');
    const curText = current && Object.keys(current).length ? formatClaimEntry(current) : 'none';

    const historyHtml = history.length
      ? '<div class="claim-events">' + history.slice().reverse().slice(0, 8).map(c =>
          '<div class="claim-event"><div><strong>' + escapeHtml(String(c.id || 'claim')) + '</strong></div>' +
          '<div style="color:var(--text-dim)">' + escapeHtml(formatClaimEntry(c)) + '</div></div>'
        ).join('') + '</div>'
      : '<div style="margin-top:2px;color:var(--text-dim)">none</div>';

    const updateDecisionCounts = {};
    updateEvents.forEach(t => {
      const k = String((t || {}).event_type || 'update').toLowerCase();
      updateDecisionCounts[k] = Number(updateDecisionCounts[k] || 0) + 1;
    });
    const updateCountPills = Object.keys(updateDecisionCounts).sort().map(k =>
      '<span class="claims-pill">' + escapeHtml(k) + ' ' + String(updateDecisionCounts[k]) + '</span>'
    ).join(' ');

    const timelineHtml = timeline.length
      ? (
          '<div style="margin-top:4px">' +
            '<span class="claims-pill">assert ' + String(assertEvents.length) + '</span> ' +
            '<span class="claims-pill">updates ' + String(updateEvents.length) + '</span> ' +
            updateCountPills +
          '</div>' +
          '<div class="claim-events" style="margin-top:6px">' +
            timeline.slice().reverse().slice(0, 12).map(t =>
              '<div class="claim-event"><div>' + eventChipHtml(String(t.event_type || 'event')) + '<strong>' + escapeHtml(String(t.event_type || 'event')) + '</strong></div>' +
              '<div style="color:var(--text-dim);margin-top:2px">' + escapeHtml(formatTimelineEntry(t)) + '</div></div>'
            ).join('') +
          '</div>'
        )
      : '<div style="margin-top:2px;color:var(--text-dim)">none</div>';

    detailEl.innerHTML =
      '<div><strong>' + String(data.slot_key || slotKey) + '</strong> ' +
      '<span class="bead-status ' + statusClass(String(row.status || 'not_found')) + '">' + String(row.status || 'not_found') + '</span></div>' +
      '<div style="margin-top:2px;color:var(--text-dim)">as_of: ' + escapeHtml(data.as_of || claimsAsOf || 'now') + '</div>' +
      '<div style="margin-top:8px"><strong>Current claim</strong><pre style="margin-top:4px">' + escapeHtml(curText) + '</pre></div>' +
      '<div style="margin-top:8px"><strong>Conflicts</strong> · ' + String(conflicts.length) + '</div>' +
      '<div style="margin-top:2px;color:var(--text-dim)">' + escapeHtml(conflicts.slice(0,3).map(c => String(c.value ?? '—')).join(' | ') || 'none') + '</div>' +
      '<div style="margin-top:8px"><strong>History entries</strong> · ' + String(history.length) + '</div>' +
      historyHtml +
      '<div style="margin-top:8px"><strong>Timeline / updates</strong> · ' + String(timeline.length) + '</div>' +
      timelineHtml;
  } catch (err) {
    if (detailEl.dataset.req !== requestId) return;
    detailEl.textContent = 'Failed to load slot detail: ' + err.message;
  }
}

function formatClaimEntry(c) {
  const parts = [];
  parts.push('value=' + String(c.value ?? '—'));
  parts.push('confidence=' + String(c.confidence ?? '—'));
  if (c.effective_from || c.effective_to) {
    parts.push('effective=' + String(c.effective_from || '…') + '→' + String(c.effective_to || '∞'));
  }
  if (c.source_turn_ids && c.source_turn_ids.length) {
    parts.push('turns=' + String(c.source_turn_ids.length));
  }
  return parts.join(' | ');
}

function formatTimelineEntry(t) {
  const claim = (t || {}).claim || {};
  const update = (t || {}).update || {};
  const bits = [];
  if (claim.id) bits.push('claim=' + String(claim.id));
  if (claim.value !== undefined) bits.push('value=' + String(claim.value));
  if (update.target_claim_id) bits.push('target=' + String(update.target_claim_id));
  if (update.decision) bits.push('decision=' + String(update.decision));
  if (update.effective_from || update.effective_to) {
    bits.push('effective=' + String(update.effective_from || '…') + '→' + String(update.effective_to || '∞'));
  }
  return bits.join(' | ') || 'no additional metadata';
}

function eventChipHtml(eventType) {
  const e = String(eventType || '').toLowerCase();
  let cls = 'event-chip';
  if (e === 'assert') cls += ' event-chip-assert';
  else if (e === 'supersede') cls += ' event-chip-supersede';
  else if (e === 'retract') cls += ' event-chip-retract';
  else if (e === 'conflict') cls += ' event-chip-conflict';
  return '<span class="' + cls + '">' + escapeHtml(e || 'event') + '</span>';
}

function isoToDatetimeLocal(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, '0');
  const day = String(d.getUTCDate()).padStart(2, '0');
  const hh = String(d.getUTCHours()).padStart(2, '0');
  const mm = String(d.getUTCMinutes()).padStart(2, '0');
  return y + '-' + m + '-' + day + 'T' + hh + ':' + mm;
}

function datetimeLocalToIso(v) {
  if (!v) return '';
  const d = new Date(v + ':00Z');
  if (Number.isNaN(d.getTime())) return '';
  return d.toISOString();
}

function formatIsoShort(iso) {
  if (!iso) return 'n/a';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toISOString().replace('T', ' ').replace('.000Z', 'Z');
}

function escapeHtml(s) {
  return String(s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function appendRuntimeCard(container, html) {
  const card = document.createElement('div');
  card.className = 'runtime-card';
  card.innerHTML = String(html || '');
  container.appendChild(card);
  return card;
}

function renderRuntimeFallback(runtime, lastTurn) {
  const el = document.getElementById('tab-runtime-content');
  el.textContent = '';
  const q = runtime?.queue || {};
  const qRows = arrayOrEmpty(runtime?.queue_breakdown);
  const s = runtime?.semantic_backend || {};
  const p = (lastTurn || {}).diagnostics || {};
  const f = runtime?.last_flush || {};
  const fHist = arrayOrEmpty(runtime?.flush_history);
  const my = runtime?.myelination || {};
  const warnCount = arrayOrEmpty(p.warnings).length;
  const mode = String(s.mode || 'degraded_allowed');
  const usable = !!s.usable_backend;
  const strictMode = mode === 'required';
  const warningText = String(s.concurrency_warning || '').trim();
  const showBackendWarning = !!(
    warningText &&
    !(mode === 'degraded_allowed' && /No semantic backend is currently active/i.test(warningText))
  );

  const c1 = appendRuntimeCard(
    el,
    '<div><strong>Async Queue</strong></div>' +
    '<div style="margin-top:4px;color:var(--text-dim)">pending: ' + String(q.pending_total ?? 0) +
    ' · processable: ' + String(q.processable_now ?? 0) + '</div>' +
    '<div style="margin-top:2px;color:var(--text-dim)">ok: ' + String(!!q.ok) + '</div>'
  );

  if (qRows.length) {
    const list = document.createElement('div');
    list.className = 'claim-events';
    qRows.forEach(r => {
      const row = document.createElement('div');
      row.className = 'claim-event';
      const err = String(r.last_error || '').trim();
      row.innerHTML =
        '<div><strong>' + escapeHtml(String(r.kind || 'queue')) + '</strong> ' +
        '<span class="runtime-badge ' + (r.circuit_open ? 'runtime-badge-bad' : 'runtime-badge-good') + '">circuit=' + String(!!r.circuit_open) + '</span></div>' +
        '<div style="color:var(--text-dim)">pending=' + String(r.pending ?? 0) +
        ' · processable=' + String(r.processable_now ?? 0) +
        ' · retry_ready=' + String(r.retry_ready ?? 0) + '</div>' +
        (err ? ('<div style="color:var(--amber)">last_error: ' + escapeHtml(err) + '</div>') : '');
      list.appendChild(row);
    });
    c1.appendChild(list);
  }
  const c2 = appendRuntimeCard(el, '');
  const semanticBadges =
    '<span class="runtime-badge ' + (strictMode ? 'runtime-badge-bad' : 'runtime-badge-warn') + '">mode=' + escapeHtml(mode) + '</span> ' +
    '<span class="runtime-badge ' + (usable ? 'runtime-badge-good' : (strictMode ? 'runtime-badge-bad' : 'runtime-badge-warn')) + '">usable=' + String(usable) + '</span> ' +
    '<span class="runtime-badge ' + (!!s.multi_worker_safe ? 'runtime-badge-good' : 'runtime-badge-warn') + '">multi-worker=' + String(!!s.multi_worker_safe) + '</span> ' +
    '<span class="runtime-badge ' + ((s.connectivity_checked && !s.connectivity_ok) ? 'runtime-badge-bad' : 'runtime-badge-good') + '">connectivity=' + String(s.connectivity_checked ? !!s.connectivity_ok : 'n/a') + '</span>';
  c2.innerHTML =
    '<div><strong>Semantic Backend</strong></div>' +
    '<div style="margin-top:4px;color:var(--text-dim)">backend: ' + String(s.backend || 'unknown') +
    ' · provider: ' + String(s.provider || 'unknown') + '</div>' +
    '<div style="margin-top:2px;color:var(--text-dim)">profile: ' + String(s.deployment_profile || 'n/a') +
    ' · rows: ' + String(s.rows_count ?? 0) + '</div>' +
    '<div style="margin-top:6px">' + semanticBadges + '</div>' +
    ((s.connectivity_checked && !s.connectivity_ok)
      ? ('<div style="margin-top:2px;color:var(--amber)">connectivity_error: ' + escapeHtml(String(s.connectivity_error || 'unknown')) + '</div>')
      : '') +
    '<div style="margin-top:4px;color:var(--text-dim)">next: ' + escapeHtml(String(s.next_step || 'n/a')) + '</div>' +
    (showBackendWarning
      ? ('<div style="margin-top:2px;color:var(--amber)">warning: ' + escapeHtml(warningText) + '</div>')
      : '');
  const c3 = appendRuntimeCard(el, '');
  const topIds = arrayOrEmpty(p.top_bead_ids).slice(0, 5);
  c3.innerHTML =
    '<div><strong>Last Answer Diagnostics</strong></div>' +
    '<div style="margin-top:4px;color:var(--text-dim)">ok: ' + String(!!p.ok) +
    ' · outcome: ' + String(p.answer_outcome || 'n/a') +
    ' · mode: ' + String(p.retrieval_mode || 'n/a') + '</div>' +
    '<div style="margin-top:2px;color:var(--text-dim)">surface: ' + String(p.source_surface || 'n/a') +
    ' · anchor: ' + String(p.anchor_reason || 'n/a') + '</div>' +
    '<div style="margin-top:2px;color:var(--text-dim)">results: ' + String(p.result_count ?? 0) +
    ' · chains: ' + String(p.chain_count ?? 0) +
    ' · warnings: ' + String(warnCount) + '</div>' +
    '<div style="margin-top:2px;color:var(--text-dim)">grounding: ' + String(p.grounding_level || 'n/a') +
    ' · required=' + String(!!p.grounding_required) +
    ' · achieved=' + String(!!p.grounding_achieved) +
    (p.intent_class ? (' · intent=' + escapeHtml(String(p.intent_class))) : '') + '</div>' +
    (p.grounding_reason
      ? ('<div style="margin-top:2px;color:var(--text-dim)">grounding reason: ' + escapeHtml(String(p.grounding_reason)) + '</div>')
      : '') +
    (topIds.length
      ? ('<div style="margin-top:2px;color:var(--text-dim)">top beads: ' + escapeHtml(topIds.join(', ')) + '</div>')
      : '') +
    (warnCount
      ? ('<div style="margin-top:2px;color:var(--amber)">warning list: ' + escapeHtml((p.warnings || []).join(' | ')) + '</div>')
      : '');
  const c4 = appendRuntimeCard(el, '');
  c4.innerHTML =
    '<div><strong>Last Flush</strong></div>' +
    '<div style="margin-top:4px;color:var(--text-dim)">ok: ' + String(!!f.flush_ok) +
    ' · flushed: ' + String(f.flushed_session || 'n/a') + '</div>' +
    '<div style="margin-top:2px;color:var(--text-dim)">trigger: ' + escapeHtml(String(f.trigger || 'n/a')) +
    ' · at: ' + escapeHtml(formatIsoShort(f.timestamp || '')) + '</div>';

  if (fHist.length) {
    const hist = document.createElement('div');
    hist.className = 'claim-events';
    fHist.slice(0, 8).forEach(ev => {
      const row = document.createElement('div');
      row.className = 'claim-event';
      row.innerHTML =
        '<div><strong>' + escapeHtml(String(ev.trigger || 'flush')) + '</strong> ' +
        '<span class="runtime-badge ' + (ev.flush_ok ? 'runtime-badge-good' : 'runtime-badge-bad') + '">ok=' + String(!!ev.flush_ok) + '</span></div>' +
        '<div style="color:var(--text-dim)">flushed=' + escapeHtml(String(ev.flushed_session || 'n/a')) +
        ' · new=' + escapeHtml(String(ev.new_session || 'n/a')) +
        ' · beads=' + String(ev.rolling_window_beads ?? 0) + '</div>' +
        '<div style="color:var(--text-dim)">at=' + escapeHtml(formatIsoShort(ev.timestamp || '')) + '</div>';
      hist.appendChild(row);
    });
    c4.appendChild(hist);
  }
  appendRuntimeCard(
    el,
    '<div><strong>Myelination</strong></div>' +
    '<div style="margin-top:4px;color:var(--text-dim)">enabled: ' + String(!!my.enabled) +
    ' · strengthened/weakened: ' + String((my.stats || {}).strengthened || 0) + '/' + String((my.stats || {}).weakened || 0) + '</div>'
  );
}

function ensureRuntimePaneRenderer() {
  return ensureSliceBinding(
    runtimePaneRenderer,
    'runtimePaneRenderer',
    '/chat-slices/runtime-pane.js',
    (mod) => (mod && typeof mod.renderRuntimePane === 'function' ? mod.renderRuntimePane : null),
    (value) => { runtimePaneRenderer = value; }
  );
}

function renderRuntime(runtime, lastTurn) {
  const safeRuntime = runtime || {};
  const safeLastTurn = lastTurn || {};
  const el = document.getElementById('tab-runtime-content');
  if (!el) return;

  renderViaSlice(
    runtimePaneRenderer,
    (renderer) => renderer(el, {
      runtime: safeRuntime,
      lastTurn: safeLastTurn,
      formatIsoShort,
    }),
    () => renderRuntimeFallback(safeRuntime, safeLastTurn),
    ensureRuntimePaneRenderer
  );
}

function appendBenchCards(container, entries) {
  arrayOrEmpty(entries).forEach(([k, v]) => {
    const c = document.createElement('div');
    c.className = 'bench-card';
    c.innerHTML = '<div class="k">' + String(k) + '</div><div class="v">' + String(v) + '</div>';
    container.appendChild(c);
  });
}

function appendBenchBucket(container, html, modalTitle, payload) {
  const row = document.createElement('div');
  row.className = 'bench-bucket';
  row.innerHTML = String(html || '');
  if (modalTitle) {
    row.addEventListener('click', () => {
      openJsonModal(String(modalTitle), payload);
    });
  }
  container.appendChild(row);
  return row;
}

function appendBenchFail(container, html, opts) {
  const cfg = opts || {};
  const row = document.createElement('div');
  row.className = 'bench-fail';
  row.innerHTML = String(html || '');
  if (cfg.background) row.style.background = String(cfg.background);
  if (cfg.borderColor) row.style.borderColor = String(cfg.borderColor);
  if (cfg.modalTitle) {
    row.addEventListener('click', () => {
      openJsonModal(String(cfg.modalTitle), cfg.payload);
    });
  }
  container.appendChild(row);
  return row;
}

function benchmarkPassFail(pass, fail) {
  return String((pass ?? 0) + '/' + (fail ?? 0));
}

function benchmarkAcc(value) {
  return Number(value || 0).toFixed(4);
}

function benchmarkNA(value) {
  if (value === null || value === undefined) return 'n/a';
  const s = String(value).trim();
  return s ? s : 'n/a';
}

function benchmarkAtValue(atIso) {
  return escapeHtml(formatIsoShort(String(atIso || '')));
}

function benchmarkLatency(value, digits) {
  const n = Number(value || 0);
  const d = Number.isFinite(Number(digits)) ? Number(digits) : 2;
  return n.toFixed(d);
}

function benchmarkLatencyMs(value, digits) {
  return benchmarkLatency(value, digits) + 'ms';
}

function benchmarkTokens(value, opts) {
  const n = Number(value ?? 0);
  const cfg = opts || {};
  return cfg.localize === false ? String(n) : n.toLocaleString();
}

function benchmarkWarnCount(warnings) {
  return arrayOrEmpty(warnings).length;
}

function benchmarkBackendModes(modes) {
  const out = arrayOrEmpty(modes)
    .map((m) => String(m || '').trim())
    .filter(Boolean)
    .join(', ');
  return out || 'unknown';
}

function benchmarkImprovedRegressed(improved, regressed) {
  return String((improved || 0) + '/' + (regressed || 0));
}

function benchmarkCaseId(caseId, fallback) {
  const s = String(caseId || '').trim();
  if (s) return s;
  return String(fallback || 'detail');
}

function benchmarkCaseTitle(prefix, caseId) {
  return String(prefix || 'Benchmark case') + ': ' + benchmarkCaseId(caseId, 'detail');
}

function benchmarkRunRowHtml(summary, fallbackRunId, atIso, includePerf) {
  const s = summary || {};
  const perf = includePerf
    ? (
      ' · latency=' + benchmarkLatencyMs(s.latency_mean_ms || 0, 2) +
      ' · tokens=' + benchmarkTokens(s.tokens_total_est || 0)
    )
    : '';
  return (
    '<div><strong>' + escapeHtml(String(s.run_id || fallbackRunId || 'run')) + '</strong></div>' +
    '<div style="margin-top:2px;color:var(--text-dim)">acc=' + benchmarkAcc(s.accuracy || 0) +
    ' · pass/fail=' + benchmarkPassFail(s.pass || 0, s.fail || 0) +
    perf + '</div>' +
    '<div style="margin-top:2px;color:var(--text-dim)">at=' + benchmarkAtValue(atIso) + '</div>'
  );
}

function benchmarkDeltaClass(delta) {
  const d = Number(delta || 0);
  if (d > 0) return 'bench-delta-good';
  if (d < 0) return 'bench-delta-bad';
  return 'bench-delta-neutral';
}

function benchmarkDeltaSpan(delta, digits) {
  const d = Number(delta || 0);
  const n = Number.isFinite(Number(digits)) ? Number(digits) : 4;
  return '<span class="' + benchmarkDeltaClass(d) + '">' + d.toFixed(n) + '</span>';
}

function renderBenchmarkFallback(summary, report, benchmarkMeta) {
  const el = document.getElementById('tab-benchmark-content');
  el.textContent = '';
  const history = arrayOrEmpty((benchmarkMeta || {}).history);
  if (!summary || !summary.cases) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = 'No benchmark run yet';
    el.appendChild(empty);
    if (history.length) {
      appendRuntimeCard(el, '<strong>Recent runs</strong>');
      history.slice(0, 8).forEach(r => {
        const s = r.summary || {};
        appendBenchBucket(
          el,
          benchmarkRunRowHtml(s, r.run_id || 'run', s.finished_at || r.created_at || '', false),
          'Benchmark run summary',
          r
        );
      });
    }
    return;
  }

  const g = document.createElement('div');
  g.className = 'bench-grid';
  const latencyMean = benchmarkLatency(((report || {}).latency_ms || {}).mean || 0, 2);
  const tokenTotal = Number(((report || {}).token_usage || {}).total_tokens_est || 0);
  const cards = [
    ['accuracy', benchmarkAcc(summary.accuracy || 0)],
    ['cases', String(summary.cases || 0)],
    ['pass/fail', benchmarkPassFail(summary.pass || 0, summary.fail || 0)],
    ['semantic', benchmarkNA(summary.semantic_mode)],
    ['latency mean (ms)', latencyMean],
    ['tokens est', benchmarkTokens(tokenTotal)],
  ];
  appendBenchCards(g, cards);
  el.appendChild(g);

  const meta = appendRuntimeCard(el, '');
  const cmp = summary.myelination_compare || null;
  const cmpLine = cmp
    ? ('<div style="margin-top:2px;color:var(--text-dim)">compare Δ=' + benchmarkAcc(cmp.accuracy_delta || 0) +
       ' · improved/regressed=' + benchmarkImprovedRegressed(cmp.improved_cases || 0, cmp.regressed_cases || 0) + '</div>')
    : '';
  meta.innerHTML =
    '<div><strong>Run config</strong></div>' +
    '<div style="margin-top:2px;color:var(--text-dim)">run_id: ' + escapeHtml(benchmarkNA(summary.run_id)) +
    ' · at: ' + benchmarkAtValue(summary.finished_at || summary.started_at || '') + '</div>' +
    '<div style="margin-top:4px;color:var(--text-dim)">root mode: ' + benchmarkNA(summary.root_mode) +
    ' · preload turns: ' + String(summary.preload_turn_count || 0) + '</div>' +
    '<div style="margin-top:2px;color:var(--text-dim)">backend modes: ' + benchmarkBackendModes(summary.backend_modes) + '</div>' +
    '<div style="margin-top:2px;color:var(--text-dim)">warnings: ' + String(benchmarkWarnCount(summary.warnings)) + '</div>' +
    cmpLine +
    '<div style="margin-top:6px"><button class="btn" id="btn-bench-raw">Open raw JSON</button></div>';
  const rawBtn = meta.querySelector('#btn-bench-raw');
  if (rawBtn) {
    rawBtn.addEventListener('click', () => {
      openJsonModal('LOCOMO Benchmark Report (raw JSON)', report || {});
    });
  }

  const r = report || null;
  if (r && r.per_bucket) {
    Object.keys(r.per_bucket).sort().forEach(k => {
      const row = r.per_bucket[k] || {};
      appendBenchBucket(
        el,
        '<strong>' + k + '</strong> · acc=' + benchmarkAcc(row.accuracy || 0) +
        ' · pass/fail=' + benchmarkPassFail(row.pass || 0, row.fail || 0)
      );
    });
  }

  if (r && r.myelination_comparison) {
    const mc = r.myelination_comparison || {};
    const baseline = mc.baseline || {};
    const enabled = mc.enabled || {};
    const delta = Number(mc.accuracy_delta || 0);
    const cases = arrayOrEmpty(mc.cases);
    const improved = cases.filter(c => !c.baseline_pass && c.enabled_pass);
    const regressed = cases.filter(c => c.baseline_pass && !c.enabled_pass);
    const changed = cases.filter(c => !!c.pass_changed);

    appendRuntimeCard(
      el,
      '<div><strong>Myelination compare</strong></div>' +
      '<div style="margin-top:4px;color:var(--text-dim)">baseline acc=' + benchmarkNA(baseline.accuracy) +
      ' · enabled acc=' + benchmarkNA(enabled.accuracy) +
      ' · delta=' + benchmarkDeltaSpan(delta, 4) + '</div>' +
      '<div style="margin-top:2px;color:var(--text-dim)">pass/fail baseline=' + benchmarkPassFail(baseline.pass ?? 0, baseline.fail ?? 0) +
      ' · enabled=' + benchmarkPassFail(enabled.pass ?? 0, enabled.fail ?? 0) + '</div>'
    );

    const mg = document.createElement('div');
    mg.className = 'bench-grid';
    appendBenchCards(mg, [
      ['improved', String(improved.length)],
      ['regressed', String(regressed.length)],
      ['changed', String(changed.length)],
      ['unchanged', String(cases.length - changed.length)],
    ]);
    el.appendChild(mg);

    if (changed.length) {
      appendRuntimeCard(el, '<strong>Pass-state changes</strong>');

      const ordered = changed.slice().sort((a, b) => {
        const aReg = (!!a.baseline_pass && !a.enabled_pass) ? 1 : 0;
        const bReg = (!!b.baseline_pass && !b.enabled_pass) ? 1 : 0;
        if (aReg !== bReg) return bReg - aReg; // regressions first
        return benchmarkCaseId(a.case_id, '').localeCompare(benchmarkCaseId(b.case_id, ''));
      });

      ordered.slice(0, 20).forEach(c => {
        const regressedNow = !!c.baseline_pass && !c.enabled_pass;
        const improvedNow = !c.baseline_pass && !!c.enabled_pass;
        appendBenchFail(
          el,
          '<div><strong>' + benchmarkCaseId(c.case_id, 'case') + '</strong> · ' + (improvedNow ? '<span class="bench-delta-good">improved</span>' : (regressedNow ? '<span class="bench-delta-bad">regressed</span>' : 'changed')) + '</div>' +
          '<div style="color:var(--text-dim);margin-top:2px">baseline=' + String(!!c.baseline_pass) +
          ' · enabled=' + String(!!c.enabled_pass) +
          ' · latency Δ=' + benchmarkLatencyMs(c.latency_delta_ms || 0, 3) + '</div>',
          {
            background: improvedNow ? 'rgba(74, 222, 128, 0.08)' : 'rgba(248, 113, 113, 0.08)',
            borderColor: improvedNow ? 'rgba(74, 222, 128, 0.30)' : 'rgba(248, 113, 113, 0.25)',
            modalTitle: benchmarkCaseTitle('Myelination compare case', c.case_id),
            payload: c,
          }
        );
      });
    }
  }

  const cases = arrayOrEmpty(r && r.cases);
  if (cases.length) {
    const fails = cases.filter(c => !c.pass);
    if (fails.length) {
      appendRuntimeCard(el, '<strong>Failing cases</strong>');
      fails.forEach(c => {
        appendBenchFail(
          el,
          '<div><strong>' + benchmarkCaseId(c.case_id, 'case') + '</strong></div>' +
          '<div style="color:var(--text-dim);margin-top:2px">expected=' + benchmarkNA(c.expected_answer_class) +
          ' · actual=' + benchmarkNA(c.actual_answer_class) + '</div>' +
          '<div style="color:var(--text-dim);margin-top:2px">surface=' + benchmarkNA(c.top_source_surface) +
          ' · anchor=' + benchmarkNA(c.top_anchor_reason) + '</div>' +
          '<div style="color:var(--text-dim);margin-top:2px">backend=' + benchmarkNA(c.benchmark_backend_mode) +
          ' · tokens=' + benchmarkTokens(((c.token_usage || {}).total_tokens_est ?? 0), { localize: false }) +
          ' · warnings=' + String(benchmarkWarnCount(c.warnings)) + '</div>',
          {
            modalTitle: benchmarkCaseTitle('Benchmark case', c.case_id),
            payload: c,
          }
        );
      });
    }
  }

  if (history.length) {
    appendRuntimeCard(el, '<strong>Recent runs</strong><div style="margin-top:2px;color:var(--text-dim)">Click a row for full payload.</div>');

    history.slice(0, 12).forEach((rowData, idx) => {
      const s = rowData.summary || {};
      appendBenchBucket(
        el,
        benchmarkRunRowHtml(s, rowData.run_id || ('run-' + idx), s.finished_at || rowData.created_at || '', true),
        'Benchmark run',
        rowData
      );
    });

    if (summary.run_id && history.length >= 2) {
      const current = history.find(hx => String((hx.summary || {}).run_id || hx.run_id || '') === String(summary.run_id));
      const baseline = history.find(hx => String((hx.summary || {}).run_id || hx.run_id || '') !== String(summary.run_id));
      if (current && baseline) {
        const cs = current.summary || {};
        const bs = baseline.summary || {};
        const dAcc = Number(cs.accuracy || 0) - Number(bs.accuracy || 0);
        const dLat = Number(cs.latency_mean_ms || 0) - Number(bs.latency_mean_ms || 0);
        const dTok = Number(cs.tokens_total_est || 0) - Number(bs.tokens_total_est || 0);
        appendRuntimeCard(
          el,
          '<div><strong>Latest vs previous run</strong></div>' +
          '<div style="margin-top:2px;color:var(--text-dim)">baseline=' + escapeHtml(String(bs.run_id || baseline.run_id || 'n/a')) +
          ' → current=' + escapeHtml(String(cs.run_id || current.run_id || 'n/a')) + '</div>' +
          '<div style="margin-top:4px;color:var(--text-dim)">accuracy Δ=' + benchmarkDeltaSpan(dAcc, 4) +
          ' · latency Δ=' + benchmarkLatencyMs(dLat, 3) +
          ' · tokens Δ=' + benchmarkTokens(dTok) + '</div>'
        );
      }
    }
  }
}

function ensureBenchmarkPaneRenderer() {
  return ensureSliceBinding(
    benchmarkPaneRenderer,
    'benchmarkPaneRenderer',
    '/chat-slices/benchmark-pane.js',
    (mod) => (mod && typeof mod.renderBenchmarkPane === 'function' ? mod.renderBenchmarkPane : null),
    (value) => { benchmarkPaneRenderer = value; }
  );
}

function renderBenchmark(summary, report, benchmarkMeta) {
  const safeSummary = summary || {};
  const safeReport = report || null;
  const safeMeta = benchmarkMeta || {};
  const el = document.getElementById('tab-benchmark-content');
  if (!el) return;

  renderViaSlice(
    benchmarkPaneRenderer,
    (renderer) => renderer(el, {
      summary: safeSummary,
      report: safeReport,
      benchmarkMeta: safeMeta,
      formatIsoShort,
      onOpenPayload: (title, payload) => {
        openJsonModal(String(title || 'Benchmark detail'), payload || {});
      },
    }),
    () => renderBenchmarkFallback(safeSummary, safeReport, safeMeta),
    ensureBenchmarkPaneRenderer
  );
}

async function refreshMemory() {
  if (authEnabled && !authReady) return;
  if (!modelOptionsHydrated) loadDemoModels();
  try {
    const stateUrl = claimsAsOf
      ? ('/v1/memory/inspect/state?as_of=' + encodeURIComponent(claimsAsOf))
      : '/v1/memory/inspect/state';
    const res = await fetch(stateUrl);
    const data = await parseApiJsonResponse(res, 'state');
    const mem = data.memory || {};
    let sess = data.session || {};
    const claims = data.claims || {};
    const entities = data.entities || {};
    const statsCompat = data.stats || {};
    let runtimeLocal = {};
    let lastTurnLocal = {};

    try {
      const rr = await fetch('/api/demo/runtime');
      const jr = await parseApiJsonResponse(rr, 'runtime');
      runtimeLocal = jr.runtime || {};
      lastTurnLocal = jr.last_turn || {};
      if (jr.session) sess = jr.session;
    } catch (_) {
      // keep inspect-only fallback
    }

    renderBeads(mem.beads || data.beads || []);
    renderAssociations(mem.associations || data.associations || []);
    renderClaims(claims.slots || data.claim_state || [], claims);
    renderEntities(entities);
    renderRuntime(data.runtime || runtimeLocal || {}, lastTurnLocal || {});
    renderRolling(mem.rolling_window || data.rolling_window || []);

    lastBenchmarkSummary = (data.benchmark || {}).last_summary || lastBenchmarkSummary;
    lastBenchmarkHistory = arrayOr((data.benchmark || {}).history, lastBenchmarkHistory);
    if ((data.benchmark || {}).has_last_report && !lastBenchmarkReport) {
      try {
        const rb = await fetch('/api/demo/benchmark/last');
        const jb = await rb.json();
        if (jb && jb.ok && jb.report) {
          lastBenchmarkReport = jb.report;
          if (jb.summary) lastBenchmarkSummary = jb.summary;
          lastBenchmarkHistory = arrayOr(jb.history, lastBenchmarkHistory);
        }
      } catch (_) {
        // best effort only
      }
    }
    renderBenchmark(lastBenchmarkSummary || {}, lastBenchmarkReport || null, {history: lastBenchmarkHistory});

    document.getElementById('stat-beads').textContent = Number(statsCompat.total_beads || (mem.beads || []).length || 0);
    document.getElementById('stat-assoc').textContent = Number(statsCompat.total_associations || (mem.associations || []).length || 0);
    document.getElementById('stat-claims').textContent = Number(statsCompat.claim_slot_count || (claims.slots || []).length || 0);
    document.getElementById('stat-entities').textContent = Number(statsCompat.entity_count || (entities.rows || []).length || 0);
    document.getElementById('stat-rolling').textContent = Number(statsCompat.rolling_window_size || (mem.rolling_window || []).length || 0);
    const usage = Number(sess.token_usage ?? statsCompat.token_usage ?? 0);
    const budget = Number(sess.context_budget ?? statsCompat.context_budget ?? 128000);
    const rollingWindowTokens = Number(
      sess.rolling_window_token_estimate ??
      statsCompat.rolling_window_token_estimate ??
      0
    );
    const totalUsedTokens = Math.min(
      Math.max(0, budget),
      Math.max(0, usage) + Math.max(0, rollingWindowTokens)
    );
    const windowPct = budget > 0 ? ((totalUsedTokens / budget) * 100) : 0;
    document.getElementById('stat-tokens').textContent = Math.round(totalUsedTokens);
    document.getElementById('stat-budget').textContent = budget;
    document.getElementById('session-badge').textContent = 'session: ' + String(sess.session_id || statsCompat.session_id || '---') + ' ▾';
    if (modelSelectEl) {
      const selectedOverride = String(sess.model_override || '').trim();
      if (modelSelectEl.value !== selectedOverride) {
        modelSelectEl.value = selectedOverride;
      }
    }

    const fill = document.getElementById('budget-fill');
    fill.style.width = windowPct.toFixed(1) + '%';
    fill.className = 'budget-fill' + (windowPct >= AUTO_FLUSH_THRESHOLD_PCT ? ' critical' : windowPct >= 50 ? ' warn' : '');
    document.getElementById('budget-text').textContent = windowPct.toFixed(1) + '% used';
    refreshErrorStreak = 0;
  } catch (err) {
    refreshErrorStreak += 1;
    if (refreshErrorStreak >= 3 && refreshTimerId) {
      clearInterval(refreshTimerId);
      refreshTimerId = null;
      addMsg('system', 'Data refresh paused due to repeated backend/proxy errors. Use Refresh or reload after backend recovers.');
    }
    console.error('refreshMemory failed:', err);
  }
}

async function showBead(id) {
  try {
    const res = await fetch('/v1/memory/inspect/beads/' + encodeURIComponent(id));
    const data = await res.json();
    const bead = data.bead || data;
    let hydrated = null;
    try {
      const rh = await fetch('/v1/memory/inspect/beads/' + encodeURIComponent(id) + '/hydrate');
      const jh = await rh.json();
      if (jh && jh.ok) hydrated = jh;
    } catch (_) {
      // optional surface
    }
    const payload = hydrated ? { bead, hydrated_sources: hydrated } : bead;
    openJsonModal(bead.title || 'Bead Detail', payload);
  } catch (err) {
    alert('Failed to load bead: ' + err.message);
  }
}

function openJsonModal(title, payload) {
  const titleEl = document.getElementById('modal-title');
  const bodyEl = document.getElementById('modal-body');
  const modalEl = document.getElementById('modal');
  if (!titleEl || !bodyEl || !modalEl) return;

  titleEl.textContent = String(title || 'Detail');
  bodyEl.textContent = JSON.stringify(payload || {}, null, 2);
  modalEl.classList.add('open');
}

function closeModal() {
  document.getElementById('modal').classList.remove('open');
}

async function seedMemory() {
  const seedBtn = document.getElementById('btn-seed');
  const prevSeedLabel = seedBtn ? seedBtn.textContent : '';
  if (seedBtn) {
    seedBtn.disabled = true;
    seedBtn.textContent = 'Seeding...';
  }

  try {
    const preloadEnabled = !!document.getElementById('bench-preload-enabled')?.checked;
    const preloadRaw = Number(document.getElementById('bench-preload-max')?.value || 200);
    const preloadMax = Number.isFinite(preloadRaw) ? Math.max(1, Math.floor(preloadRaw)) : 200;
    const continueStory = !!document.getElementById('seed-continue-story')?.checked;
    let resetBeforeRun = !!document.getElementById('seed-reset-before-run')?.checked;
    let wipeBeforeRun = !!document.getElementById('seed-wipe-memory')?.checked;

    if (preloadEnabled && continueStory) {
      if (resetBeforeRun || wipeBeforeRun) {
        const resetEl = document.getElementById('seed-reset-before-run');
        const wipeEl = document.getElementById('seed-wipe-memory');
        if (resetEl) resetEl.checked = false;
        if (wipeEl) wipeEl.checked = false;
        saveSeedResetPrefs();
        addMsg('system', 'Seed note: continuing from story bookmark, so fresh-session reset was skipped.');
      }
      resetBeforeRun = false;
      wipeBeforeRun = false;
    }

    if (resetBeforeRun) {
      const resetOut = await resetSessionForSeed({wipeMemory: wipeBeforeRun});
      if (wipeBeforeRun) {
        setStoryCursorTurn(0);
      }
      addMsg(
        'system',
        'Seed prep: fresh session ' + String(resetOut.new_session || 'n/a') +
        (resetOut.wiped_memory ? ' (memory cleared)' : '')
      );
    }

    let data = null;

    if (preloadEnabled) {
      let startTurn = 1;
      if (continueStory) {
        startTurn = Math.max(1, getStoryCursorTurn() + 1);
      }

      let totalTurns = 0;
      try {
        const metaRes = await fetch('/api/story-pack/meta');
        const meta = await metaRes.json();
        if (metaRes.ok && meta && meta.ok) {
          totalTurns = Number(meta.loaded_turns || meta.total_turns || 0) || 0;
        }
      } catch (_) {
        totalTurns = 0;
      }

      if (totalTurns > 0 && startTurn > totalTurns) {
        addMsg('system', 'Story-pack cursor is already at the end (turn ' + totalTurns + '). Reset cursor to seed from turn 1 again.');
        return;
      }

      const progress = addMsg('system', 'Seeding story-pack... starting at turn ' + startTurn);
      const res = await fetch('/api/story-pack/replay', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          start_turn: startTurn,
          max_turns: preloadMax,
          auto_flush: true,
          flush_threshold_ratio: AUTO_FLUSH_THRESHOLD_PCT / 100,
          run_checkpoints: false,
          reset_session: false,
          use_manifest_sessions: false,
          wait_for_idle: true,
          idle_timeout_ms: 120000,
          idle_poll_ms: 250,
        }),
      });
      data = await res.json();
      if (!res.ok || !data.ok) {
        const err = firstPayloadError(data) || data.error || ('HTTP ' + res.status);
        throw new Error(String(err));
      }

      const seededTotal = Number(data.seeded || data.seeded_turns || 0);
      const queueIdle = !!data.queue_idle;
      const fallbackTurns = Number(data.fallback_turns || 0);
      const range = data.turn_range || {};
      const firstTurn = Number(range.first || startTurn || 0) || 0;
      const lastTurn = Number(range.last || (firstTurn + Math.max(0, seededTotal - 1))) || 0;

      if (continueStory && seededTotal > 0 && lastTurn > 0) {
        setStoryCursorTurn(lastTurn);
      }

      progress.textContent =
        'Seeded ' + seededTotal + ' turn(s) via story-pack replay' +
        (firstTurn > 0 && lastTurn > 0 ? (' · range=' + firstTurn + '-' + lastTurn) : '') +
        ' · queue_idle=' + String(queueIdle) +
        (fallbackTurns > 0 ? (' · fallback=' + fallbackTurns) : '');
      if (fallbackTurns > 0) {
        const ferr = data && data.fallback_error_counts ? Object.entries(data.fallback_error_counts).sort((a,b)=>Number(b[1])-Number(a[1]))[0] : null;
        const ferrMsg = ferr ? (' Top error: ' + String(ferr[0])) : '';
        addMsg('system', 'Warning: fallback mode was used for ' + fallbackTurns + ' turn(s).' + ferrMsg + ' Configure model selection/API keys on backend to enable full claim/entity/association extraction.');
      }
    } else {
      const progress = addMsg('system', 'Seeding default demo turns...');
      const res = await fetch('/api/seed', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          wait_for_idle: true,
          auto_flush: true,
          flush_threshold_ratio: AUTO_FLUSH_THRESHOLD_PCT / 100,
        }),
      });
      data = await res.json();
      if (!res.ok || !data.ok) {
        const err = firstPayloadError(data) || data.error || ('HTTP ' + res.status);
        throw new Error(String(err));
      }
      const seeded = Number(data.seeded || data.seeded_turns || 0);
      progress.textContent =
        'Seeded ' + seeded + ' turn(s) via chat replay' +
        (data.flush_count != null ? (' · flushes=' + String(data.flush_count || 0)) : '') +
        ' · queue_idle=' + String(!!data.queue_idle) +
        (Number(data.fallback_turns || 0) > 0 ? (' · fallback=' + String(data.fallback_turns || 0)) : '');
      if (Number(data.fallback_turns || 0) > 0) {
        const ferr = data && data.fallback_error_counts ? Object.entries(data.fallback_error_counts).sort((a,b)=>Number(b[1])-Number(a[1]))[0] : null;
        const ferrMsg = ferr ? (' Top error: ' + String(ferr[0])) : '';
        addMsg('system', 'Warning: fallback mode was used for ' + String(data.fallback_turns || 0) + ' turn(s).' + ferrMsg + ' Configure model selection/API keys on backend to enable full claim/entity/association extraction.');
      }
    }

    refreshMemory();
  } catch (err) {
    if (String(err && err.message || '') === 'Hard reset canceled') return;
    alert('Seed failed: ' + err.message);
  } finally {
    if (seedBtn) {
      seedBtn.disabled = false;
      seedBtn.textContent = prevSeedLabel || 'Seed';
    }
  }
}

async function flushSession() {
  try {
    const res = await fetch('/api/flush', {method: 'POST'});
    const data = await res.json();
    addMsg('system',
      'Session flushed: ' + data.flushed_session + '\n' +
      'New session: ' + data.new_session + '\n' +
      'Rolling window: ' + data.rolling_window_beads + ' bead(s)'
    );
    refreshMemory();
  } catch (err) {
    alert('Flush failed: ' + err.message);
  }
}

function formatBenchmarkSummary(s) {
  if (!s) return 'Benchmark completed.';
  const warns = benchmarkWarnCount(s.warnings);
  return (
    'LOCOMO test completed\n' +
    'mode: isolated benchmark store (demo state not mutated)\n' +
    'root mode: ' + benchmarkNA(s.root_mode) + '\n' +
    'cases: ' + (s.cases ?? 0) + '\n' +
    'pass/fail: ' + benchmarkPassFail(s.pass ?? 0, s.fail ?? 0) + '\n' +
    'accuracy: ' + benchmarkAcc(s.accuracy || 0) + '\n' +
    'semantic mode: ' + benchmarkNA(s.semantic_mode) + '\n' +
    'backend modes: ' + benchmarkBackendModes(s.backend_modes) + '\n' +
    'preload turns: ' + (s.preload_turn_count ?? 0) + '\n' +
    'warnings: ' + warns
  );
}

async function runBenchmark() {
  const btn = document.getElementById('btn-benchmark');
  if (!btn) return;
  const subset = document.getElementById('bench-subset')?.value || 'local';
  const semanticMode = document.getElementById('bench-semantic')?.value || 'required';
  const myelination = document.getElementById('bench-myelination')?.value || 'off';
  const rootMode = document.getElementById('bench-root-mode')?.value || 'snapshot';
  const preloadEnabled = !!document.getElementById('bench-preload-enabled')?.checked;
  const preloadRaw = Number(document.getElementById('bench-preload-max')?.value || 200);
  const preloadMax = Number.isFinite(preloadRaw) ? Math.max(0, Math.floor(preloadRaw)) : 200;

  const prev = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Running...';
  addMsg(
    'system',
    'Running LOCOMO benchmark (' + subset + ', semantic=' + semanticMode + ', myelination=' + myelination + ', root=' + rootMode +
      ', preload=' + (preloadEnabled ? preloadMax : 0) + ')...'
  );
  try {
    const res = await fetch('/api/benchmark-run', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        subset,
        semantic_mode: semanticMode,
        vector_backend: 'local-faiss',
        myelination,
        root_mode: rootMode,
        preload_from_demo: preloadEnabled,
        preload_turns_max: preloadMax,
      }),
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      throw new Error(data.error || ('HTTP ' + res.status));
    }
    lastBenchmarkSummary = data.summary || {};
    lastBenchmarkReport = data.report || null;
    try {
      const rh = await fetch('/api/demo/benchmark/history?limit=20');
      const jh = await rh.json();
      if (jh && jh.ok) lastBenchmarkHistory = arrayOr(jh.history, lastBenchmarkHistory);
    } catch (_) {
      // best effort only
    }
    renderBenchmark(lastBenchmarkSummary, lastBenchmarkReport, {history: lastBenchmarkHistory});
    addMsg('system', formatBenchmarkSummary(data.summary || {}));
  } catch (err) {
    addMsg('system', 'Benchmark failed: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = prev;
  }
}

function switchTab(name) {
  const sel = document.getElementById('tab-selector');
  if (sel && sel.value !== name) sel.value = name;
  document.querySelectorAll('.tab-content').forEach(t => t.classList.toggle('active', t.id === 'tab-' + name));
}

function startDemoUi() {
  bindUiEventHandlers();
  loadClaimsStateFromUrl();
  loadSeedResetPrefs();
  bindSessionPopoverControls();
  loadDemoModels();
  refreshErrorStreak = 0;
  refreshMemory();
  if (refreshTimerId) clearInterval(refreshTimerId);
  refreshTimerId = setInterval(refreshMemory, 2500);
}

async function bootstrapDemo() {
  const ok = await initAuthGate();
  if (!ok) return;
  startDemoUi();
}

bootstrapDemo();
document.addEventListener('click', e => {
  const wrap = document.querySelector('.session-chip-wrap');
  if (!wrap) return;
  if (!wrap.contains(e.target)) {
    closeSessionPopover();
  }
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    closeModal();
    closeSessionPopover();
  }
});
