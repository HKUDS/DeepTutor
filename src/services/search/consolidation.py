# -*- coding: utf-8 -*-
"""
Answer Consolidation - Generate answers from raw search results

Supports two strategies:
1. template: Fast Jinja2 template rendering
2. llm: LLM-based answer synthesis (uses project's LLM config from env vars)
"""

from typing import Any

from jinja2 import BaseLoader, Environment

from src.logging import get_logger
from src.services.llm import get_llm_client

from .types import WebSearchResponse

# Module logger
_logger = get_logger("Search.Consolidation", level="INFO")


# Available consolidation types
CONSOLIDATION_TYPES = ["none", "template", "llm"]


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
    """
    Consolidate raw SERP results into formatted answers.

    IMPORTANT: Template consolidation only works for providers that have
    specific templates defined (serper, jina, serper_scholar).

    For other providers, use:
    - consolidation_type="llm" for LLM-based synthesis
    - custom_template for a custom Jinja2 template
    """

    # Map provider names to their specific templates
    # Only these providers support template consolidation
    PROVIDER_TEMPLATE_MAP = {
        "serper": "serper",
        "jina": "jina",
        "serper_scholar": "serper_scholar",
    }

    def __init__(
        self,
        consolidation_type: str = "template",
        custom_template: str | None = None,
        llm_config: dict[str, Any] | None = None,
        max_results: int = 5,
        autoescape: bool = True,
    ):
        """
        Initialize consolidator.

        Args:
            consolidation_type: "none", "template", or "llm"
            custom_template: Custom Jinja2 template string
            llm_config: Optional overrides (system_prompt, max_tokens, temperature)
            max_results: Maximum results to include in answer
            autoescape: Whether to enable Jinja2 autoescape for security (default: True)
        """
        self.consolidation_type = consolidation_type
        self.custom_template = custom_template
        self.llm_config = llm_config or {}
        self.max_results = max_results
        # Security: autoescape defaults to True (set in function signature above).
        # When True, Jinja2 auto-escapes HTML to prevent XSS.
        self.jinja_env = Environment(loader=BaseLoader(), autoescape=autoescape)  # nosec B701

        if self.custom_template is not None and autoescape:
            _logger.warning(
                "Custom Jinja2 templates are rendered with autoescape=True. "
                "HTML in rendered variables will be escaped by default; use the "
                "'safe' filter in your template if you intentionally need raw HTML."
            )

    def consolidate(self, response: WebSearchResponse) -> WebSearchResponse:
        """
        Consolidate search results into an answer.

        Args:
            response: WebSearchResponse with search_results populated

        Returns:
            WebSearchResponse with answer field populated
        """
        if self.consolidation_type == "none":
            _logger.debug("Consolidation disabled, returning raw response")
            return response

        results_count = len(response.search_results)
        _logger.info(
            f"Consolidating {results_count} results from {response.provider} using {self.consolidation_type}"
        )

        if self.consolidation_type == "template":
            response.answer = self._consolidate_with_template(response)
            _logger.success(f"Template consolidation completed ({len(response.answer)} chars)")
        elif self.consolidation_type == "llm":
            response.answer = self._consolidate_with_llm(response)
            _logger.success(f"LLM consolidation completed ({len(response.answer)} chars)")
        else:
            _logger.error(f"Unknown consolidation type: {self.consolidation_type}")
            raise ValueError(f"Unknown consolidation type: {self.consolidation_type}")

        return response

    def _get_template_for_provider(self, provider: str) -> str:
        """
        Get the template for a specific provider.

        Only provider-specific templates exist because each provider has
        different response schemas and metadata. No universal templates.

        Args:
            provider: Provider name (e.g., "serper", "jina")

        Returns:
            Template string for this provider

        Raises:
            ValueError: If no template exists for this provider
        """
        # 1. Custom template takes highest priority
        if self.custom_template:
            _logger.debug(f"Using custom template ({len(self.custom_template)} chars)")
            return self.custom_template

        # 2. Get provider-specific template
        template_key = self.PROVIDER_TEMPLATE_MAP.get(provider.lower())
        if template_key and template_key in PROVIDER_TEMPLATES:
            _logger.debug(f"Using provider-specific template: {template_key}")
            return PROVIDER_TEMPLATES[template_key]

        # 3. No template exists for this provider - fail explicitly
        available = list(PROVIDER_TEMPLATES.keys())
        _logger.error(f"No template for provider '{provider}'. Available: {available}")
        raise ValueError(
            f"No template consolidation available for provider '{provider}'. "
            f"Template consolidation only works with: {available}. "
            f"Use consolidation='llm' or provide a custom_template for other providers."
        )

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
        """Render results using Jinja2 template"""
        _logger.debug(f"Building template context for {response.provider}")

        # Get template (auto-detect provider-specific if not explicitly set)
        template_str = self._get_template_for_provider(response.provider)
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


__all__ = ["AnswerConsolidator", "CONSOLIDATION_TYPES", "PROVIDER_TEMPLATES"]
