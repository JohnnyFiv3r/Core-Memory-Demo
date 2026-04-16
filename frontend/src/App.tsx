import { useMemo } from 'react'
import { getApiBase } from './api'
import { ReactParityApp } from './ReactParityApp'

export function App() {
  const reactMode = typeof window !== 'undefined' && window.location.hash === '#react'
  const uiRev = '20260415-session-popover-11'

  if (reactMode) {
    return <ReactParityApp />
  }

  const apiBase = getApiBase()
  const src = useMemo(() => {
    if (typeof window === 'undefined') return `/chris-demo.html?ui_rev=${encodeURIComponent(uiRev)}`

    const params = new URLSearchParams(window.location.search)
    if (apiBase) params.set('api_base', apiBase)
    params.set('ui_rev', uiRev)

    const q = params.toString()
    return `/chris-demo.html${q ? `?${q}` : ''}`
  }, [apiBase, uiRev])

  return (
    <main style={{ margin: 0, padding: 0, height: '100vh', width: '100vw', overflow: 'hidden' }}>
      <iframe
        title="Core Memory Demo"
        src={src}
        style={{ border: 0, width: '100%', height: '100%' }}
        referrerPolicy="no-referrer"
      />
    </main>
  )
}
