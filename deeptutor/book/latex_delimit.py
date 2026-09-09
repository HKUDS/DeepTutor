"""Bare-LaTeX delimiter completion for textbook prose (P5).

Textbook imports (MinerU OCR → verbatim reading blocks) frequently leave math
commands undelimited inside Chinese prose — ``\\overrightarrow{OA}``,
``\\lambda``, ``x^2`` sitting next to 中文 with no ``$...$`` / ``\\(...\\)``
wrapper. The frontend KaTeX chain (rehype-katex + ``web/lib/latex.ts``) is
complete but only renders *delimited* math, so bare commands leak through as
raw text.

``delimit_bare_latex`` finds such fragments and wraps each in ``$...$``:

* ``\\command{arg}{arg}`` arg chains (``\\overrightarrow{OA}``, ``\\frac{a}{b}``)
* whitelisted solo math commands (``\\lambda``, ``\\alpha``, ``\\pi`` …)
* short sub/superscript forms (``x^2``, ``a_1``) — deliberately conservative

False-positive defenses (误判防线):

* command whitelist (教材常见数学命令集) — anything unlisted is untouched
* minimum command length (``MIN_CMD_LEN``)
* 中文紧邻判定 — a chunk qualifies only when it contains Chinese text, so
  English sentences, URLs and code are untouched by construction
* already-delimited math ($$..$$, $..$, ``\\(..\\)``, ``\\[..\\]``), fenced and
  inline code, and markdown links/images are protected verbatim

The same function runs at two points: the canonicalize/pages-import hook
(new books are correct from day one) and this module's CLI, which walks an
existing book's reading blocks in place::

    python -m deeptutor.book.latex_delimit <book_id> [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ── Whitelist (误判防线 #1) ──────────────────────────────────────────────────

#: Commands that take one or two ``{...}`` argument groups.
ARG_COMMANDS = frozenset(
    {
        "overrightarrow",
        "overleftarrow",
        "overline",
        "underline",
        "overbrace",
        "underbrace",
        "vec",
        "hat",
        "bar",
        "tilde",
        "widehat",
        "widetilde",
        "dot",
        "ddot",
        "mathbf",
        "mathrm",
        "mathit",
        "mathcal",
        "boldsymbol",
        "text",
        "operatorname",
        "frac",
        "dfrac",
        "tfrac",
        "cfrac",
        "binom",
        "dbinom",
        "sqrt",
        "substack",
    }
)

#: Solo math commands — Greek letters and common operators/relations.
SOLO_COMMANDS = frozenset(
    {
        # Greek
        "alpha",
        "beta",
        "gamma",
        "delta",
        "epsilon",
        "varepsilon",
        "zeta",
        "eta",
        "theta",
        "vartheta",
        "iota",
        "kappa",
        "lambda",
        "mu",
        "nu",
        "xi",
        "omicron",
        "pi",
        "varpi",
        "rho",
        "varrho",
        "sigma",
        "varsigma",
        "tau",
        "upsilon",
        "phi",
        "varphi",
        "chi",
        "psi",
        "omega",
        "Gamma",
        "Delta",
        "Theta",
        "Lambda",
        "Xi",
        "Pi",
        "Sigma",
        "Upsilon",
        "Phi",
        "Psi",
        "Omega",
        # Operators / relations / misc math
        "pm",
        "mp",
        "times",
        "div",
        "cdot",
        "ast",
        "oplus",
        "ominus",
        "otimes",
        "oslash",
        "odot",
        "circ",
        "bullet",
        "star",
        "leq",
        "le",
        "geq",
        "ge",
        "neq",
        "ne",
        "equiv",
        "approx",
        "simeq",
        "sim",
        "propto",
        "cong",
        "perp",
        "parallel",
        "angle",
        "measuredangle",
        "infty",
        "in",
        "notin",
        "ni",
        "subset",
        "subseteq",
        "supset",
        "supseteq",
        "cup",
        "cap",
        "emptyset",
        "varnothing",
        "nabla",
        "partial",
        "forall",
        "exists",
        "nexists",
        "neg",
        "land",
        "lor",
        "therefore",
        "because",
        "mapsto",
        "to",
        "gets",
        "leftarrow",
        "rightarrow",
        "leftrightarrow",
        "Leftarrow",
        "Rightarrow",
        "Leftrightarrow",
        "uparrow",
        "downarrow",
        "Uparrow",
        "Downarrow",
        "ldots",
        "cdots",
        "dots",
        "ddots",
        "vdots",
        "triangle",
        "square",
        "degree",
        "prime",
        "sum",
        "prod",
        "coprod",
        "int",
        "iint",
        "iiint",
        "oint",
        "bigcup",
        "bigcap",
        "bigoplus",
        "bigotimes",
        "lim",
        "max",
        "min",
        "sin",
        "cos",
        "tan",
        "cot",
        "sec",
        "csc",
        "arcsin",
        "arccos",
        "arctan",
        "log",
        "ln",
        "lg",
        "exp",
        "deg",
    }
)

#: Minimum length of a bare command name (防线 #2) — ``\\pi`` passes, ``\\x`` doesn't.
MIN_CMD_LEN = 2

COMMANDS = frozenset(c for c in ARG_COMMANDS | SOLO_COMMANDS if len(c) >= MIN_CMD_LEN)

# ── Regexes ─────────────────────────────────────────────────────────────────

# CJK ideographs + CJK punctuation + fullwidth forms.
_CJK = "一-鿿　-〿＀-￯"
CJK_RE = re.compile(f"[{_CJK}]")
_LATIN = "0-9A-Za-z"

_BRACE_GROUP = r"\{[^{}]*\}"

# \command + optional 1-2 brace args (\frac{a}{b}) + any ^/_ sub-sup chain.
_FRAG_CMD = "|".join(sorted(COMMANDS, key=len, reverse=True))
_FRAG_ARGS = rf"(?:\s*{_BRACE_GROUP}){{1,2}}"
_FRAG_SUBS = rf"(?:[\^_](?:{_BRACE_GROUP}|[{_LATIN}]))*"
FRAGMENT_RE = re.compile(rf"\\(?:{_FRAG_CMD})(?:{_FRAG_ARGS})?{_FRAG_SUBS}")

# Bare sub/superscript: single letter base + short exponent (x^2, a_1, x^{n}).
SUBSUP_RE = re.compile(
    rf"(?<![{_LATIN}$\\])(?P<frag>[A-Za-z][\^_](?:{_BRACE_GROUP}|[{_LATIN}]{{1,3}}))"
)

# Punctuation that may sit between a formula and Chinese prose without
# breaking the fragment (math operators, halfwidth brackets).
_MATH_ADJACENT = "=+-*/<>:([{'\""


def _has_cjk(text: str) -> bool:
    return CJK_RE.search(text) is not None


def _left_ok(chunk: str, start: int) -> bool:
    """True when the char before *start* can open a math fragment."""
    if start == 0:
        return True
    prev = chunk[start - 1]
    # Only an escaped/delimiter context blocks; whitespace and punctuation
    # before a formula are routine in OCR'd Chinese prose.
    return prev not in "\\$"


def _right_ok(chunk: str, end: int) -> bool:
    """True when the char after *end* can close a math fragment."""
    if end >= len(chunk):
        return True
    nxt = chunk[end]
    if nxt == "\\" and FRAGMENT_RE.match(chunk, end):
        # Adjacent command chain: \\lambda\\overrightarrow{OA} is one formula.
        return True
    # A trailing latin letter means the "command" is really part of a word
    # (e.g. \\text inside \\textbf) — not a standalone formula.
    return not (nxt.isalpha() or nxt in "\\$")


def _wrap_commands(chunk: str) -> str:
    """Wrap whitelisted bare ``\\command`` fragments in ``$...$``."""
    out: list[str] = []
    pos = 0
    for m in FRAGMENT_RE.finditer(chunk):
        if not _left_ok(chunk, m.start()) or not _right_ok(chunk, m.end()):
            continue
        out.append(chunk[pos : m.start()])
        out.append(f"${m.group(0)}$")
        pos = m.end()
    out.append(chunk[pos:])
    return "".join(out)


def _adjacent_cjk(chunk: str, pos: int, step: int) -> bool:
    """CJK directly at *pos*, allowing one OCR-typical space before it.

    ``step`` is +1 (look right from a fragment end) or -1 (look left from a
    fragment start); a space between the fragment and the Chinese char is
    tolerated because MinerU frequently inserts one.
    """
    j = pos
    if 0 <= j < len(chunk) and chunk[j] == " ":
        j += step
    return 0 <= j < len(chunk) and CJK_RE.match(chunk[j]) is not None


def _wrap_subsup(chunk: str) -> str:
    """Wrap bare ``x^2`` / ``a_1`` forms — 中文紧邻 on at least one side."""
    out: list[str] = []
    pos = 0
    for m in SUBSUP_RE.finditer(chunk):
        start, end = m.span("frag")
        left_cjk = _adjacent_cjk(chunk, start - 1, -1)
        right_cjk = _adjacent_cjk(chunk, end, 1)
        # 谨慎: require Chinese adjacency (direct or across one space) on one
        # side, so "x^2 and y_1 are variables" in English prose never qualifies.
        if not (left_cjk or right_cjk):
            continue
        if not _right_ok(chunk, end):
            continue
        out.append(chunk[pos:start])
        out.append(f"${m.group('frag')}$")
        pos = end
    out.append(chunk[pos:])
    return "".join(out)


# ── Segment scanner: protect code / math / markdown syntax ─────────────────

_MD_LINK_RE = re.compile(r"!?\[[^\]]*\]\([^)\s]*\)")
_BARE_URL_RE = re.compile(r"https?://\S+")


def _segments(text: str) -> list[tuple[str, bool]]:
    """Split *text* into (chunk, protected) segments, left to right.

    Protected segments are emitted verbatim; plain segments carry the prose
    that may contain bare LaTeX.
    """
    out: list[tuple[str, bool]] = []
    plain: list[str] = []
    i = 0
    n = len(text)

    def flush_plain() -> None:
        if plain:
            out.append(("".join(plain), False))
            plain.clear()

    while i < n:
        ch = text[i]
        if ch == "`":
            # Inline code through the closing backtick (or rest of text).
            end = text.find("`", i + 1)
            span = text[i : end + 1] if end != -1 else text[i:]
            flush_plain()
            out.append((span, True))
            i += len(span)
            continue
        if ch == "$":
            if text.startswith("$$", i):
                end = text.find("$$", i + 2)
                span = text[i : end + 2] if end != -1 else text[i:]
            else:
                j = i + 1
                while j < n and text[j] != "$":
                    if text[j] == "\\":
                        j += 1
                    j += 1
                span = text[i : j + 1] if j < n else text[i:]
            flush_plain()
            out.append((span, True))
            i += len(span)
            continue
        if text.startswith("\\(", i) or text.startswith("\\[", i):
            close = "\\)" if text[i + 1] == "(" else "\\]"
            end = text.find(close, i + 2)
            span = text[i : end + 2] if end != -1 else text[i:]
            flush_plain()
            out.append((span, True))
            i += len(span)
            continue
        m = _MD_LINK_RE.match(text, i) or _BARE_URL_RE.match(text, i)
        if m:
            flush_plain()
            out.append((m.group(0), True))
            i = m.end()
            continue
        plain.append(ch)
        i += 1
    flush_plain()
    return out


def delimit_bare_latex(text: str) -> str:
    """Wrap bare LaTeX math fragments in ``$...$`` for KaTeX rendering.

    Idempotent: text that is already fully delimited round-trips unchanged.
    Only fragments inside Chinese-prose chunks are touched (中文紧邻判定), so
    English sentences, URLs and currency amounts pass through untouched.
    """
    if not text or ("\\" not in text and "^" not in text and "_" not in text):
        return text
    parts: list[str] = []
    for chunk, protected in _segments(text):
        if protected or not _has_cjk(chunk):
            parts.append(chunk)
            continue
        wrapped = _wrap_commands(chunk)
        wrapped = _wrap_subsup(wrapped)
        parts.append(wrapped)
    return "".join(parts)


# ── 存量修复 CLI ─────────────────────────────────────────────────────────────


def fix_book(book_id: str, *, dry_run: bool = False) -> dict[str, Any]:
    """Walk an existing book's reading blocks, delimiting bare LaTeX in place.

    Returns a summary; with ``dry_run`` nothing is persisted. Mutating runs
    bump the book ``revision`` so optimistic editors notice the rewrite.
    """
    from .storage import get_book_storage

    storage = get_book_storage()
    book = storage.load_book(book_id)
    if book is None:
        raise ValueError(f"book not found: {book_id}")

    changed_blocks = 0
    touched_page_ids: list[str] = []
    for page in storage.list_pages(book_id):
        page_changed = False
        for block in page.blocks:
            if block.type.value != "reading":
                continue
            body = block.params.get("body")
            if not isinstance(body, str) or not body:
                continue
            fixed = delimit_bare_latex(body)
            if fixed != body:
                changed_blocks += 1
                page_changed = True
                if not dry_run:
                    block.params["body"] = fixed
        if page_changed and not dry_run:
            storage.save_page(page)
            touched_page_ids.append(page.id)

    summary: dict[str, Any] = {
        "book_id": book_id,
        "dry_run": dry_run,
        "blocks_fixed": changed_blocks,
        "pages_touched": touched_page_ids if dry_run else len(touched_page_ids),
    }
    if not dry_run and changed_blocks:
        from time import time

        book.revision += 1
        book.updated_at = time()
        storage.save_book(book)
        storage.append_log(
            book_id,
            f"latex_delimit: fixed {changed_blocks} reading blocks across "
            f"{len(touched_page_ids)} pages (revision {book.revision})",
            op="latex_delimit",
        )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m deeptutor.book.latex_delimit",
        description="Delimit bare LaTeX in an existing book's reading blocks",
    )
    parser.add_argument("book_id")
    parser.add_argument("--dry-run", action="store_true", help="report without writing back")
    args = parser.parse_args(argv)
    summary = fix_book(args.book_id, dry_run=args.dry_run)
    print(
        f"{summary['book_id']}: blocks_fixed={summary['blocks_fixed']} "
        f"pages_touched={summary['pages_touched']} dry_run={summary['dry_run']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
