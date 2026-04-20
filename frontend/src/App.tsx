import { useEffect, useMemo } from 'react'
import { getApiBase } from './api'

export function App() {
  const uiRev = '20260420-auth-session-06'
  const apiBase = getApiBase()

  const targetUrl = useMemo(() => {
    if (typeof window === 'undefined') return `/chat.html?ui_rev=${encodeURIComponent(uiRev)}`

    const params = new URLSearchParams(window.location.search)
    const requestedView = String(params.get('view') || 'chat').trim().toLowerCase()
    const targetPath = requestedView === 'graph' ? '/graph.html' : '/chat.html'

    params.delete('view')
    if (apiBase) params.set('api_base', apiBase)
    params.set('ui_rev', uiRev)

    const q = params.toString()
    return `${targetPath}${q ? `?${q}` : ''}`
  }, [apiBase, uiRev])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const current = `${window.location.pathname}${window.location.search}`
    if (current === targetUrl) return
    window.location.replace(targetUrl)
  }, [targetUrl])

  return (
    <main
      style={{
        margin: 0,
        padding: 0,
        height: '100vh',
        width: '100vw',
        overflow: 'hidden',
        background: '#020304',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, color: '#6ae276' }}>
        <div
          style={{
            width: 42,
            height: 42,
            borderRadius: '50%',
            border: '3px solid rgba(106, 226, 118, 0.2)',
            borderTopColor: '#6ae276',
            animation: 'cmSpin 1s linear infinite',
          }}
        />
      </div>
      <style>{'@keyframes cmSpin { to { transform: rotate(360deg); } }'}</style>
    </main>
  )
}
