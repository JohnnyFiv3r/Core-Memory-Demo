export function renderGraphSvgCanvasPane(el, opts) {
  if (!el) return

  const edges = Array.isArray((opts || {}).edges) ? opts.edges : []
  const beadMap = (opts || {}).beadMap || {}
  const graphNodeTitle = typeof (opts || {}).graphNodeTitle === 'function'
    ? opts.graphNodeTitle
    : (_map, id) => String(id || 'n/a')
  const onOpenBead = typeof (opts || {}).onOpenBead === 'function' ? opts.onOpenBead : null
  const onEdgeClick = typeof (opts || {}).onEdgeClick === 'function' ? opts.onEdgeClick : null

  const svgNs = 'http://www.w3.org/2000/svg'
  const wrap = document.createElement('div')
  wrap.className = 'graph-canvas-wrap'

  const nodesSet = new Set()
  edges.forEach((e) => {
    nodesSet.add(String((e && e.source) || ''))
    nodesSet.add(String((e && e.target) || ''))
  })
  let nodeIds = Array.from(nodesSet).filter(Boolean)

  const degree = {}
  edges.forEach((e) => {
    degree[String((e && e.source) || '')] = Number(degree[String((e && e.source) || '')] || 0) + 1
    degree[String((e && e.target) || '')] = Number(degree[String((e && e.target) || '')] || 0) + 1
  })

  const maxNodes = 64
  if (nodeIds.length > maxNodes) {
    nodeIds.sort((a, b) => Number(degree[b] || 0) - Number(degree[a] || 0))
    nodeIds = nodeIds.slice(0, maxNodes)
  }

  const keep = new Set(nodeIds)
  const limitedEdges = edges
    .filter((e) => keep.has(String((e && e.source) || '')) && keep.has(String((e && e.target) || '')))
    .slice(0, 220)

  const width = Math.max(300, Number((el && el.clientWidth) || 0) - 20)
  const height = Math.max(380, Math.min(860, 220 + (nodeIds.length * 8)))
  const cx = width / 2
  const cy = height / 2
  const radius = Math.max(90, Math.min(width, height) / 2 - 52)

  const svg = document.createElementNS(svgNs, 'svg')
  svg.setAttribute('class', 'graph-canvas')

  const baseView = { x: 0, y: 0, w: width, h: height }
  const view = { x: baseView.x, y: baseView.y, w: baseView.w, h: baseView.h }

  function applyView() {
    svg.setAttribute(
      'viewBox',
      String(view.x.toFixed(2)) + ' ' + String(view.y.toFixed(2)) + ' ' + String(view.w.toFixed(2)) + ' ' + String(view.h.toFixed(2))
    )
  }
  applyView()

  let panState = null
  let dragged = false
  let suppressClickUntil = 0
  svg.style.cursor = 'grab'

  svg.addEventListener('pointerdown', (ev) => {
    if (ev.button !== 0) return
    panState = {
      pointerId: ev.pointerId,
      sx: ev.clientX,
      sy: ev.clientY,
      ox: view.x,
      oy: view.y,
    }
    dragged = false
    try { svg.setPointerCapture(ev.pointerId) } catch (_) {}
    svg.style.cursor = 'grabbing'
  })

  svg.addEventListener('pointermove', (ev) => {
    if (!panState || ev.pointerId !== panState.pointerId) return
    const rect = svg.getBoundingClientRect()
    if (!rect.width || !rect.height) return
    const px = ev.clientX - panState.sx
    const py = ev.clientY - panState.sy
    if (Math.abs(px) > 2 || Math.abs(py) > 2) dragged = true
    const dx = px * (view.w / rect.width)
    const dy = py * (view.h / rect.height)
    view.x = panState.ox - dx
    view.y = panState.oy - dy
    applyView()
  })

  function endPan(ev) {
    if (!panState || !ev || ev.pointerId !== panState.pointerId) return
    if (dragged) suppressClickUntil = Date.now() + 180
    try { svg.releasePointerCapture(ev.pointerId) } catch (_) {}
    panState = null
    svg.style.cursor = 'grab'
  }
  svg.addEventListener('pointerup', endPan)
  svg.addEventListener('pointercancel', endPan)

  svg.addEventListener('wheel', (ev) => {
    ev.preventDefault()
    const rect = svg.getBoundingClientRect()
    if (!rect.width || !rect.height) return
    const mx = (ev.clientX - rect.left) / rect.width
    const my = (ev.clientY - rect.top) / rect.height
    const zoom = ev.deltaY < 0 ? 0.92 : 1.08
    const worldX = view.x + (mx * view.w)
    const worldY = view.y + (my * view.h)
    view.w = Math.max(140, Math.min(6000, view.w * zoom))
    view.h = Math.max(140, Math.min(6000, view.h * zoom))
    view.x = worldX - (mx * view.w)
    view.y = worldY - (my * view.h)
    applyView()
  }, { passive: false })

  svg.addEventListener('dblclick', (ev) => {
    ev.preventDefault()
    view.x = baseView.x
    view.y = baseView.y
    view.w = baseView.w
    view.h = baseView.h
    applyView()
  })

  svg.addEventListener('click', (ev) => {
    if (Date.now() < suppressClickUntil) {
      ev.preventDefault()
      ev.stopPropagation()
    }
  }, true)

  const pos = {}
  nodeIds.forEach((id, idx) => {
    if (nodeIds.length === 1) {
      pos[id] = { x: cx, y: cy }
      return
    }
    const angle = ((2 * Math.PI * idx) / nodeIds.length) - (Math.PI / 2)
    pos[id] = {
      x: cx + (radius * Math.cos(angle)),
      y: cy + (radius * Math.sin(angle)),
    }
  })

  limitedEdges.forEach((edge) => {
    const s = pos[String((edge && edge.source) || '')]
    const t = pos[String((edge && edge.target) || '')]
    if (!s || !t) return

    const line = document.createElementNS(svgNs, 'line')
    line.setAttribute('class', 'graph-edge')
    line.setAttribute('x1', String(s.x))
    line.setAttribute('y1', String(s.y))
    line.setAttribute('x2', String(t.x))
    line.setAttribute('y2', String(t.y))

    const sw = 0.9 + ((((edge && edge.confidence) === null ? 0.2 : Number((edge && edge.confidence) || 0))) * 2.1)
    line.setAttribute('stroke-width', String(sw.toFixed(2)))

    line.addEventListener('click', (ev) => {
      ev.stopPropagation()
      if (onEdgeClick) onEdgeClick(edge)
    })

    const tt = document.createElementNS(svgNs, 'title')
    tt.textContent =
      String((edge && edge.relationship) || 'associated_with') +
      ' · conf=' + String((edge && edge.confidence) === null ? 'n/a' : Number((edge && edge.confidence) || 0).toFixed(2)) +
      (((edge && edge.reason_text) ? ('\n' + String(edge.reason_text)) : ''))
    line.appendChild(tt)
    svg.appendChild(line)
  })

  nodeIds.forEach((id) => {
    const p = pos[id]
    if (!p) return

    const g = document.createElementNS(svgNs, 'g')
    g.setAttribute('class', 'graph-node')
    g.setAttribute('transform', 'translate(' + String(p.x.toFixed(2)) + ' ' + String(p.y.toFixed(2)) + ')')

    const circle = document.createElementNS(svgNs, 'circle')
    const r = 6 + Math.min(6, Number(degree[id] || 0) * 0.5)
    circle.setAttribute('r', String(r.toFixed(1)))
    g.appendChild(circle)

    const label = document.createElementNS(svgNs, 'text')
    label.setAttribute('x', '0')
    label.setAttribute('y', String(-r - 5))
    label.setAttribute('text-anchor', 'middle')
    const raw = graphNodeTitle(beadMap, id)
    label.textContent = raw.length > 20 ? (raw.slice(0, 19) + '…') : raw
    g.appendChild(label)

    const tt = document.createElementNS(svgNs, 'title')
    tt.textContent = raw + '\n' + id
    g.appendChild(tt)

    g.addEventListener('click', (ev) => {
      ev.stopPropagation()
      if (onOpenBead) onOpenBead(id)
    })

    svg.appendChild(g)
  })

  wrap.appendChild(svg)
  el.appendChild(wrap)

  const note = document.createElement('div')
  note.className = 'runtime-card'
  note.innerHTML =
    '<div><strong>Graph view</strong></div>' +
    '<div style="margin-top:2px;color:var(--text-dim)">nodes=' + String(nodeIds.length) +
    ' · edges=' + String(limitedEdges.length) +
    ' · drag to pan · wheel to zoom · double-click to reset.</div>'
  el.appendChild(note)
}
