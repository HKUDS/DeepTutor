"""Regression tests for MinerU content_list text that PDF indexing keeps."""

from pathlib import Path
from types import SimpleNamespace

from llama_index.core.node_parser import SentenceSplitter
import pymupdf

from deeptutor.services.rag.source_pages import build_pdf_documents


def _pdf(path: Path, lines: list[str]) -> None:
    pdf = pymupdf.open()
    for line in lines:
        page = pdf.new_page(width=300, height=200)
        page.insert_text((12, 36), line)
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.save(path)
    pdf.close()


def _parsed(blocks: list[dict[str, object]]) -> SimpleNamespace:
    return SimpleNamespace(
        blocks=blocks,
        markdown="Unlocated markdown must not replace located pages.",
        engine="mineru",
        parser_signature="mineru-test",
    )


def test_reference_lists_are_indexed_and_page_furniture_is_not(tmp_path: Path) -> None:
    raw = tmp_path / "kb" / "raw"
    path = raw / "attention.pdf"
    _pdf(
        path,
        [
            "Attention is all you need.",
            "Native references page.",
            "Only in the text layer.",
        ],
    )
    documents = build_pdf_documents(
        path,
        _parsed(
            [
                {"type": "text", "text": "Attention is all you need.", "page_idx": 0},
                {"type": "header", "text": "Proceedings of NIPS 2017", "page_idx": 0},
                {"type": "page_header", "text": "Running header", "page_idx": 0},
                {"type": "page_number", "text": "11", "page_idx": 0},
                {"type": "aside_text", "text": "Margin note stays.", "page_idx": 0},
                {"type": "page_footnote", "text": "Corresponding author.", "page_idx": 0},
                {
                    "type": "list",
                    "sub_type": "text",
                    "list_items": ["Encoder stack", "Decoder stack"],
                    "page_idx": 0,
                },
                {
                    "type": "list",
                    "sub_type": "ref_text",
                    "list_items": [
                        "[1] Vaswani et al. Attention Is All You Need. 2017.",
                        "[2] Bahdanau et al. Neural Machine Translation. 2015.",
                    ],
                    "page_idx": 1,
                },
                {"type": "footer", "text": "Accepted as a poster.", "page_idx": 1},
                {"type": "page_footer", "text": "Version footer", "page_idx": 1},
                {"type": "Page_Number", "text": "12", "page_idx": 1},
                {
                    "type": "table",
                    "table_body": "<table><tr><td>BLEU</td></tr></table>",
                    "table_caption": ["Table 1: scores"],
                    "table_footnote": ["Higher is better."],
                    "page_idx": 1,
                },
                {
                    "type": "image",
                    "image_caption": ["Figure 1: the model."],
                    "page_idx": 1,
                },
            ]
        ),
        raw.parent,
    )

    by_page = {
        doc.metadata["page_index"]: doc.text for doc in documents if "page_index" in doc.metadata
    }
    assert "Attention is all you need." in by_page[0]
    assert "Encoder stack" in by_page[0]
    assert "Decoder stack" in by_page[0]
    assert "Margin note stays." in by_page[0]
    assert "Corresponding author." in by_page[0]
    assert "Proceedings of NIPS 2017" not in by_page[0]
    assert "Running header" not in by_page[0]
    assert "11" not in by_page[0]

    assert "[1] Vaswani et al. Attention Is All You Need. 2017." in by_page[1]
    assert "[2] Bahdanau et al. Neural Machine Translation. 2015." in by_page[1]
    assert "BLEU" in by_page[1]
    assert "Table 1: scores" in by_page[1]
    assert "Higher is better." in by_page[1]
    assert "Figure 1: the model." in by_page[1]
    assert "Accepted as a poster." not in by_page[1]
    assert "Version footer" not in by_page[1]
    assert "12" not in by_page[1]

    assert "Only in the text layer." in by_page[2]
    assert not any(doc.metadata.get("page_status") == "unlocated" for doc in documents)
    joined = "\n".join(doc.text for doc in documents)
    assert "Proceedings of NIPS 2017" not in joined
    assert "Unlocated markdown must not replace located pages." not in joined

    nodes = SentenceSplitter(chunk_size=512, chunk_overlap=50).get_nodes_from_documents(documents)
    contents = [node.get_content().strip() for node in nodes]
    assert any("Vaswani" in content for content in contents)
    assert not any(content.isdigit() for content in contents)


def test_page_number_block_does_not_return_through_the_text_layer(tmp_path: Path) -> None:
    raw = tmp_path / "kb" / "raw"
    path = raw / "blank.pdf"
    _pdf(path, ["11"])
    parsed = _parsed([{"type": "page_number", "text": "11", "page_idx": 0}])
    parsed.markdown = ""
    documents = build_pdf_documents(path, parsed, raw.parent)
    assert [doc.metadata.get("page_index") for doc in documents] == [0]
    assert documents[0].text != "11"
    assert documents[0].metadata["page_status"] == "needs_ocr"
    nodes = SentenceSplitter(chunk_size=512, chunk_overlap=50).get_nodes_from_documents(documents)
    assert not any(node.get_content().strip().isdigit() for node in nodes)


def test_image_block_without_caption_still_uses_native_page_text(tmp_path: Path) -> None:
    raw = tmp_path / "kb" / "raw"
    path = raw / "figure.pdf"
    _pdf(path, ["Caption in the text layer."])
    parsed = _parsed([{"type": "image", "img_path": "images/fig.png", "page_idx": 0}])
    parsed.markdown = ""
    documents = build_pdf_documents(path, parsed, raw.parent)
    assert documents[0].text == "Caption in the text layer."
    assert documents[0].metadata["page_status"] == "searchable"


def test_reference_list_without_page_index_is_still_indexed(tmp_path: Path) -> None:
    raw = tmp_path / "kb" / "raw"
    path = raw / "notes.pdf"
    _pdf(path, ["Native page."])
    documents = build_pdf_documents(
        path,
        _parsed(
            [
                {
                    "type": "list",
                    "sub_type": "ref_text",
                    "list_items": ["[9] Devlin et al. BERT. 2019."],
                },
                {"type": "page_number", "text": "4"},
            ]
        ),
        raw.parent,
    )
    unlocated = [doc.text for doc in documents if doc.metadata.get("page_status") == "unlocated"]
    assert unlocated == ["[9] Devlin et al. BERT. 2019."]
    assert all("4" != doc.text.strip() for doc in documents)
    assert not any(doc.text.strip().isdigit() for doc in documents)
