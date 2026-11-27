"""Assessment values shared by producers, persistence, and the HTTP API."""

from __future__ import annotations

import copy
import re
from typing import Any, Literal, get_args

AssessmentSource = Literal[
    "deep_question", "mastery_path", "immersive_reading", "book", "partner_chat", "import"
]
QuestionOriginType = Literal["conversation", "external_import", "document_analysis"]
AssessmentType = Literal["quiz", "focus_check", "qualitative", "review"]
AssessmentResult = Literal["correct", "incorrect", "partial", "ungraded", "voided"]

ASSESSMENT_SOURCES = frozenset(get_args(AssessmentSource))
QUESTION_ORIGIN_TYPES = frozenset(get_args(QuestionOriginType))
ASSESSMENT_TYPES = frozenset(get_args(AssessmentType))
ASSESSMENT_RESULTS = frozenset(get_args(AssessmentResult))


# ---------------------------------------------------------------------------
# Math markup normalization for assessment text
# ---------------------------------------------------------------------------
#
# The Web client renders quiz text with remark-math, which only understands
# `$...$` and `$$...$$`. Generators occasionally emit bare LaTeX, and a
# fill-in-the-blank marker made of underscores (`____`) *inside* a formula is a
# KaTeX parse error ("Expected group after '_'"). rehype-katex degrades that
# error to a visible `katex-error` span, which is exactly the "raw LaTeX on the
# page" symptom. Normalize both before a payload is persisted; the client
# repeats the repair so rows written before this existed still render.

_MATH_SPAN_RE = re.compile(
    r"\$\$[\s\S]*?(?<!\\)\$\$"
    r"|\\\[[\s\S]*?\\\]"
    r"|\\\([\s\S]*?\\\)"
    r"|(?<!\\)\$(?:\\.|[^$\n])*?(?<!\\)\$"
)
_BLANK_RUN_RE = re.compile(r"(?<!\\)_{2,}")
_MATH_WORDS = frozenset(
    "sin cos tan cot sec csc log exp lim max min sup inf det dim gcd lcm "
    "mod arg".split()
)
_CJK_RE = re.compile(
    r"[぀-ヿ㐀-䶿一-鿿가-힯]"
    r"|[、。，；：？！（）《》「」【】…—]"
)
_BLANK_REPLACEMENT = r"\underline{\hspace{2em}}"
_BARE_ENV_RE = re.compile(r"\\begin\{([A-Za-z*]+)\}[\s\S]*?\\end\{\1\}")
_CODE_SPAN_RE = re.compile(r"```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]+`")
_WORD_COMMAND_RE = re.compile(r"\\([A-Za-z]+)")
_SCRIPT_TRIGGER_RE = re.compile(r"[\^_]\{")
# The base a bare script may be attached to: one variable letter, optionally
# followed by digits or a call such as `f(x)`. A word like `lim_{h -> 0}` is
# prose notation in a written answer, not a formula to wrap.
_SCRIPT_BASE_RE = re.compile(r"[A-Za-z](?:[0-9]*|\([^()\n]*\))?$")

# Common KaTeX control sequences. The scanner is deliberately conservative: a
# fragment is only promoted when every `\word` in it is listed here (or is a
# one/two-letter escape handled by `_scan_fragment_end`), so a Windows path or
# a regex such as `\d+` is never mistaken for a formula.
_KNOWN_COMMANDS = frozenset(
    """
    frac dfrac tfrac cfrac sqrt int iint iiint oint oiint oiiint sum prod
    coprod lim liminf limsup sup inf max min det gcd ln log exp sin cos tan
    cot sec csc arcsin arccos arctan sinh cosh tanh
    alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota
    kappa lambda mu nu xi omicron pi varpi rho varrho sigma varsigma tau
    upsilon phi varphi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma
    Upsilon Phi Psi Omega
    partial nabla infty emptyset varnothing forall exists nexists in notin ni
    cdot cdots ldots dots times div pm mp ast star circ bullet cap cup
    setminus subset subseteq supset supseteq le leq ge geq ne neq approx sim
    simeq cong equiv propto ll gg to rightarrow leftarrow leftrightarrow
    Rightarrow Leftarrow Leftrightarrow mapsto longrightarrow longleftarrow
    implies iff left right langle rangle lfloor rfloor lceil rceil lvert
    rvert vert Vert mid parallel perp
    text mathrm mathbf mathbb mathcal mathit mathsf mathtt operatorname
    displaystyle textstyle scriptstyle limits nolimits quad qquad hspace
    phantom underline overline underbrace overbrace widehat widetilde
    overrightarrow overleftarrow hat bar vec dot ddot tilde boxed binom
    choose dbinom tbinom begin end therefore because degree prime Re Im
    big Big bigg Bigg bigl bigr Bigl Bigr middle overset underset stackrel
    """
    .split()
)
_TRIGGER_COMMANDS = frozenset(
    """
    frac dfrac tfrac cfrac sqrt int iint iiint oint oiint oiiint sum prod
    coprod lim liminf limsup sup inf max min det gcd ln log exp sin cos tan
    cot sec csc arcsin arccos arctan sinh cosh tanh
    alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota
    kappa lambda mu nu xi omicron pi varpi rho varrho sigma varsigma tau
    upsilon phi varphi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma
    Upsilon Phi Psi Omega
    partial nabla infty emptyset varnothing forall exists nexists in notin ni
    cdot cdots ldots dots times div pm mp ast star circ bullet cap cup
    setminus subset subseteq supset supseteq le leq ge geq ne neq approx sim
    simeq cong equiv propto ll gg to rightarrow leftarrow leftrightarrow
    Rightarrow Leftarrow Leftrightarrow mapsto longrightarrow longleftarrow
    implies iff langle rangle lfloor rfloor lceil rceil
    boxed binom choose dbinom tbinom begin therefore because
    """.split()
)
_SPACING_TRIGGERS = frozenset({r"\,", r"\;", r"\!", r"\ ", r"\quad", r"\qquad"})
_MATH_PUNCTUATION = frozenset("+-*/=^_<>()[]|,.:;!'")


def _mask_spans(text: str, pattern: re.Pattern[str], label: str) -> tuple[str, list[str]]:
    spans: list[str] = []

    def replace(match: re.Match[str]) -> str:
        spans.append(match.group(0))
        return f"@@DT{label}{len(spans) - 1}@@"

    return pattern.sub(replace, text), spans


def _restore_spans(text: str, label: str, spans: list[str]) -> str:
    placeholder = re.compile(rf"@@DT{label}(\d+)@@")
    return placeholder.sub(lambda match: spans[int(match.group(1))], text)


def _plausible_inline_math(body: str) -> bool:
    """Would this dollar-delimited body be a formula rather than currency?"""
    value = body.strip()
    if not value or len(value) > 400 or "\n\n" in value:
        return False
    if re.search(r"\\[A-Za-z]+|[\^_]|\\\\", value):
        return True

    tight = not body[:1].isspace() and not body[-1:].isspace()
    if _CJK_RE.search(value):
        # "速度 = 路程/时间" is a formula; "100 起，另加 " is the gap between
        # two prices, which only looks like maths when it is loose.
        return tight and len(value) <= 40 and bool(re.search(r"[=+\-*/<>]", value))

    if len(value) > 60:
        return False
    words = re.findall(r"[A-Za-z]{3,}", value)
    return all(word.lower() in _MATH_WORDS for word in words)


def _sanitize_math_spans(text: str) -> str:
    """Make underscore blank markers parseable inside every delimited formula.

    Loose `$ ... $` pairs whose body is genuinely a formula are tightened, so a
    fill-in-the-blank formula that closed its delimiter after a space is not
    later wrapped a second time. Currency pairs such as `$5 and $10` are left
    exactly as written.
    """

    def sanitize(match: re.Match[str]) -> str:
        span = match.group(0)
        if span.startswith("$") and not span.startswith("$$"):
            body = span[1:-1]
            if not _plausible_inline_math(body):
                return span
            return f"${_BLANK_RUN_RE.sub(lambda _blank: _BLANK_REPLACEMENT, body.strip())}$"
        return _BLANK_RUN_RE.sub(lambda _blank: _BLANK_REPLACEMENT, span)

    return _MATH_SPAN_RE.sub(sanitize, text)


def _braces_balanced(fragment: str) -> bool:
    depth = 0
    i = 0
    while i < len(fragment):
        char = fragment[i]
        if char == "\\":
            i += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0


def _continues_after_space(line: str, index: int) -> bool:
    """After a space, does a formula continue rather than prose resume?"""
    next_index = index + 1
    if next_index >= len(line):
        return False
    nxt = line[next_index]
    if nxt == "\\":
        command = _WORD_COMMAND_RE.match(line, next_index)
        return command is None or command.group(1) in _KNOWN_COMMANDS
    if nxt.isdigit() or nxt in "+-*/=^_<>":
        return True
    if nxt.isascii() and nxt.isalpha():
        after = line[next_index + 1] if next_index + 1 < len(line) else ""
        return not (after.isascii() and after.isalpha())
    return False


def _scan_fragment_end(line: str, start: int) -> int:
    stop_at_pipe = line.lstrip().startswith("|")
    i = start
    depth = 0
    while i < len(line):
        char = line[i]
        if char == "\\":
            command = _WORD_COMMAND_RE.match(line, i)
            if command:
                if command.group(1) not in _KNOWN_COMMANDS:
                    break
                i = command.end()
                continue
            if i + 1 < len(line):
                i += 2
                continue
            break
        if char == "{":
            depth += 1
            i += 1
            continue
        if char == "}":
            if depth == 0:
                break
            depth -= 1
            i += 1
            continue
        if depth > 0:
            if char in "$`|":
                break
            i += 1
            continue
        if char.isspace():
            if _continues_after_space(line, i):
                i += 1
                continue
            break
        if char == "|" and stop_at_pipe:
            break
        if char.isascii() and (char.isalnum() or char in _MATH_PUNCTUATION):
            i += 1
            continue
        break

    if depth != 0:
        return start
    while i > start and line[i - 1] in " ,.;:!":
        i -= 1
    return i


def _scan_fragment_start(line: str, trigger: int) -> int:
    """Include the base of a script (`x` in `x^{2}`) and a leading coefficient."""
    if line[trigger] in "^_":
        index = trigger
        while index > 0:
            previous = line[index - 1]
            if previous.isascii() and (previous.isalnum() or previous in "(){}[]]"):
                index -= 1
            else:
                break
        return index

    index = trigger
    while index > 0 and line[index - 1].isdigit():
        index -= 1
    return index


def _next_trigger(line: str, start: int) -> tuple[int, int] | None:
    i = start
    while i < len(line):
        char = line[i]
        if char == "\\":
            command = _WORD_COMMAND_RE.match(line, i)
            if command:
                if command.group(1) in _TRIGGER_COMMANDS:
                    return i, command.end() - i
                i = command.end()
                continue
            pair = line[i : i + 2]
            if pair in _SPACING_TRIGGERS:
                return i, 2
            i += 1
            continue
        if char in "^_" and i + 1 < len(line) and line[i + 1] == "{":
            return i, 2
        i += 1
    return None


def _valid_fragment(fragment: str) -> bool:
    if not fragment or "$" in fragment or "`" in fragment:
        return False
    if not _braces_balanced(fragment):
        return False
    for command in _WORD_COMMAND_RE.finditer(fragment):
        if command.group(1) not in _KNOWN_COMMANDS:
            return False
    return bool(
        _WORD_COMMAND_RE.search(fragment)
        or _SCRIPT_TRIGGER_RE.search(fragment)
        or any(token in fragment for token in _SPACING_TRIGGERS)
    )


def _wrap_bare_latex_line(line: str) -> str:
    if "\\" not in line and not _SCRIPT_TRIGGER_RE.search(line):
        return line

    output: list[str] = []
    i = 0
    while i < len(line):
        found = _next_trigger(line, i)
        if found is None:
            output.append(line[i:])
            break

        trigger, width = found
        start = _scan_fragment_start(line, trigger)
        end = _scan_fragment_end(line, trigger)
        fragment = line[start:end]

        # A script with no base (`^{2}`) cannot stand alone as a formula, and
        # `lim_{h -> 0}` is plain-text notation rather than a script.
        if line[trigger] in "^_" and (
            start == trigger or not _SCRIPT_BASE_RE.fullmatch(line[start:trigger])
        ):
            output.append(line[i : trigger + width])
            i = trigger + width
            continue

        if end > trigger and _valid_fragment(fragment):
            output.append(line[i:start])
            output.append(f"${fragment}$")
            i = end
        else:
            output.append(line[i : trigger + width])
            i = trigger + width

    return "".join(output)


def _wrap_bare_environments(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        body = match.group(0)
        for command in _WORD_COMMAND_RE.finditer(body):
            if command.group(1) not in _KNOWN_COMMANDS:
                return body
        return f"\n$$\n{body.strip()}\n$$\n"

    return _BARE_ENV_RE.sub(replace, text)


def normalize_math_delimiters(text: str) -> str:
    """Wrap bare LaTeX in ``$...$`` and make in-math blanks KaTeX-safe.

    Existing ``$...$``, ``$$...$$``, ``\\(...\\)`` and ``\\[...\\]`` spans are
    respected; fenced code and inline code are left untouched. Idempotent.
    """

    if not text:
        return text
    value = str(text)

    code_masked, code_spans = _mask_spans(value, _CODE_SPAN_RE, "CODE")

    # Sanitize already-delimited maths and put it beyond the bare-LaTeX pass,
    # or `$$...\begin{aligned}...$$` would be promoted a second time.
    sanitized = _sanitize_math_spans(code_masked)
    math_masked, math_spans = _mask_spans(sanitized, _MATH_SPAN_RE, "MATH")

    # Promote whole undelimited environments, then mask the `$$` blocks that
    # created so their bodies are not scanned line by line.
    env_wrapped = _wrap_bare_environments(math_masked)
    env_masked, env_spans = _mask_spans(env_wrapped, _MATH_SPAN_RE, "ENV")

    wrapped = "\n".join(
        _wrap_bare_latex_line(line) for line in env_masked.split("\n")
    )
    value = _restore_spans(wrapped, "ENV", env_spans)
    value = _restore_spans(value, "MATH", math_spans)
    # A blank that only became "inside maths" after the wrapping pass still
    # needs the KaTeX-safe form; this is what makes a second call a no-op.
    value = _sanitize_math_spans(value)
    value = _restore_spans(value, "CODE", code_spans)
    return value


def _strip_math_and_code(text: str) -> str:
    code_masked, _ = _mask_spans(text, _CODE_SPAN_RE, "CODE")
    math_masked, _ = _mask_spans(code_masked, _MATH_SPAN_RE, "MATH")
    return math_masked


def _has_bare_script(text: str) -> bool:
    """Mirror the wrapper's script rule so `lim_{h -> 0}` is not flagged."""
    for match in _SCRIPT_TRIGGER_RE.finditer(text):
        trigger = match.start()
        start = _scan_fragment_start(text, trigger)
        if start < trigger and _SCRIPT_BASE_RE.fullmatch(text[start:trigger]):
            return True
    return False


def _has_bare_latex(text: str) -> bool:
    value = _strip_math_and_code(str(text))
    if _has_bare_script(value):
        return True
    for command in _WORD_COMMAND_RE.finditer(value):
        if command.group(1) in _TRIGGER_COMMANDS:
            return True
    return any(token in value for token in _SPACING_TRIGGERS)


def _has_unsafe_math_blank(text: str) -> bool:
    return any(
        _BLANK_RUN_RE.search(match.group(0))
        for match in _MATH_SPAN_RE.finditer(str(text))
    )


_QUIZ_TEXT_FIELDS = ("question", "correct_answer", "explanation")


def normalize_quiz_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a quiz payload with all text fields math-normalized."""

    normalized = copy.deepcopy(payload)
    questions = normalized.get("questions")
    if not isinstance(questions, list):
        return normalized

    for question in questions:
        if not isinstance(question, dict):
            continue
        for field in _QUIZ_TEXT_FIELDS:
            if isinstance(question.get(field), str):
                question[field] = normalize_math_delimiters(question[field])
        options = question.get("options")
        if isinstance(options, dict):
            question["options"] = {
                key: normalize_math_delimiters(value)
                if isinstance(value, str)
                else value
                for key, value in options.items()
            }
    return normalized


def validate_quiz_payload(payload: dict[str, Any]) -> list[str]:
    """Report quiz text that would reach the reader as raw LaTeX.

    Empty after :func:`normalize_quiz_payload`; callers run it on generated
    quizzes to catch a regression rather than silently persisting broken text.
    """

    issues: list[str] = []
    questions = payload.get("questions") if isinstance(payload, dict) else None
    if not isinstance(questions, list):
        return ["questions: expected a list"]

    for index, question in enumerate(questions):
        if not isinstance(question, dict):
            issues.append(f"questions[{index}]: expected an object")
            continue
        for field in _QUIZ_TEXT_FIELDS:
            value = question.get(field)
            if isinstance(value, str) and (
                _has_bare_latex(value) or _has_unsafe_math_blank(value)
            ):
                issues.append(
                    f"questions[{index}].{field}: contains bare LaTeX or an "
                    "unsafe in-math blank marker"
                )
        options = question.get("options")
        if isinstance(options, dict):
            for key, value in options.items():
                if isinstance(value, str) and (
                    _has_bare_latex(value) or _has_unsafe_math_blank(value)
                ):
                    issues.append(
                        f"questions[{index}].options[{key!r}]: contains bare "
                        "LaTeX or an unsafe in-math blank marker"
                    )
    return issues
