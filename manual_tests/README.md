# Manual Source Ingest Checks

This folder contains manual verification scripts for source ingest behavior.

## Purpose

- Script type: manual integration check for source URL ingest/data pipeline behavior
- CI policy: not part of CI blocking checks
- Scope: ad-hoc debugging and demo-stage verification only

## How To Run

From repository root:

```bash
python manual_tests/source_ingest_check.py
```

## Ownership

- Current status: maintenance handed over to the professional QA/testing team
- Development team usage: optional, only when local troubleshooting is needed
