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

P5fix 召回补丁 adds the 整行数学主体 form the 09-09 production sweep found
leaking (36 bare spots on 人教A版选必一 页8): lines whose content *is* the
math — connective equalities like ``(1) a+b=\\overrightarrow{OA}+
\\overrightarrow{AB}=\\overrightarrow{OB};`` and single-line derivations like
``\\lambda(\\mu a)=(\\lambda\\mu)a``. Per-fragment wrapping is wrong there (a
command followed by a variable — ``\\mu a`` — is deliberately not a fragment),
so a line that is *math-dominant* (≥2 whitelisted commands, no prose words, no
CJK outside the numbering/punctuation frame) is wrapped as one whole
``$...$`` span, with any leading 题号 and trailing punctuation kept outside.

The same function runs at two points: the canonicalize/pages-import hook
(new books are correct from day one) and this module's CLI, which walks an
existing book's reading blocks in place::

    python -m deeptutor.book.latex_delimit <book_id> [--dry-run]

The CLI (and every caller) writes through the engine's official block-write
path — the one ``figure_backfill`` proved API-visible: ``params["body"]`` is
the generator *input*, but ``payload["body"]`` is what ``GET /pages/{id}``
serves, so a fix that only touches ``params`` shows 41 delimitations in the
file and 0 in the API (09-09 生产实锤). Both layers are updated and persisted
with the same ``storage.save_page`` call ``engine.insert_block`` /
``engine.update_block`` use; fixing ``params`` too keeps a future regenerate
(reading generator copies params → payload) from silently undoing the fix.
"""

from __future__ import annotations

import argparse
import logging
import re
from time import time
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

# ── 数学主体行（P5fix 召回补丁）─────────────────────────────────────────────

# 散文信号：命令剥掉后残留的小写英文词（"and"、"is"、"here"）——出现即不是
# 纯数学串。全大写 2-4 字母（OA、AB、CB）与单字母变量不算词。
_LOWERCASE_WORD_RE = re.compile(r"(?<![A-Za-z\\])[a-z]{2,}")

# Maximal runs of non-CJK characters — the unit 整行/整段数学 wraps as one.
_RUN_RE = re.compile(f"[^{_CJK}]+")


def _is_math_dominant(run: str) -> bool:
    """A non-CJK run that *is* the math: ≥2 whitelisted commands, an equation
    operator, no prose words, no URL.

    ``\\mu a`` 这类"命令+变量"连写不是 FRAGMENT_RE 片段（右邻字母被
    ``_right_ok`` 刻意挡下），所以逐片段包装在连等式串上必然漏——这种串
    只能整体包。判定收得极紧：``=`` 把无关的命令并列表（``\\lambda 与
    \\mu``）挡在外面，剥掉命令后残留任何小写英文词（散文）即不算，
    英文句子在构造上就被排除。
    """
    if "=" not in run or "://" in run:
        return False
    if len(FRAGMENT_RE.findall(run)) < 2:
        return False
    # 命令连同其花括号参数一起剥掉，\text{...} 里的词、向量记号 OA 不触发散文判定。
    return _LOWERCASE_WORD_RE.search(FRAGMENT_RE.sub(" ", run)) is None


def _wrap_math_runs(line: str) -> str | None:
    """Wrap every math-dominant non-CJK run of *line* in one ``$...$`` span.

    Returns the rewritten line, or ``None`` when nothing qualified (caller
    falls back to the per-fragment path). Runs may sit 整行 or between 中文 —
    ``(1) a+b=\\overrightarrow{OA}+\\overrightarrow{AB}=\\overrightarrow{OB};``
    and ``\\lambda(\\mu a)=(\\lambda\\mu)a，即数乘结合律。`` both qualify.
    """
    out: list[str] = []
    pos = 0
    changed = False
    for m in _RUN_RE.finditer(line):
        run = m.group(0)
        core = run.strip()
        if not core or not _is_math_dominant(core):
            continue
        changed = True
        left = run[: len(run) - len(run.lstrip())]
        right = run[len(run.rstrip()) :]
        out.append(line[pos : m.start()])
        out.append(f"{left}${core}${right}")
        pos = m.end()
    if not changed:
        return None
    out.append(line[pos:])
    return "".join(out)


def _process_plain_line(line: str, chunk_has_cjk: bool) -> str:
    """One plain (unprotected) line: 整段数学主体优先，否则逐片段包装."""
    wrapped = _wrap_math_runs(line)
    if wrapped is not None:
        # 数学串已整体入 $...$；剩余片段继续逐片段包装（$...$ 自动受保护）。
        parts = []
        for chunk, protected in _segments(wrapped):
            parts.append(chunk if protected else _wrap_subsup(_wrap_commands(chunk)))
        return "".join(parts)
    if not chunk_has_cjk:
        # 老防线保持：无中文的行不做逐片段包装（英文句子/代码在构造上不碰）。
        return line
    return _wrap_subsup(_wrap_commands(line))


def _process_plain_chunk(chunk: str) -> str:
    chunk_has_cjk = _has_cjk(chunk)
    if "\n" not in chunk:
        return _process_plain_line(chunk, chunk_has_cjk)
    return "\n".join(_process_plain_line(line, chunk_has_cjk) for line in chunk.split("\n"))


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
    Plain chunks go line by line: an 整行数学主体 line wraps whole, everything
    else keeps the 中文紧邻 per-fragment path (English sentences, URLs and
    currency amounts pass through untouched).
    """
    if not text or ("\\" not in text and "^" not in text and "_" not in text):
        return text
    parts: list[str] = []
    for chunk, protected in _segments(text):
        if protected:
            parts.append(chunk)
            continue
        parts.append(_process_plain_chunk(chunk))
    return "".join(parts)


# ── 存量修复 CLI ─────────────────────────────────────────────────────────────


def _block_change_layers(block: Any) -> list[str]:
    """Which body layers of this reading block ``delimit_bare_latex`` would
    change — pure probe, no mutation (dry-run stays read-only)."""
    changed: list[str] = []
    body = block.params.get("body")
    if isinstance(body, str) and body and delimit_bare_latex(body) != body:
        changed.append("params")
    rendered = (block.payload or {}).get("body")
    if isinstance(rendered, str) and rendered and delimit_bare_latex(rendered) != rendered:
        changed.append("payload")
    return changed


def _apply_block_layers(block: Any, layers: list[str]) -> None:
    """Write the changed layers the way ``engine.update_block`` writes a body.

    The rendered ``payload["body"]`` is what ``GET /pages/{id}`` serves (the
    truth the 09-09 sweep proved a params-only edit never reaches), and
    ``params["body"]`` is what the reading generator copies back on any
    regenerate — fixing only one layer either shows nothing in the API or gets
    silently undone by the next regenerate.
    """
    if "params" in layers:
        block.params["body"] = delimit_bare_latex(block.params["body"])
    if "payload" in layers:
        # engine.update_block 的 body 写法：payload + format 一起落。
        block.payload = {
            **(block.payload or {}),
            "body": delimit_bare_latex(block.payload["body"]),
            "format": "markdown",
        }
    block.updated_at = time()


def _resolve_write_storage(book_id: str) -> Any:
    """Pick the storage layer the page API will actually serve *book_id* from.

    ``resolve_book`` (multi_user/book_access) serves shared books from the
    admin workspace; the admin + student views of a production shared textbook
    all read that layer. A CLI run's ``get_book_storage()`` follows the
    *current user*, so ``-u deeptutor`` against a shared book wrote (a copy
    in) the user workspace the API never read — the 09-27 double-workspace
    miss. Probe the admin layer first (a book living there is a shared
    textbook, and that is the layer every reader hits), then fall back to the
    current user's own workspace; when neither has the book, return own so the
    familiar not-found error still surfaces.
    """
    from deeptutor.multi_user.paths import get_admin_path_service

    from .storage import BookStorage, get_book_storage

    admin = BookStorage(path_service=get_admin_path_service())
    if admin.load_book(book_id) is not None:
        return admin
    own = get_book_storage()
    if own.load_book(book_id) is not None:
        return own
    return own


def fix_book(book_id: str, *, dry_run: bool = False, storage: Any = None) -> dict[str, Any]:
    """Walk an existing book's reading blocks, delimiting bare LaTeX in place.

    Loads pages through the engine (same read path the API serves from) and
    persists with ``storage.save_page`` — the write every official engine
    mutation (``insert_block``, ``update_block``) lands through, which is what
    makes the fix API-visible. Returns a summary; with ``dry_run`` nothing is
    persisted. Mutating runs bump the book ``revision`` so optimistic editors
    notice the rewrite.

    Without an injected ``storage`` the write layer is resolved against where
    the book actually lives (admin shared layer when the book is there, else
    the current user's own workspace) — see :func:`_resolve_write_storage`.
    """
    from .engine import BookEngine

    if storage is None:
        storage = _resolve_write_storage(book_id)
    engine = BookEngine(storage=storage)
    book = engine.load_book(book_id)
    if book is None:
        raise ValueError(f"book not found: {book_id}")

    changed_blocks = 0
    touched_page_ids: list[str] = []
    for page in engine.list_pages(book_id):
        page_changed = False
        for block in page.blocks:
            if block.type.value != "reading":
                continue
            layers = _block_change_layers(block)
            if not layers:
                continue
            changed_blocks += 1
            page_changed = True
            if not dry_run:
                _apply_block_layers(block, layers)
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
