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

const DEFAULT_BEAD_TYPES = ['decision', 'lesson', 'goal', 'evidence', 'context', 'outcome', 'checkpoint', 'process_flush', 'session_start', 'session_end']
const DEFAULT_STATUS = ['open', 'default', 'candidate', 'promoted', 'archived', 'conflict']

function defaultBeadTypeClass(type) {
  return DEFAULT_BEAD_TYPES.includes(type) ? 'bead-type-' + type : 'bead-type-default'
}

function defaultStatusClass(status) {
  return DEFAULT_STATUS.includes(status) ? 'status-' + status : 'status-default'
}

function BeadsPane(props) {
  const beads = Array.isArray(props.beads) ? props.beads : []
  const beadTypeClass = typeof props.beadTypeClass === 'function' ? props.beadTypeClass : defaultBeadTypeClass
  const statusClass = typeof props.statusClass === 'function' ? props.statusClass : defaultStatusClass

  if (!beads.length) {
    return React.createElement('div', { className: 'empty-state' }, 'No beads yet')
  }

  return React.createElement(
    React.Fragment,
    null,
    ...beads.map((b, idx) => {
      const beadId = String((b && b.id) || '')
      const turns = Array.isArray(b && b.source_turn_ids) ? b.source_turn_ids : []
      const summary = Array.isArray(b && b.summary) ? b.summary : []
      const type = String((b && b.type) || 'unknown')
      const status = String((b && b.status) || 'default')
      const title = String((b && b.title) || '')

      return React.createElement(
        'div',
        {
          className: 'bead-card',
          key: beadId || String(idx),
          onClick: () => {
            if (typeof props.onOpenBead === 'function' && beadId) {
              props.onOpenBead(beadId)
            }
          },
        },
        React.createElement(
          'div',
          { className: 'bead-header' },
          React.createElement('span', { className: 'bead-type ' + beadTypeClass(type) }, type),
          React.createElement('span', { className: 'bead-title' }, title || 'untitled'),
          React.createElement('span', { className: 'bead-status ' + statusClass(status) }, status)
        ),
        summary.length
          ? React.createElement('div', { className: 'bead-summary' }, summary.join(' · '))
          : null,
        React.createElement(
          'div',
          { className: 'bead-id' },
          beadId +
            ' · ' +
            (turns.join(', ') || 'no turn') +
            ((b && b.hydrate_available) ? ' · hydrate✓' : '')
        )
      )
    })
  )
}

export function renderBeadsPane(container, props) {
  if (!container) return
  const root = getRoot(container)
  root.render(React.createElement(BeadsPane, props || {}))
}
