"""
Answer Consolidation - Generate answers from raw search results

Strategies (chosen automatically):
- Provider-specific Jinja2 template when available (serper, jina, serper_scholar)
- Generic fallback template for all other raw-SERP providers
- Optional LLM synthesis when ``use_llm=True``
"""

import logging
from typing import Any

from jinja2 import BaseLoader, Environment

from deeptutor.services.llm import get_llm_client

from .types import WebSearchResponse

_logger = logging.getLogger(__name__)


# =============================================================================
# PROVIDER-SPECIFIC TEMPLATES
# =============================================================================
# Only providers that return raw SERP results (supports_answer=False) need templates.
# AI providers (Perplexity, Tavily, Baidu, Exa) already generate answers.
PROVIDER_TEMPLATES = {
    # -------------------------------------------------------------------------
    # SERPER TEMPLATE
    # -------------------------------------------------------------------------
    "serper": """{% if knowledge_graph %}
## {{ knowledge_graph.title }}{% if knowledge_graph.type %} ({{ knowledge_graph.type }}){% endif %}

{{ knowledge_graph.description }}
{% if knowledge_graph.attributes %}
{% for key, value in knowledge_graph.attributes.items() %}
- **{{ key }}**: {{ value }}
{% endfor %}
{% endif %}
{% if knowledge_graph.website %}🔗 [{{ knowledge_graph.website }}]({{ knowledge_graph.website }}){% endif %}

---
{% endif %}
{% if answer_box %}
### Direct Answer
{{ answer_box.answer or answer_box.snippet }}
{% if answer_box.title %}*Source: [{{ answer_box.title }}]({{ answer_box.link }})*{% endif %}

---
{% endif %}
### Search Results for "{{ query }}"

{% for result in results[:max_results] %}
**[{{ loop.index }}] {{ result.title }}**
{{ result.snippet }}
{% if result.date %}📅 {{ result.date }}{% endif %}
🔗 {{ result.url }}
{% if result.sitelinks %}
  └ Related: {% for link in result.sitelinks[:3] %}[{{ link.title }}]({{ link.link }}){% if not loop.last %} | {% endif %}{% endfor %}
{% endif %}

{% endfor %}
{% if people_also_ask %}
---
### People Also Ask
{% for qa in people_also_ask[:3] %}
**Q: {{ qa.question }}**
{{ qa.snippet }}
*[{{ qa.title }}]({{ qa.link }})*

{% endfor %}
{% endif %}
{% if related_searches %}
---
*Related searches: {% for rs in related_searches[:5] %}{{ rs.query }}{% if not loop.last %}, {% endif %}{% endfor %}*
{% endif %}""",
    # -------------------------------------------------------------------------
    # JINA TEMPLATE
    # -------------------------------------------------------------------------
    "jina": """### Search Results for "{{ query }}"

{% for result in results[:max_results] %}
---
## [{{ loop.index }}] {{ result.title }}

{% if result.attributes.date %}📅 *{{ result.attributes.date }}*{% endif %}

{% if result.content %}
{% if result.snippet %}*{{ result.snippet }}*{% endif %}

### Content Preview
{{ result.content[:2000] }}{% if result.content|length > 2000 %}

*[Content truncated - {{ result.attributes.tokens|default('many') }} tokens total]*{% endif %}
{% else %}
*{{ result.snippet }}*
{% endif %}

🔗 [{{ result.url }}]({{ result.url }})

{% endfor %}
---
*{{ results|length }} results via Jina Reader{% if results and results|length > 0 and not results[0].content %} (no-content mode){% endif %}*

{% if links %}
### Extracted Links
{% for name, url in links.items()[:10] %}
- [{{ name }}]({{ url }})
{% endfor %}
{% endif %}
{% if images %}
### Images Found
{% for alt, src in images.items()[:5] %}
- ![{{ alt }}]({{ src }})
{% endfor %}
{% endif %}""",
    # -------------------------------------------------------------------------
    # SERPER SCHOLAR TEMPLATE
    # -------------------------------------------------------------------------
    "serper_scholar": """### Academic Results for "{{ query }}"

{% for result in results[:max_results] %}
**[{{ loop.index }}] {{ result.title }}**{% if result.attributes.year %} ({{ result.attributes.year }}){% endif %}

{% if result.attributes.publicationInfo %}*{{ result.attributes.publicationInfo }}*{% endif %}

{{ result.snippet }}

{% if result.attributes.pdfUrl %}📄 [PDF]({{ result.attributes.pdfUrl }}) | {% endif %}🔗 [Link]({{ result.url }})
{% if result.attributes.citedBy %}📚 Cited by: {{ result.attributes.citedBy }}{% endif %}

{% endfor %}
---
*{{ results|length }} academic papers found via Google Scholar*""",
}


class AnswerConsolidator:
    """Consolidate raw SERP results into a formatted answer.

    By default, uses Jinja2 templates (provider-specific when available,
    generic fallback otherwise).  Set ``use_llm=True`` to upgrade to
    LLM-based synthesis instead.
    """

    PROVIDER_TEMPLATE_MAP = {
        "serper": "serper",
        "jina": "jina",
        "serper_scholar": "serper_scholar",
        "serply_scholar": "serper_scholar",
    }

    def __init__(
        self,
        *,
        use_llm: bool = False,
        custom_template: str | None = None,
        llm_config: dict[str, Any] | None = None,
        max_results: int = 5,
        autoescape: bool = True,
    ):
        self.use_llm = use_llm
        self.custom_template = custom_template
        self.llm_config = llm_config or {}
        self.max_results = max_results
        self.jinja_env = Environment(loader=BaseLoader(), autoescape=autoescape)  # nosec B701

        if self.custom_template is not None and autoescape:
            _logger.warning(
                "Custom Jinja2 templates are rendered with autoescape=True. "
                "HTML in rendered variables will be escaped by default; use the "
                "'safe' filter in your template if you intentionally need raw HTML."
            )

    def consolidate(self, response: WebSearchResponse) -> WebSearchResponse:
        """Consolidate search results into an answer."""
        results_count = len(response.search_results)

        if self.use_llm:
            _logger.info(f"Consolidating {results_count} results from {response.provider} via LLM")
            response.answer = self._consolidate_with_llm(response)
            _logger.info(f"LLM consolidation completed ({len(response.answer)} chars)")
        else:
            _logger.info(
                f"Consolidating {results_count} results from {response.provider} via template"
            )
            response.answer = self._consolidate_with_template(response)
            _logger.info(f"Template consolidation completed ({len(response.answer)} chars)")

        return response

    def _get_template_for_provider(self, provider: str) -> str | None:
        """Return the best Jinja2 template for *provider*, or ``None``."""
        if self.custom_template:
            _logger.debug(f"Using custom template ({len(self.custom_template)} chars)")
            return self.custom_template

        template_key = self.PROVIDER_TEMPLATE_MAP.get(provider.lower())
        if template_key and template_key in PROVIDER_TEMPLATES:
            _logger.debug(f"Using provider-specific template: {template_key}")
            return PROVIDER_TEMPLATES[template_key]

        _logger.debug(f"No specific template for '{provider}', using generic fallback")
        return None

    def _build_provider_context(self, response: WebSearchResponse) -> dict[str, Any]:
        """
        Build template context with provider-specific fields.

        Each provider has unique response fields that we extract from metadata.
        """
        # Base context (common to all providers)
        context: dict[str, Any] = {
            "query": response.query,
            "provider": response.provider,
            "model": response.model,
            "max_results": self.max_results,
            "results": [
                {
                    "title": r.title,
                    "url": r.url,
                    "snippet": r.snippet,
                    "date": r.date,
                    "source": r.source,
                    "content": r.content,
                    "sitelinks": r.sitelinks,
                    "attributes": r.attributes,
                }
                for r in response.search_results
            ],
            "citations": [
                {
                    "id": c.id,
                    "reference": c.reference,
                    "url": c.url,
                    "title": c.title,
                    "snippet": c.snippet,
                }
                for c in response.citations
            ],
            "timestamp": response.timestamp,
        }

        # Extract provider-specific metadata
        metadata = response.metadata or {}
        provider_lower = response.provider.lower()

        # -----------------------------------------------------------------
        # SERPER-specific context
        # -----------------------------------------------------------------
        if provider_lower == "serper":
            context["knowledge_graph"] = metadata.get("knowledgeGraph")
            context["answer_box"] = metadata.get("answerBox")
            context["people_also_ask"] = metadata.get("peopleAlsoAsk")
            context["related_searches"] = metadata.get("relatedSearches")

        # -----------------------------------------------------------------
        # JINA-specific context
        # -----------------------------------------------------------------
        elif provider_lower == "jina":
            context["links"] = metadata.get("links", {})
            context["images"] = metadata.get("images", {})

        return context

    def _consolidate_with_template(self, response: WebSearchResponse) -> str:
        """Render results using Jinja2 template or fallback to simple formatting"""
        _logger.debug(f"Building template context for {response.provider}")

        # Get template (auto-detect provider-specific if not explicitly set)
        template_str = self._get_template_for_provider(response.provider)

        # Fallback: if no template available, use simple result formatting
        if template_str is None:
            _logger.info(f"Using fallback simple formatting for {response.provider}")
            return self._format_simple_results(response)

        template = self.jinja_env.from_string(template_str)

        # Build context with provider-specific fields
        context = self._build_provider_context(response)
        _logger.debug(
            f"Context has {len(context.get('results', []))} results, {len(context.get('citations', []))} citations"
        )

        try:
            rendered = template.render(**context)
            _logger.debug("Template rendered successfully")
            return rendered
        except Exception as e:
            _logger.error(f"Template rendering failed: {e}")
            raise

    def _consolidate_with_llm(self, response: WebSearchResponse) -> str:
        """Generate answer using LLM."""
        system_prompt, user_prompt = self._build_prompts(response)

        llm = get_llm_client()
        max_tokens = self.llm_config.get("max_tokens", 1000)
        temperature = self.llm_config.get("temperature", 0.3)

        return llm.complete_sync(
            prompt=user_prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    def _build_prompts(self, response: WebSearchResponse) -> tuple[str, str]:
        """Build system and user prompts for LLM consolidation."""
        results_text = []
        for i, r in enumerate(response.search_results[: self.max_results], 1):
            text = f"[{i}] {r.title}\nURL: {r.url}\n"
            if r.snippet:
                text += f"{r.snippet}\n"
            if r.content:
                text += f"{r.content[:5000]}{'...' if len(r.content) > 5000 else ''}"
            results_text.append(text)

        system_prompt = self.llm_config.get(
            "system_prompt",
            """You are a search result consolidator. Your output will be used as grounding context for another LLM.

Task: Extract and structure relevant information from web search results.

Output format:
- Start with a brief factual summary (2-3 sentences)
- List key facts as bullet points with citation numbers [1], [2], etc.
- Include specific data: numbers, dates, names, definitions
- Note any conflicting information between sources
- End with a "Sources:" section listing [n] URL pairs

Be factual and dense. Omit filler words. Prioritize information diversity.""",
        )

        user_prompt = f"""Query: {response.query}

Search Results:
---
{chr(10).join(results_text)}
---

Consolidate these results into structured grounding context."""

        return system_prompt, user_prompt

    def _format_simple_results(self, response: WebSearchResponse) -> str:
        """
        Format search results using a simple, provider-agnostic format.

        This is used as a fallback when no provider-specific template is available.
        """
        lines = [f'### Search Results for "{response.query}"', ""]

        for i, result in enumerate(response.search_results[: self.max_results], 1):
            lines.append(f"**[{i}] {result.title}**")
            if result.snippet:
                lines.append(f"{result.snippet}")
            if result.source:
                lines.append(f"*Source: {result.source}*")
            lines.append(f"🔗 [{result.url}]({result.url})")
            lines.append("")

        if response.search_results:
            lines.append(f"---\n*{len(response.search_results)} results via {response.provider}*")
        else:
            lines.append("*No results found.*")

        return "\n".join(lines)


__all__ = ["AnswerConsolidator", "PROVIDER_TEMPLATES"]
