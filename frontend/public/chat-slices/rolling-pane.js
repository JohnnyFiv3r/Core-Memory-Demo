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

function defaultBeadTypeClass(type) {
  const known = ['decision', 'lesson', 'goal', 'evidence', 'context', 'outcome', 'checkpoint', 'process_flush', 'session_start', 'session_end']
  return known.includes(type) ? 'bead-type-' + type : 'bead-type-default'
}

function RollingPane({ items, beadTypeClass }) {
  if (!Array.isArray(items) || items.length === 0) {
    return React.createElement('div', { className: 'empty-state' }, 'Rolling window empty')
  }

  const classify = typeof beadTypeClass === 'function' ? beadTypeClass : defaultBeadTypeClass

  return React.createElement(
    React.Fragment,
    null,
    ...items.map((r, idx) =>
      React.createElement(
        'div',
        { className: 'rolling-item', key: String((r || {}).id || (r || {}).bead_id || idx) },
        React.createElement(
          'span',
          { className: 'bead-type ' + classify(String((r || {}).type || '')) },
          String((r || {}).type || 'context')
        ),
        React.createElement('span', null, String((r || {}).title || ''))
      )
    )
  )
}

export function renderRollingPane(container, items, beadTypeClass) {
  if (!container) return
  const root = getRoot(container)
  root.render(React.createElement(RollingPane, { items: Array.isArray(items) ? items : [], beadTypeClass }))
}

