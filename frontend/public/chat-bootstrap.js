(function () {
  const AUTH_TOKEN_KEY = 'CORE_MEMORY_AUTH_TOKEN';
  const SESSION_KEY = 'CORE_MEMORY_CLIENT_SESSION_ID';
  const params = new URLSearchParams(window.location.search);
  const qRaw = (params.get('api_base') || '').trim();
  let s = '';
  try { s = (localStorage.getItem('CORE_MEMORY_API_BASE') || '').trim(); } catch {}
  const isHostedDemo = window.location.hostname === 'demo.usecorememory.com';
  const q = isHostedDemo ? '' : qRaw;
  const defaultApiBase = isHostedDemo ? '' : '';
  const hostedDirectBase = isHostedDemo ? 'https://core-memory-demo.onrender.com' : '';
  const apiBase = (q || (isHostedDemo ? defaultApiBase : s) || '').replace(/\/+$/, '');
  const apiOrigin = (() => {
    try { return apiBase ? new URL(apiBase, window.location.origin).origin : ''; } catch { return ''; }
  })();
  const hostedDirectOrigin = (() => {
    try { return hostedDirectBase ? new URL(hostedDirectBase, window.location.origin).origin : ''; } catch { return ''; }
  })();
  window.__CORE_MEMORY_HOSTED_DIRECT_BASE = hostedDirectBase;
  if (isHostedDemo && qRaw) {
    try {
      const clean = new URL(window.location.href);
      clean.searchParams.delete('api_base');
      window.history.replaceState({}, document.title, clean.toString());
    } catch {}
  }
  const forceRoot = String(params.get('force_root') || '').trim() === '1';
  if (forceRoot && window.self === window.top && /\/chat\.html$/.test(window.location.pathname)) {
    const rootUrl = new URL('/', window.location.origin);
    if (window.location.search) rootUrl.search = window.location.search;
    rootUrl.searchParams.delete('force_root');
    window.location.replace(rootUrl.toString());
    return;
  }
  try {
    if (q) localStorage.setItem('CORE_MEMORY_API_BASE', apiBase);
    else if (isHostedDemo) localStorage.removeItem('CORE_MEMORY_API_BASE');
    else if (apiBase) localStorage.setItem('CORE_MEMORY_API_BASE', apiBase);
  } catch {}
  const nativeFetch = window.fetch.bind(window);
  window.__CORE_MEMORY_NATIVE_FETCH = nativeFetch;
  window.__CORE_MEMORY_SET_TOKEN = (token) => {
    try {
      if (token) localStorage.setItem(AUTH_TOKEN_KEY, String(token));
      else localStorage.removeItem(AUTH_TOKEN_KEY);
    } catch {}
  };
  window.__CORE_MEMORY_GET_TOKEN = () => {
    try { return (localStorage.getItem(AUTH_TOKEN_KEY) || '').trim(); } catch { return ''; }
  };
  window.__CORE_MEMORY_REFRESH_TOKEN = async () => {
    return '';
  };

  function getOrCreateClientSessionId() {
    try {
      const existing = String(localStorage.getItem(SESSION_KEY) || '').trim();
      if (existing) return existing;
    } catch (_) {}

    let next = '';
    try {
      if (window.crypto && typeof window.crypto.randomUUID === 'function') {
        next = String(window.crypto.randomUUID()).trim();
      }
    } catch (_) {}
    if (!next) {
      next = 'sess-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
    }

    try { localStorage.setItem(SESSION_KEY, next); } catch (_) {}
    return next;
  }

  function resolveTargetUrl(input) {
    try {
      const raw = (typeof input === 'string') ? input : String((input && input.url) || '');
      return new URL(raw, window.location.origin);
    } catch (_) {
      return null;
    }
  }

  function shouldAttachCoreHeaders(targetUrl) {
    if (!targetUrl) return false;
    const origin = String(targetUrl.origin || '');
    if (!origin) return false;
    if (origin === window.location.origin) return true;
    if (apiOrigin && origin === apiOrigin) return true;
    if (hostedDirectOrigin && origin === hostedDirectOrigin) return true;
    return false;
  }

  window.fetch = (input, init) => {
    const originalInput = input;
    const nextInit = Object.assign({}, init || {});
    const inheritedHeaders = (!nextInit.headers && input && typeof input !== 'string' && input.headers)
      ? input.headers
      : undefined;

    if (apiBase && typeof input === 'string' && input.startsWith('/')) {
      input = apiBase + input;
    }

    const targetUrl = resolveTargetUrl(input);
    const headers = new Headers(nextInit.headers || inheritedHeaders || undefined);

    if (shouldAttachCoreHeaders(targetUrl)) {
      const token = window.__CORE_MEMORY_GET_TOKEN();
      if (token && !headers.has('Authorization')) {
        headers.set('Authorization', 'Bearer ' + token);
      }

      const sessionId = getOrCreateClientSessionId();
      if (sessionId && !headers.has('X-Core-Memory-Session')) {
        headers.set('X-Core-Memory-Session', sessionId);
      }
    }

    nextInit.headers = headers;
    const rawInput = originalInput;
    const tryHostedDirect = () => {
      if (!hostedDirectBase || typeof rawInput !== 'string' || !rawInput.startsWith('/')) return null;
      return nativeFetch(hostedDirectBase + rawInput, nextInit);
    };

    return nativeFetch(input, nextInit)
      .then((resp) => {
        if (resp.status === 401 && shouldAttachCoreHeaders(targetUrl) && typeof window.__CORE_MEMORY_REFRESH_TOKEN === 'function') {
          return Promise.resolve(window.__CORE_MEMORY_REFRESH_TOKEN())
            .then((freshToken) => {
              const tok = String(freshToken || '').trim();
              if (!tok) return resp;
              const retryInit = Object.assign({}, nextInit);
              const retryHeaders = new Headers(retryInit.headers || undefined);
              retryHeaders.set('Authorization', 'Bearer ' + tok);
              retryInit.headers = retryHeaders;
              return nativeFetch(input, retryInit);
            })
            .catch(() => resp);
        }
        if (resp.status >= 500) {
          const alt = tryHostedDirect();
          if (alt) return alt;
        }
        return resp;
      })
      .catch((err) => {
        if (apiBase && typeof input === 'string' && input.startsWith(apiBase + '/')) {
          const fallback = input.slice(apiBase.length);
          return nativeFetch(fallback, nextInit);
        }
        const alt = tryHostedDirect();
        if (alt) return alt;
        throw err;
      });
  };
  window.__CORE_MEMORY_API_BASE = apiBase;
})();
