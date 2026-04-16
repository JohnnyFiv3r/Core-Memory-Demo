import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { GraphCanvas } from 'reagraph'
import './graph.css'

type BeadRow = {
  id?: string
  title?: string
  type?: string
  status?: string
  source_turn_ids?: string[]
}

type AssocRow = {
  id?: string
  source_bead?: string
  target_bead?: string
  relationship?: string
  confidence?: number
  explanation?: string
}

type InspectStateResponse = {
  ok?: boolean
  memory?: {
    beads?: BeadRow[]
    associations?: AssocRow[]
  }
}

const params = new URLSearchParams(window.location.search)
const queryBase = (params.get('api_base') || '').trim()
let localBase = ''
try {
  localBase = (localStorage.getItem('CORE_MEMORY_API_BASE') || '').trim()
} catch {
  localBase = ''
}
const defaultBase = window.location.hostname === 'demo.usecorememory.com' ? 'https://core-memory-demo.onrender.com' : ''
const apiBase = (queryBase || localBase || defaultBase || '').replace(/\/+$/, '')
if (apiBase) {
  try {
    localStorage.setItem('CORE_MEMORY_API_BASE', apiBase)
  } catch {
    // best effort only
  }
}

async function apiFetchJson<T>(path: string): Promise<T> {
  const url = apiBase && path.startsWith('/') ? `${apiBase}${path}` : path
  const res = await fetch(url)
  const body = await res.json()
  if (!res.ok) {
    const msg = (body && (body.error || body.message)) || `HTTP ${res.status}`
    throw new Error(String(msg))
  }
  return body as T
}

function typeColor(type: string | undefined): string {
  const t = String(type || '').toLowerCase()
  if (t === 'decision') return '#6ae276'
  if (t === 'evidence') return '#6ecfe0'
  if (t === 'lesson') return '#8bc894'
  if (t === 'goal') return '#f2d56b'
  if (t === 'outcome') return '#f08a7a'
  if (t === 'context') return '#8d96a9'
  return '#7ca0ab'
}

function App(): React.JSX.Element {
  const graphRef = useRef<any>(null)
  const [beads, setBeads] = useState<BeadRow[]>([])
  const [associations, setAssociations] = useState<AssocRow[]>([])
  const [relation, setRelation] = useState<string>('all')
  const [minConf, setMinConf] = useState<number>(0)
  const [search, setSearch] = useState<string>('')
  const [auto, setAuto] = useState<boolean>(true)
  const [detail, setDetail] = useState<string>('')
  const [meta, setMeta] = useState<string>('')

  const closeGraphView = useCallback(() => {
    try {
      window.close()
    } catch {
      // ignore
    }
    if (window.history.length > 1) {
      window.history.back()
      return
    }
    window.location.assign('./')
  }, [])

  const refresh = useCallback(async () => {
    setMeta('')
    let data: InspectStateResponse | null = null
    let lastErr: unknown = null

    for (const stateUrl of ['/v1/memory/inspect/state', '/api/demo/state']) {
      try {
        data = await apiFetchJson<InspectStateResponse>(stateUrl)
        break
      } catch (err) {
        lastErr = err
      }
    }

    if (!data) throw lastErr instanceof Error ? lastErr : new Error('state_fetch_failed')

    const nextBeads = Array.isArray(data.memory?.beads) ? data.memory?.beads || [] : []
    const nextAssoc = Array.isArray(data.memory?.associations) ? data.memory?.associations || [] : []
    setBeads(nextBeads)
    setAssociations(nextAssoc)
  }, [])

  useEffect(() => {
    refresh().catch((err: unknown) => {
      const msg = err instanceof Error ? err.stack || err.message : String(err)
      setMeta(`load error: ${msg}`)
      setDetail(`Failed to load graph data.\n\n${msg}`)
    })
  }, [refresh])

  useEffect(() => {
    if (!auto) return
    const id = window.setInterval(() => {
      refresh().catch((err: unknown) => {
        const msg = err instanceof Error ? err.stack || err.message : String(err)
        setMeta(`refresh error: ${msg}`)
        setDetail(`Runtime error while refreshing graph.\n\n${msg}`)
      })
    }, 4000)
    return () => window.clearInterval(id)
  }, [auto, refresh])

  const edgesRaw = useMemo(() => {
    return associations
      .map((r, idx) => {
        const src = String(r.source_bead || '').trim()
        const dst = String(r.target_bead || '').trim()
        if (!src || !dst) return null
        return {
          id: String(r.id || `edge-${idx}-${src.slice(0, 6)}-${dst.slice(0, 6)}`),
          source: src,
          target: dst,
          relationship: String(r.relationship || 'associated_with'),
          confidence: Number(r.confidence || 0),
          reason_text: String(r.explanation || ''),
        }
      })
      .filter((x): x is NonNullable<typeof x> => Boolean(x))
  }, [associations])

  const relationOptions = useMemo(() => {
    return Array.from(new Set(edgesRaw.map((e) => e.relationship))).sort()
  }, [edgesRaw])

  const graphData = useMemo(() => {
    const beadMap = new Map<string, BeadRow>()
    beads.forEach((b) => {
      const id = String(b.id || '').trim()
      if (id) beadMap.set(id, b)
    })

    const q = search.trim().toLowerCase()
    const filteredEdges = edgesRaw.filter((e) => {
      if (relation !== 'all' && e.relationship !== relation) return false
      if (Number.isFinite(minConf) && e.confidence < minConf) return false
      if (!q) return true
      const srcTitle = String((beadMap.get(e.source)?.title || e.source) || '').toLowerCase()
      const dstTitle = String((beadMap.get(e.target)?.title || e.target) || '').toLowerCase()
      const hay = [srcTitle, dstTitle, e.relationship.toLowerCase(), e.reason_text.toLowerCase()].join(' ')
      return hay.includes(q)
    })

    const ids = new Set<string>()
    const degree = new Map<string, number>()

    filteredEdges.forEach((e) => {
      ids.add(e.source)
      ids.add(e.target)
      degree.set(e.source, (degree.get(e.source) || 0) + 1)
      degree.set(e.target, (degree.get(e.target) || 0) + 1)
    })

    if (!ids.size) {
      const candidates = beads.filter((b) => {
        const id = String(b.id || '').trim()
        if (!id) return false
        if (!q) return true
        const hay = [String(b.title || ''), String(b.type || ''), String(b.status || '')].join(' ').toLowerCase()
        return hay.includes(q)
      })
      candidates.slice(0, 180).forEach((b) => {
        const id = String(b.id || '').trim()
        if (!id) return
        ids.add(id)
        degree.set(id, degree.get(id) || 0)
      })
    }

    const nodes = Array.from(ids).map((id) => {
      const bead = beadMap.get(id) || {}
      const d = Number(degree.get(id) || 1)
      return {
        id,
        label: String(bead.title || id),
        size: Math.max(3, Math.min(14, 4 + d * 1.1)),
        fill: typeColor(bead.type),
        data: {
          bead_id: id,
          title: bead.title,
          type: bead.type,
          status: bead.status,
          source_turn_ids: bead.source_turn_ids || [],
        },
      }
    })

    const edges = filteredEdges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      label: e.relationship,
      size: 0.5 + Math.max(0, Math.min(1, Number(e.confidence || 0))) * 2.2,
      data: {
        relationship: e.relationship,
        confidence: e.confidence,
        reason_text: e.reason_text,
      },
    }))

    return { nodes, edges }
  }, [beads, edgesRaw, minConf, relation, search])

  const onNodeClick = useCallback(async (node: { id?: string; data?: { bead_id?: string } }) => {
    const id = String(node?.id || node?.data?.bead_id || '').trim()
    if (!id) return
    try {
      const row = await apiFetchJson<unknown>(`/v1/memory/inspect/beads/${encodeURIComponent(id)}`)
      setDetail(JSON.stringify(row, null, 2))
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setDetail(JSON.stringify({ error: msg, bead_id: id }, null, 2))
    }
  }, [])

  const onEdgeClick = useCallback((edge: { source?: string; target?: string; label?: string; data?: { confidence?: number; reason_text?: string; relationship?: string } }) => {
    setDetail(
      JSON.stringify(
        {
          source: edge?.source,
          target: edge?.target,
          relationship: edge?.label || edge?.data?.relationship,
          confidence: edge?.data?.confidence,
          reason_text: edge?.data?.reason_text,
        },
        null,
        2,
      ),
    )
  }, [])

  return (
    <div className="graph-page">
      <header className="graph-header">
        <div className="graph-title">
          <img className="graph-brand" src="/core-memory-banner.svg" alt="Core Memory" />
          <span className="graph-subtitle">Causal Graph</span>
        </div>
        <div className="graph-controls">
          <label>relation</label>
          <select value={relation} onChange={(e) => setRelation(e.target.value)}>
            <option value="all">all</option>
            {relationOptions.map((r) => (
              <option value={r} key={r}>
                {r}
              </option>
            ))}
          </select>
          <label>min conf</label>
          <input
            value={minConf}
            onChange={(e) => setMinConf(Number(e.target.value || 0))}
            type="number"
            min={0}
            max={1}
            step={0.05}
            style={{ width: 78 }}
          />
          <label>search</label>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            type="text"
            placeholder="node/edge"
            style={{ width: 140 }}
          />
          <label>
            <input checked={auto} onChange={(e) => setAuto(e.target.checked)} type="checkbox" /> auto
          </label>
          <button
            type="button"
            onClick={() => {
              refresh().catch((err: unknown) => {
                const msg = err instanceof Error ? err.message : String(err)
                setMeta(`refresh error: ${msg}`)
              })
            }}
          >
            Refresh
          </button>
          <button
            type="button"
            onClick={() => {
              try {
                if (graphRef.current && typeof graphRef.current.fitNodesInView === 'function') graphRef.current.fitNodesInView()
              } catch {
                // noop
              }
            }}
          >
            Fit
          </button>
          <button type="button" onClick={closeGraphView}>
            Close Graph
          </button>
        </div>
      </header>

      <div className="graph-layout">
        <div className="graph-panel">
          <div className="graph-host">
            <GraphCanvas
              ref={(r: unknown) => {
                graphRef.current = r
              }}
              nodes={graphData.nodes}
              edges={graphData.edges}
              layoutType="forceDirected3d"
              cameraMode="rotate"
              draggable
              animated={false}
              labelType="all"
              edgeLabelPosition="inline"
              theme={{
                canvas: { background: '#05070c' },
                arrow: { fill: '#5b6a8a', activeFill: '#6ae276' },
                node: {
                  fill: '#7ca0ab',
                  activeFill: '#6ae276',
                  opacity: 0.95,
                  selectedOpacity: 1,
                  inactiveOpacity: 0.2,
                  label: { color: '#e1e4ed', stroke: '#05070c', activeColor: '#ffffff' },
                  subLabel: { color: '#8b8fa3', stroke: 'transparent', activeColor: '#e1e4ed' },
                },
                edge: {
                  fill: '#5b6a8a',
                  activeFill: '#6ae276',
                  opacity: 0.7,
                  selectedOpacity: 1,
                  inactiveOpacity: 0.2,
                  label: { color: '#b8c0d8', stroke: '#05070c', activeColor: '#ffffff' },
                },
                lasso: { border: '1px solid #6ae276', background: 'rgba(106,226,118,0.18)' },
                ring: { fill: '#1f2838', activeFill: '#6ae276' },
              }}
              onNodeClick={onNodeClick}
              onEdgeClick={onEdgeClick}
            />
          </div>
        </div>

        <div className="graph-panel graph-side">
          {meta ? <div className="graph-meta">{meta}</div> : null}
          {detail ? (
            <pre className="graph-detail">{detail}</pre>
          ) : (
            <div className="graph-empty-state">
              <div className="graph-empty-state-icon">◌</div>
              <div>Select a node or edge.</div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

createRoot(document.getElementById('graph-root') as HTMLElement).render(<App />)
