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

function GraphControlsPane(props) {
  const beadCount = Number(props.beadCount || 0)
  const edgeCount = Number(props.edgeCount || 0)
  const viewMode = String(props.viewMode || 'list')
  const showFilters = !!props.showFilters
  const relationOptions = Array.isArray(props.relationOptions) ? props.relationOptions : ['all']
  const relationValue = String(props.relationValue || 'all')
  const minConfidence = Number(props.minConfidence || 0)
  const search = String(props.search || '')

  return React.createElement(
    React.Fragment,
    null,
    React.createElement(
      'div',
      { className: 'graph-toolbar' },
      React.createElement(
        'div',
        {
          dangerouslySetInnerHTML: {
            __html:
              '<div><strong>Graph pane</strong></div>' +
              '<div style="margin-top:2px;color:var(--text-dim)">beads=' + String(beadCount) +
              ' · associations=' + String(edgeCount) + '</div>',
          },
        }
      ),
      React.createElement(
        'div',
        { className: 'graph-toggle' },
        React.createElement(
          'button',
          {
            type: 'button',
            className: 'graph-toggle-btn' + (viewMode === 'list' ? ' active' : ''),
            onClick: () => {
              if (typeof props.onSetMode === 'function') props.onSetMode('list')
            },
          },
          'List view'
        ),
        React.createElement(
          'button',
          {
            type: 'button',
            className: 'graph-toggle-btn' + (viewMode === 'graph' ? ' active' : ''),
            onClick: () => {
              if (typeof props.onSetMode === 'function') props.onSetMode('graph')
            },
          },
          'Graph view'
        )
      )
    ),
    showFilters
      ? React.createElement(
          'div',
          { className: 'graph-filters' },
          React.createElement('span', { className: 'graph-filter-label' }, 'Filters'),
          React.createElement(
            'select',
            {
              className: 'control-select',
              style: { width: '160px' },
              value: relationValue,
              onChange: (ev) => {
                if (typeof props.onSetRelation === 'function') {
                  props.onSetRelation(String((ev && ev.target && ev.target.value) || 'all'))
                }
              },
            },
            ...relationOptions.map((rel) =>
              React.createElement('option', { key: String(rel), value: String(rel) }, String(rel))
            )
          ),
          React.createElement('input', {
            className: 'control-input',
            type: 'number',
            min: '0',
            max: '1',
            step: '0.05',
            style: { width: '90px' },
            value: Number.isFinite(minConfidence) ? String(minConfidence.toFixed(2)) : '0.00',
            onChange: (ev) => {
              if (typeof props.onSetMinConfidence === 'function') {
                props.onSetMinConfidence((ev && ev.target && ev.target.value) || '0')
              }
            },
          }),
          React.createElement('input', {
            className: 'control-input',
            type: 'text',
            placeholder: 'search node/edge',
            style: { flex: 1, minWidth: '160px' },
            value: search,
            onInput: (ev) => {
              if (typeof props.onSetSearch === 'function') {
                props.onSetSearch(String((ev && ev.target && ev.target.value) || '').trim())
              }
            },
          })
        )
      : null
  )
}

export function renderGraphControlsPane(container, props) {
  if (!container) return
  const root = getRoot(container)
  root.render(React.createElement(GraphControlsPane, props || {}))
}
