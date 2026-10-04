# test: plugins entry-point loader contract tests

Branch: `test/plugins-entrypoint-loader-20261004` (based on `origin/main` @ `ef2d9e5c3`)

## Scope

New file `tests/plugins/test_entrypoint_loader.py` — 13 contract tests pinning the
current behaviour of the entry-point loader stack, as groundwork for upstream
#961 (learning resource providers with lifecycle controls) and #1307 (managed
third-party plugin platform). No product code was modified.

Layers exercised:

- `deeptutor/core/entry_points.py` — shared `load_entry_point_group` plumbing
- `deeptutor/plugins/loader.py` — `discover_plugins` / `load_plugin_capability`
- `deeptutor/runtime/registry/capability_registry.py` — `CapabilityRegistry.load_plugins`

## Path families covered (asserting current real behaviour)

1. **Normal loading** — clean entry points are coerced in order (`load_entry_point_group`);
   class- and instance-yielding plugins produce manifests (`discover_plugins`); the
   canonical `deeptutor.extensions` group registers into the registry.
2. **Missing dependencies** — an entry point raising `ModuleNotFoundError` at load is
   skipped while others load; instantiation via `load_plugin_capability` propagates a
   missing module (discovery isolates, instantiation does not); a legacy manifest whose
   entry cannot import aborts the remaining legacy manifests (logged only at debug).
3. **Load-error isolation** — a raising entry point is skipped with a warning naming the
   group and entry point; a failing group read returns `[]` with a warning; a coercer
   returning `None` rejects without error.
4. **Duplicate registration** — two canonical entry points shipping the same capability
   name keep the first and warn "already registered"; a legacy plugin with a taken name
   is skipped after canonical wins, and legacy-group presence emits a `DeprecationWarning`.
5. **Disable-gating status quo** — `PluginManifest` has no `enabled`/`disabled` field
   (structural fields only), and the only gates are structural (empty entry,
   `tool.py` entry, non-capability `type`) and short-circuit before resolving the entry,
   so a gated manifest never imports its target.

## Commands and results

```
python -m pytest -q -p no:cacheprovider tests/plugins/test_entrypoint_loader.py
→ 13 passed, 1 warning in 0.27s

python -m pytest -q -p no:cacheprovider tests/plugins/
→ 19 passed, 2 warnings in 0.25s   (13 new + 6 pre-existing in test_loader.py)

python -m ruff check tests/plugins/test_entrypoint_loader.py
→ All checks passed!
```

Full verbose run: `pytest-output.txt`.

Environment: Python 3.13.13, pytest 9.1.1, shared repo venv; worktree of
`/Users/Shared/DeepTutor` at `origin/main` (`ef2d9e5c3`, release v1.6.12).
