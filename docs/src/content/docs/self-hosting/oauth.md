---
title: Codex sign-in
description: Sign in to OpenAI Codex with your own ChatGPT plan and confirm the callback.
quadrant: how-to
---

OpenAI Codex sign-in uses your own ChatGPT plan. It does not need `OPENAI_API_KEY`.

## Sign in

1. Open **Settings → Models & services** and add **OpenAI Codex**.
2. Complete the browser sign-in that DeepTutor opens.
3. The provider redirects the browser to `GET /api/auth/openai-codex/callback` with `code` and `state`, or `error` if the provider refused the login.
4. A successful callback page says that authentication was received. Return to DeepTutor.

The model list comes from that account's live catalog. Signing in publishes a profile. The profile becomes the active model only when no LLM is configured yet.

## Where the token lives

Tokens are stored only in `data/system/user-secrets/<owner>/private/openai-codex/`. DeepTutor does not read or modify a `~/.codex` CLI login. A token authorizes one person's plan, so the profile cannot be shared through user grants. Each account, including a non-admin user, signs in for itself. The resulting models, catalog, and sign-out stay on that account.

## Containers

A default local Docker or Podman deployment uses its own loopback network, so the browser callback needs a temporary bridge during sign-in. The exact Docker, Compose, Podman, and teardown commands are in the repository's [containerization guide](https://github.com/HKUDS/DeepTutor/blob/dev/docs-for-dev/CONTAINERIZATION.md#temporary-local-codex-oauth-bridge).
