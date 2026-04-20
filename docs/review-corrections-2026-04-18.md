# Core Memory Demo review corrections (2026-04-18)

This note captures stale/inaccurate items observed in `core-memory-demo-fix-list` when compared against `MidwestJohn/corememorydemo` at `43b2d8c` plus follow-up corrections landed today.

## Corrected / stale assertions

- **D2 (Auth0 blocks local eval) is partially stale**
  - `demo_auth_enabled` defaults to `false` in backend settings, so local eval does not require Auth0 unless explicitly enabled.
  - `.env.example` and README now document this default.

- **D14 (rate limits are global-anonymous) is stale**
  - Rate limiter identity key is scoped by client session header when present (`sess:<id>`), then principal sub, then client IP (`sub:<id>` / `ip:<host>`), not a single global bucket.

- **D6 context update**
  - `heavy_operation_slot()` supports per-identity-only gating by default (`ABUSE_HEAVY_MAX_CONCURRENT=0`, `ABUSE_HEAVY_MAX_CONCURRENT_PER_IDENTITY=1`), so one caller's heavy run does not globally block all others.

## Additional hardening applied in this correction pass

- **Pinned backend dependency**
  - `backend/requirements.txt` now pins Core-Memory to a concrete commit SHA instead of `@master`.

- **Resolved hidden React parity drift path**
  - `frontend/src/App.tsx` no longer branches on `#react`.
  - Removed unused parity remnants (`frontend/src/ReactParityApp.tsx`, `frontend/src/react-parity.css`) to avoid dead-code ambiguity.

## Remaining concern from the review

- Larger P2 modernization item still remains (full React extraction from monolithic HTML).

## Additional follow-up corrections

- Benchmark "last run" surfaces now use a disk-backed snapshot fallback (`benchmark-history.jsonl`) and mutable in-process cache updates (no stale imported-global rebinds).
- Root app no longer uses iframe embedding as the primary delivery path and now defaults to the chat surface (`chat.html`).
- Graph View no longer redirects away from chat; it opens as an in-app overlay (`graph.html` iframe modal) and closes back to the same chat session.

## Follow-up items completed after this correction pass

- Landing defaults to chat (`/chat.html`) with Graph as an in-app overlay modal (no redirect/route swap).
- Turn token tracking no longer uses `(chars + 500) // 4`; runtime now uses model-aware estimation (tiktoken when available, deterministic byte/segment fallback otherwise).
- Demo now exposes model selection (`/api/demo/models`, `/api/demo/model`) and a chat-header model picker with credential-aware options.
- Chat now exposes live pipeline progress via async endpoints (`POST /api/chat/start`, `GET /api/chat/status/{job_id}`), and the UI surfaces retrieval/generation/linking/diagnostics stages instead of static typing dots.
- Render deploy config no longer hard-codes single-instance (`numInstances: 1` removed); instance count is now an environment-level deploy setting, not a repo-advertised cap.
- Hidden React parity route debt is now fully resolved by deleting unused parity files, not just removing route entry.
- Added baseline frontend security headers in `vercel.json`, including CSP + nosniff/referrer/frame protections.
- Removed inline DOM event attributes from `chat.html` (`onclick`/`onchange`/`onkeydown`) and bound handlers in script to reduce CSP friction.
- Externalized `chat.html` inline scripts into `chat-bootstrap.js` and `chat-app.js`, then tightened CSP `script-src` by removing `'unsafe-inline'` for scripts.
- Began pane-by-pane React extraction: Rolling Window tab now renders via a dedicated React module (`frontend/public/chat-slices/rolling-pane.js`) loaded by `chat-app.js`, with graceful fallback if module load fails.
- Continued pane extraction: Claims tab now renders via React module (`frontend/public/chat-slices/claims-pane.js`) with existing claim-detail loader integration and fallback preservation in `chat-app.js`.
- Continued pane extraction: Entities tab now renders via React module (`frontend/public/chat-slices/entities-pane.js`) with merge action callbacks and fallback preservation in `chat-app.js`.
- Continued pane extraction: Runtime tab now renders via React module (`frontend/public/chat-slices/runtime-pane.js`) with fallback preservation in `chat-app.js`.
- Continued pane extraction: Benchmark tab now renders via React module (`frontend/public/chat-slices/benchmark-pane.js`) with modal-open callback wiring and fallback preservation in `chat-app.js`.
- Continued pane extraction: Beads tab now renders via React module (`frontend/public/chat-slices/beads-pane.js`) with bead-open callback wiring and fallback preservation in `chat-app.js`.
- Continued pane extraction: Associations tab now renders via React module (`frontend/public/chat-slices/associations-pane.js`) with fallback preservation in `chat-app.js`.
- Continued graph extraction: Graph list rows now render via React module (`frontend/public/chat-slices/graph-list-pane.js`) with bead-open callback wiring and fallback preservation in `chat-app.js`.
- Continued graph extraction: Graph toolbar and filter controls now render via React module (`frontend/public/chat-slices/graph-controls-pane.js`) with mode/filter callback wiring and fallback preservation in `chat-app.js`.
- Continued graph extraction: Graph edge-detail card/actions now render via React module (`frontend/public/chat-slices/graph-edge-detail-pane.js`) with bead-open callback wiring and fallback preservation in `chat-app.js`.
- Continued graph extraction: Graph filtered-summary/legend card now renders via React module (`frontend/public/chat-slices/graph-summary-pane.js`) with fallback preservation in `chat-app.js`.
- Continued graph extraction: Graph 3D canvas host wrapper now renders via dedicated slice module (`frontend/public/chat-slices/graph-canvas-host.js`) with fallback preservation in `chat-app.js`.
- Continued graph extraction: SVG graph fallback canvas now renders via dedicated slice module (`frontend/public/chat-slices/graph-svg-canvas.js`) with fallback preservation in `chat-app.js`.
- Continued graph extraction: Reagraph runtime loader/render bridge now routes through dedicated slice module (`frontend/public/chat-slices/graph-3d-runtime.js`) with fallback preservation in `chat-app.js`.
- Continued graph extraction: Reagraph data-shaping/type-color mapping now routes through dedicated slice module (`frontend/public/chat-slices/graph-reagraph-data.js`) with fallback preservation in `chat-app.js`.
- Continued graph extraction: Shared graph utility helpers now route through dedicated slice module (`frontend/public/chat-slices/graph-utils.js`) covering edge normalization, relation/search filtering, node-title lookup, and entity id normalization with fallback preservation in `chat-app.js`.
- Continued graph extraction: Removed remaining inline Reagraph runtime bridge from `chat-app.js`; 3D runtime now resolves through `frontend/public/chat-slices/graph-3d-runtime.js` only (with SVG fallback still preserved on load/render failure).
- Cleanup pass: removed dead legacy `renderGraphLegend()` from `chat-app.js` after summary/legend responsibilities moved to `frontend/public/chat-slices/graph-summary-pane.js`.
- Cleanup pass: removed dead legacy helpers `openReagraphArchiveWindow()` and `showTyping()` from `chat-app.js` after event-binding migration and pipeline-status UI changes made them unused.
- Cleanup pass: simplified graph fallback utilities in `chat-app.js` by removing redundant `*Fallback` helper wrappers (`graphNumConfidenceFallback`, `graphNodeTitleFallback`, `graphEntityIdFallback`, `graphTypeColorFallback`) while preserving behavior.
- Cleanup pass: consolidated repeated graph slice dynamic-import boilerplate in `chat-app.js` via shared `lazyLoadSlice()` helper and rewired graph module loaders to use it.
- Cleanup pass: extended shared `lazyLoadSlice()` usage to non-graph pane loaders (`beads`, `associations`, `rolling`, `claims`, `entities`, `runtime`, `benchmark`) to reduce repeated dynamic-import boilerplate.
- Cleanup pass: centralized repeated renderer-or-fallback invocation patterns in `chat-app.js` via shared `renderViaSlice()` helper across graph + non-graph pane render paths.
- Cleanup pass: replaced per-module `*LoadPromise` variables with shared keyed loader registry (`sliceLoadState` + `ensureSliceLoad()`) and rewired all `ensure*` slice loaders to use it.
- Cleanup pass: added shared `ensureSliceBinding()` helper and rewired all `ensure*` slice loaders to use it, removing repeated guard-and-load wrapper boilerplate.
- Cleanup pass: added shared `callGraphUtils()` helper and rewired graph utility callsites (`graphNumConfidence`, `graphNodeTitle`, `normalizeGraphEdges`, `applyGraphFilters`, `graphEntityId`) to remove repeated module-method/fallback boilerplate.
- Cleanup pass: added generic `callSliceWithFallback()` helper and rewired module-backed compute/factory paths (`reagraphDataFromEdges`, `createGraphCanvasHost`) to remove repeated try/fallback blocks.
- Cleanup pass: added shared `openJsonModal()` helper and rewired repeated modal-open callsites across entities/benchmark/bead detail flows.
- Cleanup pass: added shared `arrayOrEmpty()` helper and rewired repeated array-normalization callsites in pane/render flows to reduce defensive `Array.isArray(...) ? ... : []` boilerplate.
- Cleanup pass: added `arrayOr()` and `firstPayloadError()` helpers, then rewired remaining array-check/error-extraction patterns (including benchmark history + seed error handling) to remove residual `Array.isArray` boilerplate.
- Cleanup pass: added benchmark UI helpers `appendBenchCards()` and `appendBenchBucket()` and rewired repeated benchmark card/bucket row construction in `renderBenchmarkFallback()`.
- Cleanup pass: added shared `appendRuntimeCard()` helper and rewired repeated runtime-card creation blocks in runtime + benchmark fallback rendering.
- Cleanup pass: added shared `appendBenchFail()` helper and rewired repeated benchmark fail-row creation/click wiring in `renderBenchmarkFallback()`.
- Cleanup pass: added shared `benchmarkRunRowHtml()` helper and rewired repeated benchmark run-summary row markup construction in `renderBenchmarkFallback()`.
- Cleanup pass: added shared `benchmarkDeltaClass()`/`benchmarkDeltaSpan()` helpers and rewired benchmark delta rendering callsites to use them.
- Cleanup pass: added shared `benchmarkPassFail()` helper and rewired benchmark pass/fail formatting callsites in fallback rendering and summary text.
- Cleanup pass: added shared `benchmarkAcc()` helper and rewired benchmark accuracy formatting callsites to remove repeated `toFixed(4)` boilerplate.
- Cleanup pass: added shared `benchmarkNA()` helper and rewired benchmark `n/a` fallback text formatting callsites in fallback rendering and summary text.
- Cleanup pass: added shared `benchmarkAtValue()` helper and rewired benchmark timestamp label formatting callsites in fallback rendering.
- Cleanup pass: added shared benchmark latency/token helpers (`benchmarkLatency()`, `benchmarkLatencyMs()`, `benchmarkTokens()`) and rewired benchmark formatting callsites in fallback rendering.
- Cleanup pass: added shared `benchmarkWarnCount()` helper and rewired benchmark warning-count formatting callsites in fallback rendering and summary text.
- Cleanup pass: added shared `benchmarkBackendModes()` helper and rewired backend-mode label formatting callsites in fallback rendering and summary text.
- Cleanup pass: added shared `benchmarkImprovedRegressed()` helper and rewired improved/regressed pair formatting in benchmark fallback rendering.
- Cleanup pass: added shared `benchmarkCaseId()` / `benchmarkCaseTitle()` helpers and rewired benchmark case-id/title composition callsites in fallback rendering.
- Cleanup pass: added shared `benchmarkBool()` helper and rewired benchmark baseline/enabled boolean label formatting in pass-state change rows.
