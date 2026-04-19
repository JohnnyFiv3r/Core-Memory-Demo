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

function fmtIso(value) {
  const raw = String(value || '').trim()
  if (!raw) return 'n/a'
  const d = new Date(raw)
  if (Number.isNaN(d.getTime())) return raw
  return d.toISOString().replace('T', ' ').replace('.000Z', 'Z')
}

function badgeClass(ok, badWhenFalse = true) {
  if (ok) return 'runtime-badge-good'
  return badWhenFalse ? 'runtime-badge-bad' : 'runtime-badge-warn'
}

function RuntimePane(props) {
  const runtime = props.runtime || {}
  const lastTurn = props.lastTurn || {}
  const formatIsoShort = typeof props.formatIsoShort === 'function' ? props.formatIsoShort : fmtIso

  const q = runtime.queue || {}
  const qRows = Array.isArray(runtime.queue_breakdown) ? runtime.queue_breakdown : []
  const s = runtime.semantic_backend || {}
  const p = (lastTurn || {}).diagnostics || {}
  const f = runtime.last_flush || {}
  const fHist = Array.isArray(runtime.flush_history) ? runtime.flush_history : []
  const my = runtime.myelination || {}

  const warnCount = Array.isArray(p.warnings) ? p.warnings.length : 0
  const mode = String(s.mode || 'degraded_allowed')
  const usable = !!s.usable_backend
  const strictMode = mode === 'required'
  const warningText = String(s.concurrency_warning || '').trim()
  const showBackendWarning = !!(
    warningText &&
    !(mode === 'degraded_allowed' && /No semantic backend is currently active/i.test(warningText))
  )

  const topIds = Array.isArray(p.top_bead_ids) ? p.top_bead_ids.slice(0, 5) : []

  return React.createElement(
    React.Fragment,
    null,
    React.createElement(
      'div',
      { className: 'runtime-card' },
      React.createElement('div', null, React.createElement('strong', null, 'Async Queue')),
      React.createElement(
        'div',
        { style: { marginTop: '4px', color: 'var(--text-dim)' } },
        'pending: ' + String(q.pending_total ?? 0) + ' · processable: ' + String(q.processable_now ?? 0)
      ),
      React.createElement('div', { style: { marginTop: '2px', color: 'var(--text-dim)' } }, 'ok: ' + String(!!q.ok)),
      qRows.length
        ? React.createElement(
            'div',
            { className: 'claim-events' },
            ...qRows.map((r, idx) => {
              const err = String((r && r.last_error) || '').trim()
              return React.createElement(
                'div',
                { className: 'claim-event', key: String((r && r.kind) || idx) },
                React.createElement(
                  'div',
                  null,
                  React.createElement('strong', null, String((r && r.kind) || 'queue')),
                  ' ',
                  React.createElement(
                    'span',
                    { className: 'runtime-badge ' + (r && r.circuit_open ? 'runtime-badge-bad' : 'runtime-badge-good') },
                    'circuit=' + String(!!(r && r.circuit_open))
                  )
                ),
                React.createElement(
                  'div',
                  { style: { color: 'var(--text-dim)' } },
                  'pending=' + String((r && r.pending) ?? 0) +
                    ' · processable=' +
                    String((r && r.processable_now) ?? 0) +
                    ' · retry_ready=' +
                    String((r && r.retry_ready) ?? 0)
                ),
                err
                  ? React.createElement('div', { style: { color: 'var(--amber)' } }, 'last_error: ' + err)
                  : null
              )
            })
          )
        : null
    ),

    React.createElement(
      'div',
      { className: 'runtime-card' },
      React.createElement('div', null, React.createElement('strong', null, 'Semantic Backend')),
      React.createElement(
        'div',
        { style: { marginTop: '4px', color: 'var(--text-dim)' } },
        'backend: ' + String(s.backend || 'unknown') + ' · provider: ' + String(s.provider || 'unknown')
      ),
      React.createElement(
        'div',
        { style: { marginTop: '2px', color: 'var(--text-dim)' } },
        'profile: ' + String(s.deployment_profile || 'n/a') + ' · rows: ' + String(s.rows_count ?? 0)
      ),
      React.createElement(
        'div',
        { style: { marginTop: '6px' } },
        React.createElement(
          'span',
          { className: 'runtime-badge ' + (strictMode ? 'runtime-badge-bad' : 'runtime-badge-warn') },
          'mode=' + mode
        ),
        ' ',
        React.createElement(
          'span',
          { className: 'runtime-badge ' + (usable ? 'runtime-badge-good' : (strictMode ? 'runtime-badge-bad' : 'runtime-badge-warn')) },
          'usable=' + String(usable)
        ),
        ' ',
        React.createElement(
          'span',
          { className: 'runtime-badge ' + (!!s.multi_worker_safe ? 'runtime-badge-good' : 'runtime-badge-warn') },
          'multi-worker=' + String(!!s.multi_worker_safe)
        ),
        ' ',
        React.createElement(
          'span',
          { className: 'runtime-badge ' + ((s.connectivity_checked && !s.connectivity_ok) ? 'runtime-badge-bad' : 'runtime-badge-good') },
          'connectivity=' + String(s.connectivity_checked ? !!s.connectivity_ok : 'n/a')
        )
      ),
      s.connectivity_checked && !s.connectivity_ok
        ? React.createElement(
            'div',
            { style: { marginTop: '2px', color: 'var(--amber)' } },
            'connectivity_error: ' + String(s.connectivity_error || 'unknown')
          )
        : null,
      React.createElement(
        'div',
        { style: { marginTop: '4px', color: 'var(--text-dim)' } },
        'next: ' + String(s.next_step || 'n/a')
      ),
      showBackendWarning
        ? React.createElement('div', { style: { marginTop: '2px', color: 'var(--amber)' } }, 'warning: ' + warningText)
        : null
    ),

    React.createElement(
      'div',
      { className: 'runtime-card' },
      React.createElement('div', null, React.createElement('strong', null, 'Last Answer Diagnostics')),
      React.createElement(
        'div',
        { style: { marginTop: '4px', color: 'var(--text-dim)' } },
        'ok: ' + String(!!p.ok) +
          ' · outcome: ' +
          String(p.answer_outcome || 'n/a') +
          ' · mode: ' +
          String(p.retrieval_mode || 'n/a')
      ),
      React.createElement(
        'div',
        { style: { marginTop: '2px', color: 'var(--text-dim)' } },
        'surface: ' + String(p.source_surface || 'n/a') + ' · anchor: ' + String(p.anchor_reason || 'n/a')
      ),
      React.createElement(
        'div',
        { style: { marginTop: '2px', color: 'var(--text-dim)' } },
        'results: ' + String(p.result_count ?? 0) + ' · chains: ' + String(p.chain_count ?? 0) + ' · warnings: ' + String(warnCount)
      ),
      React.createElement(
        'div',
        { style: { marginTop: '2px', color: 'var(--text-dim)' } },
        'grounding: ' +
          String(p.grounding_level || 'n/a') +
          ' · required=' +
          String(!!p.grounding_required) +
          ' · achieved=' +
          String(!!p.grounding_achieved) +
          (p.intent_class ? (' · intent=' + String(p.intent_class)) : '')
      ),
      p.grounding_reason
        ? React.createElement(
            'div',
            { style: { marginTop: '2px', color: 'var(--text-dim)' } },
            'grounding reason: ' + String(p.grounding_reason)
          )
        : null,
      topIds.length
        ? React.createElement(
            'div',
            { style: { marginTop: '2px', color: 'var(--text-dim)' } },
            'top beads: ' + topIds.join(', ')
          )
        : null,
      warnCount
        ? React.createElement(
            'div',
            { style: { marginTop: '2px', color: 'var(--amber)' } },
            'warning list: ' + (Array.isArray(p.warnings) ? p.warnings.join(' | ') : '')
          )
        : null
    ),

    React.createElement(
      'div',
      { className: 'runtime-card' },
      React.createElement('div', null, React.createElement('strong', null, 'Last Flush')),
      React.createElement(
        'div',
        { style: { marginTop: '4px', color: 'var(--text-dim)' } },
        'ok: ' + String(!!f.flush_ok) + ' · flushed: ' + String(f.flushed_session || 'n/a')
      ),
      React.createElement(
        'div',
        { style: { marginTop: '2px', color: 'var(--text-dim)' } },
        'trigger: ' + String(f.trigger || 'n/a') + ' · at: ' + formatIsoShort(f.timestamp || '')
      ),
      fHist.length
        ? React.createElement(
            'div',
            { className: 'claim-events' },
            ...fHist.slice(0, 8).map((ev, idx) =>
              React.createElement(
                'div',
                { className: 'claim-event', key: String((ev && ev.timestamp) || idx) },
                React.createElement(
                  'div',
                  null,
                  React.createElement('strong', null, String((ev && ev.trigger) || 'flush')),
                  ' ',
                  React.createElement(
                    'span',
                    { className: 'runtime-badge ' + ((ev && ev.flush_ok) ? 'runtime-badge-good' : 'runtime-badge-bad') },
                    'ok=' + String(!!(ev && ev.flush_ok))
                  )
                ),
                React.createElement(
                  'div',
                  { style: { color: 'var(--text-dim)' } },
                  'flushed=' + String((ev && ev.flushed_session) || 'n/a') +
                    ' · new=' +
                    String((ev && ev.new_session) || 'n/a') +
                    ' · beads=' +
                    String((ev && ev.rolling_window_beads) ?? 0)
                ),
                React.createElement(
                  'div',
                  { style: { color: 'var(--text-dim)' } },
                  'at=' + formatIsoShort((ev && ev.timestamp) || '')
                )
              )
            )
          )
        : null
    ),

    React.createElement(
      'div',
      { className: 'runtime-card' },
      React.createElement('div', null, React.createElement('strong', null, 'Myelination')),
      React.createElement(
        'div',
        { style: { marginTop: '4px', color: 'var(--text-dim)' } },
        'enabled: ' +
          String(!!my.enabled) +
          ' · strengthened/weakened: ' +
          String((my.stats || {}).strengthened || 0) +
          '/' +
          String((my.stats || {}).weakened || 0)
      )
    )
  )
}

export function renderRuntimePane(container, props) {
  if (!container) return
  const root = getRoot(container)
  root.render(React.createElement(RuntimePane, props || {}))
}
