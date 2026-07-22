# DeepTutor v1.0.0-beta.4 Release Notes

**Release Date:** 2026.04.10

## Highlights

### Embedding Progress Tracking & Rate Limit Retry
Added real-time embedding progress reporting during knowledge base initialization — the UI now shows `batch N/M complete` as documents are embedded. HTTP 429 (Too Many Requests) responses are automatically retried with exponential back-off, and a configurable `batch_delay` parameter lets free-tier users throttle requests to stay within rate limits. Progress callbacks are properly cleaned up in `finally` blocks to prevent leaking into subsequent search calls.

### Cross-Platform Start Tour Dependency Management
The onboarding start tour now auto-installs bootstrap dependencies (e.g. PyYAML) if missing, and supports system-dependency installation across macOS (Homebrew), Linux (apt/dnf/yum), and Windows (winget/Chocolatey) for Math Animator prerequisites like LaTeX, FFmpeg, Cairo, and CMake. The `typer[all]` dependency was also simplified to `typer` to avoid pulling unnecessary extras.

### Case-Insensitive MIME Validation
Fixed a platform-dependent bug where files with uppercase extensions (e.g. `report.PDF`, `data.JSON`) bypassed MIME type validation on Linux. `mimetypes.guess_type()` now receives the lowercased filename, consistent with the extension whitelist check.

## Community Contributions

- **@oxkage** — Embedding progress tracking and HTTP 429 rate limit retry (#268)
- **@kuishou68** — Case-insensitive MIME type validation fix (#272, closes #271)

**Full Changelog**: https://github.com/HKUDS/DeepTutor/compare/v1.0.0-beta.3...v1.0.0-beta.4
