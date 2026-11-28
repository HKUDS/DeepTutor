"""Read a model's tool-call arguments without mangling the LaTeX in them.

Tool arguments arrive as a JSON string, and a model writing maths into one
routinely leaves the backslashes unescaped — ``"矩阵如下：\\begin{pmatrix}…"``
rather than ``"\\\\begin{pmatrix}…"``. Strict JSON rejects that, so the call
falls through to ``json_repair``, which *decodes* the backslashes as JSON
escapes instead of passing them through:

* ``\\begin`` becomes a backspace character followed by ``egin`` (``\\b`` is a
  JSON escape);
* ``\\frac`` becomes a form feed followed by ``rac`` (``\\f``);
* ``\\theta``/``\\times`` become a tab plus the rest of the word (``\\t``);
* ``\\right``/``\\rho`` become a carriage return (``\\r``).

The corruption is silent — the call still parses — and it lands on the one
surface a learner reads: the mastery answer card hands KaTeX
``\\x08egin{pmatrix}`` and shows a parse error instead of the matrix. The
frontend's normaliser cannot recover what was already lost here.

Strict JSON is still tried first and honoured exactly. Only when the
arguments are *already* malformed is the text repaired, and in that pass a
backslash that is plainly LaTeX is left literal. ``\\n`` and ``\\t`` are the
only ambiguous cases (a model also writes them for real newlines and tabs),
so those stay JSON escapes unless the word after them spells a LaTeX command.
``\\\\`` is left as a JSON escape unless the document visibly carries
unescaped maths elsewhere. Only then is a pair a LaTeX row break rather than
a correctly escaped single backslash; in a properly escaped document
(fractions, paths, Windows directories) it keeps its JSON meaning.
"""

from __future__ import annotations

import json
import re
from typing import Any

import json_repair

#: Four hex digits after ``\u`` make it a JSON unicode escape.
_HEX4 = re.compile(r"[0-9a-fA-F]{4}")
#: The control word that follows a backslash, if any.
_WORD = re.compile(r"[A-Za-z]+")
#: Proof that a backslash in this text is LaTeX, not JSON escaping. A document
#: that JSON-escaped its maths has ``\\begin``; one that did not has
#: ``\begin`` or ``\pi``. Only in the second does a ``\\`` mean a row break
#: rather than one escaped backslash — so only then is it preserved.
_LATEX_HINT = re.compile(
    r"(?<!\\)\$"
    r"|(?<!\\)\\[\(\[\{]"
    r"|(?<!\\)\\begin\s*\{|(?<!\\)\\end\s*\{"
    r"|(?<!\\)\\(?:frac|sqrt|left|right|text|mathrm|mathbf|sum|int|partial|infty)\b"
    r"|(?<!\\)\\(?:alpha|beta|gamma|delta|theta|lambda|mu|sigma|pi|times|cdot|nabla)\b"
)

#: LaTeX commands whose first letter is ``n`` or ``t``. ``\n``/``\t`` are the
#: only escapes a model legitimately writes both ways, so the word that
#: follows decides: ``\theta`` is maths, ``\nNext sentence`` is a newline.
_LATEX_N_OR_T = frozenset(
    """
    nabla ne nearrow neg neq newline nexists ngeq nleq nmid not notin
    nparallel nprec nsim nsubseteq nsucc nsupseteq ntriangleleft
    ntriangleright nu nvdash nwarrow
    tan tanh tau tbinom text textbf textcolor textit textmd textnormal
    textrm textsf textstyle texttt tfrac therefore theta thickapprox
    thicksim thickspace thinspace tilde times tiny top triangle
    triangledown triangleleft trianglelefteq triangleq triangleright
    twoheadleftarrow twoheadrightarrow
    """.split()
)


def preserve_latex_escapes(text: str) -> str:
    """Escape the literal backslashes in malformed tool arguments.

    A backslash that starts a JSON escape (``"``, ``\\``, ``/``, ``uXXXX``,
    and ``n``/``t`` before a non-command word) is kept as written; every other
    backslash came from prose — LaTeX — and is doubled so the repair pass
    leaves a backslash in the value instead of an invisible control character.
    """
    if "\\" not in text:
        return text

    # A backslash escaped as JSON and a LaTeX row break look the same on the
    # wire. Only the presence of unescaped maths elsewhere decides which one
    # this document means.
    row_breaks_are_literal = _LATEX_HINT.search(text) is not None

    out: list[str] = []
    index = 0
    end = len(text)

    while index < end:
        char = text[index]
        if char != "\\" or index + 1 >= end:
            out.append(char)
            index += 1
            continue

        following = text[index + 1]

        if following in '"\\/':
            if following == "\\" and row_breaks_are_literal:
                out.append("\\\\\\\\")
            else:
                out.append(char)
                out.append(following)
            index += 2
            continue

        if following == "u" and _HEX4.fullmatch(text[index + 2 : index + 6]):
            out.append(text[index : index + 6])
            index += 6
            continue

        if following == "r" and text[index + 2 : index + 3] == "n":
            # A Windows line ending written as escapes, not `\right`.
            out.append(text[index : index + 3])
            index += 3
            continue

        if following in "nt":
            word = _WORD.match(text, index + 1)
            if word is None or word.group(0) not in _LATEX_N_OR_T:
                out.append(char)
                out.append(following)
                index += 2
                continue

        # Not a JSON escape: a LaTeX control sequence. Keep the backslash.
        out.append("\\\\")
        out.append(following)
        index += 2

    return "".join(out)


def repair_tool_arguments(text: str) -> Any:
    """Repair malformed argument text, keeping the LaTeX it carries."""
    return json_repair.loads(preserve_latex_escapes(text))


def load_tool_arguments(arguments: Any) -> Any:
    """Parse argument text, exactly as written when it is valid JSON."""
    if not isinstance(arguments, str):
        return arguments
    try:
        return json.loads(arguments)
    except (TypeError, ValueError, RecursionError):
        return repair_tool_arguments(arguments)


__all__ = ["load_tool_arguments", "preserve_latex_escapes", "repair_tool_arguments"]
