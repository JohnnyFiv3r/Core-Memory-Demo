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

function deltaClass(v) {
  if (v > 0) return 'bench-delta-good'
  if (v < 0) return 'bench-delta-bad'
  return 'bench-delta-neutral'
}

function fmtIso(value) {
  const raw = String(value || '').trim()
  if (!raw) return 'n/a'
  const d = new Date(raw)
  if (Number.isNaN(d.getTime())) return raw
  return d.toISOString().replace('T', ' ').replace('.000Z', 'Z')
}

function BenchmarkPane(props) {
  const summary = props.summary || {}
  const report = props.report || null
  const benchmarkMeta = props.benchmarkMeta || {}
  const history = Array.isArray(benchmarkMeta.history) ? benchmarkMeta.history : []
  const formatIsoShort = typeof props.formatIsoShort === 'function' ? props.formatIsoShort : fmtIso
  const openPayload = typeof props.onOpenPayload === 'function' ? props.onOpenPayload : () => {}

  const suite = String((summary || {}).suite || '')
  const isLocomo = suite && suite !== 'fixture_smoke'

  if (!summary || (!summary.cases && !summary.qa_cases)) {
    return React.createElement(
      React.Fragment,
      null,
      React.createElement('div', { className: 'empty-state' }, 'No benchmark run yet'),
      history.length
        ? React.createElement(
            React.Fragment,
            null,
            React.createElement('div', { className: 'runtime-card' }, React.createElement('strong', null, 'Recent runs')),
            ...history.slice(0, 8).map((r, idx) => {
              const s = r.summary || {}
              return React.createElement(
                'div',
                {
                  className: 'bench-bucket',
                  key: String((s.run_id || r.run_id || idx)),
                  onClick: () => openPayload('Benchmark run summary', r),
                },
                React.createElement('div', null, React.createElement('strong', null, String(s.run_id || r.run_id || 'run'))),
                React.createElement(
                  'div',
                  { style: { marginTop: '2px', color: 'var(--text-dim)' } },
                  (String(s.suite || '') && String(s.suite || '') !== 'fixture_smoke'
                  ? ('suite=' + String(s.suite || 'locomo') +
                    ' · f1=' + Number(s.answer_f1_mean || 0).toFixed(4) +
                    ' · recall@5=' + Number(s.evidence_recall_at_5 || 0).toFixed(4))
                  : ('acc=' + Number(s.accuracy || 0).toFixed(4) +
                    ' · pass/fail=' +
                    String((s.pass || 0) + '/' + (s.fail || 0)))
                ) +
                ' · at=' +
                formatIsoShort(String(s.finished_at || r.created_at || ''))
                )
              )
            })
          )
        : null
    )
  }

  const latencyMean = Number(((report || {}).latency_ms || {}).mean || 0).toFixed(2)
  const tokenTotal = Number(((report || {}).token_usage || {}).total_tokens_est || 0)
  const cards = isLocomo
    ? [
        ['suite', String(summary.suite || 'locomo')],
        ['samples', String(summary.samples || 0)],
        ['qa cases', String(summary.qa_cases || 0)],
        ['turns ingested', String(summary.turns_ingested || 0)],
        ['answer f1', Number(summary.answer_f1_mean || 0).toFixed(4)],
        ['recall@5', Number(summary.evidence_recall_at_5 || 0).toFixed(4)],
      ]
    : [
        ['accuracy', Number(summary.accuracy || 0).toFixed(4)],
        ['cases', String(summary.cases || 0)],
        ['pass/fail', String((summary.pass || 0) + '/' + (summary.fail || 0))],
        ['semantic', String(summary.semantic_mode || 'n/a')],
        ['latency mean (ms)', latencyMean],
        ['tokens est', tokenTotal.toLocaleString()],
      ]

  const cmp = summary.myelination_compare || null
  const r = report || null

  let compareSection = null
  if (r && r.myelination_comparison) {
    const mc = r.myelination_comparison || {}
    const baseline = mc.baseline || {}
    const enabled = mc.enabled || {}
    const delta = Number(mc.accuracy_delta || 0)
    const cases = Array.isArray(mc.cases) ? mc.cases : []
    const improved = cases.filter(c => !c.baseline_pass && c.enabled_pass)
    const regressed = cases.filter(c => c.baseline_pass && !c.enabled_pass)
    const changed = cases.filter(c => !!c.pass_changed)

    const changedOrdered = changed.slice().sort((a, b) => {
      const aReg = (!!a.baseline_pass && !a.enabled_pass) ? 1 : 0
      const bReg = (!!b.baseline_pass && !b.enabled_pass) ? 1 : 0
      if (aReg !== bReg) return bReg - aReg
      return String(a.case_id || '').localeCompare(String(b.case_id || ''))
    })

    compareSection = React.createElement(
      React.Fragment,
      null,
      React.createElement(
        'div',
        { className: 'runtime-card' },
        React.createElement('div', null, React.createElement('strong', null, 'Myelination compare')),
        React.createElement(
          'div',
          { style: { marginTop: '4px', color: 'var(--text-dim)' } },
          'baseline acc=' + String(baseline.accuracy ?? 'n/a') +
            ' · enabled acc=' +
            String(enabled.accuracy ?? 'n/a') +
            ' · delta='
        ),
        React.createElement('div', { className: deltaClass(delta), style: { marginTop: '2px' } }, String(delta.toFixed(4))),
        React.createElement(
          'div',
          { style: { marginTop: '2px', color: 'var(--text-dim)' } },
          'pass/fail baseline=' +
            String((baseline.pass ?? 0) + '/' + (baseline.fail ?? 0)) +
            ' · enabled=' +
            String((enabled.pass ?? 0) + '/' + (enabled.fail ?? 0))
        )
      ),
      React.createElement(
        'div',
        { className: 'bench-grid' },
        ...[
          ['improved', String(improved.length)],
          ['regressed', String(regressed.length)],
          ['changed', String(changed.length)],
          ['unchanged', String(cases.length - changed.length)],
        ].map(([k, v]) =>
          React.createElement(
            'div',
            { className: 'bench-card', key: k },
            React.createElement('div', { className: 'k' }, k),
            React.createElement('div', { className: 'v' }, v)
          )
        )
      ),
      changedOrdered.length
        ? React.createElement(
            React.Fragment,
            null,
            React.createElement('div', { className: 'runtime-card' }, React.createElement('strong', null, 'Pass-state changes')),
            ...changedOrdered.slice(0, 20).map((c, idx) => {
              const regressedNow = !!c.baseline_pass && !c.enabled_pass
              const improvedNow = !c.baseline_pass && !!c.enabled_pass
              return React.createElement(
                'div',
                {
                  className: 'bench-fail',
                  key: String(c.case_id || idx),
                  style: {
                    background: improvedNow ? 'rgba(74, 222, 128, 0.08)' : 'rgba(248, 113, 113, 0.08)',
                    borderColor: improvedNow ? 'rgba(74, 222, 128, 0.30)' : 'rgba(248, 113, 113, 0.25)',
                  },
                  onClick: () => openPayload('Myelination compare case: ' + String(c.case_id || 'detail'), c),
                },
                React.createElement(
                  'div',
                  null,
                  React.createElement('strong', null, String(c.case_id || 'case')),
                  ' · ',
                  React.createElement(
                    'span',
                    { className: improvedNow ? 'bench-delta-good' : (regressedNow ? 'bench-delta-bad' : 'bench-delta-neutral') },
                    improvedNow ? 'improved' : (regressedNow ? 'regressed' : 'changed')
                  )
                ),
                React.createElement(
                  'div',
                  { style: { color: 'var(--text-dim)', marginTop: '2px' } },
                  'baseline=' +
                    String(!!c.baseline_pass) +
                    ' · enabled=' +
                    String(!!c.enabled_pass) +
                    ' · latency Δ=' +
                    String(Number(c.latency_delta_ms || 0).toFixed(3)) +
                    'ms'
                )
              )
            })
          )
        : null
    )
  }

  const fails = r && Array.isArray(r.cases) ? r.cases.filter(c => !c.pass) : []

  let recentRunsCompare = null
  if (summary.run_id && history.length >= 2) {
    const current = history.find(hx => String((hx.summary || {}).run_id || hx.run_id || '') === String(summary.run_id))
    const baseline = history.find(hx => String((hx.summary || {}).run_id || hx.run_id || '') !== String(summary.run_id))
    if (current && baseline) {
      const cs = current.summary || {}
      const bs = baseline.summary || {}
      if (isLocomo) {
        const dF1 = Number(cs.answer_f1_mean || 0) - Number(bs.answer_f1_mean || 0)
        const dRecall = Number(cs.evidence_recall_at_5 || 0) - Number(bs.evidence_recall_at_5 || 0)
        recentRunsCompare = React.createElement(
          'div',
          { className: 'runtime-card' },
          React.createElement('div', null, React.createElement('strong', null, 'Latest vs previous run')),
          React.createElement(
            'div',
            { style: { marginTop: '2px', color: 'var(--text-dim)' } },
            'baseline=' + String(bs.run_id || baseline.run_id || 'n/a') + ' → current=' + String(cs.run_id || current.run_id || 'n/a')
          ),
          React.createElement(
            'div',
            { style: { marginTop: '4px', color: 'var(--text-dim)' } },
            'answer f1 Δ='
          ),
          React.createElement('div', { className: deltaClass(dF1), style: { marginTop: '2px' } }, dF1.toFixed(4)),
          React.createElement(
            'div',
            { style: { marginTop: '2px', color: 'var(--text-dim)' } },
            'recall@5 Δ=' + dRecall.toFixed(4)
          )
        )
      } else {
        const dAcc = Number(cs.accuracy || 0) - Number(bs.accuracy || 0)
        const dLat = Number(cs.latency_mean_ms || 0) - Number(bs.latency_mean_ms || 0)
        const dTok = Number(cs.tokens_total_est || 0) - Number(bs.tokens_total_est || 0)
        recentRunsCompare = React.createElement(
          'div',
          { className: 'runtime-card' },
          React.createElement('div', null, React.createElement('strong', null, 'Latest vs previous run')),
          React.createElement(
            'div',
            { style: { marginTop: '2px', color: 'var(--text-dim)' } },
            'baseline=' + String(bs.run_id || baseline.run_id || 'n/a') + ' → current=' + String(cs.run_id || current.run_id || 'n/a')
          ),
          React.createElement(
            'div',
            { style: { marginTop: '4px', color: 'var(--text-dim)' } },
            'accuracy Δ='
          ),
          React.createElement('div', { className: deltaClass(dAcc), style: { marginTop: '2px' } }, dAcc.toFixed(4)),
          React.createElement(
            'div',
            { style: { marginTop: '2px', color: 'var(--text-dim)' } },
            'latency Δ=' + dLat.toFixed(3) + 'ms · tokens Δ=' + dTok.toLocaleString()
          )
        )
      }
    }
  }

  return React.createElement(
    React.Fragment,
    null,
    React.createElement(
      'div',
      { className: 'bench-grid' },
      ...cards.map(([k, v]) =>
        React.createElement(
          'div',
          { className: 'bench-card', key: k },
          React.createElement('div', { className: 'k' }, k),
          React.createElement('div', { className: 'v' }, v)
        )
      )
    ),
    React.createElement(
      'div',
      { className: 'runtime-card' },
      React.createElement('div', null, React.createElement('strong', null, 'Run config')),
      React.createElement(
        'div',
        { style: { marginTop: '2px', color: 'var(--text-dim)' } },
        'run_id: ' +
          String(summary.run_id || 'n/a') +
          ' · at: ' +
          formatIsoShort(String(summary.finished_at || summary.started_at || ''))
      ),
      React.createElement(
        'div',
        { style: { marginTop: '4px', color: 'var(--text-dim)' } },
        isLocomo
          ? ('root mode: ' + String(summary.root_mode || 'n/a') +
            ' · answer mode: ' + String(summary.answer_mode || 'n/a') +
            ' · retrieval k: ' + String(summary.retrieval_k || 'n/a'))
          : ('root mode: ' + String(summary.root_mode || 'n/a') + ' · preload turns: ' + String(summary.preload_turn_count || 0))
      ),
      React.createElement(
        'div',
        { style: { marginTop: '2px', color: 'var(--text-dim)' } },
        isLocomo
          ? ('artifact path: ' + String(summary.artifact_path || 'n/a'))
          : ('backend modes: ' + String((summary.backend_modes || []).join(', ') || 'unknown'))
      ),
      React.createElement(
        'div',
        { style: { marginTop: '2px', color: 'var(--text-dim)' } },
        'warnings: ' + String((summary.warnings || []).length)
      ),
      cmp
        ? React.createElement(
            'div',
            { style: { marginTop: '2px', color: 'var(--text-dim)' } },
            'compare Δ=' +
              String(Number(cmp.accuracy_delta || 0).toFixed(4)) +
              ' · improved/regressed=' +
              String((cmp.improved_cases || 0) + '/' + (cmp.regressed_cases || 0))
          )
        : null,
      React.createElement(
        'div',
        { style: { marginTop: '6px' } },
        React.createElement(
          'button',
          { className: 'btn', onClick: () => openPayload('LOCOMO Benchmark Report (raw JSON)', report || {}) },
          'Open raw JSON'
        )
      )
    ),
    isLocomo && r && r.scores && r.scores.by_category
      ? React.createElement(
          React.Fragment,
          null,
          React.createElement('div', { className: 'runtime-card' }, React.createElement('strong', null, 'By category')),
          ...Object.keys(r.scores.by_category || {}).sort().map((k) => {
            const row = (r.scores.by_category || {})[k] || {}
            return React.createElement(
              'div',
              { className: 'bench-bucket', key: k },
              React.createElement('strong', null, 'category ' + k),
              ' · qa=', String(row.qa_count || 0),
              ' · f1=', Number(row.answer_f1_mean || 0).toFixed(4),
              ' · recall@5=', Number(row['evidence_recall@5'] || 0).toFixed(4),
              ' · mrr=', Number(row.mrr || 0).toFixed(4)
            )
          })
        )
      : null,
    !isLocomo && r && r.per_bucket
      ? React.createElement(
          React.Fragment,
          null,
          ...Object.keys(r.per_bucket).sort().map((k) => {
            const row = r.per_bucket[k] || {}
            return React.createElement(
              'div',
              { className: 'bench-bucket', key: k },
              React.createElement('strong', null, k),
              ' · acc=',
              Number(row.accuracy || 0).toFixed(4),
              ' · pass/fail=',
              String((row.pass || 0) + '/' + (row.fail || 0))
            )
          })
        )
      : null,
    compareSection,
    !isLocomo && fails.length
      ? React.createElement(
          React.Fragment,
          null,
          React.createElement('div', { className: 'runtime-card' }, React.createElement('strong', null, 'Failing cases')),
          ...fails.map((c, idx) =>
            React.createElement(
              'div',
              {
                className: 'bench-fail',
                key: String(c.case_id || idx),
                onClick: () => openPayload('Benchmark case: ' + String(c.case_id || 'detail'), c),
              },
              React.createElement('div', null, React.createElement('strong', null, String(c.case_id || 'case'))),
              React.createElement(
                'div',
                { style: { color: 'var(--text-dim)', marginTop: '2px' } },
                'expected=' +
                  String(c.expected_answer_class || 'n/a') +
                  ' · actual=' +
                  String(c.actual_answer_class || 'n/a')
              ),
              React.createElement(
                'div',
                { style: { color: 'var(--text-dim)', marginTop: '2px' } },
                'surface=' + String(c.top_source_surface || 'n/a') + ' · anchor=' + String(c.top_anchor_reason || 'n/a')
              ),
              React.createElement(
                'div',
                { style: { color: 'var(--text-dim)', marginTop: '2px' } },
                'backend=' +
                  String(c.benchmark_backend_mode || 'n/a') +
                  ' · tokens=' +
                  String(((c.token_usage || {}).total_tokens_est ?? 0)) +
                  ' · warnings=' +
                  String((c.warnings || []).length)
              )
            )
          )
        )
      : null,
    history.length
      ? React.createElement(
          React.Fragment,
          null,
          React.createElement(
            'div',
            { className: 'runtime-card' },
            React.createElement('strong', null, 'Recent runs'),
            React.createElement(
              'div',
              { style: { marginTop: '2px', color: 'var(--text-dim)' } },
              'Click a row for full payload.'
            )
          ),
          ...history.slice(0, 12).map((rowData, idx) => {
            const s = rowData.summary || {}
            return React.createElement(
              'div',
              {
                className: 'bench-bucket',
                key: String(s.run_id || rowData.run_id || idx),
                onClick: () => openPayload('Benchmark run', rowData),
              },
              React.createElement('div', null, React.createElement('strong', null, String(s.run_id || rowData.run_id || ('run-' + idx)))),
              React.createElement(
                'div',
                { style: { marginTop: '2px', color: 'var(--text-dim)' } },
                'acc=' +
                  Number(s.accuracy || 0).toFixed(4) +
                  ' · pass/fail=' +
                  String((s.pass || 0) + '/' + (s.fail || 0)) +
                  ' · latency=' +
                  Number(s.latency_mean_ms || 0).toFixed(2) +
                  'ms · tokens=' +
                  Number(s.tokens_total_est || 0).toLocaleString()
              ),
              React.createElement(
                'div',
                { style: { marginTop: '2px', color: 'var(--text-dim)' } },
                'at=' + formatIsoShort(String(s.finished_at || rowData.created_at || ''))
              )
            )
          }),
          recentRunsCompare
        )
      : null
  )
}

export function renderBenchmarkPane(container, props) {
  if (!container) return
  const root = getRoot(container)
  root.render(React.createElement(BenchmarkPane, props || {}))
}
