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

function GraphSummaryPane(props) {
  const filteredEdges = Array.isArray(props.filteredEdges) ? props.filteredEdges : []
  const totalEdges = Number(props.totalEdges || 0)

  const counts = {}
  filteredEdges.forEach((e) => {
    const rel = String((e && e.relationship) || 'associated_with')
    counts[rel] = Number(counts[rel] || 0) + 1
  })
  const rows = Object.entries(counts).sort((a, b) => Number(b[1]) - Number(a[1]))

  return React.createElement(
    React.Fragment,
    null,
    React.createElement(
      'div',
      { className: 'runtime-card' },
      React.createElement('div', null, React.createElement('strong', null, 'Filtered graph')),
      React.createElement(
        'div',
        { style: { marginTop: '2px', color: 'var(--text-dim)' } },
        'showing ' + String(filteredEdges.length) + ' / ' + String(totalEdges) + ' edges'
      )
    ),
    filteredEdges.length
      ? React.createElement(
          'div',
          { className: 'graph-legend' },
          ...rows.slice(0, 14).map(([rel, n]) =>
            React.createElement(
              'span',
              { className: 'graph-chip', key: rel },
              rel,
              ' ',
              React.createElement('span', { className: 'graph-chip-count' }, String(n))
            )
          ),
          rows.length > 14
            ? React.createElement('span', { className: 'graph-chip', key: '__more' }, '+' + String(rows.length - 14) + ' more')
            : null
        )
      : null
  )
}

export function renderGraphSummaryPane(container, props) {
  if (!container) return
  const root = getRoot(container)
  root.render(React.createElement(GraphSummaryPane, props || {}))
}
