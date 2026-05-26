"""Document loading for the LlamaIndex RAG pipeline."""

from __future__ import annotations

import base64
import logging
import mimetypes
import re
from pathlib import Path
from typing import Any, Iterable

from llama_index.core import Document
from llama_index.core.schema import ImageNode

from deeptutor.services.embedding import get_embedding_client
from deeptutor.services.llm.client import get_llm_client
from deeptutor.services.rag.file_routing import FileTypeRouter
from deeptutor.utils.document_extractor import DocumentExtractionError, extract_text_from_path
from deeptutor.utils.document_validator import DocumentValidator

IMAGE_DESCRIPTION_SYSTEM_PROMPT = (
    "You describe images for a retrieval-augmented knowledge base. "
    "Be factual, concise, and include any visible text, labels, diagrams, "
    "tables, logos, or important visual relationships. Do not invent details."
)

IMAGE_DESCRIPTION_PROMPT = (
    "Describe this image so that a text-only answer generator can understand "
    "and cite it later. Include visible text/OCR if present, the main subject, "
    "and any educational or technical meaning. Keep the answer under 180 words."
)

# Match Markdown image references: ![alt](path) or ![](path)
_MD_IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
# Max size for embedding referenced images as data URIs
_MAX_EMBED_IMAGE_SIZE = 500 * 1024  # 500 KB


class LlamaIndexDocumentLoader:
    """Convert source files into LlamaIndex ``Document`` objects."""

    def __init__(self, logger=None) -> None:
        self.logger = logger or logging.getLogger(__name__)

    async def load(self, file_paths: Iterable[str]) -> list[Any]:
        documents: list[Any] = []
        classification = FileTypeRouter.classify_files(list(file_paths))

        for file_path_str in classification.parser_files:
            file_path = Path(file_path_str)
            self.logger.info(f"Parsing document: {file_path.name}")
            text = self._extract_parser_text(file_path)
            self._append_if_nonempty(documents, file_path, text)

        for file_path_str in classification.text_files:
            file_path = Path(file_path_str)
            self.logger.info(f"Parsing text: {file_path.name}")
            text = await FileTypeRouter.read_text_file(str(file_path))
            self._append_if_nonempty(documents, file_path, text)

        if classification.image_files:
            image_nodes = await self._load_image_nodes(classification.image_files)
            documents.extend(image_nodes)

        for file_path_str in classification.unsupported:
            self.logger.warning(f"Skipped unsupported file: {Path(file_path_str).name}")

        return documents

    def _extract_parser_text(self, file_path: Path) -> str:
        max_bytes = (
            DocumentValidator.MAX_PDF_SIZE
            if file_path.suffix.lower() == ".pdf"
            else DocumentValidator.MAX_FILE_SIZE
        )
        try:
            return extract_text_from_path(file_path, max_bytes=max_bytes, max_chars=None)
        except (DocumentExtractionError, OSError) as exc:
            self.logger.error(f"Failed to extract {file_path.name}: {exc}")
            return ""

    async def _load_image_nodes(self, file_paths: list[str]) -> list[ImageNode]:
        embedding_client = get_embedding_client()
        llm_client = get_llm_client()

        unsupported_reasons = []
        if not embedding_client.supports_multimodal_contents():
            unsupported_reasons.append(
                "embedding provider/model does not support multimodal contents "
                f"(binding={embedding_client.config.binding}, "
                f"model={embedding_client.config.model})"
            )
        if not llm_client.supports_multimodal_images():
            unsupported_reasons.append(
                "LLM provider/model does not support multimodal image input "
                f"(binding={llm_client.config.binding}, model={llm_client.config.model})"
            )
        if unsupported_reasons:
            reason_text = "; ".join(unsupported_reasons)
            for file_path_str in file_paths:
                self.logger.warning(
                    "Skipped image file because image indexing requires both "
                    f"multimodal embedding and multimodal LLM support; {reason_text}: "
                    f"{Path(file_path_str).name}"
                )
            return []

        paths = [Path(file_path_str) for file_path_str in file_paths]
        embedded_paths: list[Path] = []
        descriptions: list[str] = []
        contents = []
        for path in paths:
            try:
                image_payload = self._load_image_payload(path)
                description = await self._describe_image(
                    path,
                    image_payload["base64"],
                    image_payload["mimetype"],
                )
                if not description:
                    self.logger.warning(
                        "Skipped image file because the configured multimodal LLM "
                        f"returned no description: {path.name}"
                    )
                    continue
                contents.append({"image": image_payload["data_uri"]})
                embedded_paths.append(path)
                descriptions.append(description)
            except OSError as exc:
                self.logger.error(f"Failed to read image {path.name}: {exc}")
            except Exception as exc:
                self.logger.error(
                    "Failed to describe image %s with configured multimodal LLM "
                    "(binding=%s, model=%s): %s",
                    path.name,
                    llm_client.config.binding,
                    llm_client.config.model,
                    exc,
                )

        if not contents:
            return []

        try:
            embeddings = await embedding_client.embed_contents(contents)
        except Exception as exc:
            self.logger.error(
                "Failed to embed image contents with configured multimodal embedding "
                "provider/model (binding=%s, model=%s): %s",
                embedding_client.config.binding,
                embedding_client.config.model,
                exc,
            )
            return []
        nodes: list[ImageNode] = []
        for path, description, embedding in zip(embedded_paths, descriptions, embeddings):
            mimetype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            nodes.append(
                ImageNode(
                    text=f"[Image] {path.name}\n\n{description}",
                    image_path=str(path),
                    image_mimetype=mimetype,
                    metadata={
                        "file_name": path.name,
                        "file_path": str(path),
                        "content_type": "image",
                        "image_description": description,
                    },
                    embedding=embedding,
                )
            )
            self.logger.info(f"Loaded image: {path.name} ({len(embedding)}D vector)")
        return nodes

    async def _describe_image(self, file_path: Path, image_base64: str, mimetype: str) -> str:
        llm_client = get_llm_client()
        response = await llm_client.complete(
            IMAGE_DESCRIPTION_PROMPT,
            system_prompt=IMAGE_DESCRIPTION_SYSTEM_PROMPT,
            image_data=image_base64,
            image_mime_type=mimetype,
            image_filename=file_path.name,
        )
        return response.strip()

    def _load_image_payload(self, file_path: Path) -> dict[str, str]:
        size = file_path.stat().st_size
        if size > DocumentValidator.MAX_FILE_SIZE:
            raise OSError(
                f"image file too large: {size} bytes; "
                f"maximum allowed: {DocumentValidator.MAX_FILE_SIZE} bytes"
            )
        mimetype = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(file_path.read_bytes()).decode("ascii")
        return {
            "base64": encoded,
            "data_uri": f"data:{mimetype};base64,{encoded}",
            "mimetype": mimetype,
        }

    def _resolve_markdown_images(self, text: str, md_file_path: Path) -> str:
        """Resolve local image references in Markdown to inline data URIs.

        Images referenced by URL or data URI are left untouched. Images whose
        resolved path doesn't exist or exceeds the size limit are also kept
        as-is so they may still work at serving time.
        """
        def _replace(m: re.Match) -> str:
            alt_text = m.group(1)
            img_path = m.group(2).strip()
            # Skip external URLs and data URIs
            if img_path.startswith(("http://", "https://", "data:")):
                return m.group(0)
            # Resolve relative to the markdown file's parent directory
            resolved = (md_file_path.parent / img_path).resolve()
            if not resolved.exists() or not resolved.is_file():
                return m.group(0)
            try:
                img_bytes = resolved.read_bytes()
                if len(img_bytes) > _MAX_EMBED_IMAGE_SIZE:
                    self.logger.debug(f"Image too large to embed ({len(img_bytes)}B): {img_path}")
                    return m.group(0)
                mime = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
                b64 = base64.b64encode(img_bytes).decode("ascii")
                self.logger.info(f"Embedded image: {img_path} ({len(img_bytes)}B) as data URI")
                return f"![{alt_text}](data:{mime};base64,{b64})"
            except OSError:
                return m.group(0)

        return _MD_IMAGE_RE.sub(_replace, text)

    def _append_if_nonempty(self, documents: list[Any], file_path: Path, text: str) -> None:
        if text.strip():
            # Preprocess Markdown images if this looks like a Markdown file
            is_markdown = file_path.suffix.lower() in (".md", ".markdown")
            final_text = self._resolve_markdown_images(text, file_path) if is_markdown else text
            documents.append(
                Document(
                    text=final_text,
                    metadata={
                        "file_name": file_path.name,
                        "file_path": str(file_path),
                    },
                )
            )
            self.logger.info(
                f"Loaded: {file_path.name} ({len(final_text)} chars)"
                f"{' (with embedded images)' if is_markdown and final_text != text else ''}"
            )
        else:
            self.logger.warning(f"Skipped empty document: {file_path.name}")
