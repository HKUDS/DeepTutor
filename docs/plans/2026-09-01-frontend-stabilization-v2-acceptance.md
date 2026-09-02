# DeepTutor v2 Frontend Acceptance Record

**Recorded:** 2026-09-01

**Branch:** `codex/frontend-stabilization-v2`

**Scope:** Frontend stabilization, v2 turn protocol migration, feature-boundary cleanup, lifecycle UX unification, responsive/accessibility repair, and release-gate hardening.

## Decision

The frontend implementation is complete and suitable for integration with the stabilized backend. Final release approval remains conditional on running the registered multi-worker browser suite against the real four-worker Redis fixture and completing the normal canary rollout. This document does not substitute mocked transport evidence for that external proof.

## Architecture acceptance

- Browser chat traffic uses the generated v2 turn protocol through `TurnRuntimeClient` and `UnifiedTurnClient`.
- The obsolete browser `/api/v1/chat` transport, recovery client, legacy chat shells, and compatibility barrels are removed. A source guard prevents them from returning.
- Chat state is an external store with selector subscriptions. A 500-content-event test records 501 message renders (initial plus each event) and exactly one sidebar render.
- Chat, Settings, Knowledge, Co-Writer, Reading, Mastery, and Watching are represented as explicit route/feature boundaries rather than route-owned cross-feature implementations.
- Terminal, retryable, cancellation-pending, waiting-for-input, reconnecting, and foreign-observer states share the same turn lifecycle model and status vocabulary.
- Runtime health and protocol compatibility are visible to the user without exposing credentials or raw internal diagnostics.

## Build and performance gates

Next.js 16 no longer exposes useful route-level data in the old client-reference-manifest shape. `route_budgets.mjs` now starts the production server, reads the scripts actually loaded by each route, and subtracts the framework and common root shell. These are raw loaded JavaScript bytes, not transfer-size claims.

| Surface | Measured JS | Budget |
| --- | ---: | ---: |
| Landing `/` | 274 KB | 300 KB |
| Chat | 978 KB | 1,020 KB |
| Settings | 807 KB | 840 KB |
| Knowledge | 517 KB | 540 KB |
| Co-Writer index | 292 KB | 320 KB |
| Co-Writer document | 493 KB | 515 KB |
| Reading | 1,083 KB | 1,120 KB |
| Mastery | 949 KB | 980 KB |
| Root app shell | 373 KB | 390 KB |

The production build generates 73 static pages. The following large implementation modules remain optimization debt rather than boundary violations:

| Lines | Module |
| ---: | --- |
| 2,830 | `features/chat/components/ChatWorkspace.tsx` |
| 2,703 | `features/chat/trace/TracePresentation.tsx` |
| 2,475 | `features/co-writer/components/CoWriterWorkspace.tsx` |
| 2,363 | `features/chat/ChatStateAdapter.tsx` |

Future size work should split these by interaction path without recreating cross-feature state ownership.

## Automated acceptance matrix

`npm run check` is the deterministic local and CI release gate, in this order:

1. generated protocol drift and contract compatibility;
2. architecture dependency rules;
3. TypeScript;
4. Node test suite;
5. rendered Vitest suite;
6. ESLint;
7. i18n parity/audit;
8. production build;
9. route budgets.

The browser audit covers semantic landmark/accessibility rules, keyboard-reachable controls, focus return, reduced motion, responsive Reading annotations, and the complete video-learning flow. The release UI matrix checks all six primary surfaces across Snow/Cream/Dark/Glass, English/Chinese, 390 px mobile, tablet, desktop, and a 200%-zoom-equivalent layout viewport. Every matrix case checks horizontal overflow, keyboard focus where controls are present, empty credential fields, and secret-shaped DOM text. CI starts the built production frontend and runs this browser gate after `npm run check`. The critical turn browser suite covers reconnect, cancellation acknowledgement, waiting input, retryable worker loss, reload replay, and foreign observation. Desktop and iPhone 13 reduced-motion projects are registered.

The multi-worker suite defines six scenarios across two browser projects (12 cases) and refuses to run unless its fixture reports exactly four workers plus healthy Redis. CI runs it on schedule or manual dispatch when `DEEPTUTOR_MULTI_WORKER_E2E_URL` is configured, and uploads JSON evidence.

## Recorded verification

| Gate | Result | Observed duration |
| --- | --- | ---: |
| Protocol drift | Pass | included in full gate |
| Architecture | Pass — 733 modules, 1,902 dependencies, 0 violations | included in full gate |
| Node tests | 928 passed | 2.47 s test process |
| Rendered tests | 31 passed | 1.53 s |
| ESLint | 0 errors, 57 existing warnings | included in full gate |
| i18n | parity passed; audit reports 36 possible literals for follow-up | included in full gate |
| Production build | 73 pages | 9.8 s compile + 8.7 s TypeScript |
| Route budgets | 9/9 passed | included in full gate |
| Focused interaction/accessibility audit | 11/11 passed | 6.2 s |
| Release UI matrix | 192 surface/configuration checks passed | 16.2 s |
| Four-worker browser suite | 12 cases registered; intentionally skipped without fixture | external gate |

The i18n audit is a heuristic report and its current candidate list includes code examples, product names, and other known non-copy literals; parity and lint remain the enforced correctness gates. The 57 lint warnings are pre-existing warning-level debt, with no lint errors introduced by this work.

## External release gate

Before declaring the combined frontend/backend release ready:

1. expose the deterministic fixture controls used by `tests/e2e/fixtures/runtime.ts` from an isolated test deployment;
2. set `DEEPTUTOR_MULTI_WORKER_E2E_URL` and `DEEPTUTOR_MULTI_WORKER_E2E=1`;
3. run `npm run test:e2e:multi-worker` and retain the evidence artifact;
4. canary the compatibility window and confirm no v1 browser requests, sequence gaps, duplicate events, or credential-bearing logs;
5. remove any backend compatibility window only after the canary remains clean.

Until those steps run against the backend deployment, the honest status is **frontend accepted; integrated multi-worker release pending**.
