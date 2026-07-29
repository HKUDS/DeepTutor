# LiteLLM gateway

This directory contains the secret-free proxy config used by
`docker-compose.litellm.yml` and `compose.litellm.yaml`.

The managed PostgreSQL URL is supplied as `LITELLM_DATABASE_URL`. LiteLLM
stores virtual keys, key/user/team spend, budgets and rate-limit state there;
DeepTutor's `data/system/usage.sqlite3` remains the exact token-quota ledger.

After the proxy is healthy, create a virtual key from the proxy network using
the LiteLLM master key. For a user-scoped key, use the DeepTutor user id as
`user_id` and keep the model name at `deeptutor-default`:

```bash
curl -sS -X POST http://litellm:4000/key/generate \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"models":["deeptutor-default"],"user_id":"u_<user-id>","max_budget":1,"budget_duration":"30d"}'
```

Put the returned virtual key in the admin LLM profile, with base URL
`http://litellm:4000/v1` and model `deeptutor-default`. Do not put a master key
in a user grant or browser response.
