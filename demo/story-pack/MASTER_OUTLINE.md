# 204-Turn Core Memory Demo Story Outline

## Summary

This story follows a regulated analytics product from cold start to launch. It begins as Northstar, survives compliance churn and runtime trouble, is renamed Compass, and finishes with a stable current-state canon plus preserved historical layers.

## Act Map

| Act | Turns | Session | Focus |
| --- | --- | --- | --- |
| 01 | 001-016 | `cm-story-s1` | Cold start, first durable facts, grounded recall baseline |
| 02 | 017-034 | `cm-story-s1` | Architecture expansion, regions, SLO, pilot customer |
| 03 | 035-052 | `cm-story-s1` | Entity seeding, owners, aliases, naming drift |
| 04 | 053-066 | mixed | Pre-flush inspection, first flush, reset-proof recall |
| 05 | 067-086 | `cm-story-s2` | Auth churn, deadline slip, vendor conflict, claim history |
| 06 | 087-104 | `cm-story-s2` | Semantic backend debate, pgvector vs Qdrant, degraded expectations |
| 07 | 105-120 | `cm-story-s2` | Degraded retrieval week, partial vs abstain, last-answer diagnostics |
| 08 | 121-138 | `cm-story-s2` | Queue backpressure postmortem, evidence -> decision -> lesson -> outcome |
| 09 | 139-156 | `cm-story-s2` | Rebrand to Compass, merge review, alias adjudication |
| 10 | 157-174 | `cm-story-s2` | `as_of` replay, historical reconciliation, stable current state |
| 11 | 175-186 | `cm-story-s2` | Snapshot benchmark expectations and isolated-run reasoning |
| 12 | 187-204 | `cm-story-s2` | Launch state, clean benchmark comparison, final flush |

## Checkpoints

- After Turn `058`: flush `cm-story-s1`, then continue in `cm-story-s2`.
- After Turn `186`: run an isolated `snapshot` benchmark.
- After Turn `200`: run an isolated `clean` benchmark.
- After Turn `204`: run the final session flush.

## Stable Current-State Canon by the End

- Product name: `Compass` with `Northstar` and `NS` preserved historically.
- Database: `PostgreSQL` chosen for `JSONB` support and about `2x` better representative-workload performance.
- Auth vendor: `WorkOS`.
- Production semantic backend: `Qdrant`.
- Local/staging fallback context: `pgvector` plus explicit lexical fallback behavior in degraded cases.
- Launch customers: `Mercury Health` and `Redwood Clinics`.
- Key owners: `Maya Chen`, `Priya Nair`, `Luis Ortega`.

## Historical Layers That Must Stay Queryable

- Pre-rebrand product naming (`Northstar`, `Northstar API`, `NS Console`).
- Auth vendor evolution (`Auth0` first, `WorkOS` later, `Okta` as procurement conflict).
- Degraded retrieval week and its conservative answer policy.
- Queue backpressure root cause and mitigation history.
- Earlier semantic direction before `Qdrant` became current.
