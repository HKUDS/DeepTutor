from __future__ import annotations

import logging

logger = logging.getLogger("iso_solve.extractor")

EXTRACT_SYSTEM = (
    "You are a precise answer extractor. "
    "Given a problem and a model response, extract only the final answer.\n\n"
    "Rules:\n"
    "- Output only the answer itself.\n"
    "- Do not output explanation or any prefix like 'Answer:'.\n"
    "- If no clear final answer exists, output exactly: NONE"
)

EXTRACT_USER = """\
## Problem
{question}

## Model Response
{model_output}

{extract_hint}

Extract the final answer:"""


async def extract_answer(
    question: str,
    model_output: str,
    extract_hint: str = "",
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    max_tokens: int = 256,
    temperature: float | None = None,
) -> str | None:
    from src.services.llm import complete

    prompt = EXTRACT_USER.format(
        question=question,
        model_output=model_output,
        extract_hint=extract_hint or "",
    )
    kwargs = {
        "prompt": prompt,
        "system_prompt": EXTRACT_SYSTEM,
        "temperature": temperature if temperature is not None else 0.0,
        "max_tokens": max_tokens,
    }
    if model:
        kwargs["model"] = model
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url

    try:
        response = await complete(**kwargs)
        answer = response.strip()
        if not answer or answer.upper() == "NONE":
            return None
        if answer.lower().startswith("answer:"):
            answer = answer.split(":", 1)[1].strip()
        return answer or None
    except Exception as exc:
        logger.warning("LLM extraction failed: %s", exc)
        return None
