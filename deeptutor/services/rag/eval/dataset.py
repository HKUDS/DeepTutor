"""QA-set schema for knowledge-base retrieval evaluation.

An evaluation set is a list of cases; each case pairs one natural-language
query with the source passages an ideal retrieval should return for it. The
passages ("gold") are verbatim excerpts of the indexed documents, so a case
stays meaningful across re-indexing, re-embedding, and engine changes — a chunk
identifier does not survive an index rebuild, but document text does.

Two on-disk shapes are supported:

* ``.jsonl`` / ``.ndjson`` — one case object per line (recommended: a long set
  stays reviewable in a diff);
* ``.json`` — either a bare list of cases or ``{"name": ..., "cases": [...]}``.

Case fields:

* ``query`` (required) — the question or phrase handed to retrieval.
* ``gold`` (required) — one excerpt or a list of excerpts that should be
  retrieved. A single string is accepted as a one-passage list.
* ``id`` (optional) — a stable label used in reports; defaults to ``q1``, ``q2``…
* ``notes`` (optional) — free text carried through to the report.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

JSONL_SUFFIXES = frozenset({".jsonl", ".ndjson"})


class EvalDatasetError(ValueError):
    """Raised when an evaluation set cannot be read or is structurally invalid."""


class EvalCase(BaseModel):
    """One query with the gold passages that should be retrieved for it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str
    gold: list[str] = Field(min_length=1)
    id: str = ""
    notes: str = ""

    @field_validator("query")
    @classmethod
    def _require_query(cls, value: str) -> str:
        """Reject a blank query — there is nothing to retrieve for it."""
        text = (value or "").strip()
        if not text:
            raise ValueError("query must be a non-empty string")
        return text

    @field_validator("gold", mode="before")
    @classmethod
    def _coerce_gold(cls, value: Any) -> Any:
        """Accept a single excerpt string as a one-passage gold list."""
        if isinstance(value, str):
            return [value]
        return value

    @field_validator("gold")
    @classmethod
    def _require_gold(cls, value: list[str]) -> list[str]:
        """Reject an empty or blank gold list — matching would be meaningless."""
        passages = [(item or "").strip() for item in value]
        if not passages or any(not passage for passage in passages):
            raise ValueError("gold must hold at least one non-empty passage")
        return passages

    @field_validator("id", "notes", mode="before")
    @classmethod
    def _coerce_text(cls, value: Any) -> str:
        """Treat a missing/null label or note as an empty string."""
        return "" if value is None else str(value).strip()


class EvalDataset(BaseModel):
    """A named collection of evaluation cases."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = "eval-set"
    cases: list[EvalCase] = Field(min_length=1)
    source: str = ""

    def __len__(self) -> int:
        """Number of cases in the set."""
        return len(self.cases)

    def iter_cases(self) -> Iterator[EvalCase]:
        """Iterate the cases in file order."""
        return iter(self.cases)

    def limited(self, limit: int | None) -> EvalDataset:
        """Return a copy holding at most ``limit`` cases (``None`` keeps all)."""
        if limit is None or limit >= len(self.cases):
            return self
        return self.model_copy(update={"cases": self.cases[: max(0, limit)]})

    @classmethod
    def from_cases(cls, cases: Sequence[EvalCase | dict], *, name: str = "eval-set") -> EvalDataset:
        """Build a dataset programmatically (used by tests and scripts)."""
        return cls(name=name, cases=[_coerce_case(case, index) for index, case in enumerate(cases)])


def _coerce_case(case: EvalCase | dict, index: int) -> EvalCase:
    """Validate one in-memory case, filling in a default id."""
    if isinstance(case, EvalCase):
        return case if case.id else case.model_copy(update={"id": f"q{index + 1}"})
    validated = EvalCase.model_validate(case)
    return validated if validated.id else validated.model_copy(update={"id": f"q{index + 1}"})


def _first_error(exc: ValidationError) -> str:
    """Flatten a pydantic error into one readable line."""
    error = exc.errors()[0]
    location = ".".join(str(part) for part in error.get("loc", ())) or "case"
    return f"{location}: {error.get('msg', 'invalid value')}"


def _case_context(raw: Any) -> str:
    """A short excerpt of the offending case, to make errors actionable."""
    if isinstance(raw, dict):
        query = raw.get("query")
        if isinstance(query, str) and query.strip():
            return f" (query: {query.strip()[:48]!r})"
    return ""


def _build_case(raw: Any, index: int, path: Path) -> EvalCase:
    """Validate one raw case object, raising with file/line context."""
    if not isinstance(raw, dict):
        raise EvalDatasetError(
            f"{path}: case #{index + 1} must be a JSON object, got {type(raw).__name__}."
        )
    try:
        case = EvalCase.model_validate(raw)
    except ValidationError as exc:
        raise EvalDatasetError(
            f"{path}: case #{index + 1}{_case_context(raw)} is invalid — {_first_error(exc)}"
        ) from exc
    return case if case.id else case.model_copy(update={"id": f"q{index + 1}"})


def _parse_jsonl(text: str, path: Path) -> list[Any]:
    """Parse one case object per non-blank line, reporting the failing line."""
    cases: list[Any] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise EvalDatasetError(
                f"{path}: line {line_number} is not valid JSON — {exc.msg}"
            ) from exc
    return cases


def _parse_json(text: str, path: Path) -> tuple[list[Any], str]:
    """Parse either a bare case list or an object with ``name`` and ``cases``."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EvalDatasetError(f"{path}: is not valid JSON — {exc.msg}") from exc
    if isinstance(payload, list):
        return payload, ""
    if isinstance(payload, dict):
        cases = payload.get("cases")
        if not isinstance(cases, list):
            raise EvalDatasetError(f"{path}: object form must hold a 'cases' list.")
        name = payload.get("name")
        return cases, str(name).strip() if isinstance(name, str) else ""
    raise EvalDatasetError(f"{path}: must hold a list of cases or an object with 'cases'.")


def _reject_duplicate_ids(cases: Sequence[EvalCase], path: Path) -> None:
    """Fail on repeated case ids so report rows cannot be ambiguous."""
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            raise EvalDatasetError(f"{path}: duplicate case id {case.id!r}.")
        seen.add(case.id)


def load_dataset(path: str | Path, *, name: str = "") -> EvalDataset:
    """Read an evaluation set from ``path``.

    Args:
        path: A ``.jsonl``, ``.ndjson`` or ``.json`` file.
        name: Overrides the set name; defaults to the file's ``name`` field,
            then to the file stem.

    Returns:
        The parsed, validated dataset.

    Raises:
        EvalDatasetError: The file is missing, unreadable, of an unsupported
            format, empty, or holds an invalid or duplicated case.
    """
    target = Path(path).expanduser()
    if not target.exists():
        raise EvalDatasetError(f"Evaluation set not found: {target}")
    if target.is_dir():
        raise EvalDatasetError(f"Evaluation set must be a file, not a directory: {target}")

    suffix = target.suffix.lower()
    if suffix not in JSONL_SUFFIXES and suffix != ".json":
        raise EvalDatasetError(
            f"Unsupported evaluation set format {target.suffix!r}; use .jsonl or .json."
        )

    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvalDatasetError(f"Could not read {target}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise EvalDatasetError(f"{target} is not UTF-8 text: {exc}") from exc

    if suffix in JSONL_SUFFIXES:
        raw_cases, set_name = _parse_jsonl(text, target), ""
    else:
        raw_cases, set_name = _parse_json(text, target)

    if not raw_cases:
        raise EvalDatasetError(f"Evaluation set {target} holds no cases.")

    cases = [_build_case(raw, index, target) for index, raw in enumerate(raw_cases)]
    _reject_duplicate_ids(cases, target)
    return EvalDataset(name=name or set_name or target.stem, cases=cases, source=str(target))


__all__ = [
    "EvalCase",
    "EvalDataset",
    "EvalDatasetError",
    "JSONL_SUFFIXES",
    "load_dataset",
]
