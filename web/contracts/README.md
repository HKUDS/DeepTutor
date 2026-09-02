# Generated frontend contracts

The backend owns the wire contract. Do not edit files under `schema/` or
`generated/` by hand.

From the repository root, refresh both layers after a backend contract change:

```bash
python scripts/export_frontend_contracts.py
cd web && npm run contracts:generate
```

CI runs `python scripts/export_frontend_contracts.py --check` in backend contract
tests and `npm run contracts:check` before frontend typechecking. A drift failure
means the committed artifacts must be regenerated with the commands above.
