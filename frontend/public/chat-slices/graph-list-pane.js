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

function GraphListPane(props) {
  const edges = Array.isArray(props.edges) ? props.edges : []
  const beadMap = props.beadMap || {}
  const graphNodeTitle = typeof props.graphNodeTitle === 'function'
    ? props.graphNodeTitle
    : (_map, id) => String(id || 'n/a')

  return React.createElement(
    React.Fragment,
    null,
    ...edges.slice(0, 140).map((a, idx) => {
      const src = String((a && a.source) || '')
      const dst = String((a && a.target) || '')
      const srcTitle = graphNodeTitle(beadMap, src)
      const dstTitle = graphNodeTitle(beadMap, dst)
      const rel = String((a && a.relationship) || 'associated_with')
      const conf = (a && a.confidence) === null ? 'n/a' : Number((a && a.confidence) || 0).toFixed(2)

      return React.createElement(
        'div',
        { className: 'bench-bucket', key: String((a && a.id) || idx) },
        React.createElement('div', null, React.createElement('strong', null, rel)),
        React.createElement('div', { style: { marginTop: '2px', color: 'var(--text-dim)' } }, 'source: ' + srcTitle),
        React.createElement('div', { style: { marginTop: '2px', color: 'var(--text-dim)' } }, 'target: ' + dstTitle),
        React.createElement('div', { style: { marginTop: '2px', color: 'var(--text-dim)' } }, 'confidence: ' + conf),
        React.createElement(
          'div',
          { style: { marginTop: '6px', display: 'flex', gap: '6px', flexWrap: 'wrap' } },
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
    })
  )
}

export function renderGraphListPane(container, props) {
  if (!container) return
  const root = getRoot(container)
  root.render(React.createElement(GraphListPane, props || {}))
}
