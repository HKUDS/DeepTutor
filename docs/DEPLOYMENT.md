# Production docs deployment

`docs.deeptutor.info` serves the Astro/Starlight static build through Cloudflare Workers Static Assets. GitHub Pages serves pull request and fork previews through [the docs workflow](../.github/workflows/docs.yml).

## Build a release

Use Node.js 22 and run these commands from the repository root. Build from the release tag, with the production origin and root base.

```bash
(
  set -e
  python3 -X utf8 docs/scripts/check_docs.py
  cd docs
  npm ci
  DOCS_SITE=https://docs.deeptutor.info DOCS_BASE=/ DOCS_NOINDEX=0 \
    ASTRO_TELEMETRY_DISABLED=1 npm run build
  cd ..
  DOCS_BASE=/ python3 -X utf8 docs/scripts/check_docs.py dist
)
```

Astro writes the English and Chinese pages and their assets to `docs/dist/`.

## Wrangler configuration and credentials

The production workflow and Wrangler configuration are proposed. Before the first deployment from this repository, copy the production Worker's current settings to `docs/wrangler.toml`. The file needs the existing Worker's `name` and `compatibility_date`, plus `[assets]` with `directory = "./dist"`. Confirm the current custom domain and routing settings in Cloudflare before the first deploy. Use the same exact Wrangler version locally and in CI.

| Environment variable | Purpose |
| --- | --- |
| `CLOUDFLARE_API_TOKEN` | Deploy and roll back Workers in the production Cloudflare account. Store it in the GitHub production environment for CD. |
| `CLOUDFLARE_ACCOUNT_ID` | Selects the account that owns the production Worker. |

## Deploy and verify

With the confirmed production configuration and credentials, switch to `docs/` and set `WRANGLER_VERSION` to the exact version agreed for production.

```bash
npx --yes --package="wrangler@${WRANGLER_VERSION:?Set the approved Wrangler version}" \
  wrangler deployments list --config wrangler.toml
```

Record the active Worker version ID before deploying.

```bash
npx --yes --package="wrangler@${WRANGLER_VERSION:?Set the approved Wrangler version}" \
  wrangler deploy --config wrangler.toml
```

Record the release tag and the new Worker version ID. Open the English and Chinese home pages, then check a documentation page and its images or styles.

For automatic production deployment, publish a release from a tag that contains the docs and the planned `docs-cd.yml`. Add the workflow to the default branch before using `workflow_dispatch` for docs-only fixes. See [GitHub Actions workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#release). PR checks and previews continue to use `docs.yml` without Cloudflare credentials.

## Roll back

Restore the recorded previous Worker version in the Cloudflare dashboard, or run the following from `docs/` with the production credentials. Set `PREVIOUS_VERSION_ID` to the known-good Worker version.

```bash
npx --yes --package="wrangler@${WRANGLER_VERSION:?Set the approved Wrangler version}" \
  wrangler rollback "${PREVIOUS_VERSION_ID:?Set the known-good Worker version}" --config wrangler.toml
```

Verify both locales and reload a documentation page to check its assets. If Cloudflare no longer retains the version, rebuild from the last known-good tag and deploy that build using the confirmed production settings.

See the Cloudflare [Static Assets configuration](https://developers.cloudflare.com/workers/static-assets/binding/) and [Workers rollback procedure](https://developers.cloudflare.com/workers/versions-and-deployments/rollbacks/).
