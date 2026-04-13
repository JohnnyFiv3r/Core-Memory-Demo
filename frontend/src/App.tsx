import { useEffect, useMemo, useState } from 'react'
import { api, getApiBase } from './api'

type Tab = 'Chat' | 'Memory' | 'Graph' | 'Claims' | 'Entities' | 'Runtime' | 'Benchmark'
const TABS: Tab[] = ['Chat', 'Memory', 'Graph', 'Claims', 'Entities', 'Runtime', 'Benchmark']

export function App() {
  const [tab, setTab] = useState<Tab>('Chat')
  const [state, setState] = useState<any>(null)
  const [runtime, setRuntime] = useState<any>(null)
  const [benchmark, setBenchmark] = useState<any>(null)
  const [err, setErr] = useState('')
  const [chatIn, setChatIn] = useState('')
  const [chatLog, setChatLog] = useState<Array<{ role: string; text: string }>>([])

  async function refresh() {
    try {
      const [s, r, b] = await Promise.all([api.inspectState(), api.runtime(), api.benchmarkLast()])
      setState(s)
      setRuntime(r)
      setBenchmark(b)
      setErr('')
    } catch (e: any) {
      setErr(String(e?.message || e))
    }
  }

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 4000)
    return () => clearInterval(t)
  }, [])

  const mem = state?.memory || {}
  const claims = state?.claims || {}
  const entities = state?.entities || {}

  const stats = useMemo(() => {
    return {
      beads: Number((state?.stats || {}).total_beads || (mem.beads || []).length || 0),
      assoc: Number((state?.stats || {}).total_associations || (mem.associations || []).length || 0),
      claims: Number((state?.stats || {}).claim_slot_count || (claims.slots || []).length || 0),
      entities: Number((state?.stats || {}).entity_count || (entities.rows || []).length || 0),
      rolling: Number((state?.stats || {}).rolling_window_size || (mem.rolling_window || []).length || 0),
    }
  }, [state])

  async function sendChat() {
    const msg = chatIn.trim()
    if (!msg) return
    setChatLog((x) => [...x, { role: 'user', text: msg }])
    setChatIn('')
    try {
      const out = await api.chat(msg)
      setChatLog((x) => [...x, { role: 'assistant', text: String(out?.assistant || '') }])
      await refresh()
    } catch (e: any) {
      setChatLog((x) => [...x, { role: 'system', text: `chat failed: ${String(e?.message || e)}` }])
    }
  }

  async function seed() {
    try {
      const out = await api.seed()
      setChatLog((x) => [...x, { role: 'system', text: `seeded: ${out?.seeded || 0}` }])
      await refresh()
    } catch (e: any) {
      setErr(String(e?.message || e))
    }
  }

  async function flush() {
    try {
      const out = await api.flush()
      setChatLog((x) => [...x, { role: 'system', text: `flushed ${out?.flushed_session} -> ${out?.new_session}` }])
      await refresh()
    } catch (e: any) {
      setErr(String(e?.message || e))
    }
  }

  async function runBenchmark() {
    try {
      await api.benchmarkRun({ subset: 'local', semantic_mode: 'degraded_allowed', root_mode: 'snapshot', limit: 3 })
      await refresh()
    } catch (e: any) {
      setErr(String(e?.message || e))
    }
  }

  return (
    <main style={{ fontFamily: 'Inter, system-ui, sans-serif', padding: 16, maxWidth: 1180, margin: '0 auto' }}>
      <h1 style={{ marginBottom: 8 }}>Core Memory Demo</h1>
      <p style={{ color: '#555', marginTop: 0 }}>
        API base: <code>{getApiBase()}</code>
      </p>

      <section style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              border: '1px solid #ddd',
              borderRadius: 999,
              padding: '5px 12px',
              fontSize: 12,
              background: t === tab ? '#111' : '#fff',
              color: t === tab ? '#fff' : '#111',
              cursor: 'pointer',
            }}
          >
            {t}
          </button>
        ))}
      </section>

      <section style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        <span>Beads: <b>{stats.beads}</b></span>
        <span>Assoc: <b>{stats.assoc}</b></span>
        <span>Claims: <b>{stats.claims}</b></span>
        <span>Entities: <b>{stats.entities}</b></span>
        <span>Rolling: <b>{stats.rolling}</b></span>
      </section>

      <section style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <button onClick={seed}>Seed</button>
        <button onClick={flush}>Flush</button>
        <button onClick={runBenchmark}>Run Benchmark</button>
        <button onClick={refresh}>Refresh</button>
      </section>

      {err ? <pre style={{ color: 'crimson' }}>{err}</pre> : null}

      {tab === 'Chat' ? (
        <section style={{ border: '1px solid #eee', borderRadius: 10, padding: 12 }}>
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              style={{ flex: 1 }}
              placeholder="Ask anything..."
              value={chatIn}
              onChange={(e) => setChatIn(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') sendChat()
              }}
            />
            <button onClick={sendChat}>Send</button>
          </div>
          <div style={{ marginTop: 10, display: 'grid', gap: 6 }}>
            {chatLog.map((row, i) => (
              <div key={i} style={{ border: '1px solid #eee', borderRadius: 8, padding: 8 }}>
                <b>{row.role}</b>
                <div>{row.text}</div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {tab === 'Memory' ? <Json title="Memory" data={mem} /> : null}
      {tab === 'Graph' ? <Json title="Graph (associations)" data={mem.associations || []} /> : null}
      {tab === 'Claims' ? <Json title="Claims" data={claims} /> : null}
      {tab === 'Entities' ? <Json title="Entities" data={entities} /> : null}
      {tab === 'Runtime' ? <Json title="Runtime" data={runtime} /> : null}
      {tab === 'Benchmark' ? <Json title="Benchmark" data={benchmark} /> : null}
    </main>
  )
}

function Json({ title, data }: { title: string; data: any }) {
  return (
    <section style={{ border: '1px solid #eee', borderRadius: 10, padding: 12 }}>
      <h3 style={{ marginTop: 0 }}>{title}</h3>
      <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{JSON.stringify(data, null, 2)}</pre>
    </section>
  )
}
