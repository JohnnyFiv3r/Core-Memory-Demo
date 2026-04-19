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

function AssociationsPane(props) {
  const assocs = Array.isArray(props.assocs) ? props.assocs : []

  if (!assocs.length) {
    return React.createElement('div', { className: 'empty-state' }, 'No associations yet')
  }

  return React.createElement(
    React.Fragment,
    null,
    ...assocs.map((a, idx) => {
      const source = String((a && a.source_bead) || '')
      const target = String((a && a.target_bead) || '')
      const relationship = String((a && a.relationship) || 'associated_with')
      const explanation = String((a && a.explanation) || '').trim()
      return React.createElement(
        'div',
        { className: 'assoc-card', key: String((a && a.id) || idx) },
        React.createElement('div', { className: 'assoc-rel' }, relationship),
        React.createElement('div', { className: 'assoc-beads' }, source.slice(0, 16) + ' → ' + target.slice(0, 16)),
        explanation ? React.createElement('div', { className: 'assoc-expl' }, explanation) : null
      )
    })
  )
}

export function renderAssociationsPane(container, props) {
  if (!container) return
  const root = getRoot(container)
  root.render(React.createElement(AssociationsPane, props || {}))
}
