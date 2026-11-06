"""Generate a synthetic protocol fixture using published DocVortex renderers.

Only pure Python schema/render modules are loaded from the verified wheel.
This does not run a document parser or a model and does not install DocVortex.
"""

from __future__ import annotations

import base64
from hashlib import sha256
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType

ROOT = Path(__file__).resolve().parent
WHEEL = Path(sys.argv[1]).resolve()
TARGET = ROOT


def namespace(name: str) -> None:
    """Avoid importing unrelated native document analyzers from package init."""
    module = ModuleType(name)
    module.__path__ = [str(WHEEL) + "/" + name.replace(".", "/")]
    sys.modules[name] = module


def main() -> None:
    for name in (
        "docvortex",
        "docvortex.foundation",
        "docvortex.render",
        "docvortex.render._internal",
        "docvortex.render._internal.structured_content",
        "docvortex.render._internal.markdown",
    ):
        namespace(name)
    schema = importlib.import_module("docvortex.schema")
    render = importlib.import_module("docvortex.render.structured_content")
    markdown = importlib.import_module("docvortex.render.markdown")
    bbox = [0.05, 0.10, 0.85, 0.40]
    raw = {
        "schema": "docvortex.middle",
        "schema_version": "2.0",
        "metadata": {
            "file_suffix": "pdf",
            "producer": {"name": "synthetic-contract-fixture", "version": "1"},
            "document": {"page_count": 1},
        },
        "is_full_document": True,
        "pages": [
            {
                "page_idx": 0,
                "blocks": [
                    {
                        "type": "text",
                        "index": 0,
                        "bbox": bbox,
                        "content": [{"type": "text", "content": "Synthetic source evidence."}],
                    },
                    {"type": "equation", "index": 1, "bbox": bbox, "content": "E=mc^2"},
                    {
                        "type": "table",
                        "index": 2,
                        "bbox": bbox,
                        "content": [
                            {
                                "type": "table_body",
                                "index": 2,
                                "content": "<table><tr><td>A</td><td>B</td></tr></table>",
                            }
                        ],
                    },
                    {
                        "type": "image",
                        "index": 3,
                        "bbox": bbox,
                        "content": [
                            {
                                "type": "image_body",
                                "index": 3,
                                "content": "",
                                "image_path": "images/figure.png",
                            },
                            {
                                "type": "image_caption",
                                "content": [
                                    {"type": "text", "content": "Synthetic reference diagram"}
                                ],
                            },
                        ],
                    },
                ],
            }
        ],
    }
    model = schema.MiddleJson.from_dict(raw)
    TARGET.mkdir(parents=True, exist_ok=True)
    for name, value in {
        "middle_json.json": model.to_dict(),
        "structured_content.json": render.render_structured_content(model),
    }.items():
        (TARGET / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    (TARGET / "markdown.md").write_text(markdown.render_markdown(model) + "\n", encoding="utf-8")
    (TARGET / "images").mkdir(exist_ok=True)
    (TARGET / "images/figure.png").write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
    )
    provenance = {
        "kind": "synthetic contract fixture; not output of a model-backed MinerU parse",
        "mineru_release": "4.1.3",
        "docvortex_release": "0.6.8",
        "docvortex_wheel_filename": WHEEL.name,
        "docvortex_wheel_sha256": sha256(WHEEL.read_bytes()).hexdigest(),
        "schema_source": "docvortex/schema.py:MiddleJson",
        "renderer_sources": [
            "docvortex/render/structured_content.py",
            "docvortex/render/markdown.py",
        ],
        "bundle_source": "mineru/parser/base.py:ParseResult.save and mineru/kit/common.py:save_parse_result",
        "generator": "generate.py",
    }
    (TARGET / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Published schema and renderers generated {TARGET}")


if __name__ == "__main__":
    main()
