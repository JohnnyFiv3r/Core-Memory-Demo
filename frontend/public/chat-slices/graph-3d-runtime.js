const REACT_ESM_SRC = 'https://esm.sh/react@18.3.1'
const REACT_DOM_CLIENT_ESM_SRC = 'https://esm.sh/react-dom@18.3.1/client'
const REAGRAPH_ESM_SRC = 'https://esm.sh/reagraph@4.30.8?bundle&deps=react@18.3.1,react-dom@18.3.1'

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

export async function renderGraph3DRuntimePane(opts) {
  const safe = opts || {}
  if (!safe.canvasHost || !safe.wrap || !safe.graph) {
    throw new Error('graph_3d_runtime_missing_context')
  }

  const { React, createRoot, GraphCanvas } = await ensureRuntime()
  if (safe.el && !safe.el.contains(safe.canvasHost)) return

  const root = createRoot(safe.canvasHost)
  safe.wrap.__cmUnmount = () => {
    try { root.unmount() } catch (_) {}
  }

  root.render(
    React.createElement(GraphCanvas, {
      nodes: safe.graph.nodes,
      edges: safe.graph.edges,
      layoutType: 'forceDirected3d',
      cameraMode: 'orbit',
      draggable: true,
      animated: true,
      labelType: 'all',
      edgeLabelPosition: 'inline',
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
