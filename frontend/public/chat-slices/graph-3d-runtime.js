const REACT_ESM_SRC = 'https://esm.sh/react@18.3.1'
const REACT_DOM_CLIENT_ESM_SRC = 'https://esm.sh/react-dom@18.3.1/client'
const REAGRAPH_ESM_SRC = 'https://esm.sh/reagraph@4.30.8?bundle&deps=react@18.3.1,react-dom@18.3.1'

const ROTATE_DEG_PER_SEC = 4
const ROTATE_START_DELAY_MS = 600
const ROTATE_MAX_NODES = 600
const DEG2RAD = Math.PI / 180

let loadPromise = null

function graphEntityId(v) {
  if (v && typeof v === 'object') return String(v.id || v.name || '')
  return String(v || '')
}

function ensureRuntime() {
  if (loadPromise) return loadPromise

  loadPromise = Promise.all([
    import(REACT_ESM_SRC),
    import(REACT_DOM_CLIENT_ESM_SRC),
    import(REAGRAPH_ESM_SRC),
  ]).then(([reactMod, reactDomMod, reagraphMod]) => {
    const React = reactMod && (reactMod.default || reactMod)
    const createRoot = reactDomMod && reactDomMod.createRoot
    const GraphCanvas = reagraphMod && reagraphMod.GraphCanvas
    if (!React || !createRoot || !GraphCanvas) {
      throw new Error('reagraph_runtime_missing_exports')
    }
    return { React, createRoot, GraphCanvas }
  }).catch((err) => {
    loadPromise = null
    throw err
  })

  return loadPromise
}

// Drive a gentle idle rotation through reagraph's underlying camera-controls
// instance (graphRef.getControls()), and stop it for good the first time the
// user grabs the camera. reagraph's built-in cameraMode="orbit" spins too fast
// (hardcoded 20 deg/s) and never yields, so we run cameraMode="pan" and rotate
// ourselves. Best-effort: any failure just leaves a static, draggable graph.
function startSlowAutoRotate(graphRef, nodeCount) {
  let rafId = 0
  let startTimer = 0
  let lastTs = 0
  let stopped = false
  let controls = null

  const stop = () => {
    stopped = true
    if (rafId) cancelAnimationFrame(rafId)
    rafId = 0
    if (controls && typeof controls.removeEventListener === 'function') {
      try { controls.removeEventListener('control', stop) } catch (_) {}
    }
  }

  const tick = (ts) => {
    if (stopped || !controls) return
    const delta = lastTs ? (ts - lastTs) / 1000 : 0
    lastTs = ts
    try {
      controls.azimuthAngle += ROTATE_DEG_PER_SEC * delta * DEG2RAD
      controls.update(delta)
    } catch (_) {
      stop()
      return
    }
    rafId = requestAnimationFrame(tick)
  }

  const begin = () => {
    if (stopped) return
    const ref = graphRef && graphRef.current
    controls = ref && typeof ref.getControls === 'function' ? ref.getControls() : null
    if (!controls) {
      startTimer = window.setTimeout(begin, 250)
      return
    }
    if (Number(nodeCount || 0) > ROTATE_MAX_NODES) return
    if (typeof controls.addEventListener === 'function') {
      try { controls.addEventListener('control', stop) } catch (_) {}
    }
    lastTs = 0
    rafId = requestAnimationFrame(tick)
  }

  startTimer = window.setTimeout(begin, ROTATE_START_DELAY_MS)

  return () => {
    window.clearTimeout(startTimer)
    stop()
  }
}

export async function renderGraph3DRuntimePane(opts) {
  const safe = opts || {}
  if (!safe.canvasHost || !safe.wrap || !safe.graph) {
    throw new Error('graph_3d_runtime_missing_context')
  }

  const { React, createRoot, GraphCanvas } = await ensureRuntime()
  if (safe.el && !safe.el.contains(safe.canvasHost)) return

  const graphRef = { current: null }
  const nodeCount = (safe.graph.nodes || []).length
  let stopRotate = null

  const root = createRoot(safe.canvasHost)
  safe.wrap.__cmUnmount = () => {
    if (typeof stopRotate === 'function') {
      try { stopRotate() } catch (_) {}
    }
    try { root.unmount() } catch (_) {}
  }

  root.render(
    React.createElement(GraphCanvas, {
      ref: (r) => {
        graphRef.current = r
        if (r && !stopRotate) {
          stopRotate = startSlowAutoRotate(graphRef, nodeCount)
        }
      },
      nodes: safe.graph.nodes,
      edges: safe.graph.edges,
      layoutType: 'forceDirected3d',
      // pan (not orbit) so our own slow rotation is the only auto-motion.
      cameraMode: 'pan',
      draggable: true,
      animated: true,
      labelType: 'all',
      edgeLabelPosition: 'inline',
      edgeArrowPosition: 'end',
      theme: safe.theme || {},
      onNodeClick: (node) => {
        const id = graphEntityId(node && (node.id || (node.data || {}).id))
        if (id && typeof safe.onNodeClick === 'function') safe.onNodeClick(id)
      },
      onEdgeClick: (edge) => {
        if (!edge || typeof safe.onEdgeClick !== 'function') return
        const data = edge.data || {}
        safe.onEdgeClick({
          source: edge.source,
          target: edge.target,
          relationship: edge.label || data.relationship || 'associated_with',
          confidence: data.confidence,
          reason_text: data.reason_text,
        })
      },
    })
  )
}
