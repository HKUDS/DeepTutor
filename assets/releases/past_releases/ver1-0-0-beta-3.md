# DeepTutor v1.0.0-beta.3 Release Notes

**Release Date:** 2026.04.08

## Highlights

### Remove LiteLLM Dependency
Replaced the `litellm` abstraction layer with native `openai` and `anthropic` SDKs across both the services and TutorBot layers. Added a new `OpenAICompatProvider` (covering OpenAI, DeepSeek, Mistral, StepFun, XiaoMi-MiMo, Qianfan, oVMS, and more) and a dedicated `AnthropicProvider`. The settings UI now includes a provider dropdown with auto base-URL filling. Auto-fallback to streaming is triggered when tool-call format errors occur (fixes #265).

### Windows Math Animator Compatibility

Fixed `SelectorEventLoop` incompatibility on Windows by replacing `asyncio.create_subprocess_exec` with `subprocess.Popen` + reader threads + `asyncio.Queue`, preserving real-time line-by-line progress output. Also applied `ProactorEventLoop` policy for subprocess support on Windows.

### Robust JSON Parsing for LLM Outputs

Seven agent modules (planner, idea, design, note, reporting, citation, data structures) now use `parse_json_response()` instead of raw `json.loads()`, correctly handling LLM responses wrapped in markdown code fences. A `_UNSET` sentinel was introduced for the fallback parameter so callers can explicitly request `None` as the failure value.

### Guided Learning Fixes

- Fixed KaTeX math rendering by configuring `$...$` and `$$...$$` delimiters, removing broken SRI integrity hashes, and adding parent-window fallback rendering for bare LaTeX text nodes.
- Fixed backend poll (`fetchPageStatuses`) overwriting user's tab navigation by only accepting `current_index` when the user hasn't navigated yet.
- Increased guide agent `max_tokens` from 8192 to 16384 to prevent HTML truncation.

### Full Internationalization

Completed i18n coverage for the web UI — all hardcoded strings across workspace, utility, sidebar, and component pages are now translation-keyed with full English and Chinese locale files.

## Community Contributions

- **@kevinmw** — Windows Math Animator renderer fix, Guided Learning KaTeX rendering & polling fix (#256, #266)
- **@LocNguyenSGU** — GitHub Copilot provider login docs (#262)
- **@kagura-agent** — `parse_json_response` for LLM outputs to handle markdown fences

**Full Changelog**: https://github.com/HKUDS/DeepTutor/compare/v1.0.0-beta.2...v1.0.0-beta.3
