# DeepTutor v1.1.0-beta Release Notes

**Release Date:** 2026.04.14

## Highlights

### URL-based Chat Routing
Migrated the chat experience from query-parameter session IDs (`/?session=xxx`) to a dedicated `/chat/[[...sessionId]]` catch-all route. The root page now redirects to `/chat`, and session loading is driven entirely by the URL path — no more `sessionStorage` restore on mount. Sidebar navigation, new-chat, and session-select flows all point to `/chat` or `/chat/<id>`, making sessions bookmarkable and shareable.

### Snow Theme
Added a new **Snow** theme — a clean, pure-white palette with slate-blue accents and subtle warm primary tones. The theme cycle is now snow → light → dark → glass. The ThemeScript, settings page, i18n keys, and CSS variables all include the new option.

### WebSocket Heartbeat & Auto-Reconnect
The `UnifiedWSClient` now sends a client-side heartbeat ping every 30 seconds and treats 45 seconds of silence as a dead connection. On unexpected disconnection, the client retries with exponential backoff (200 ms base, up to 5 attempts) and sends a `resume_from` message with the last `turn_id` / `seq` so the server can replay missed events.

### Streaming Idle Timeout
`UnifiedChatContext` runs a background timer that detects streaming sessions with no incoming events for 60 seconds. Stale sessions are automatically failed with a user-visible timeout error and their WebSocket runners are cleaned up.

### ChatComposer Performance Optimization
Wrapped `ChatComposer` in `React.memo` and internalized `input`, `showAtPopup`, and `textareaRef` state. The textarea value and auto-resize layout effect no longer trigger parent re-renders, eliminating severe input lag in long conversations.

### Embedding Provider Registry Overhaul
Replaced the flat `EMBEDDING_PROVIDER_DEFAULTS` dictionary with a typed `EmbeddingProviderSpec` dataclass carrying `label`, `default_api_base`, `adapter`, `default_model`, and `default_dim`. The settings API now returns a dedicated embedding provider dropdown (separate from the LLM list), and selecting a provider auto-fills the default embedding dimension.

### Serper Search Provider
Restored **Serper** as a first-class search provider (previously deprecated). Added `SERPER_API_KEY` env fallback, registered the provider module, and updated all deprecation messages.

### Deep Research Reporting Resilience
Section writing in the reporting agent now falls back to raw LLM output when JSON parsing fails, instead of aborting the entire report. The fallback strips JSON wrappers from the response and logs a warning.

### Markdown Renderer Code Block Fix
Fixed inline vs. block code detection in `SimpleMarkdownRenderer`. Multi-line content now renders inside a styled `<pre>` block, while single-line code renders as an inline `<code>` element — resolving cases where inline backticks produced full code blocks.

### Ollama Embedding Response Support
The OpenAI-compatible embedding adapter now handles Ollama's singular `"embedding"` key (flat vector), in addition to the existing `"data"` / `"embeddings"` response shapes.

### Launcher `.env.local` Auto-Generation
`start_web.py` and `start_tour.py` now write `web/.env.local` with the resolved backend port, so the frontend picks up the correct `NEXT_PUBLIC_API_BASE` even when started independently via `npm run dev`.

### Test Suite Expansion
Added 11 new test modules covering `UnifiedContext`, `StreamBus`, `ChatOrchestrator`, `ContextBuilder`, `TurnRuntime`, `RAGTool`, `WebSearch`, `CircuitBreaker`, `JSONParser`, `EmbeddingExtraction`, and a shared `conftest.py` with common fixtures.

### Input Lag Fix
Resolved severe keystroke lag in long conversations by virtualizing the message list rendering and debouncing scroll-position updates.

## Community Contributions

- **@pietrondo** — Use `npm.cmd` on Windows for proper npm command execution (#309)
- **@markjanzer** — Prefer unresolved `sys.executable` to stay inside venv (#310)
- **@OldSuns** — Pass `extra_headers` to `llm_complete` in config test runner (#307)
- **@srinivasrk** — Lower `oauth-cli-kit` version constraint to match available releases (#315)
- **@Jah-yee** — Fix typo: Chinses → Chinese (#320)

**Full Changelog**: https://github.com/HKUDS/DeepTutor/compare/v1.0.3...v1.1.0-beta
