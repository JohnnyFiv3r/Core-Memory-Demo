import { useEffect, useState } from 'react'
import { getApiBase, getBackendMeta } from './api'

const TABS = ['Chat', 'Memory', 'Graph', 'Claims', 'Entities', 'Runtime', 'Benchmark']

export function App() {
  const [meta, setMeta] = useState<any>(null)
  const [err, setErr] = useState<string>('')

  useEffect(() => {
    getBackendMeta()
      .then(setMeta)
      .catch((e) => setErr(String(e?.message || e)))
  }, [])

  return (
    <main style={{ fontFamily: 'Inter, system-ui, sans-serif', padding: 16, maxWidth: 1100, margin: '0 auto' }}>
      <h1 style={{ marginBottom: 8 }}>Core Memory Demo</h1>
      <p style={{ color: '#555', marginTop: 0 }}>
        T1 scaffold. API base: <code>{getApiBase()}</code>
      </p>

      <section style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16 }}>
        {TABS.map((tab) => (
          <span key={tab} style={{ border: '1px solid #ddd', borderRadius: 999, padding: '4px 10px', fontSize: 12 }}>
            {tab}
          </span>
        ))}
      </section>

      <section style={{ border: '1px solid #eee', borderRadius: 10, padding: 12 }}>
        <h3 style={{ marginTop: 0 }}>Backend handshake</h3>
        {err ? <pre style={{ color: 'crimson' }}>{err}</pre> : null}
        <pre style={{ margin: 0 }}>{JSON.stringify(meta, null, 2)}</pre>
      </section>
    </main>
  )
}
