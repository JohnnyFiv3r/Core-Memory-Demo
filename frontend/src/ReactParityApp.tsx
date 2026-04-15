import { useEffect, useMemo, useState } from 'react'
import { api } from './api'
import './react-parity.css'

type Tab = 'Memory' | 'Graph' | 'Claims' | 'Entities' | 'Runtime' | 'Benchmark'
const TABS: Tab[] = ['Memory', 'Graph', 'Claims', 'Entities', 'Runtime', 'Benchmark']

export function ReactParityApp() {
  const [tab, setTab] = useState<Tab>('Memory')
  const [state, setState] = useState<any>(null)
  const [runtime, setRuntime] = useState<any>(null)
  const [benchmark, setBenchmark] = useState<any>(null)
  const [chatIn, setChatIn] = useState('')
  const [err, setErr] = useState('')
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
  }, [state, mem, claims, entities])

  async function sendChat() {
    const message = chatIn.trim()
    if (!message) return
    setChatLog((rows) => [...rows, { role: 'user', text: message }])
    setChatIn('')
    try {
      const out = await api.chat(message)
      setChatLog((rows) => [...rows, { role: 'assistant', text: String(out?.assistant || '') }])
      await refresh()
    } catch (e: any) {
      setChatLog((rows) => [...rows, { role: 'system', text: `chat failed: ${String(e?.message || e)}` }])
    }
  }

  async function seed() {
    try {
      const out = await api.seed()
      setChatLog((rows) => [...rows, { role: 'system', text: `seeded ${out?.seeded || 0}` }])
      await refresh()
    } catch (e: any) {
      setErr(String(e?.message || e))
    }
  }

  async function flush() {
    try {
      const out = await api.flush()
      setChatLog((rows) => [...rows, { role: 'system', text: `flushed ${out?.flushed_session} → ${out?.new_session}` }])
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

  const tabData =
    tab === 'Memory'
      ? mem
      : tab === 'Graph'
        ? mem.associations || []
        : tab === 'Claims'
          ? claims
          : tab === 'Entities'
            ? entities
            : tab === 'Runtime'
              ? runtime
              : benchmark

  return (
    <div className="parity-root">
      <header className="parity-header">
        <div className="parity-title">Core Memory <span>Live Demo</span> (React port)</div>
        <div className="parity-actions">
          <button className="btn" onClick={seed}>Seed</button>
          <button className="btn" onClick={flush}>Flush</button>
          <button className="btn" onClick={runBenchmark}>Run Benchmark</button>
          <button className="btn btn-accent" onClick={refresh}>Refresh</button>
        </div>
      </header>

      <section className="parity-main">
        <section className="parity-chat">
          <div className="parity-stats">
            <span className="chip">Beads: <b>{stats.beads}</b></span>
            <span className="chip">Assoc: <b>{stats.assoc}</b></span>
            <span className="chip">Claims: <b>{stats.claims}</b></span>
            <span className="chip">Entities: <b>{stats.entities}</b></span>
            <span className="chip">Rolling: <b>{stats.rolling}</b></span>
          </div>

          {err ? <div className="error">{err}</div> : null}

          <div className="parity-messages">
            {chatLog.map((row, i) => (
              <div key={i} className={`msg msg-${row.role}`}>
                {row.text}
              </div>
            ))}
          </div>

          <div className="parity-input">
            <input
              value={chatIn}
              placeholder="Ask anything..."
              onChange={(e) => setChatIn(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') sendChat()
              }}
            />
            <button className="btn btn-accent" onClick={sendChat}>Send</button>
          </div>
        </section>

        <aside className="parity-inspector">
          <div className="parity-tabs">
            {TABS.map((t) => (
              <div key={t} className={`tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
                {t}
              </div>
            ))}
          </div>
          <div className="parity-body">
            {tab === 'Memory' && Array.isArray(mem?.beads) ? (
              <>
                {mem.beads.slice(0, 30).map((b: any) => (
                  <div className="card" key={b.id || Math.random()}>
                    <div className="bead-title">{b.title || '(untitled)'}</div>
                    <div className="bead-meta">{b.type || 'bead'} • {b.id || 'unknown'}</div>
                  </div>
                ))}
                <div className="card"><pre className="json">{JSON.stringify(mem, null, 2)}</pre></div>
              </>
            ) : (
              <div className="card"><pre className="json">{JSON.stringify(tabData, null, 2)}</pre></div>
            )}
          </div>
        </aside>
      </section>
    </div>
  )
}
