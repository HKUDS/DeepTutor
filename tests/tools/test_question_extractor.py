from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import types


def _load_question_extractor_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "deeptutor"
        / "tools"
        / "question"
        / "question_extractor.py"
    )

    stubbed_modules = {
        "deeptutor.services.config": {"get_agent_params": lambda *_args, **_kwargs: {}},
        "deeptutor.services.llm": {"complete": lambda *_args, **_kwargs: None},
        "deeptutor.services.llm.capabilities": {
            "supports_response_format": lambda *_args, **_kwargs: False
        },
        "deeptutor.services.llm.config": {"get_llm_config": lambda: None},
        "deeptutor.utils.json_parser": {"parse_json_response": lambda *_args, **_kwargs: {}},
    }

    original_modules: dict[str, types.ModuleType | None] = {}
    for module_name, attributes in stubbed_modules.items():
        original_modules[module_name] = sys.modules.get(module_name)
        module = types.ModuleType(module_name)
        for attr_name, value in attributes.items():
            setattr(module, attr_name, value)
        sys.modules[module_name] = module

    try:
        spec = importlib.util.spec_from_file_location("question_extractor_under_test", module_path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for module_name, original_module in original_modules.items():
            if original_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original_module


def test_load_parsed_paper_supports_nested_hybrid_auto_output(tmp_path: Path) -> None:
    question_extractor = _load_question_extractor_module()
    paper_dir = tmp_path / "mimic_exam"
    parsed_dir = paper_dir / "hybrid_auto"
    images_dir = parsed_dir / "images"
    images_dir.mkdir(parents=True)

    markdown_path = parsed_dir / "exam.md"
    markdown_path.write_text("# Exam content", encoding="utf-8")

    content_list_path = parsed_dir / "exam_content_list.json"
    content_list_path.write_text(
        json.dumps([{"type": "text", "text": "Question 1"}], ensure_ascii=False),
        encoding="utf-8",
    )

    (images_dir / "figure.png").write_text("image-bytes", encoding="utf-8")

    markdown_content, content_list, discovered_images_dir = question_extractor.load_parsed_paper(
        paper_dir
    )

    assert markdown_content == "# Exam content"
    assert content_list == [{"type": "text", "text": "Question 1"}]
    assert discovered_images_dir == images_dir


def _load_module_with(complete_result, agent_params):
    """Load question_extractor with stubbed services for the given completion."""
    module_path = (
        Path(__file__).resolve().parents[2]
        / "deeptutor"
        / "tools"
        / "question"
        / "question_extractor.py"
    )

    async def _complete(*_args, **_kwargs):
        return complete_result

    stubbed_modules = {
        "deeptutor.services.config": {"get_agent_params": lambda *_a, **_k: agent_params},
        "deeptutor.services.llm": {"complete": _complete},
        "deeptutor.services.llm.capabilities": {
            "supports_response_format": lambda *_a, **_k: False
        },
        "deeptutor.services.llm.config": {"get_llm_config": lambda: None},
        "deeptutor.utils.json_parser": {"parse_json_response": lambda *_a, **_k: {}},
    }

    original_modules: dict[str, types.ModuleType | None] = {}
    for module_name, attributes in stubbed_modules.items():
        original_modules[module_name] = sys.modules.get(module_name)
        module = types.ModuleType(module_name)
        for attr_name, value in attributes.items():
            setattr(module, attr_name, value)
        sys.modules[module_name] = module

    try:
        spec = importlib.util.spec_from_file_location("question_extractor_under_test", module_path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for module_name, original_module in original_modules.items():
            if original_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original_module


def test_none_llm_response_raises_valueerror_not_typeerror(tmp_path: Path) -> None:
    import pytest

    module = _load_module_with(None, {"temperature": 0.0, "max_tokens": 16})
    with pytest.raises(ValueError):
        module.extract_questions_with_llm(
            "# Exam", None, tmp_path, "key", "https://example/v1", "model", binding="openai"
        )
