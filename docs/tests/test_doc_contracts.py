"""Doc contract tests: the docs must not describe things the code lacks.

These catch a class of drift that link checking cannot see. A page can have
every link resolve, build clean, and still tell a reader to run a command that
no longer exists or call an endpoint that was never mounted.

Scope is deliberately narrow. The tests assert *existence*, not correctness:
that a named command is registered, a named path is served, a stated version
matches. They cannot tell whether an explanation is still honest, only whether
the things it cites still exist.
"""

from __future__ import annotations

import re

import doc_facts
import pytest

# ── CLI commands ────────────────────────────────────────────────────────────

# ``deeptutor <group> <sub>``. The group is required; the subcommand is
# optional because the CLI has bare commands such as ``deeptutor doctor``.
# Whitespace is ``[ \t]`` rather than ``\s`` so a match cannot span a line
# break and pair the last word of one line with the first word of the next
# (``Run deeptutor`` / ``kb list`` must not read as ``deeptutor kb``). The
# trailing lookahead ends the match at the end of the token, so ``deep`` in
# ``deeptutor run deep_solve`` is not read as a subcommand, and the token class
# includes ``_`` because capability names such as ``deep_question`` are words
# rather than subcommands.
COMMAND = re.compile(
    r"\bdeeptutor[ \t]+([a-z][a-z0-9_-]*)(?:[ \t]+([a-z][a-z0-9_-]*))?(?![a-z0-9_-])"
)

# Commands inside fenced examples are checked too — that is where readers copy
# them from, and it is most of the mentions on the site. Only lines that
# actually *invoke* the CLI count, so a path or a container name does not:
#
#   deeptutor kb list                    → invocation (line start)
#   $ deeptutor kb list                  → invocation (shell prompt)
#   DEEPTUTOR_HOME=/opt/deeptutor deeptutor start → invocation (env prefix)
#   SESSION_ID=$(deeptutor run chat ...)  → invocation (command substitution)
#   docker exec deeptutor python ...      → NOT an invocation: `deeptutor` is
#                                           the container name, `python` the
#                                           command, so this would otherwise
#                                           look like `deeptutor python`.
FENCED_COMMAND = re.compile(
    r"""
    (?:
        ^[ \t]*(?:\$[ \t]+)?                     # line start, optional prompt
        (?:[A-Z][A-Z0-9_]*=[^\s(]+[ \t]+)*       # optional env assignments
      | \$\( | `                                # command substitution / backtick
      | &&[ \t]* | ;[ \t]* | \|[ \t]*            # chained or piped command
    )
    deeptutor[ \t]+([a-z][a-z0-9_-]*)(?:[ \t]+([a-z][a-z0-9_-]*))?(?![a-z0-9_-])
    """,
    re.VERBOSE | re.MULTILINE,
)

# Subcommand slots that are values, not command names: ``deeptutor run chat``
# takes a capability, ``deeptutor kb create my-kb`` takes a name.
NOT_A_SUBCOMMAND = {
    # capability names accepted by ``run``
    "chat",
    "ask_questions",
    "deep_solve",
    "deep_question",
    "deep_research",
    "visualize",
    "math_animator",
    "mastery_path",
    "immersive_reading",
    "video_lesson",
    "audio_overview",
    # placeholder / variable tokens that appear in prose
    "x",
    "y",
}


def _documented_commands() -> list[tuple[str, str, str]]:
    """Yield ``(page, group, subcommand)`` for every command the docs show.

    Two sources, because they answer slightly different questions:

    * prose (fences stripped) — a sentence that names a command is a claim that
      the command exists;
    * fenced blocks — scanned for lines that *invoke* the CLI, since a code
      sample is what readers copy and most mentions on the site live there.

    Mentions that describe a *retired* command are skipped. The migration table
    in ``partners/index.md`` deliberately names ``deeptutor bot ...`` to explain
    what replaced it; treating that as a claim about the current CLI would make
    the test demand a command the project removed on purpose.
    """
    found = []
    for page in doc_facts.documentation_pages():
        relative = page.relative_to(doc_facts.REPO_ROOT).as_posix()
        prose = doc_facts.page_text(page)
        for match in COMMAND.finditer(prose):
            if _describes_retired_mention(prose, match.start()):
                continue
            found.append((relative, match.group(1), match.group(2) or ""))
        fenced = page.read_text(encoding="utf-8")
        for match in FENCED_COMMAND.finditer(fenced):
            if _describes_retired_mention(fenced, match.start()):
                continue
            found.append((relative, match.group(1), match.group(2) or ""))
    return found


# Words that, near the match, signal the sentence is about a command that no
# longer exists rather than one a reader should run.
RETIRED_MARKERS = (
    "old ",
    "legacy",
    "no longer",
    "removed",
    "deprecated",
    "such as `deeptutor",
    "replaces",
    "replaced",
    "instead of",
    "used to be",
    "formerly",
    "previous",
)


def _describes_retired_mention(text: str, position: int, window: int = 90) -> bool:
    """Whether the match sits in a sentence about a retired command or endpoint."""
    start = max(0, position - window)
    context = text[start : position + window].lower()
    return any(marker in context for marker in RETIRED_MARKERS)


def test_documented_cli_groups_exist() -> None:
    """Every ``deeptutor <group>`` in prose names a registered command group."""
    known = doc_facts.cli_groups()
    unknown: dict[str, set[str]] = {}

    for page, group, _subcommand in _documented_commands():
        if group in known:
            continue
        unknown.setdefault(group, set()).add(page)

    assert not unknown, _format_unknown_groups(unknown, known)


def _format_unknown_groups(unknown: dict[str, set[str]], known: set[str]) -> str:
    lines = ["Documentation references CLI groups that are not registered:", ""]
    for group in sorted(unknown):
        pages = ", ".join(sorted(unknown[group]))
        lines.append(f"  deeptutor {group}  ({pages})")
    lines += ["", f"Registered groups: {', '.join(sorted(known))}"]
    return "\n".join(lines)


def test_documented_cli_subcommands_exist() -> None:
    """Every ``deeptutor <group> <sub>`` in prose names a real subcommand.

    Groups whose registration cannot be read statically are skipped rather than
    failed: an unknown registration shape must not turn into a false report.
    """
    unknown: dict[str, set[str]] = {}

    for page, group, subcommand in _documented_commands():
        if not subcommand or subcommand in NOT_A_SUBCOMMAND:
            continue
        available = doc_facts.cli_subcommands(group)
        if available is None:
            continue
        if subcommand in available:
            continue
        unknown.setdefault(f"{group} {subcommand}", set()).add(page)

    assert not unknown, _format_unknown_subcommands(unknown)


def _format_unknown_subcommands(unknown: dict[str, set[str]]) -> str:
    lines = ["Documentation references CLI subcommands that are not registered:", ""]
    for command in sorted(unknown):
        pages = ", ".join(sorted(unknown[command]))
        lines.append(f"  deeptutor {command}  ({pages})")
    lines += [
        "",
        "Either the command was renamed or removed, or the page needs an update.",
    ]
    return "\n".join(lines)


# ── HTTP routes ─────────────────────────────────────────────────────────────

# A documented API path: starts at /api/ and continues with path segments,
# optionally ending in a path parameter or a common resource suffix.
API_PATH = re.compile(r"/api/[A-Za-z0-9_{}/.-]+")

# Paths that belong to a third-party API the docs describe rather than to
# DeepTutor's own backend. The Mattermost channel speaks Mattermost's v4 API,
# so ``/api/v4/users/me`` is a real endpoint that this repo does not mount.
#
# This is checked against the *page*, not the path alone. A blanket "any
# /api/v1/ is foreign" rule would silently skip the exact mistake this test was
# written for: docs telling readers to POST to our own endpoint under /api/v1,
# which DeepTutor does not mount.
#
# Entry semantics keep the table from turning into a page-wide exemption: an
# entry ending in ``/`` is a prefix, any other entry matches only that exact
# path. So ``/api/v1`` on the providers page exempts the OpenRouter/Lemonade
# base URL but still reports ``/api/v1/chat`` there, which is the mistake this
# test exists to catch.
FOREIGN_API_PAGES = {
    # page: third-party product whose API paths are legitimate there.
    #
    # Both the current and the reorganized path are listed: the docs tree moved
    # from ``partners/`` to ``channels/international/``, and the test has to be
    # correct against whichever layout it runs on.
    # Mattermost needs both forms: the prose warns readers *not* to append
    # ``/api/v4`` to a base URL, and the channel also drives deeper endpoints
    # such as ``/api/v4/users/me``.
    "docs/src/content/docs/channels/international/mattermost.md": ("/api/v4", "/api/v4/"),
    "docs/src/content/docs/zh-cn/channels/international/mattermost.md": ("/api/v4", "/api/v4/"),
    "docs/src/content/docs/partners/mattermost.md": ("/api/v4", "/api/v4/"),
    "docs/src/content/docs/zh-cn/partners/mattermost.md": ("/api/v4", "/api/v4/"),
    # Provider base URLs users paste into settings (BytePlus, Zhipu, VolcEngine,
    # OpenRouter, Lemonade), plus the Ollama embedding profile; third-party
    # routes, not DeepTutor routes.
    "docs/src/content/docs/get-started/providers.md": (
        "/api/v3",
        "/api/paas/v4",
        "/api/coding/v3",
        "/api/v1",
        "/api/embed",
    ),
    "docs/src/content/docs/zh-cn/get-started/providers.md": (
        "/api/v3",
        "/api/paas/v4",
        "/api/coding/v3",
        "/api/v1",
        "/api/embed",
    ),
    # Ollama's endpoint on the host: http://host.docker.internal:11434/api/embed.
    "docs/src/content/docs/get-started/docker.md": ("/api/embed",),
    "docs/src/content/docs/zh-cn/get-started/docker.md": ("/api/embed",),
    # The msteams channel runs its own built-in HTTP server on :3978 (Bot
    # Framework adapter), separate from the FastAPI app.
    "docs/src/content/docs/partners/msteams.md": ("/api/messages",),
    "docs/src/content/docs/zh-cn/partners/msteams.md": ("/api/messages",),
}


def _is_foreign_api_path(page: str, path: str) -> bool:
    """Whether the path is a third-party endpoint documented on this page.

    An entry ending in ``/`` is a prefix; anything else matches that exact path
    only. The asymmetry is deliberate: a third-party API *family* is a prefix,
    while a bare base URL such as ``/api/v1`` must not exempt every path that
    happens to start with it.
    """
    for entry in FOREIGN_API_PAGES.get(page, ()):
        if path == entry:
            return True
        if entry.endswith("/") and path.startswith(entry):
            return True
    return False


def _documented_api_paths() -> list[tuple[str, str]]:
    """Every ``/api/...`` path the docs show, prose and examples alike.

    Examples are included because that is where a reader actually sends the
    request: a ``curl`` block pointing at a route the backend does not mount is
    a worse failure than a prose mention. Frontmatter stays excluded.
    """
    found = []
    for page in doc_facts.documentation_pages():
        relative = page.relative_to(doc_facts.REPO_ROOT).as_posix()
        text = doc_facts.page_body(page)
        for match in API_PATH.finditer(text):
            # A sentence that says the endpoint was removed is history, not a
            # claim that it is callable — the same exemption CLI commands get.
            if _describes_retired_mention(text, match.start()):
                continue
            path = match.group(0).rstrip(".,;:)`'\"")
            # A path may end in a template parameter (``/api/x/{a}/{b}``); strip
            # trailing punctuation must not eat the closing braces.
            while path.endswith("{") or path.endswith("}"):
                path = path[:-1]
            if path.count("/") < 2:
                continue
            found.append((relative, path))
    return found


def test_documented_api_paths_are_served() -> None:
    """Every ``/api/...`` path in prose matches a route the backend mounts.

    This is what caught the four ``/api/v1/...`` references: DeepTutor mounts no
    ``/api/v1`` prefix, so those requests returned 404 while the docs presented
    them as the way to call the endpoint.
    """
    known = doc_facts.api_paths()
    unknown: dict[str, set[str]] = {}

    for page, path in _documented_api_paths():
        if doc_facts.matches_api_path(path, known):
            continue
        if _is_foreign_api_path(page, path):
            continue
        unknown.setdefault(path, set()).add(page)

    assert not unknown, _format_unknown_api_paths(unknown)


def _format_unknown_api_paths(unknown: dict[str, set[str]]) -> str:
    lines = ["Documentation references API paths the backend does not mount:", ""]
    for path in sorted(unknown):
        pages = ", ".join(sorted(unknown[path]))
        lines.append(f"  {path}  ({pages})")
    lines += [
        "",
        "Check the router prefix in deeptutor/modules/manifests/*.json.",
        "A common mistake is adding an /api/v1 segment: no such prefix exists.",
    ]
    return "\n".join(lines)


# ── Versions ────────────────────────────────────────────────────────────────

# A pinned install such as ``"deeptutor[full]==1.7.4"``.
VERSION_PIN = re.compile(r"deeptutor(?:\[[a-z,]+\])?==(\d+\.\d+\.\d+)")


def _pinned_versions() -> list[tuple[str, str]]:
    found = []
    for page in doc_facts.documentation_pages():
        relative = page.relative_to(doc_facts.REPO_ROOT).as_posix()
        for match in VERSION_PIN.finditer(page.read_text(encoding="utf-8")):
            found.append((relative, match.group(1)))
    return found


def test_version_pins_match_project_version() -> None:
    """Install commands pin the version the source tree actually declares."""
    current = doc_facts.project_version()
    stale = [(page, version) for page, version in _pinned_versions() if version != current]

    assert not stale, _format_stale_pins(stale, current)


def _format_stale_pins(stale: list[tuple[str, str]], current: str) -> str:
    lines = [
        f"Documentation pins a version other than {current} (deeptutor/__version__.py):",
        "",
    ]
    for page, version in stale:
        lines.append(f"  {page}: =={version}")
    lines += [
        "",
        "Update the pin, or write the family as 1.7.x when the exact patch",
        "release is not what the page is describing.",
    ]
    return "\n".join(lines)


def test_project_version_is_readable() -> None:
    """Guard the reader itself: a silent parse failure would disable the check."""
    assert re.fullmatch(r"\d+\.\d+\.\d+", doc_facts.project_version())


# ── Frontmatter ─────────────────────────────────────────────────────────────

FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
DESCRIPTION = re.compile(r"^description:\s*\S", re.MULTILINE)


def test_pages_have_descriptions() -> None:
    """Every page sets a frontmatter description.

    Starlight uses it for the meta description and the search result snippet, so
    a missing one degrades both without breaking the build.
    """
    missing = []
    for page in doc_facts.documentation_pages():
        text = page.read_text(encoding="utf-8")
        match = FRONTMATTER.match(text)
        relative = page.relative_to(doc_facts.REPO_ROOT).as_posix()
        if match is None or not DESCRIPTION.search(match.group(1)):
            missing.append(relative)

    assert not missing, "Pages missing a frontmatter description:\n" + "\n".join(
        f"  {page}" for page in missing
    )
