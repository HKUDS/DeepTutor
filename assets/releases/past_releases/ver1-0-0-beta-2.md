# DeepTutor v1.0.0-beta.2 Release Notes

**Release Date:** 2026.04.07

## Highlights

### Hot Settings Reload

Model settings changes (API keys, model selection, endpoints) now take effect immediately — no server restart required. The runtime LLM, embedding, and config caches are automatically invalidated after saving via the Settings page or onboarding tour.

### MinerU Nested Output Support

The question extractor now discovers parsed markdown in nested MinerU output directories (e.g. `hybrid_auto/`), fixing cases where MinerU successfully parsed a document but question generation still failed because the markdown was not found.

### Mimic WebSocket Fix

Fixed a `NameError` crash on the `/mimic` WebSocket endpoint caused by missing `sys` and `Path` imports.

### Python 3.11+ Minimum

Dropped Python 3.10 support. The minimum required version is now **Python 3.11**. CI matrix, `pyproject.toml`, and all documentation have been updated accordingly.

### CI & Maintenance

- Removed Dependabot automatic dependency update PRs
- Streamlined CI test matrix to Python 3.11 / 3.12
- Added regression tests for question extractor, mimic WebSocket router, and settings cache invalidation

## Community Contributions

- **@2023Anita** — MinerU nested output fix and Python 3.11 dependency marker (#250, #251)
- **@YizukiAme** — Mimic WebSocket import fix and settings cache invalidation (#253, #254)

**Full Changelog**: https://github.com/HKUDS/DeepTutor/compare/v1.0.0-beta.1...v1.0.0-beta.2
