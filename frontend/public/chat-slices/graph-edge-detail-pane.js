import React from 'https://esm.sh/react@18.3.1'
import { createRoot } from 'https://esm.sh/react-dom@18.3.1/client'

const ROOTS = new WeakMap()

function getRoot(container) {
  let root = ROOTS.get(container)
  if (!root) {
    root = createRoot(container)
    ROOTS.set(container, root)
  }
  return root
}

function graphEntityId(v) {
  if (v && typeof v === 'object') return String(v.id || v.name || '')
  return String(v || '')
}

function graphNodeTitle(beadMap, id) {
  const bead = (beadMap || {})[String(id || '')] || {}
  return String(bead.title || id || 'n/a')
}

function GraphEdgeDetailPane(props) {
  const edge = props.edge || null
  const beadMap = props.beadMap || {}

  if (!edge) {
    return React.createElement(
      React.Fragment,
      null,
      React.createElement('div', null, React.createElement('strong', null, 'Edge details')),
      React.createElement(
        'div',
        { style: { marginTop: '2px', color: 'var(--text-dim)' } },
        'Click an edge in graph view to inspect and jump to source/target beads.'
      )
    )
  }

  const src = graphEntityId((edge || {}).source)
  const dst = graphEntityId((edge || {}).target)
  const srcTitle = graphNodeTitle(beadMap, src)
  const dstTitle = graphNodeTitle(beadMap, dst)
  const conf = edge && edge.confidence !== null ? Number(edge.confidence).toFixed(2) : 'n/a'
  const reason = String((edge || {}).reason_text || '').trim()

  return React.createElement(
    React.Fragment,
    null,
    React.createElement('div', null, React.createElement('strong', null, String((edge || {}).relationship || 'associated_with'))),
    React.createElement('div', { style: { marginTop: '2px', color: 'var(--text-dim)' } }, 'source: ' + srcTitle),
    React.createElement('div', { style: { marginTop: '2px', color: 'var(--text-dim)' } }, 'target: ' + dstTitle),
    React.createElement('div', { style: { marginTop: '2px', color: 'var(--text-dim)' } }, 'confidence: ' + conf),
    reason ? React.createElement('div', { style: { marginTop: '4px' } }, reason) : null,
    React.createElement(
      'div',
      { style: { marginTop: '8px', display: 'flex', gap: '6px', flexWrap: 'wrap' } },
      src
        ? React.createElement(
            'button',
            {
              className: 'btn',
              onClick: (ev) => {
                ev.stopPropagation()
                if (typeof props.onOpenBead === 'function') props.onOpenBead(src)
              },
            },
            'Open source'
          )
        : null,
      dst
        ? React.createElement(
            'button',
            {
              className: 'btn',
              onClick: (ev) => {
                ev.stopPropagation()
                if (typeof props.onOpenBead === 'function') props.onOpenBead(dst)
              },
            },
            'Open target'
          )
        : null
    )
  )
}

export function renderGraphEdgeDetailPane(container, props) {
  if (!container) return
  const root = getRoot(container)
  root.render(React.createElement(GraphEdgeDetailPane, props || {}))
}
