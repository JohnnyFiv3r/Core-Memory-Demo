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

function fmtIso(value, fallback) {
  const raw = String(value || '').trim()
  if (!raw) return fallback || 'n/a'
  const d = new Date(raw)
  if (Number.isNaN(d.getTime())) return raw
  return d.toISOString().replace('T', ' ').replace('.000Z', 'Z')
}

function EntitiesPane(props) {
  const entityMeta = props.entityMeta || {}
  const rows = Array.isArray(entityMeta.rows) ? entityMeta.rows : []
  const counts = entityMeta.counts || {}
  const merges = Array.isArray(entityMeta.merge_proposals) ? entityMeta.merge_proposals : []
  const formatIsoShort = typeof props.formatIsoShort === 'function'
    ? props.formatIsoShort
    : (v) => fmtIso(v, 'n/a')

  return React.createElement(
    React.Fragment,
    null,
    React.createElement(
      'div',
      { className: 'claims-toolbar' },
      React.createElement(
        'button',
        {
          className: 'btn',
          onClick: () => {
            if (typeof props.onSuggestMerges === 'function') props.onSuggestMerges()
          },
        },
        'Suggest merges'
      ),
      React.createElement(
        'button',
        {
          className: 'btn',
          onClick: () => {
            if (typeof props.onRefresh === 'function') props.onRefresh()
          },
        },
        'Refresh'
      )
    ),
    React.createElement(
      'div',
      { style: { marginBottom: '8px' } },
      React.createElement('span', { className: 'claims-pill' }, 'total ' + String(counts.total ?? rows.length)),
      ' ',
      React.createElement('span', { className: 'claims-pill' }, 'active ' + String(counts.active ?? 0)),
      ' ',
      React.createElement('span', { className: 'claims-pill' }, 'merged ' + String(counts.merged ?? 0)),
      ' ',
      React.createElement('span', { className: 'claims-pill' }, 'merge proposals ' + String(merges.length))
    ),
    rows.length === 0
      ? React.createElement('div', { className: 'empty-state' }, 'No entity registry rows yet')
      : React.createElement(
          React.Fragment,
          null,
          ...rows.slice(0, 80).map((r, idx) => {
            const status = String((r && r.status) || 'active')
            return React.createElement(
              'div',
              { className: 'runtime-card', key: String((r && r.id) || idx) },
              React.createElement(
                'div',
                null,
                React.createElement('strong', null, String((r && (r.label || r.id)) || 'entity')),
                ' ',
                React.createElement(
                  'span',
                  { className: 'runtime-badge ' + (status === 'active' ? 'runtime-badge-good' : 'runtime-badge-warn') },
                  status
                )
              ),
              React.createElement(
                'div',
                { style: { marginTop: '2px', color: 'var(--text-dim)' } },
                'id: ' + String((r && r.id) || 'n/a')
              ),
              React.createElement(
                'div',
                { style: { marginTop: '2px', color: 'var(--text-dim)' } },
                'aliases: ' + String((r && r.aliases_count) ?? 0) +
                  ' · confidence: ' +
                  String((r && r.confidence) ?? 'n/a') +
                  ' · provenance: ' +
                  String((r && r.provenance_count) ?? 0)
              ),
              (r && r.merged_into)
                ? React.createElement(
                    'div',
                    { style: { marginTop: '2px', color: 'var(--amber)' } },
                    'merged_into: ' + String(r.merged_into)
                  )
                : null,
              React.createElement(
                'div',
                { style: { marginTop: '2px', color: 'var(--text-dim)' } },
                'updated: ' + formatIsoShort((r && r.updated_at) || '')
              ),
              Array.isArray(r && r.aliases) && (r.aliases || []).length
                ? React.createElement(
                    'div',
                    { style: { marginTop: '4px', color: 'var(--text-dim)', fontSize: '11px' } },
                    'aliases: ' + (r.aliases || []).slice(0, 8).join(', ')
                  )
                : null
            )
          })
        ),
    merges.length
      ? React.createElement(
          React.Fragment,
          null,
          React.createElement(
            'div',
            { className: 'runtime-card' },
            React.createElement('strong', null, 'Entity merge proposals'),
            React.createElement(
              'div',
              { style: { marginTop: '2px', color: 'var(--text-dim)' } },
              'Pending proposals can be accepted/rejected directly from this panel.'
            )
          ),
          ...merges.slice(0, 20).map((m, idx) => {
            const status = String((m && m.status) || 'n/a')
            const isPending = status === 'pending'
            return React.createElement(
              'div',
              {
                className: 'bench-bucket',
                key: String((m && m.id) || idx),
                onClick: () => {
                  if (typeof props.onOpenProposal === 'function') props.onOpenProposal(m)
                },
              },
              React.createElement(
                'div',
                null,
                React.createElement('strong', null, String((m && m.id) || 'proposal')),
                ' ',
                React.createElement(
                  'span',
                  { className: 'runtime-badge ' + (isPending ? 'runtime-badge-warn' : 'runtime-badge-good') },
                  status
                )
              ),
              React.createElement(
                'div',
                { style: { marginTop: '2px', color: 'var(--text-dim)' } },
                'score=' + String(Number((m && m.score) || 0).toFixed(3)) +
                  ' · left=' +
                  String((m && m.left_entity_id) || 'n/a') +
                  ' · right=' +
                  String((m && m.right_entity_id) || 'n/a')
              ),
              React.createElement(
                'div',
                { style: { marginTop: '2px', color: 'var(--text-dim)' } },
                'reasons: ' + String((((m && m.reasons) || []).join(', ')) || 'n/a')
              ),
              isPending
                ? React.createElement(
                    'div',
                    { style: { marginTop: '6px', display: 'flex', gap: '6px', flexWrap: 'wrap' } },
                    React.createElement(
                      'button',
                      {
                        className: 'btn',
                        onClick: (ev) => {
                          ev.stopPropagation()
                          if (typeof props.onDecideMerge === 'function') {
                            props.onDecideMerge(m, 'accept', String((m && m.left_entity_id) || ''))
                          }
                        },
                      },
                      'Accept (keep left)'
                    ),
                    React.createElement(
                      'button',
                      {
                        className: 'btn',
                        onClick: (ev) => {
                          ev.stopPropagation()
                          if (typeof props.onDecideMerge === 'function') {
                            props.onDecideMerge(m, 'accept', String((m && m.right_entity_id) || ''))
                          }
                        },
                      },
                      'Accept (keep right)'
                    ),
                    React.createElement(
                      'button',
                      {
                        className: 'btn btn-warn',
                        onClick: (ev) => {
                          ev.stopPropagation()
                          if (typeof props.onDecideMerge === 'function') {
                            props.onDecideMerge(m, 'reject', null)
                          }
                        },
                      },
                      'Reject'
                    )
                  )
                : React.createElement(
                    'div',
                    { style: { marginTop: '4px', color: 'var(--text-dim)', fontSize: '11px' } },
                    'reviewer: ' + String((m && m.reviewer) || 'n/a') +
                      ' · reviewed_at: ' +
                      formatIsoShort(String((m && m.reviewed_at) || ''))
                  )
            )
          })
        )
      : null
  )
}

export function renderEntitiesPane(container, props) {
  if (!container) return
  const root = getRoot(container)
  root.render(React.createElement(EntitiesPane, props || {}))
}
