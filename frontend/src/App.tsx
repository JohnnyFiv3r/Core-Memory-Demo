import { useMemo } from 'react'
import { getApiBase } from './api'
import { ReactParityApp } from './ReactParityApp'

export function App() {
  const reactMode = typeof window !== 'undefined' && window.location.hash === '#react'
  const uiRev = '20260415-session-popover-4'

  if (reactMode) {
    return <ReactParityApp />
  }

  const apiBase = getApiBase()
  const src = useMemo(() => {
    if (!apiBase) return `/chris-demo.html?ui_rev=${encodeURIComponent(uiRev)}`
    return `/chris-demo.html?api_base=${encodeURIComponent(apiBase)}&ui_rev=${encodeURIComponent(uiRev)}`
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
