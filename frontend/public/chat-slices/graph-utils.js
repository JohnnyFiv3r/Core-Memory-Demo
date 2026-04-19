export function graphNumConfidence(v) {
  const n = Number(v)
  return Number.isFinite(n) ? Math.max(0, Math.min(1, n)) : null
}

export function graphNodeTitle(beadMap, id) {
  const bead = (beadMap || {})[String(id || '')] || {}
  return String(bead.title || id || 'n/a')
}

export function graphEntityId(v) {
  if (v && typeof v === 'object') return String(v.id || v.name || '')
  return String(v || '')
}

export function normalizeGraphEdges(assocs) {
  const out = []
  ;(assocs || []).forEach((a, idx) => {
    const src = String((a || {}).source_bead || (a || {}).source_bead_id || '').trim()
    const dst = String((a || {}).target_bead || (a || {}).target_bead_id || '').trim()
    if (!src || !dst) return
    out.push({
      id: String((a || {}).id || ('edge-' + idx + '-' + src.slice(0, 6) + '-' + dst.slice(0, 6))),
      source: src,
      target: dst,
      relationship: String((a || {}).relationship || 'associated_with'),
      confidence: graphNumConfidence((a || {}).confidence),
      reason_text: String((a || {}).reason_text || (a || {}).explanation || ''),
    })
  })
  return out
}

export function applyGraphFilters(edges, beadMap, filters) {
  const rel = String((filters || {}).relation || 'all')
  const minConfidence = Number((filters || {}).minConfidence || 0)
  const search = String((filters || {}).search || '').trim().toLowerCase()

  return (edges || []).filter((e) => {
    if (rel !== 'all' && String((e || {}).relationship || '') !== rel) return false
    if ((e || {}).confidence !== null && Number.isFinite(minConfidence) && Number(e.confidence) < minConfidence) return false
    if (!search) return true

    const srcTitle = graphNodeTitle(beadMap, (e || {}).source).toLowerCase()
    const dstTitle = graphNodeTitle(beadMap, (e || {}).target).toLowerCase()
    const hay = [
      srcTitle,
      dstTitle,
      String((e || {}).relationship || '').toLowerCase(),
      String((e || {}).reason_text || '').toLowerCase(),
      String((e || {}).source || '').toLowerCase(),
      String((e || {}).target || '').toLowerCase(),
    ].join(' ')

    return hay.includes(search)
  })
}
