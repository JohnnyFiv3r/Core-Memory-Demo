import React, { useEffect, useRef, useState } from 'https://esm.sh/react@18.3.1'
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

function defaultStatusClass(status) {
  const known = ['open', 'default', 'candidate', 'promoted', 'archived', 'conflict']
  return known.includes(status) ? 'status-' + status : 'status-default'
}

function ClaimsPane(props) {
  const rows = Array.isArray(props.rows) ? props.rows : []
  const claimsMeta = props.claimsMeta || {}
  const counts = claimsMeta.counts || {}
  const statusClass = typeof props.statusClass === 'function' ? props.statusClass : defaultStatusClass
  const selectedClaimSlot = String(props.selectedClaimSlot || '').trim()
  const claimsDetailOpen = !!props.claimsDetailOpen
  const asOfInputValue = String(props.asOfInputValue || '')
  const asOfLabel = String(props.asOfLabel || 'now')

  const [asOfLocal, setAsOfLocal] = useState(asOfInputValue)
  const detailRef = useRef(null)

  useEffect(() => {
    setAsOfLocal(asOfInputValue)
  }, [asOfInputValue])

  useEffect(() => {
    if (!claimsDetailOpen || !selectedClaimSlot || !detailRef.current) return
    detailRef.current.textContent = 'Loading slot detail...'
    if (typeof props.loadDetail === 'function') {
      props.loadDetail(selectedClaimSlot, detailRef.current)
    }
  }, [claimsDetailOpen, selectedClaimSlot, asOfLabel, props])

  return React.createElement(
    React.Fragment,
    null,
    React.createElement(
      'div',
      { className: 'claims-toolbar' },
      React.createElement('input', {
        type: 'datetime-local',
        className: 'control-input',
        style: { width: '200px' },
        title: 'As-of timestamp (UTC)',
        value: asOfLocal,
        onChange: (e) => setAsOfLocal(String((e && e.target && e.target.value) || '')),
      }),
      React.createElement(
        'button',
        {
          className: 'btn',
          onClick: () => {
            if (typeof props.onApplyAsOfValue === 'function') {
              props.onApplyAsOfValue(asOfLocal)
            }
          },
        },
        'Apply as-of'
      ),
      React.createElement(
        'button',
        {
          className: 'btn',
          onClick: () => {
            setAsOfLocal('')
            if (typeof props.onClearAsOf === 'function') {
              props.onClearAsOf()
            }
          },
        },
        'Now'
      )
    ),
    React.createElement(
      'div',
      { style: { marginBottom: '8px' } },
      React.createElement('span', { className: 'claims-pill' }, 'active ' + String(counts.active ?? 0)),
      ' ',
      React.createElement('span', { className: 'claims-pill' }, 'conflict ' + String(counts.conflict ?? 0)),
      ' ',
      React.createElement('span', { className: 'claims-pill' }, 'retracted ' + String(counts.retracted ?? 0)),
      ' ',
      React.createElement('span', { className: 'claims-pill' }, 'other ' + String(counts.other ?? 0)),
      React.createElement(
        'span',
        { style: { marginLeft: '6px', color: 'var(--text-dim)', fontSize: '11px' } },
        'as_of: ' + asOfLabel
      )
    ),
    rows.length === 0
      ? React.createElement('div', { className: 'empty-state' }, 'No claim-state slots yet')
      : React.createElement(
          'div',
          { className: 'claims-layout' },
          React.createElement(
            'div',
            { className: 'claims-list' },
            React.createElement(
              'div',
              {
                style: {
                  padding: '8px 10px',
                  borderBottom: '1px solid var(--border)',
                  fontSize: '11px',
                  color: 'var(--text-dim)',
                },
              },
              'Select a claim slot to open detail view.'
            ),
            ...rows.map((r, idx) => {
              const slotKey = String((r && r.slot_key) || '')
              const status = String((r && r.status) || 'not_found')
              const active = slotKey === selectedClaimSlot
              return React.createElement(
                'div',
                {
                  className: 'claim-row' + (active ? ' active' : ''),
                  key: slotKey || String(idx),
                  onClick: () => {
                    if (typeof props.onSelectSlot === 'function') {
                      props.onSelectSlot(slotKey)
                    }
                  },
                },
                React.createElement(
                  'div',
                  null,
                  React.createElement('strong', null, slotKey || '-'),
                  ' ',
                  React.createElement('span', { className: 'bead-status ' + statusClass(status) }, status)
                ),
                React.createElement(
                  'div',
                  { style: { marginTop: '2px', color: 'var(--text-dim)' } },
                  'value: ' + String((r && r.value) ?? '—') +
                    ' · conflicts: ' +
                    String((r && r.conflict_count) ?? 0)
                )
              )
            })
          ),
          React.createElement(
            'div',
            { className: 'claims-detail-overlay' + (claimsDetailOpen ? ' open' : '') },
            React.createElement('button', {
              type: 'button',
              className: 'claims-detail-backdrop',
              'aria-label': 'Close claim detail',
              onClick: () => {
                if (typeof props.onCloseDetail === 'function') props.onCloseDetail()
              },
            }),
            React.createElement(
              'div',
              { className: 'claims-detail-panel' },
              React.createElement(
                'div',
                { className: 'claims-detail-head' },
                React.createElement('strong', null, 'Claim detail'),
                React.createElement(
                  'span',
                  { style: { color: 'var(--text-dim)' } },
                  'slot: ' + (selectedClaimSlot || 'n/a')
                ),
                React.createElement(
                  'button',
                  {
                    type: 'button',
                    className: 'claims-detail-close',
                    'aria-label': 'Close claim detail',
                    onClick: () => {
                      if (typeof props.onCloseDetail === 'function') props.onCloseDetail()
                    },
                  },
                  '×'
                )
              ),
              React.createElement(
                'div',
                { className: 'claims-detail-body' },
                React.createElement('div', { className: 'claim-detail', ref: detailRef }, 'Loading slot detail...')
              )
            )
          )
        )
  )
}

export function renderClaimsPane(container, props) {
  if (!container) return
  const root = getRoot(container)
  root.render(React.createElement(ClaimsPane, props || {}))
}

