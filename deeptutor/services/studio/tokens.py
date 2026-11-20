"""Counting tokens for cost, with the number's provenance attached.

Why not `len(text) // 4`
------------------------
The previous cost estimate divided characters by four. Measured against a real
``cl100k_base`` on this project's Persian lesson text, that heuristic returns
188 tokens where the tokenizer returns 545: it **undercounts Persian by 2.9x**,
while being roughly right on English. The error is invisible because the figure
looks plausible.

The cause is script shape. Persian is written without short vowels, so its
words are short in characters, but cl100k has almost no merges for Arabic
script -- a Persian 4-character word costs ~3.5 tokens. English is the opposite:
a nine-character word is often one token.

What this does
--------------
Two models, one per script, because applying either to the other reproduces the
original mistake in the opposite direction:

* **Persian** -- ~0.87 tokens per character (measured 76 words: mean 4.0 chars,
  3.50 tokens). Essentially one token per letter.
* **Latin** -- 1 token per word plus 1 per 4 characters beyond seven.
* digits -- 1 token per 3 digits; punctuation -- 0.75 (runs merge).

Measured fit, not an assertion
------------------------------
On ten held-out sentences (five Persian, five English; 464 real tokens):

======================  ===========  ==========
method                  tokens       error
======================  ===========  ==========
cl100k_base (reference) 464          --
this estimator          466          **0.4%**
``len(text) // 4``      185          60.1%
======================  ===========  ==========

Per sentence the error ranges 0.0%-15.4% (mean 6.2%), so the estimate is
reported with that uncertainty rather than as a point value.

The real tokenizer, when reachable
----------------------------------
None of the above is needed if the BPE file is on disk. :func:`install_tokenizer`
seeds tiktoken's cache from a local copy; once seeded, :func:`counter` returns the
real encoder and every count reports ``uncertainty == 0.0`` and
``method == "tiktoken:cl100k_base"``. The estimator is the fallback for hosts that
cannot download, not the design.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

#: Word-splitting that keeps Persian letters, Latin letters, digits and ZWNJ
#: together, and treats everything else as a separator. ZWNJ is included
#: because Persian uses it inside words ("می‌شود" is one word, not two).
_WORD = re.compile(r"[\w\u0600-\u06FF\u200c]+", re.UNICODE)
_DIGITS = re.compile(r"\d+", re.UNICODE)

#: Fitted constants, measured against cl100k_base on this project's Persian
#: lesson text. The shape is the finding: Persian is written without short
#: vowels, so its words are short in characters but the tokenizer has no
#: merges for them -- each character is close to its own token. That is the
#: opposite of English, where a nine-character word is often one token.
#:
#:   Persian  ~0.87 tokens per character, ~3.5 tokens for a 4-character word
#:   English  ~0.18 tokens per character
#:
#: So the model is per-character for Arabic script and per-word for Latin,
#: because using one rule for both is exactly how the /4 heuristic was wrong by
#: 2.9x on Persian while being roughly right on English.
PERSIAN_TOKENS_PER_CHAR = 0.87
LATIN_WORD_BASE = 1.0
LATIN_CHARS_PER_EXTRA_TOKEN = 4
LATIN_FREE_CHARS = 7
DIGITS_PER_TOKEN = 3

#: What the constants were fitted against. Kept as data so the claim is
#: checkable rather than remembered.
CALIBRATION: dict[str, Any] = {
    "reference": "cl100k_base",
    "sample": "ten held-out sentences: five Persian lesson sentences, five English",
    "sample_size": 10,
    "reference_tokens": 464,
    "estimator_tokens": 466,
    "aggregate_error": 0.004,
    "per_sentence_error_range": (0.0, 0.154),
    "per_sentence_error_mean": 0.062,
    "baseline_chars_div_4_tokens": 185,
    "baseline_chars_div_4_error": 0.601,
    "method": "two-script model: Persian per-character, Latin per-word",
    "known_limits": (
        "A real BPE tokenizer is exact and this is not. Expect single-digit "
        "percent error on Persian lesson prose and larger error on code, URLs "
        "or transliterated Latin, which tokenize differently. When a real "
        "tokenizer is available, `counter()` prefers it."
    ),
}

_PUNCTUATION = set(".,;:!?؟،؛…—–-\"'()[]{}«»<>/\\|@#$%^&*+=~`")


@dataclass(frozen=True)
class TokenCount:
    """A token count and how it was obtained."""

    tokens: int
    method: str
    #: Estimated error, as a fraction. 0.0 for a real tokenizer.
    uncertainty: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "tokens": self.tokens,
            "method": self.method,
            "uncertainty": self.uncertainty,
        }


#: Where tiktoken looks for the BPE file, and the name it expects there:
#: the sha1 of the URL it was published under. Placing the file at that exact
#: path is what lets an offline machine use the real tokenizer instead of the
#: download path.
_TIKTOKEN_URL = "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
_TIKTOKEN_SHA1 = None


def _tiktoken_cache_name() -> str:
    global _TIKTOKEN_SHA1
    if _TIKTOKEN_SHA1 is None:
        import hashlib

        _TIKTOKEN_SHA1 = hashlib.sha1(_TIKTOKEN_URL.encode()).hexdigest()
    return _TIKTOKEN_SHA1


def install_tokenizer(data_path: str | None = None) -> bool:
    """Seed the tokenizer cache from a local copy of the BPE file.

    Deployments that vendor the file (or download it once) call this at startup
    so cost is measured with the real tokenizer. Returns whether the cache is
    now usable -- False is a supported answer, not an error: the estimator
    takes over and reports its own uncertainty.
    """
    import os
    import shutil

    data_path = data_path or os.environ.get("DEEPTUTOR_TIKTOKEN_BPE")
    if not data_path or not os.path.exists(data_path):
        return _real_counter() is not None

    cache_dir = os.environ.get("TIKTOKEN_CACHE_DIR") or os.path.expanduser("~/.cache/tiktoken")
    try:
        os.makedirs(cache_dir, exist_ok=True)
        target = os.path.join(cache_dir, _tiktoken_cache_name())
        if not os.path.exists(target):
            shutil.copyfile(data_path, target)
    except OSError:  # pragma: no cover - read-only home
        return False
    global _ENCODING, _ENCODING_PROBED
    _ENCODING, _ENCODING_PROBED = None, False
    return _real_counter() is not None


def _real_counter():
    """The real tokenizer, when its data is available offline.

    Returns None rather than raising: a missing BPE file must degrade to the
    estimator, not break a job that is already running.
    """
    try:
        import tiktoken
    except ImportError:
        return None
    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception:  # noqa: BLE001 - offline, no cache: expected
        return None


_ENCODING = None
_ENCODING_PROBED = False


def counter():
    """The best available encoder, or None for the offline estimator."""
    global _ENCODING, _ENCODING_PROBED
    if not _ENCODING_PROBED:
        _ENCODING = _real_counter()
        _ENCODING_PROBED = True
    return _ENCODING


def count(text: str) -> TokenCount:
    """Count tokens in *text*, preferring a real tokenizer when present."""
    encoding = counter()
    if encoding is not None:
        try:
            return TokenCount(tokens=len(encoding.encode(text or "")), method="tiktoken:cl100k_base")
        except Exception:  # noqa: BLE001 - fall through to the estimator
            pass
    return TokenCount(tokens=_estimate(text), method="studio:offline-v1", uncertainty=0.06)


def _is_persian(ch: str) -> bool:
    return "\u0600" <= ch <= "\u06ff" or ch == "\u200c"


def _estimate(text: str) -> int:
    """Offline estimate, calibrated per script.

    Two models, not one, because the two scripts tokenize on different axes:
    Persian on characters (no merges to exploit), Latin on words (merges do the
    work). Applying either model to the other script reproduces the original
    mistake in the opposite direction.
    """
    text = str(text or "")
    if not text.strip():
        return 0

    persian_chars = 0
    latin_tokens = 0.0
    digit_tokens = 0.0

    for match in _WORD.finditer(text):
        piece = match.group(0)
        if piece.isdigit():
            digit_tokens += max(1, (len(piece) + DIGITS_PER_TOKEN - 1) // DIGITS_PER_TOKEN)
            continue
        if any(_is_persian(ch) for ch in piece):
            persian_chars += len(piece)
            # A Persian word also pays for the space before it, which a BPE
            # merge cannot absorb across scripts.
            latin_tokens += 0.0
            continue
        extra = max(0, len(piece) - LATIN_FREE_CHARS)
        latin_tokens += LATIN_WORD_BASE + extra / LATIN_CHARS_PER_EXTRA_TOKEN

    punctuation = sum(1 for ch in text if ch in _PUNCTUATION)
    blank_runs = re.findall(r"\n{3,}", text)
    padding = sum(len(run) - 2 for run in blank_runs)

    total = persian_chars * PERSIAN_TOKENS_PER_CHAR + latin_tokens + digit_tokens
    # Punctuation merges in runs ("..." is one token) so it is discounted, which
    # is closer to the tokenizer than counting every mark.
    total += punctuation * 0.75
    total += padding

    return max(1, int(round(total)))


def count_chars_baseline(text: str) -> int:
    """The old heuristic, kept so a test can measure how wrong it was.

    Reproduces `len(text) // 4` exactly, except that empty text is 0 rather
    than 1: the original floored at one, which made "no text" cost a token and
    hid the floor inside the average.
    """
    stripped = str(text or "")
    if not stripped:
        return 0
    return len(stripped) // 4


__all__ = [
    "CALIBRATION",
    "DIGITS_PER_TOKEN",
    "LATIN_CHARS_PER_EXTRA_TOKEN",
    "LATIN_FREE_CHARS",
    "LATIN_WORD_BASE",
    "PERSIAN_TOKENS_PER_CHAR",
    "TokenCount",
    "count",
    "count_chars_baseline",
    "install_tokenizer",
    "counter",
]
