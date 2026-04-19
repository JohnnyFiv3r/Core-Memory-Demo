export function createGraphCanvasHost(container, opts) {
  if (!container) return null

  const wrap = document.createElement('div')
  wrap.className = 'graph-3d-wrap'

  const canvasHost = document.createElement('div')
  canvasHost.className = 'graph-3d-canvas'
  wrap.appendChild(canvasHost)

  const note = document.createElement('div')
  note.className = 'graph-3d-note'
  note.textContent = String((opts || {}).noteText || 'Loading 3D graph...')
  wrap.appendChild(note)

  container.appendChild(wrap)

  return {
    wrap,
    canvasHost,
    setNote: (text) => {
      note.textContent = String(text || '')
    },
    removeNote: () => {
      if (note && note.parentNode) note.remove()
    },
    removeCanvasHost: () => {
      if (canvasHost && canvasHost.parentNode) canvasHost.remove()
    },
  }
}
