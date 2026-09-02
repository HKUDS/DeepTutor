# DeepTutor v2 Frontend Baseline

**Captured:** 2026-09-01

**Git base:** `02b68dda` (`dev`)

**Purpose:** Preserve the observable frontend contract and measurable starting point before the v2 protocol, state, and feature-boundary migration.

## 1. Turn lifecycle contract

The fixture-backed characterization test records these client commands:

- `start_turn` with content, session, and capability;
- `subscribe_turn` with `after_seq`;
- `resume_from` with the last sequence;
- `regenerate` with overrides;
- `cancel_turn`;
- `submit_user_reply` with structured answers.

The successful event fixture starts with `session`, advances monotonically by `seq`, pauses at `wait_for_input`, resumes content, and ends with `done` carrying authoritative terminal metadata. The failed fixture ends with `error_code=worker_lost` and `retryable=true`.

The initial test run failed as expected:

```text
tests/turn-lifecycle-characterization.test.ts(10,7): error TS2322:
Type '"wait_for_input"' is not assignable to type 'StreamEventType'.
```

The temporary handwritten frontend union was brought into parity with the already-existing Python `StreamEventType.WAIT_FOR_INPUT`. Generated contracts replace this union in the contract phase.

## 2. Source baseline

### Largest TypeScript modules

| Lines | Module |
| ---: | --- |
| 2,808 | `app/(workspace)/home/[[...sessionId]]/page.tsx` |
| 2,750 | `components/chat/home/TracePanels.tsx` |
| 2,542 | `app/(workspace)/co-writer/[docId]/page.tsx` |
| 2,377 | `context/UnifiedChatContext.tsx` |
| 1,979 | `components/settings/SettingsContext.tsx` |
| 1,949 | `components/knowledge/EngineDetail.tsx` |
| 1,664 | `components/chat/home/ChatMessages.tsx` |
| 1,635 | `components/settings/ServiceConfigEditor.tsx` |
| 1,522 | `components/memory/MemorySection.tsx` |
| 1,473 | `components/knowledge/CreateKbModal.tsx` |
| 1,444 | `lib/knowledge-api.ts` |
| 1,404 | `app/(utility)/settings/document-parsing/page.tsx` |
| 1,386 | `components/quiz/QuizViewer.tsx` |
| 1,250 | `app/(workspace)/book/components/BookCreator.tsx` |
| 1,239 | `components/chat/home/ChatComposer.tsx` |
| 1,208 | `components/chat/home/SessionViewerPanel.tsx` |
| 1,206 | `app/(workspace)/book/page.tsx` |
| 1,023 | `components/space/SkillsSection.tsx` |
| 1,023 | `components/cli-apps/CliAppsSection.tsx` |
| 1,003 | `components/chat/home/StandaloneComposer.tsx` |
| 991 | `components/chat/home/AskUserOptions.tsx` |
| 989 | `components/memory/MemoryGraph.tsx` |
| 942 | `components/memory/MemoryRunPanel.tsx` |
| 931 | `components/partners/PartnerChat.tsx` |
| 905 | `components/reading/ReaderPane.tsx` |

There are 169,601 lines across canonical TS/TSX source and tests, excluding dependencies and generated build directories.

### Route and state ownership indicators

| Measure | Baseline |
| --- | ---: |
| App route pages | 81 |
| Client route pages | 63 |
| Modules declaring React Context | 9 |
| `useUnifiedChat()` consumer modules | 11 |
| Node test files | 136 |
| Node test cases | 846 |

Source sizes for the requested routes:

| Route module | Lines | Bytes |
| --- | ---: | ---: |
| Chat `/home/[[...sessionId]]` | 2,808 | 109,463 |
| Continuous Settings `/settings` | 37 | 1,512 |
| Knowledge `/knowledge` | 19 | 477 |
| Co-Writer `/co-writer/[docId]` | 2,542 | 90,677 |

The small Settings and Knowledge route shells do not imply a small surface: Settings imports route modules into a continuous page and Knowledge delegates into large component/API modules.

## 3. Build and client-chunk baseline

The production build completed successfully with Next.js 16.2.3. Client chunk sizes below are the unique chunks referenced by each route page module in the generated client-reference manifest; they include shared chunks referenced from that entry and are comparison metrics, not transfer-size claims.

| Surface | Referenced client JS | Chunks |
| --- | ---: | ---: |
| Chat | 692 KB | 20 |
| Settings | 505 KB | 19 |
| Knowledge | 293 KB | 7 |
| Co-Writer | 209 KB | 7 |
| Mastery study | 686 KB | 19 |
| Workspace shell / `UnifiedChatContext` set | 318 KB | 14 |

The existing `npm run perf:check` does not understand the Next.js 16 client-reference manifest. It reads removed `entryJSFiles` data and fails with:

```text
TypeError: Cannot read properties of undefined (reading '[project]/app/layout')
```

This is a baseline tooling defect. No passing route-budget claim is made.

## 4. Check duration baseline

Measured on the same checkout with Node 25.6.0 after `npm ci --legacy-peer-deps`:

| Check | Result | Wall time |
| --- | --- | ---: |
| TypeScript, non-incremental | Pass | 9.95 s |
| Source-only ESLint, quiet | Pass | 16.27 s |
| Node tests | 846 passed | 4.57 s process / 2.02 s test duration |
| Production build | Pass | 20.4 s compile + 7.8 s TypeScript |
| Route budgets | Tool crash | n/a |

`npm ci` reported engine warnings because some dependencies support even-numbered Node releases while the capture environment used Node 25. It also reported 11 dependency audit findings. Neither warning was silently treated as a source-test failure; the supported CI Node version remains the release authority.

## 5. Visual baseline

Twenty-four screenshots are stored in `2026-09-01-frontend-stabilization-v2-baseline-screenshots/`:

- Chat empty, streaming, and retryable-error states;
- Settings;
- Immersive Reading;
- Mastery Path;
- Snow and Dark themes;
- 1440×1000 desktop and 390×844 mobile viewports.

Chat streaming/error screenshots use a deterministic browser-injected WebSocket fixture with the recorded event envelope. Empty, Settings, Reading, and Mastery screenshots use the built frontend without a backend. The resulting Settings load warning and Reading HTTP 500 state are intentionally preserved as part of the error baseline.

Observed interaction problems to preserve as regression targets:

- A retryable `worker_lost` error can coexist with a `Done` stage heading, giving contradictory lifecycle language.
- Streaming status is embedded in message trace presentation rather than exposed as one stable cross-surface state region.
- Settings renders a very long continuous document with weak use of available desktop width.
- Mobile Chat keeps the composer reachable, but lifecycle feedback competes with message content and has no dedicated stable slot.
- Reading has a persistent inline retry affordance, while equivalent lifecycle semantics are not shared with Chat or Mastery.

The deterministic multi-worker backend fixture does not exist yet, so this phase does not claim live reconnect, cross-worker replay, or cancellation-acknowledgement screenshots.

## 6. Reproduction commands

```bash
cd web
npm ci --legacy-peer-deps
npx tsc --noEmit --incremental false
npx eslint app components context features hooks lib tests --quiet
npm run test:node
npm run build
npm run perf:check
```

The lifecycle browser audit is registered under the `critical-turns` Playwright project. It remains explicitly skipped until the deterministic backend fixture is delivered in the multi-worker acceptance phase.

## 7. Post-refactor comparison

The completed frontend pass replaces the obsolete manifest-based bundle estimate with an HTML-entry measurement from a production Next.js server. The two size tables therefore use different methods and must not be interpreted as a byte-for-byte regression chart. The new measurement is reproducible, route-specific, and enforced by `npm run perf:check`.

The final implementation and gate evidence are recorded in [`2026-09-01-frontend-stabilization-v2-acceptance.md`](./2026-09-01-frontend-stabilization-v2-acceptance.md). In particular, the old `/api/v1/chat` browser transport and compatibility surfaces have been removed, route shells now sit behind explicit feature boundaries, and a 500-event selector test proves that streamed content does not rerender the session sidebar.
