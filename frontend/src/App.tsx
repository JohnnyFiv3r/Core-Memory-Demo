import { useMemo } from 'react'
import { getApiBase } from './api'

export function App() {
  const apiBase = getApiBase()
  const src = useMemo(() => {
    if (!apiBase) return '/chris-demo.html'
    return `/chris-demo.html?api_base=${encodeURIComponent(apiBase)}`
  }, [apiBase])

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
