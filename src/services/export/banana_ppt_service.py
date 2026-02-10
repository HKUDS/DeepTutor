import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

from src.logging import get_logger
from src.services.config import BananaPptImageConfig, get_banana_ppt_config
from src.services.llm import complete as llm_complete
from src.services.llm import get_llm_config, get_token_limit_kwargs

logger = get_logger("BananaPPTService")

_LAYOUTS = {
    "SECTION_HEADER",
    "OVERVIEW",
    "SPLIT_IMAGE_LEFT",
    "SPLIT_IMAGE_RIGHT",
    "TOP_IMAGE",
    "TYPOGRAPHIC_WITH_IMAGE",
    "QUOTE",
    "TYPOGRAPHIC",
    "SPLIT_LEFT",
    "SPLIT_RIGHT",
}


class BananaPptService:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.config = get_banana_ppt_config(project_root)
        self.cache_dir = project_root / "data" / "user" / "ppt_images"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def generate_outline(
        self,
        source_content: str,
        style_prompt: Optional[str] = None,
        max_slides: Optional[int] = None,
    ) -> Dict[str, Any]:
        if not source_content:
            raise ValueError("source_content is empty")

        max_slides = max(1, int(max_slides or self.config.max_slides))
        trimmed_content = self._trim_source(source_content)
        style_prompt = (style_prompt or "").strip()

        system_prompt = (
            "You are a world-class presentation designer and consultant. "
            "Return ONLY valid JSON with keys: title, subtitle, themeColor, accentColor, slides. "
            "slides must be an array of objects with keys: title, points, layout, imagePrompt. "
            "Do not include markdown or commentary."
        )
        user_prompt = (
            f"Create a high-end, professional presentation from the content below.\n\n"
            f"Constraints:\n"
            f"- Maximum slides: {max_slides}\n"
            f"- Generate 7-9 slides for comprehensive coverage\n"
            f"- Keep bullets concise (<= 12 words each)\n"
            f"- Provide themeColor (primary hex) and accentColor (secondary hex) that complement each other\n\n"
            f"Use a VARIETY of creative slide layouts (do not repeat the same layout consecutively):\n"
            f"- SECTION_HEADER: Impactful full-screen transition slide with bold title\n"
            f"- OVERVIEW: Grid-based agenda or summary slide with 4 boxes\n"
            f"- SPLIT_IMAGE_LEFT: Full-height image on left, text on right\n"
            f"- SPLIT_IMAGE_RIGHT: Full-height image on right, text on left\n"
            f"- TOP_IMAGE: Wide banner image at top, text below\n"
            f"- TYPOGRAPHIC_WITH_IMAGE: Design-focused typography with a framed image element\n"
            f"- QUOTE: Large centered impactful quote with decorative marks\n"
            f"- TYPOGRAPHIC: Text-only with vertical accent bar (no image)\n\n"
            f"CRITICAL rules for 'imagePrompt' (follow strictly):\n"
            f"- DO NOT request data charts, graphs, bar charts, pie charts, heat maps, or data visualizations\n"
            f"- DO NOT request flowcharts, timelines, org charts, or diagrams with text labels\n"
            f"- DO NOT include brand logos, company names, or specific product names\n"
            f"- ONLY describe abstract visual metaphors, scenic illustrations, or conceptual imagery\n"
            f"- Example: Instead of 'quarterly sales bar chart', use 'abstract upward arrows symbolizing growth with gradient colors'\n"
            f"- Example: Instead of 'city sales heat map', use 'futuristic cityscape with glowing network connections'\n"
            f"- The AI generates pure visual illustrations WITHOUT any text, numbers, or labels\n"
        )
        if style_prompt:
            user_prompt += f"- Style guidance: {style_prompt}\n"

        user_prompt += f"\nContent:\n{trimmed_content}"

        outline_cfg = self.config.outline
        llm_cfg = get_llm_config()
        model = outline_cfg.model or llm_cfg.model
        api_key = outline_cfg.api_key or llm_cfg.api_key
        base_url = outline_cfg.base_url or llm_cfg.base_url
        binding = outline_cfg.binding or llm_cfg.binding

        if not model:
            raise ValueError("No LLM model configured for outline generation")

        kwargs = {"temperature": outline_cfg.temperature}
        kwargs.update(get_token_limit_kwargs(model, outline_cfg.max_tokens))

        raw = await llm_complete(
            prompt=user_prompt,
            system_prompt=system_prompt,
            model=model,
            api_key=api_key,
            base_url=base_url,
            binding=binding,
            **kwargs,
        )

        data = self._extract_json(raw)
        if not data:
            raise ValueError("Failed to parse outline JSON")

        return self._normalize_outline(data, max_slides)

    async def generate_image(self, prompt: str) -> str:
        prompt = (prompt or "").strip()
        if not prompt:
            return ""

        img_cfg = self.config.image
        if not img_cfg.model or not img_cfg.base_url:
            logger.warning("BananaPPT image config missing model/base_url")
            return ""

        cache_key = self._hash_prompt(prompt, img_cfg)
        cached = self._read_cached_image(cache_key)
        if cached:
            return cached

        if img_cfg.binding == "gemini":
            image_data = self._generate_gemini_image(prompt, img_cfg)
        elif img_cfg.binding == "openai":
            image_data = self._generate_openai_image(prompt, img_cfg)
        else:
            logger.warning(f"Unsupported image binding: {img_cfg.binding}")
            return ""

        if not image_data:
            return ""

        self._write_cached_image(cache_key, image_data)
        return image_data

    def _trim_source(self, source: str, max_chars: int = 16000) -> str:
        cleaned = (source or "").strip()
        if len(cleaned) <= max_chars:
            return cleaned
        return cleaned[:max_chars]

    def _normalize_outline(self, outline: Dict[str, Any], max_slides: int) -> Dict[str, Any]:
        title = str(outline.get("title") or "Presentation")
        subtitle = str(outline.get("subtitle") or "")
        theme_color = self._normalize_hex(outline.get("themeColor"), "#3b82f6")
        accent_color = self._normalize_hex(outline.get("accentColor"), "#f59e0b")

        slides = []
        for slide in outline.get("slides") or []:
            if not isinstance(slide, dict):
                continue
            slide_title = str(slide.get("title") or "Slide")
            points = [str(p) for p in (slide.get("points") or []) if str(p).strip()]
            layout = str(slide.get("layout") or "TYPOGRAPHIC")
            if layout not in _LAYOUTS:
                layout = "TYPOGRAPHIC"
            image_prompt = slide.get("imagePrompt")
            if image_prompt is not None:
                image_prompt = str(image_prompt).strip() or None
            
            # If slide has imagePrompt but layout doesn't support images, upgrade it
            if image_prompt and layout == "TYPOGRAPHIC":
                layout = "TYPOGRAPHIC_WITH_IMAGE"
            
            slides.append(
                {
                    "title": slide_title,
                    "points": points,
                    "layout": layout,
                    "imagePrompt": image_prompt,
                }
            )
            if len(slides) >= max_slides:
                break

        if not slides:
            slides = [{"title": "Overview", "points": [], "layout": "TYPOGRAPHIC"}]

        return {
            "title": title,
            "subtitle": subtitle,
            "themeColor": theme_color,
            "accentColor": accent_color,
            "slides": slides,
        }

    def _normalize_hex(self, value: Any, fallback: str) -> str:
        if not value:
            return fallback
        text = str(value).strip()
        if not text.startswith("#"):
            text = f"#{text}"
        if re.match(r"^#[0-9a-fA-F]{6}$", text):
            return text.lower()
        return fallback

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        match = re.search(r"```json\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except Exception:
                pass

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                return None
        return None

    def _hash_prompt(self, prompt: str, cfg: BananaPptImageConfig) -> str:
        hasher = hashlib.sha256()
        hasher.update(cfg.model.encode("utf-8"))
        hasher.update(b"|")
        hasher.update(cfg.aspect_ratio.encode("utf-8"))
        hasher.update(b"|")
        hasher.update(prompt.encode("utf-8"))
        return hasher.hexdigest()

    def _read_cached_image(self, cache_key: str) -> Optional[str]:
        path = self.cache_dir / f"{cache_key}.png"
        if not path.exists():
            return None
        data = path.read_bytes()
        b64 = base64.b64encode(data).decode("utf-8")
        return f"data:image/png;base64,{b64}"

    def _write_cached_image(self, cache_key: str, data_url: str) -> None:
        try:
            header, b64_data = data_url.split(",", 1)
            if "base64" not in header:
                return
            data = base64.b64decode(b64_data)
            path = self.cache_dir / f"{cache_key}.png"
            path.write_bytes(data)
        except Exception as exc:
            logger.warning(f"Failed to cache image: {exc}")

    def _generate_gemini_image(self, prompt: str, cfg: BananaPptImageConfig) -> Optional[str]:
        url = cfg.base_url.rstrip("/")
        url = f"{url}/models/{cfg.model}:generateContent"
        params = {"key": cfg.api_key} if cfg.api_key else None
        
        # Add constraint to prevent garbled text in generated images
        # Also encourage abstract visual interpretation for data-related requests
        enhanced_prompt = (
            f"Create a professional, artistic illustration for a presentation slide. "
            f"The theme is: {prompt}. "
            f"CRITICAL RULES: "
            f"1. Generate ONLY abstract visual metaphors, NOT literal data charts or graphs. "
            f"2. Do NOT include any text, words, letters, numbers, labels, or typography. "
            f"3. If the theme mentions charts/graphs/data, create abstract visual representations instead "
            f"(e.g., flowing gradients, geometric patterns, upward arrows for growth). "
            f"4. Use professional, modern design aesthetics with smooth gradients and clean shapes. "
            f"5. The image should be purely visual and artistic."
        )
        
        payload = {
            "contents": [{"parts": [{"text": enhanced_prompt}]}],
        }
        try:
            # Increase timeout to 120s for large image generation
            resp = requests.post(url, params=params, json=payload, timeout=120)
            resp.raise_for_status()
            # Log response size for debugging
            resp_size = len(resp.content)
            logger.info(f"Gemini image response received: {resp_size} bytes")
            data = resp.json()
        except Exception as exc:
            error_msg = f"Gemini image request failed: {exc}"
            if 'resp' in locals():
                try:
                    error_msg += f" | Response size: {len(resp.content)} bytes"
                except:
                    pass
            logger.warning(error_msg)
            return None

        image = self._extract_inline_image(data)
        if not image:
            # Log truncated response for debugging (first 500 chars)
            resp_preview = json.dumps(data)[:500]
            logger.warning(f"Gemini image response missing inline data. Response preview: {resp_preview}...")
            return None
        mime, b64 = image
        logger.info(f"Gemini image extracted: mime={mime}, data_length={len(b64)} chars")
        return f"data:{mime};base64,{b64}"

    def _generate_openai_image(self, prompt: str, cfg: BananaPptImageConfig) -> Optional[str]:
        base = cfg.base_url.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        url = f"{base}/images/generations"
        size = "1792x1024" if cfg.aspect_ratio == "16:9" else "1024x1024"
        headers = {"Authorization": f"Bearer {cfg.api_key}"}
        payload = {
            "model": cfg.model,
            "prompt": prompt,
            "size": size,
            "response_format": "b64_json",
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning(f"OpenAI image request failed: {exc}")
            return None

        b64 = None
        if isinstance(data, dict):
            items = data.get("data") or []
            if items and isinstance(items[0], dict):
                b64 = items[0].get("b64_json")
        if not b64:
            logger.warning("OpenAI image response missing b64_json")
            return None
        return f"data:image/png;base64,{b64}"

    def _extract_inline_image(self, data: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        candidates = data.get("candidates") or []
        for candidate in candidates:
            content = candidate.get("content") or {}
            parts = content.get("parts") or []
            for part in parts:
                inline = part.get("inlineData") or part.get("inline_data")
                if not inline:
                    continue
                b64 = inline.get("data")
                if not b64:
                    continue
                mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
                return mime, b64
        return None
