from __future__ import annotations

import logging
import os
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from .base import BenchmarkAdapter, apply_limit
from benchmark.iso_solve.core.types import Problem

logger = logging.getLogger("iso_solve.aalcr")

AALCR_SYSTEM_PROMPT = (
    "You are an expert analyst. You will be given a set of documents followed by a question. "
    "Read all documents carefully, then answer the question using information from the documents. "
    "Think step by step, synthesizing information across multiple documents as needed. "
    "Finish your response with: FINAL ANSWER: [YOUR ANSWER]"
)

_FINAL_ANSWER_RE = re.compile(r"FINAL\s+ANSWER\s*:\s*(.+)", re.IGNORECASE | re.DOTALL)


def _parse_semicolon_list(value: str) -> list[str]:
    """Parse a semicolon-separated field (AA-LCR uses `;` as delimiter)."""
    if not value or not value.strip():
        return []
    return [v.strip() for v in value.split(";") if v.strip()]


def _extract_documents(data_dir: str) -> str:
    """Extract the AA-LCR zip and return the root directory containing documents.

    Zip structure: lcr/{Category}/{document_set_id}/{filename}.txt
    Returns the path to the 'lcr' directory after extraction.

    Handles encoding: the zip lacks the UTF-8 flag so Python decodes filenames
    as CP437, mangling non-ASCII characters. We re-encode via CP437 and decode
    as UTF-8 (with NFC normalization) to recover correct filenames.
    """
    import unicodedata

    zip_path = os.path.join(data_dir, "extracted_text", "AA-LCR_extracted-text.zip")
    if not os.path.isfile(zip_path):
        raise FileNotFoundError(
            f"Document archive not found at {zip_path}. "
            "Ensure the full dataset was downloaded."
        )

    extract_dir = os.path.join(data_dir, "_extracted")
    lcr_dir = os.path.join(extract_dir, "lcr")
    if os.path.isdir(lcr_dir):
        return lcr_dir

    logger.info("Extracting AA-LCR documents from %s ...", zip_path)
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            try:
                raw_bytes = info.filename.encode("cp437")
                correct_name = unicodedata.normalize("NFC", raw_bytes.decode("utf-8"))
            except (UnicodeDecodeError, UnicodeEncodeError):
                correct_name = info.filename

            out_path = os.path.join(extract_dir, correct_name)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with zf.open(info) as src, open(out_path, "wb") as dst:
                dst.write(src.read())

    logger.info("Extracted to %s", extract_dir)
    return lcr_dir


def _build_file_index(lcr_dir: str) -> dict[str, dict[str, str]]:
    """Build {document_set_id: {filename: abs_path}} index from extracted docs."""
    index: dict[str, dict[str, str]] = defaultdict(dict)
    for category_dir in Path(lcr_dir).iterdir():
        if not category_dir.is_dir():
            continue
        for docset_dir in category_dir.iterdir():
            if not docset_dir.is_dir():
                continue
            ds_id = docset_dir.name
            for fpath in docset_dir.iterdir():
                if fpath.is_file():
                    index[ds_id][fpath.name] = str(fpath)
    return dict(index)


def _resolve_local_paths(
    file_index: dict[str, dict[str, str]],
    document_set_id: str,
    filenames: list[str],
) -> list[str]:
    """Resolve filenames to local paths using the pre-built index."""
    docset_files = file_index.get(document_set_id, {})
    resolved: list[str] = []
    for fname in filenames:
        path = docset_files.get(fname)
        if path:
            resolved.append(path)
        else:
            logger.debug(
                "File '%s' not found in document set '%s'", fname, document_set_id
            )
    return resolved


def _load_document_text(local_paths: list[str]) -> str:
    """Read and concatenate document text from local file paths."""
    parts: list[str] = []
    for path in local_paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            doc_name = os.path.basename(path)
            parts.append(f"=== Document: {doc_name} ===\n{content}")
        except Exception as exc:
            logger.warning("Failed to read document %s: %s", path, exc)
    return "\n\n".join(parts)


class AALCRAdapter(BenchmarkAdapter):
    @property
    def name(self) -> str:
        return "aalcr"

    @property
    def breakdown_keys(self) -> list[str]:
        return ["document_category"]

    @property
    def skip_extract(self) -> bool:
        return True

    @property
    def extract_hint(self) -> str:
        return "Extract the final answer after 'FINAL ANSWER:'. The answer is typically a short phrase, number, or list."

    @property
    def judge_hint(self) -> str:
        return (
            "IMPORTANT GRADING INSTRUCTIONS:\n"
            "1. The candidate response is the FULL model output, not a pre-extracted answer. "
            "Read through the entire response and check whether the key factual content "
            "from the ground-truth answer is present.\n"
            "2. Judge ONLY on substantive content. Abbreviated names, full legal names, and "
            "common short-form variants of the same entity are all equivalent.\n"
            "3. If the ground-truth lists multiple items, the response is CORRECT as long as "
            "it identifies ALL of them, even if surrounded by extra explanation or caveats.\n"
            "4. If the question asks for N items but the ground-truth contains fewer than N, "
            "the response is CORRECT as long as it identifies all items in the ground-truth, "
            "even if it notes that fewer than N exist.\n"
            "5. Ignore differences in punctuation, capitalization, word order, formatting, "
            "and any additional contextual details the response may include.\n"
            "6. When in doubt, lean toward CORRECT if the core factual content matches."
        )

    def load_dataset(self, bench_cfg: dict[str, Any], args: Any) -> list[Problem]:
        import csv

        from huggingface_hub import snapshot_download

        dataset_id = bench_cfg.get("dataset_id", "ArtificialAnalysis/AA-LCR")
        data_dir = snapshot_download(repo_id=dataset_id, repo_type="dataset")

        lcr_dir = _extract_documents(data_dir)
        file_index = _build_file_index(lcr_dir)
        logger.info(
            "Document index: %d document sets, %d total files",
            len(file_index),
            sum(len(v) for v in file_index.values()),
        )

        csv_path = os.path.join(data_dir, "AA-LCR_Dataset.csv")
        if not os.path.isfile(csv_path):
            csv_candidates = list(Path(data_dir).rglob("*.csv"))
            if csv_candidates:
                csv_path = str(csv_candidates[0])
            else:
                raise FileNotFoundError(f"No CSV file found in {data_dir}")

        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        problems: list[Problem] = []
        for row in rows:
            question_id = int(row.get("question_id", 0))
            document_set_id = row.get("document_set_id", "")
            filenames_raw = row.get("data_source_filenames", "")

            filenames = _parse_semicolon_list(filenames_raw)
            local_paths = _resolve_local_paths(file_index, document_set_id, filenames)

            if not local_paths:
                logger.warning(
                    "Question %s (set=%s): no documents resolved (filenames=%s)",
                    question_id,
                    document_set_id,
                    filenames_raw[:120],
                )
            elif len(local_paths) < len(filenames):
                logger.warning(
                    "Question %s (set=%s): only %d/%d documents resolved",
                    question_id,
                    document_set_id,
                    len(local_paths),
                    len(filenames),
                )

            problems.append(
                Problem(
                    id=f"aalcr_{question_id:04d}",
                    question=row["question"],
                    ground_truth=str(row.get("answer", "")),
                    benchmark="aalcr",
                    system_prompt=AALCR_SYSTEM_PROMPT,
                    metadata={
                        "document_category": row.get("document_category", "Unknown"),
                        "document_set_id": document_set_id,
                        "question_id": question_id,
                        "input_tokens": int(row.get("input_tokens", 0)),
                        "local_paths": local_paths,
                    },
                )
            )
        return problems

    def filter_problems(
        self,
        problems: list[Problem],
        bench_cfg: dict[str, Any],
        args: Any,
    ) -> list[Problem]:
        filter_cfg = bench_cfg.get("filter", {})
        categories = getattr(args, "aalcr_categories", None) or filter_cfg.get("categories")
        limit = args.limit or filter_cfg.get("limit")
        seed = getattr(args, "seed", filter_cfg.get("seed", 42))
        sequential = getattr(args, "sequential", False)

        filtered = problems
        if categories:
            cat_set = {c.lower() for c in categories}
            filtered = [
                p for p in filtered
                if str(p.metadata.get("document_category", "")).lower() in cat_set
            ]
        return apply_limit(filtered, limit, seed, sequential)

    def _load_docs_for_problem(self, problem: Problem) -> str:
        local_paths = problem.metadata.get("local_paths", [])
        if not local_paths:
            return ""
        return _load_document_text(local_paths)

    def build_direct_request(self, problem: Problem, multimodal: bool = True) -> dict[str, Any]:  # noqa: ARG002
        doc_text = self._load_docs_for_problem(problem)
        if doc_text:
            user_content = f"{doc_text}\n\n---\n\nQuestion: {problem.question}"
        else:
            user_content = problem.question
        return {
            "messages": [
                {"role": "system", "content": problem.system_prompt},
                {"role": "user", "content": user_content},
            ]
        }

    def build_pipeline_request(self, problem: Problem, multimodal: bool = True) -> dict[str, Any]:  # noqa: ARG002
        doc_text = self._load_docs_for_problem(problem)
        if doc_text:
            prompt = f"{doc_text}\n\n---\n\nQuestion: {problem.question}"
        else:
            prompt = problem.question
        return {"prompt": prompt, "image_url": None}

    def extract_fallback(self, model_output: str) -> str | None:
        matches = _FINAL_ANSWER_RE.findall(model_output)
        if matches:
            ans = matches[-1].strip()
            return ans.split("\n")[0].strip() if ans else None
        text = model_output.strip()
        return text.splitlines()[-1].strip() if text else None

    def judge_fallback(self, problem: Problem, extracted: str | None) -> tuple[bool, str]:
        if extracted is None:
            return False, "No extracted answer"
        pred = extracted.strip().lower()
        gold = problem.ground_truth.strip().lower()
        if pred == gold:
            return True, "exact match"
        if gold in pred or pred in gold:
            return True, "substring match fallback"
        return False, "no match fallback"

    def preview(self, problem: Problem) -> str:
        n_docs = len(problem.metadata.get("local_paths", []))
        tokens = problem.metadata.get("input_tokens", "?")
        return (
            f"id={problem.id} "
            f"category={problem.metadata.get('document_category', '?')} "
            f"docs={n_docs} tokens={tokens} "
            f"question={problem.question[:100]}"
        )
