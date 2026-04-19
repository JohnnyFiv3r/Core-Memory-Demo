function graphTypeColor(type) {
  const t = String(type || '').toLowerCase()
  if (t === 'decision') return '#6ae276'
  if (t === 'evidence') return '#22d3ee'
  if (t === 'lesson') return '#4ade80'
  if (t === 'goal') return '#fbbf24'
  if (t === 'outcome') return '#f87171'
  if (t === 'context') return '#8b8fa3'
  return '#7ca0ab'
}

export function buildReagraphData(edges, beadMap) {
  const safeEdges = Array.isArray(edges) ? edges : []
  const safeMap = beadMap || {}

  const nodeMap = {}
  const degree = {}

  safeEdges.forEach((e) => {
    const s = String((e && e.source) || '')
    const t = String((e && e.target) || '')
    if (!s || !t) return

    degree[s] = Number(degree[s] || 0) + 1
    degree[t] = Number(degree[t] || 0) + 1

    if (!nodeMap[s]) {
      const b = safeMap[s] || {}
      nodeMap[s] = { id: s, title: String(b.title || s), type: String(b.type || 'context') }
    }
    if (!nodeMap[t]) {
      const b = safeMap[t] || {}
      nodeMap[t] = { id: t, title: String(b.title || t), type: String(b.type || 'context') }
    }
  })

  const nodes = Object.values(nodeMap).map((n) => {
    const d = Number(degree[n.id] || 1)
    return {
      id: n.id,
      label: String(n.title || n.id || 'node'),
      size: Math.max(3, Math.min(14, 4 + (d * 1.1))),
      fill: graphTypeColor(n.type),
      data: {
        id: n.id,
        title: n.title,
        type: n.type,
        degree: d,
      },
    }
  })

  const links = safeEdges
    .map((e) => ({
      id: String((e && e.id) || ''),
      source: String((e && e.source) || ''),
      target: String((e && e.target) || ''),
      label: String((e && e.relationship) || 'associated_with'),
      size: 0.5 + (Math.max(0, Math.min(1, Number(((e && e.confidence) ?? 0)))) * 2.2),
      data: {
        relationship: String((e && e.relationship) || 'associated_with'),
        confidence: Number(((e && e.confidence) ?? 0)),
        reason_text: String((e && e.reason_text) || ''),
      },
    }))
    .filter((l) => l.source && l.target)

  return { nodes, edges: links }
}
