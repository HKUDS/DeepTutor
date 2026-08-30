"""Resolved PaddleOCR (飞桨) cloud configuration.

Read-side adapter between the persisted ``document_parsing.json`` settings
(owned by :class:`RuntimeSettingsService`) and the PaddleOCR parser backend in
this package. Mirrors the MinerU resolver shape: the parser code never touches
the storage shape directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from deeptutor.services.config.runtime_settings import load_paddle_settings


class PaddleError(RuntimeError):
    """Raised when a PaddleOCR cloud parse fails (API error, misconfiguration,
    timeout). Carries a user-facing message; the capability layer surfaces it
    as a stream error."""


@dataclass(frozen=True)
class PaddleConfig:
    """Validated PaddleOCR cloud parsing configuration.

    ``api_token`` is the AI Studio access token
    (https://aistudio.baidu.com/account/accessToken, free 20000 pages/day).
    The remaining booleans map to the API ``optionalPayload`` knobs
    (camelCased on the wire by the backend).
    """

    api_token: str = ""
    base_url: str = "https://paddleocr.aistudio-app.com"
    model: str = "PaddleOCR-VL-1.6"
    use_layout_detection: bool = True
    use_chart_recognition: bool = False
    use_ocr_for_image_block: bool = False
    use_doc_orientation_classify: bool = False
    use_doc_unwarping: bool = False
    layout_threshold: float = 0.5
    write_images: bool = True
    request_timeout: float = 120.0
    poll_timeout: float = 600.0

    @property
    def api_keys(self) -> list[str]:
        value = str(self.api_token or "").strip()
        return [value] if value else []

    def optional_payload(self) -> dict:
        """The API ``optionalPayload`` dict (snake_case; backend camelCases it)."""
        return {
            "use_doc_orientation_classify": self.use_doc_orientation_classify,
            "use_doc_unwarping": self.use_doc_unwarping,
            "use_layout_detection": self.use_layout_detection,
            "use_chart_recognition": self.use_chart_recognition,
            "use_ocr_for_image_block": self.use_ocr_for_image_block,
            "layout_threshold": float(self.layout_threshold),
        }


def resolve_paddle_config() -> PaddleConfig:
    """Load the effective PaddleOCR config from ``document_parsing.json``."""
    settings = load_paddle_settings()
    return PaddleConfig(
        api_token=str(settings.get("api_token") or "").strip(),
        base_url=str(settings.get("base_url") or "https://paddleocr.aistudio-app.com").strip(),
        model=str(settings.get("model") or "PaddleOCR-VL-1.6").strip(),
        use_layout_detection=bool(settings.get("use_layout_detection", True)),
        use_chart_recognition=bool(settings.get("use_chart_recognition", False)),
        use_ocr_for_image_block=bool(settings.get("use_ocr_for_image_block", False)),
        use_doc_orientation_classify=bool(settings.get("use_doc_orientation_classify", False)),
        use_doc_unwarping=bool(settings.get("use_doc_unwarping", False)),
        layout_threshold=float(settings.get("layout_threshold", 0.5) or 0.5),
        write_images=bool(settings.get("write_images", True)),
        request_timeout=float(settings.get("request_timeout", 120) or 120),
        poll_timeout=float(settings.get("poll_timeout", 600) or 600),
    )


__all__ = ["PaddleConfig", "PaddleError", "resolve_paddle_config"]
