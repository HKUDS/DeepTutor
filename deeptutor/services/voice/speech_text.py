"""LaTeX/math verbalizer for the TTS pre-layer.

``strip_markdown_for_speech`` already drops Markdown structure. This module
turns the remaining math into words a voice model can read without saying
"dollar", "backslash", "caret", or "underscore".

Scope is deliberately Pareto, not a full MathSpeak engine:

* Only math islands (``$…$``, ``$$…$$``, ``\\(…\\)``, ``\\[…\\]``,
  ``\\begin{equation|align|…}``) get script handling (``^`` / ``_``), so
  snake_case prose is left alone.
* High-frequency algebra is verbalized: fractions, roots, limits, Greek,
  relations, trig/log, blackboard number sets.
* Structural TeX (``\\left``, braces, environments) is stripped.
* Function words are English; they are portable across OpenAI-compatible TTS
  engines, including Chinese voices that already mix English math terms.
"""

from __future__ import annotations

import re

# ── lexicons ──────────────────────────────────────────────────────────────

_GREEK = {
    "alpha": "alpha",
    "beta": "beta",
    "gamma": "gamma",
    "delta": "delta",
    "epsilon": "epsilon",
    "varepsilon": "epsilon",
    "zeta": "zeta",
    "eta": "eta",
    "theta": "theta",
    "vartheta": "theta",
    "iota": "iota",
    "kappa": "kappa",
    "lambda": "lambda",
    "mu": "mu",
    "nu": "nu",
    "xi": "xi",
    "pi": "pi",
    "varpi": "pi",
    "rho": "rho",
    "sigma": "sigma",
    "varsigma": "sigma",
    "tau": "tau",
    "upsilon": "upsilon",
    "phi": "phi",
    "varphi": "phi",
    "chi": "chi",
    "psi": "psi",
    "omega": "omega",
    "Alpha": "capital alpha",
    "Beta": "capital beta",
    "Gamma": "capital gamma",
    "Delta": "capital delta",
    "Theta": "capital theta",
    "Lambda": "capital lambda",
    "Xi": "capital xi",
    "Pi": "capital pi",
    "Sigma": "capital sigma",
    "Phi": "capital phi",
    "Psi": "capital psi",
    "Omega": "capital omega",
}

_FUNCTIONS = {
    "arcsin": "arcsine",
    "arccos": "arccosine",
    "arctan": "arctangent",
    "sinh": "hyperbolic sine",
    "cosh": "hyperbolic cosine",
    "tanh": "hyperbolic tangent",
    "sin": "sine",
    "cos": "cosine",
    "tan": "tangent",
    "cot": "cotangent",
    "sec": "secant",
    "csc": "cosecant",
    "log": "log",
    "ln": "natural log",
    "lg": "log",
    "exp": "exponential",
    "min": "min",
    "max": "max",
    "inf": "infimum",
    "sup": "supremum",
    "det": "determinant",
    "dim": "dimension",
    "ker": "kernel",
    "deg": "degree",
    "gcd": "GCD",
    "lcm": "LCM",
    "arg": "arg",
    "Pr": "probability",
}

_OPERATORS = {
    "leqslant": "less than or equal to",
    "geqslant": "greater than or equal to",
    "subseteq": "subset of or equal to",
    "supseteq": "superset of or equal to",
    "leftrightarrow": "if and only if",
    "Leftrightarrow": "if and only if",
    "rightarrow": "to",
    "Rightarrow": "implies",
    "leftarrow": "from",
    "Leftarrow": "implied by",
    "longrightarrow": "to",
    "infty": "infinity",
    "emptyset": "empty set",
    "varnothing": "empty set",
    "partial": "partial",
    "nabla": "del",
    "cdots": "dot dot dot",
    "ldots": "dot dot dot",
    "dots": "dot dot dot",
    "cdot": "times",
    "times": "times",
    "star": "star",
    "ast": "times",
    "div": "divided by",
    "pm": "plus or minus",
    "mp": "minus or plus",
    "leq": "less than or equal to",
    "geq": "greater than or equal to",
    "neq": "not equal to",
    "ne": "not equal to",
    "approx": "approximately",
    "equiv": "equivalent to",
    "sim": "similar to",
    "propto": "proportional to",
    "cong": "congruent to",
    "forall": "for all",
    "exists": "there exists",
    "notin": "not in",
    "subset": "subset of",
    "supset": "superset of",
    "cup": "union",
    "cap": "intersection",
    "vee": "or",
    "wedge": "and",
    "oplus": "plus",
    "otimes": "tensor",
    "land": "and",
    "lor": "or",
    "lnot": "not",
    "neg": "not",
    "to": "to",
    "gets": "from",
    "implies": "implies",
    "iff": "if and only if",
    "in": "in",
    "ni": "contains",
    "le": "less than or equal to",
    "ge": "greater than or equal to",
    "ll": "much less than",
    "gg": "much greater than",
    "mid": "given",
    "parallel": "parallel to",
    "perp": "perpendicular to",
    "degree": "degrees",
    "circ": "compose",
    "bullet": "times",
    "prime": "prime",
    "ell": "l",
    "hbar": "h bar",
    "Re": "real part",
    "Im": "imaginary part",
}

_SPACING_DROP = {
    "qquad": " ",
    "quad": " ",
    "hspace": "",
    "vspace": "",
    "phantom": "",
    "mathstrut": "",
    "displaystyle": "",
    "textstyle": "",
    "scriptstyle": "",
    "left": "",
    "right": "",
    "bigl": "",
    "bigr": "",
    "Bigl": "",
    "Bigr": "",
    "biggl": "",
    "biggr": "",
    "Biggl": "",
    "Biggr": "",
    "big": "",
    "Big": "",
    "bigg": "",
    "Bigg": "",
    "nolimits": "",
    "limits": "",
    "notag": "",
    "tag": "",
    "label": "",
}

_BLACKBOARD = {
    "R": "the reals",
    "N": "the naturals",
    "Z": "the integers",
    "Q": "the rationals",
    "C": "the complexes",
}

_MATH_ENVS = frozenset(
    {
        "equation",
        "equation*",
        "align",
        "align*",
        "aligned",
        "gather",
        "gather*",
        "displaymath",
        "math",
        "cases",
        "array",
        "matrix",
        "pmatrix",
        "bmatrix",
        "vmatrix",
        "Vmatrix",
        "multline",
        "split",
    }
)

_UNICODE_MATH = {
    "≤": " less than or equal to ",
    "≥": " greater than or equal to ",
    "≠": " not equal to ",
    "≈": " approximately ",
    "≡": " equivalent to ",
    "∞": " infinity ",
    "×": " times ",
    "÷": " divided by ",
    "±": " plus or minus ",
    "→": " to ",
    "←": " from ",
    "⇒": " implies ",
    "⇔": " if and only if ",
    "∈": " in ",
    "∉": " not in ",
    "⊂": " subset of ",
    "⊆": " subset of or equal to ",
    "∪": " union ",
    "∩": " intersection ",
    "∀": " for all ",
    "∃": " there exists ",
    "∂": " partial ",
    "∇": " del ",
    "√": " square root of ",
    "∑": " sum ",
    "∏": " product ",
    "∫": " integral ",
    "°": " degrees ",
    "·": " times ",
    "⋅": " times ",
}

_STYLE_NAMES = (
    "operatorname",
    "boldsymbol",
    "mathbf",
    "mathbb",
    "mathcal",
    "mathit",
    "mathsf",
    "mathtt",
    "textrm",
    "textbf",
    "textit",
    "mathrm",
    "text",
    "mbox",
    "overline",
    "underline",
    "widehat",
    "widetilde",
    "hat",
    "bar",
    "vec",
    "dot",
    "tilde",
    "check",
    "acute",
    "grave",
    "breve",
)

_ACCENT_SPEAK = {
    "overline": "{inner} bar",
    "underline": "{inner} underline",
    "widehat": "{inner} hat",
    "widetilde": "{inner} tilde",
    "hat": "{inner} hat",
    "bar": "{inner} bar",
    "vec": "{inner} vector",
    "dot": "{inner} dot",
    "tilde": "{inner} tilde",
    "check": "{inner} check",
}

_LIMIT_HEAD = {
    "oint": "contour integral",
    "int": "integral",
    "sum": "sum",
    "prod": "product",
    "lim": "limit",
}

_FRAC_NAMES = ("dfrac", "tfrac", "cfrac", "frac")
_SIMPLE_OPERAND = re.compile(r"^[\w.]+$", re.UNICODE)
_COMMAND = re.compile(r"\\(?:[a-zA-Z]+|.)")
_BEGIN_ENV = re.compile(r"\\begin\{([^}]+)\}")
_LEFTOVER_DOLLAR = re.compile(r"\$+")
_PAD_PLUS_EQ = re.compile(r"\s*([+=])\s*")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_LOOSE_TEX = re.compile(
    r"\\(?:"
    + "|".join(
        re.escape(name)
        for name in sorted(
            {
                *_GREEK,
                *_OPERATORS,
                *_FUNCTIONS,
                *_SPACING_DROP,
                *_FRAC_NAMES,
                *_STYLE_NAMES,
                *_LIMIT_HEAD,
                "sqrt",
                "binom",
                "mathbb",
            },
            key=len,
            reverse=True,
        )
    )
    + r")(?![a-zA-Z])"
)
_WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]:\\|\\\\)[^\s]*")


def _skip_ws(s: str, i: int) -> int:
    n = len(s)
    while i < n and s[i].isspace():
        i += 1
    return i


def _is_escaped(s: str, i: int) -> bool:
    bs = 0
    j = i - 1
    while j >= 0 and s[j] == "\\":
        bs += 1
        j -= 1
    return bs % 2 == 1


def _read_group(s: str, i: int) -> tuple[str, int] | None:
    """Read a ``{…}`` group starting at ``i``. Returns ``(inner, after)``."""
    if i >= len(s) or s[i] != "{":
        return None
    depth = 0
    j = i
    n = len(s)
    while j < n:
        ch = s[j]
        if ch == "\\" and j + 1 < n:
            j += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1 : j], j + 1
        j += 1
    return None


def _read_tex_token(s: str, i: int) -> tuple[str | None, int]:
    """Read one TeX token: a ``{group}``, a ``\\command``, or one character."""
    i = _skip_ws(s, i)
    if i >= len(s):
        return None, i
    if s[i] == "{":
        grp = _read_group(s, i)
        if grp is None:
            return s[i], i + 1
        inner, end = grp
        return inner, end
    match = _COMMAND.match(s, i)
    if match:
        return match.group(0), match.end()
    return s[i], i + 1


def _until_stable(fn, text: str, *, limit: int = 8) -> str:
    for _ in range(limit):
        nxt = fn(text)
        if nxt == text:
            return nxt
        text = nxt
    return text


def _speak_operand(piece: str) -> str:
    piece = piece.strip()
    if not piece:
        return ""
    if _SIMPLE_OPERAND.fullmatch(piece):
        return piece
    return f"({piece})"


def _replace_named_commands(text: str, mapping: dict[str, str]) -> str:
    if not mapping:
        return text
    keys = sorted(mapping, key=len, reverse=True)
    pattern = re.compile(r"\\(" + "|".join(re.escape(k) for k in keys) + r")(?![a-zA-Z])")
    return pattern.sub(lambda m: f" {mapping[m.group(1)]} ", text)


def _unwrap_style_once(text: str) -> str:
    out: list[str] = []
    i = 0
    n = len(text)
    names = "|".join(re.escape(name) for name in _STYLE_NAMES)
    opener = re.compile(r"\\(" + names + r")(?![a-zA-Z])")
    while i < n:
        match = opener.search(text, i)
        if not match:
            out.append(text[i:])
            break
        out.append(text[i : match.start()])
        i = _skip_ws(text, match.end())
        inner, end = _read_tex_token(text, i)
        name = match.group(1)
        if inner is None:
            i = match.end()
            continue
        spoken = _ACCENT_SPEAK.get(name)
        if spoken:
            out.append(" " + spoken.format(inner=inner.strip()) + " ")
        else:
            out.append(inner)
        i = end
    return "".join(out)


def _replace_blackboard_sets(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        letter = match.group(1)
        return f" {_BLACKBOARD.get(letter, letter)} "

    return re.sub(r"\\mathbb\s*\{([RNZQC])\}", repl, text)


def _replace_frac_once(text: str) -> str:
    out: list[str] = []
    i = 0
    n = len(text)
    opener = re.compile(r"\\(?:" + "|".join(_FRAC_NAMES) + r")(?![a-zA-Z])")
    while i < n:
        match = opener.search(text, i)
        if not match:
            out.append(text[i:])
            break
        out.append(text[i : match.start()])
        i = match.end()
        num, i = _read_tex_token(text, i)
        den, i = _read_tex_token(text, i)
        if num is None or den is None:
            continue
        num_s = _speak_operand(_verbalize_math(num))
        den_s = _speak_operand(_verbalize_math(den))
        out.append(f" {num_s} over {den_s} ")
    return "".join(out)


def _replace_sqrt_once(text: str) -> str:
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        j = text.find(r"\sqrt", i)
        if j == -1 or (j + 5 < n and text[j + 5].isalpha()):
            if j == -1:
                out.append(text[i:])
                break
            out.append(text[i : j + 5])
            i = j + 5
            continue
        out.append(text[i:j])
        i = j + 5
        i = _skip_ws(text, i)
        root: str | None = None
        if i < n and text[i] == "[":
            close = text.find("]", i + 1)
            if close != -1:
                root = text[i + 1 : close]
                i = close + 1
                i = _skip_ws(text, i)
        inner, i = _read_tex_token(text, i)
        if inner is None:
            continue
        spoken = _speak_operand(_verbalize_math(inner))
        if root is None or root.strip() in {"", "2"}:
            out.append(f" square root of {spoken} ")
        elif root.strip() == "3":
            out.append(f" cube root of {spoken} ")
        else:
            root_s = _speak_operand(_verbalize_math(root))
            out.append(f" {root_s} root of {spoken} ")
    return "".join(out)


def _replace_binom_once(text: str) -> str:
    out: list[str] = []
    i = 0
    n = len(text)
    opener = re.compile(r"\\binom(?![a-zA-Z])")
    while i < n:
        match = opener.search(text, i)
        if not match:
            out.append(text[i:])
            break
        out.append(text[i : match.start()])
        i = match.end()
        top, i = _read_tex_token(text, i)
        bot, i = _read_tex_token(text, i)
        if top is None or bot is None:
            continue
        out.append(
            f" {_speak_operand(_verbalize_math(top))} choose "
            f"{_speak_operand(_verbalize_math(bot))} "
        )
    return "".join(out)


def _replace_limits_once(text: str) -> str:
    out: list[str] = []
    i = 0
    n = len(text)
    opener = re.compile(r"\\(" + "|".join(_LIMIT_HEAD) + r")(?![a-zA-Z])")
    while i < n:
        match = opener.search(text, i)
        if not match:
            out.append(text[i:])
            break
        out.append(text[i : match.start()])
        i = match.end()
        i = _skip_ws(text, i)
        sub = None
        sup = None
        if i < n and text[i] == "_":
            sub, i = _read_tex_token(text, i + 1)
            i = _skip_ws(text, i)
        if i < n and text[i] == "^":
            sup, i = _read_tex_token(text, i + 1)
        head = _LIMIT_HEAD[match.group(1)]
        parts = [head]
        if match.group(1) == "lim":
            if sub:
                parts.append("as")
                parts.append(_verbalize_math(sub).strip())
            if sup:
                parts.append("to")
                parts.append(_verbalize_math(sup).strip())
        else:
            if sub:
                parts.append("from")
                parts.append(_verbalize_math(sub).strip())
            if sup:
                parts.append("to")
                parts.append(_verbalize_math(sup).strip())
        out.append(" " + " ".join(p for p in parts if p) + " ")
    return "".join(out)


def _speak_sup(inner: str) -> str:
    token = inner.strip()
    token = _replace_named_commands(token, {**_GREEK, **_OPERATORS, **_FUNCTIONS})
    token = token.strip()
    if token in {"2"}:
        return " squared "
    if token in {"3"}:
        return " cubed "
    if token in {"-1"}:
        return " inverse "
    if token in {"T", "t", "top", "intercal"}:
        return " transpose "
    if token in {"prime", "'"}:
        return " prime "
    if token in {"circ", "o", "\\circ"}:
        return " degrees "
    if token in {"*"}:
        return " star "
    return f" to the {token} "


def _verbalize_scripts(text: str) -> str:
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in "^_" and not _is_escaped(text, i):
            kind = ch
            token, nxt = _read_tex_token(text, i + 1)
            if token is None:
                i += 1
                continue
            i = nxt
            if kind == "^":
                out.append(_speak_sup(token))
            else:
                spoken = _verbalize_math(token).strip() if "\\" in token else token.strip()
                out.append(f" sub {spoken} ")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _drop_unknown_commands(text: str) -> str:
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "\\" and i + 1 < n:
            match = re.match(r"\\[a-zA-Z]+", text[i:])
            if match:
                i += match.end()
                i = _skip_ws(text, i)
                if i < n and text[i] == "{":
                    grp = _read_group(text, i)
                    if grp is not None:
                        inner, i = grp
                        out.append(inner)
                continue
            nxt = text[i + 1]
            if nxt in "{}":
                i += 2
                continue
            if nxt in "[]()|,.;!":
                out.append(nxt)
                i += 2
                continue
            if nxt in ",;! \\":
                out.append(" ")
                i += 2
                continue
            i += 2
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _drop_braces(text: str) -> str:
    return text.replace("{", " ").replace("}", " ")


def _verbalize_math(text: str) -> str:
    """Turn one math island's inner TeX into speakable words."""
    if not text:
        return ""
    out = text.replace("&", " ")
    out = out.replace(r"\\", ", ")
    out = _replace_blackboard_sets(out)
    out = _until_stable(_unwrap_style_once, out)
    out = _until_stable(_replace_frac_once, out)
    out = _until_stable(_replace_sqrt_once, out)
    out = _until_stable(_replace_binom_once, out)
    out = _until_stable(_replace_limits_once, out)
    out = _replace_named_commands(out, {**_GREEK, **_OPERATORS, **_FUNCTIONS, **_SPACING_DROP})
    out = _verbalize_scripts(out)
    out = _drop_unknown_commands(out)
    out = _drop_braces(out)
    out = _PAD_PLUS_EQ.sub(r" \1 ", out)
    out = _MULTI_SPACE.sub(" ", out)
    return out.strip()


def _replace_unicode(text: str) -> str:
    if not text:
        return text
    out = text
    for src, spoken in _UNICODE_MATH.items():
        if src in out:
            out = out.replace(src, spoken)
    return out


def _verbalize_loose_commands(text: str) -> str:
    """Convert leftover TeX commands in prose; never touch bare ``_`` / ``^``.

    Windows paths are passed through even when nearby prose contains TeX.
    """
    if "\\" not in text or not _LOOSE_TEX.search(text):
        return text

    def speak(segment: str) -> str:
        out = _replace_blackboard_sets(segment)
        out = _until_stable(_unwrap_style_once, out)
        out = _until_stable(_replace_frac_once, out)
        out = _until_stable(_replace_sqrt_once, out)
        out = _until_stable(_replace_binom_once, out)
        out = _until_stable(_replace_limits_once, out)
        # Unknown commands in prose may be path segments or product names.
        # Only an explicit math island is safe to clean up destructively.
        return _replace_named_commands(out, {**_GREEK, **_OPERATORS, **_FUNCTIONS, **_SPACING_DROP})

    parts: list[str] = []
    offset = 0
    for match in _WINDOWS_PATH.finditer(text):
        parts.append(speak(text[offset : match.start()]))
        parts.append(match.group())
        offset = match.end()
    parts.append(speak(text[offset:]))
    return "".join(parts)


def _emit_island(inner: str, *, math_speak: bool) -> str:
    return _verbalize_math(inner) if math_speak else inner


def verbalize_latex_for_speech(text: str, *, math_speak: bool = True) -> str:
    """Replace math islands with speakable prose, or just unwrap delimiters.

    ``math_speak=True`` (default) verbalizes fractions, powers, Greek, and
    operators. ``math_speak=False`` still strips ``$`` / ``$$`` / ``\\(``
    wrappers so TTS never says "dollar", but leaves the inner TeX as-is.

    Bare underscores outside math are preserved (``file_name`` stays intact).
    Leftover ``$`` from broken markup is dropped.
    """
    if not text:
        return ""
    if "$" not in text and "\\" not in text:
        return _replace_unicode(text) if math_speak else text

    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("$$", i) and not _is_escaped(text, i):
            end = text.find("$$", i + 2)
            if end != -1:
                out.append(" ")
                out.append(_emit_island(text[i + 2 : end], math_speak=math_speak))
                out.append(" ")
                i = end + 2
                continue
        if text.startswith("\\[", i):
            end = text.find("\\]", i + 2)
            if end != -1:
                out.append(" ")
                out.append(_emit_island(text[i + 2 : end], math_speak=math_speak))
                out.append(" ")
                i = end + 2
                continue
        if text.startswith("\\(", i):
            end = text.find("\\)", i + 2)
            if end != -1:
                out.append(" ")
                out.append(_emit_island(text[i + 2 : end], math_speak=math_speak))
                out.append(" ")
                i = end + 2
                continue
        begin = _BEGIN_ENV.match(text, i)
        if begin and begin.group(1) in _MATH_ENVS:
            env = begin.group(1)
            end_tag = f"\\end{{{env}}}"
            end = text.find(end_tag, begin.end())
            if end != -1:
                out.append(" ")
                out.append(_emit_island(text[begin.end() : end], math_speak=math_speak))
                out.append(" ")
                i = end + len(end_tag)
                continue
        if text[i] == "$" and not _is_escaped(text, i):
            j = i + 1
            while j < n:
                if text[j] == "\n":
                    j = -1
                    break
                if text[j] == "$" and not _is_escaped(text, j):
                    break
                j += 1
            if j > i:
                out.append(" ")
                out.append(_emit_island(text[i + 1 : j], math_speak=math_speak))
                out.append(" ")
                i = j + 1
                continue
        out.append(text[i])
        i += 1

    spoken = "".join(out)
    if math_speak:
        spoken = _verbalize_loose_commands(spoken)
        spoken = _replace_unicode(spoken)
    spoken = _LEFTOVER_DOLLAR.sub("", spoken)
    return spoken


__all__ = ["verbalize_latex_for_speech"]
