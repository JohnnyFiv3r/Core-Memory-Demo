import { useEffect, useMemo, useState } from 'react'
import { getApiBase } from './api'

const FIRST_LOAD_SPLASH_KEY = 'CM_FIRST_LOAD_SPLASH_DONE'
const FIRST_LOAD_SPLASH_MS = 2000

export function App() {
  const uiRev = '20260418-graph-default-01'
  const [showSplash, setShowSplash] = useState(() => {
    if (typeof window === 'undefined') return false
    try {
      return window.sessionStorage.getItem(FIRST_LOAD_SPLASH_KEY) !== '1'
    } catch {
      return true
    }
  })

  useEffect(() => {
    if (!showSplash) return
    try {
      window.sessionStorage.setItem(FIRST_LOAD_SPLASH_KEY, '1')
    } catch {
      // best effort only
    }
    const timer = window.setTimeout(() => setShowSplash(false), FIRST_LOAD_SPLASH_MS)
    return () => window.clearTimeout(timer)
  }, [showSplash])

  const apiBase = getApiBase()
  const src = useMemo(() => {
    if (typeof window === 'undefined') return `/graph.html?ui_rev=${encodeURIComponent(uiRev)}`

    const params = new URLSearchParams(window.location.search)
    const requestedView = String(params.get('view') || 'graph').trim().toLowerCase()
    const targetPath = requestedView === 'demo' || requestedView === 'legacy' ? '/chris-demo.html' : '/graph.html'
    params.delete('view')
    if (apiBase) params.set('api_base', apiBase)
    params.set('ui_rev', uiRev)

    const q = params.toString()
    return `${targetPath}${q ? `?${q}` : ''}`
  }, [apiBase, uiRev])

  return (
    <main style={{ margin: 0, padding: 0, height: '100vh', width: '100vw', overflow: 'hidden', background: '#020304' }}>
      <style>{'@keyframes cmFirstLoadSpin { to { transform: rotate(360deg); } }'}</style>
      {showSplash ? (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 9999,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: '#020304',
          }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
            <div
              style={{
                width: 46,
                height: 46,
                borderRadius: '50%',
                border: '3px solid rgba(106, 226, 118, 0.2)',
                borderTopColor: '#6ae276',
                animation: 'cmFirstLoadSpin 1s linear infinite',
              }}
            />
            <div
              style={{
                color: '#6ae276',
                fontSize: 12,
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif',
              }}
            >
              Loading Core Memory
            </div>
          </div>
        </div>
      ) : null}
      <iframe
        title="Core Memory Demo"
        src={src}
        style={{
          border: 0,
          width: '100%',
          height: '100%',
          opacity: showSplash ? 0 : 1,
          transition: 'opacity 140ms ease',
        }}
        referrerPolicy="no-referrer"
      />
    </main>
  )
}
