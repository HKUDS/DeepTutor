# Scientific research workflows

DeepTutor mounts `preprint`, `research_audit` and `research_lit` for scientific
paper requests, paper-search-enabled chat, and Deep Research. They are
context-gated tools; the seven user-toggleable tools remain unchanged.

- `preprint(paper, action="read", pages=[...])` reads the primary arXiv PDF,
  preserves requested versions and legacy archive IDs, records its SHA-256 and
  returns page-level text and original-source links. Downloads are capped at
  32 MiB and PDFs at 500 pages; a pass reads at most 20 pages / 36,000 characters.
  Coverage and missing extractable text are explicit.
- `preprint(..., action="figures")` selects caption-candidate pages unless the
  caller names pages. It renders faithful original pages rather than claiming
  automatic figure crops. At most two images go into request-local model
  context for a vision-capable model; pixels never enter durable tool metadata.
  Links identify the source version and page. Rendering does not prove the
  model actually inspected every image.
- `research_audit(paper, repository, ref="HEAD", files=[...], checks=[...])`
  resolves a GitHub revision to a commit and reads up to eight static files.
  Quote checks require both paper and code quotations to exist in those
  fetched sources. Numeric differences are candidates for semantic review:
  parameter mapping, units, defaults and active paths still matter. The
  Local/admin native reads can use the existing `GITHUB_TOKEN` environment
  credential; other accounts use their own authorized MCP connection rather
  than borrowing a deployment token. Public API rate-limit/access failures
  remain unverified failures. The workflow does not execute downloaded repository code or certify experimental
  reproduction. Use full primary text for equations and methods, and report
  runtime/environment/data checks that remain unverified.
- `research_lit(topic, followups=[...])` searches primary arXiv metadata, with up
  to three explicit follow-up queries, and deduplicates paper identities.
  Its matrix records source, author, evidence level and coverage. Read full
  papers before assigning agreement/disagreement; Deep Research's APPEND queue
  supports recursive investigation of contradictions and evidence gaps.

The report compares claim, method, data, metric, result and limitation with
paper-page and commit-file citations. Author findings, the model's inference,
generated summaries and community annotations remain distinct evidence layers.
Unavailable retrieval is a failure, not an empty set or a verified finding.

## alphaXiv and self-hosted research MCP

The catalog includes the official [alphaXiv MCP endpoint](https://www.alphaxiv.org/docs/mcp)
with OAuth and four research-reading tools: discovery, full-paper text, page
queries and repository files. Library-write tools are not enabled by this
preset. Request `fullText=true` with `get_paper_content` when primary evidence
is needed; its default intermediate report is generated analysis.

Chat and Deep Research use the same account/workspace/partner grant view for
these tools. `preprint(action="mcp", mcp_tool="<qualified name>", arguments={...})`
can invoke an advertised, authorized research-reading operation. A self-hosted
Feynman-style MCP server can expose audit/lit/arxiv/alphaxiv operations or
read-only discussion/annotation operations through this binding.

`preprint(action="discussion")` reads the public alphaXiv paper page and marks
annotation coverage unverified: generated overviews and dynamically omitted
comments must not be presented as the primary paper or a complete discussion
export. The current official MCP documentation does not advertise a dedicated
comments endpoint. If a configured server exposes `get_comments`,
`get_discussions`, `get_annotations` or `get_errata`, that output is explicitly
marked as the community annotation layer; unavailable tools remain unavailable.

## Trusted private MCP origins

An administrator can approve a dedicated remote server origin by setting
`allow_private_network=true` in the admin MCP registry. The editor exposes this
setting; a disabled admin entry may serve as an approval without advertising a
shared tool connection. An account's own server can select the same flag only
when its exact scheme, host and port match a current admin approval.

```json
{
  "servers": {
    "research_origin_approval": {
      "url": "http://research.internal:8080/mcp",
      "allow_private_network": true,
      "enabled": false
    }
  }
}
```

The exception permits only RFC1918 Docker/LAN addresses for that origin.
Self-service loopback, cloud-metadata/link-local addresses and other private
origins remain blocked. DNS and approval are checked at connection/request
boundaries and tool admission; revoking the admin flag blocks a pooled
connection's next call. Self-service redirects remain disabled; shared
transport redirects are checked before connecting to their target. This
setting changes neither `web_fetch` nor native paper/repository downloads.
Legacy administrator-owned local/stdio configurations keep their original
behavior. Native arXiv metadata is paced in-process; provider rate-limit errors
remain visible. See the [arXiv API documentation](https://info.arxiv.org/help/api/user-manual.html).
