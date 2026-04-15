# Turn Index

| Turns | Act | Session | Primary behaviors |
| --- | --- | --- | --- |
| 001-016 | Act 01: Cold Start and First Durable Facts | `cm-story-s1` | No-memory baseline, first claims, first graph chain, first grounded answers |
| 017-034 | Act 02: Architecture Expansion | `cm-story-s1` | Multi-tenant ingestion, immutable audit, retention, regions, SLO, pilot customer |
| 035-052 | Act 03: Entity Seeding and Naming Drift | `cm-story-s1` | Named owners, aliases, entity recurrence, merge-readiness signals |
| 053-066 | Act 04: First Flush and Reset-Proof Recall | mixed | Pre-flush inspection, archive continuity, post-reset recall |
| 067-086 | Act 05: Compliance Churn and Claim History | `cm-story-s2` | Deadline slip, Mercury-only exception, Auth0/WorkOS/Okta conflict, `as_of` replay |
| 087-104 | Act 06: Search and Semantic Strategy Debate | `cm-story-s2` | pgvector vs Qdrant, lexical fallback, staging vs production, runtime expectations |
| 105-120 | Act 07: Degraded Retrieval Week | `cm-story-s2` | Degraded mode, partial vs abstain, last-answer diagnostics |
| 121-138 | Act 08: Queue Backpressure Postmortem | `cm-story-s2` | Runtime evidence, graph-based postmortem, durable mitigations |
| 139-156 | Act 09: Rebrand and Merge Review | `cm-story-s2` | Compass rename, entity merge accept/reject flow, preserved aliases |
| 157-174 | Act 10: Historical Reconciliation | `cm-story-s2` | Historical truth, current truth, resolved auth/backend canon |
| 175-186 | Act 11: Snapshot Benchmark Pass | `cm-story-s2` | Benchmark expectations, isolated snapshot reasoning, drilldown language |
| 187-204 | Act 12: Launch, Clean Benchmark, Final Flush | `cm-story-s2` | Launch-state canon, clean benchmark comparison, final flush |

## Checkpoint Index

| After turn | Checkpoint | Notes |
| --- | --- | --- |
| 058 | Session flush | Rotate from `cm-story-s1` to `cm-story-s2` |
| 186 | Snapshot benchmark | Run on copied state only |
| 200 | Clean benchmark | Run on a fresh isolated root |
| 204 | Final flush | Archive the final launch-state story |
