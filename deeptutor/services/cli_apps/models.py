"""CLI app catalog: one installable command-line tool, and how to install it.

The catalog is a snapshot of the two `CLI-Anything
<https://github.com/HKUDS/CLI-Anything>`_ registries. Three rules shape this
module, and each one exists because the snapshot is **third-party data**:

**We never run the registry's ``install_cmd``.** It is parsed into an
:class:`InstallPlan` whose argv *we* build. A JSON field executed verbatim is
arbitrary command execution driven by a file we periodically re-sync; the entries
already include ``curl … | bash`` and ``cd … && npm link``, which is exactly the
shape that rule refuses. Everything the parser does not recognise becomes
:attr:`InstallKind.UNSUPPORTED` with a reason a person can read — catalogued and
visibly not installable, rather than silently dropped.

**First-party harnesses are pinned.** 66 of the entries install from one
repository, so one reviewed commit pins them all; the parser substitutes that
commit for the unpinned ``git+…`` the registry ships. Entries pointing at a
*different* upstream cannot be pinned from registry data and are labelled
:attr:`AppTrust.THIRD_PARTY` so the choice to install one is an informed one.

**Names that become paths are validated.** ``entry_point`` and ``name`` are used
to build a filesystem path and an executable argv, so both are matched against a
strict pattern here rather than trusted downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
import shlex
from typing import Literal
from urllib.parse import urlsplit

#: An app id becomes a directory name, a tool name suffix and a grant key, so it
#: is the intersection of what all three accept.
APP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

#: An entry point is resolved as a file inside the app's own bin directory. No
#: separators, no leading dot: it must not be able to name anything else.
ENTRY_POINT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

#: The one repository whose harnesses are pinned to a reviewed commit.
HARNESS_REPO = "https://github.com/HKUDS/CLI-Anything.git"

#: Prefix of the tool name an installed app is exposed under. Lives in this
#: dependency-free module because the chat pipeline needs to recognise the name
#: (to inject the turn's sandbox context) without importing the provider, the
#: runner, and the sandbox layer behind them.
TOOL_PREFIX = "cli_"

AppOrigin = Literal["harness", "public"]


class InstallKind(str, Enum):
    """How an app is installed, in terms of a command we build ourselves."""

    #: ``pip install git+<HARNESS_REPO>@<pin>#subdirectory=…`` — first-party.
    PINNED_HARNESS = "pinned-harness"
    #: ``pip install git+<other repo>[@ref]`` — third-party, pinned only if the
    #: registry itself named a ref.
    PIP_GIT = "pip-git"
    #: ``pip install <name>`` from PyPI.
    PIP = "pip"
    #: ``npm install -g --prefix <app dir>`` — needs node in the runtime image.
    NPM = "npm"
    #: Catalogued for discovery, not installable here. Carries a reason.
    UNSUPPORTED = "unsupported"


class AppTrust(str, Enum):
    """Where the code comes from — the only honest input to "should I install?"."""

    #: From the reviewed CLI-Anything commit this build pins.
    FIRST_PARTY = "first-party"
    #: From some other upstream, at whatever version it publishes today.
    THIRD_PARTY = "third-party"


class AppRuntime(str, Enum):
    """Which interpreter the installed executable needs at run time."""

    PYTHON = "python"
    NODE = "node"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class InstallPlan:
    """The install we would perform, as data.

    ``argv`` is built by :func:`plan_install` and is the *only* thing the
    installer runs. ``reason`` is set only for :attr:`InstallKind.UNSUPPORTED`
    and is written for the administrator reading the store, not for a log.
    """

    kind: InstallKind
    runtime: AppRuntime
    trust: AppTrust
    #: pip requirement or npm package — what gets installed, for display.
    target: str = ""
    reason: str = ""

    @property
    def installable(self) -> bool:
        return self.kind is not InstallKind.UNSUPPORTED

    @property
    def pinned(self) -> bool:
        """Whether this install resolves to one fixed revision.

        Surfaced rather than kept internal: "installs whatever that repository's
        default branch holds today" is the single most useful thing to know
        before installing somebody else's code, and it is invisible otherwise.
        """
        if self.kind is InstallKind.PINNED_HARNESS:
            return True
        if self.kind is InstallKind.PIP_GIT:
            # `git+<url>@<ref>` — a ref the registry itself named. Looked for in
            # the *path* so a ``user@host`` authority does not read as a pin.
            url = urlsplit(self.target.removeprefix("git+").partition("#")[0])
            return "@" in url.path
        return False


@dataclass(frozen=True, slots=True)
class CliAppEntry:
    """One app in the catalog."""

    id: str
    display_name: str
    description: str
    category: str
    origin: AppOrigin
    entry_point: str
    install: InstallPlan
    version: str = ""
    requires: str = ""
    homepage: str = ""
    source_url: str = ""
    #: Where the app's agent-facing doc lives. A repo-relative path for a
    #: harness, a URL for several public entries, or "" — read from the
    #: *installed* package at load time, never fetched.
    doc_ref: str = ""
    install_notes: str = ""

    def __post_init__(self) -> None:
        if APP_ID_RE.match(self.id) is None:
            raise ValueError(f"Invalid CLI app id {self.id!r}: must match {APP_ID_RE.pattern}")
        if not self.display_name.strip():
            raise ValueError(f"CLI app {self.id!r} needs a display name")
        if not self.description.strip():
            raise ValueError(f"CLI app {self.id!r} needs a description")
        # An installable app must name an executable we can resolve; an
        # unsupported one need not, since nothing will ever run it.
        if self.install.installable and ENTRY_POINT_RE.match(self.entry_point) is None:
            raise ValueError(
                f"CLI app {self.id!r} has an unusable entry point {self.entry_point!r}: "
                f"must match {ENTRY_POINT_RE.pattern}"
            )

    @property
    def trust(self) -> AppTrust:
        return self.install.trust


def plan_install(
    *,
    app_id: str,
    install_cmd: str,
    package_manager: str,
    harness_pin: str,
) -> InstallPlan:
    """Turn a registry ``install_cmd`` into a plan, or refuse it with a reason.

    Recognition is deliberately narrow and shape-based: the command is tokenised
    and matched against the four forms we know how to run safely. Anything with a
    pipe, a redirect, a ``cd``, an ``&&``, or a package manager we do not have is
    refused — a command we half-understand is the one that gets executed wrongly.
    """
    text = (install_cmd or "").strip()
    if not text:
        return InstallPlan(
            kind=InstallKind.UNSUPPORTED,
            runtime=AppRuntime.NONE,
            trust=AppTrust.THIRD_PARTY,
            reason=(
                "Ships with its host application rather than being installed, so "
                "there is nothing for DeepTutor to install."
            ),
        )

    if any(token in text for token in ("&&", "||", "|", ">", ";", "$(", "`")):
        return InstallPlan(
            kind=InstallKind.UNSUPPORTED,
            runtime=AppRuntime.NONE,
            trust=AppTrust.THIRD_PARTY,
            reason=(
                "Its published install command is a shell script rather than a "
                "single package install. DeepTutor builds every install command "
                "itself and will not run a shell pipeline from the catalog."
            ),
        )

    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = []
    if not tokens:
        return _unsupported_manager(package_manager or "unknown")

    if tokens[0] == "pip" and tokens[1:2] == ["install"]:
        return _plan_pip(tokens[2:], app_id=app_id, harness_pin=harness_pin)
    # `python3 -m pip install …` is the same install spelled differently.
    if tokens[:4] in (["python3", "-m", "pip", "install"], ["python", "-m", "pip", "install"]):
        return _plan_pip(tokens[4:], app_id=app_id, harness_pin=harness_pin)
    if tokens[0] == "npm" and tokens[1:2] == ["install"]:
        return _plan_npm(tokens[2:])
    return _unsupported_manager(package_manager or tokens[0])


def _plan_pip(args: list[str], *, app_id: str, harness_pin: str) -> InstallPlan:
    """Plan a pip install from its arguments (everything after ``pip install``)."""
    requirements = [arg for arg in args if not arg.startswith("-")]
    if len(requirements) != 1:
        return InstallPlan(
            kind=InstallKind.UNSUPPORTED,
            runtime=AppRuntime.NONE,
            trust=AppTrust.THIRD_PARTY,
            reason=(
                "Its published install command installs more than one package, "
                "which DeepTutor does not model as a single app."
            ),
        )
    requirement = requirements[0]

    if requirement.startswith("git+"):
        url, _, fragment = requirement[4:].partition("#")
        base, _, ref = url.partition("@")
        if base == HARNESS_REPO:
            # Substitute our reviewed commit for the unpinned URL the registry
            # ships. This is the whole reason the parser exists.
            subdirectory = fragment.partition("subdirectory=")[2]
            if not subdirectory:
                subdirectory = f"{app_id}/agent-harness"
            return InstallPlan(
                kind=InstallKind.PINNED_HARNESS,
                runtime=AppRuntime.PYTHON,
                trust=AppTrust.FIRST_PARTY,
                target=f"git+{HARNESS_REPO}@{harness_pin}#subdirectory={subdirectory}",
            )
        # A third-party repository. Keep whatever ref it named; there is nothing
        # to pin it to if it named none.
        return InstallPlan(
            kind=InstallKind.PIP_GIT,
            runtime=AppRuntime.PYTHON,
            trust=AppTrust.THIRD_PARTY,
            target=requirement,
        )

    return InstallPlan(
        kind=InstallKind.PIP,
        runtime=AppRuntime.PYTHON,
        trust=AppTrust.THIRD_PARTY,
        target=requirement,
    )


def _plan_npm(args: list[str]) -> InstallPlan:
    packages = [arg for arg in args if not arg.startswith("-")]
    if len(packages) != 1:
        return InstallPlan(
            kind=InstallKind.UNSUPPORTED,
            runtime=AppRuntime.NONE,
            trust=AppTrust.THIRD_PARTY,
            reason=(
                "Its published install command installs more than one package, "
                "which DeepTutor does not model as a single app."
            ),
        )
    return InstallPlan(
        kind=InstallKind.NPM,
        runtime=AppRuntime.NODE,
        trust=AppTrust.THIRD_PARTY,
        target=packages[0],
    )


def _unsupported_manager(manager: str) -> InstallPlan:
    return InstallPlan(
        kind=InstallKind.UNSUPPORTED,
        runtime=AppRuntime.NONE,
        trust=AppTrust.THIRD_PARTY,
        reason=(
            f"Installs with {manager}, which the DeepTutor runtime image does not "
            "carry. Install it into the sandbox image yourself if you need it."
        ),
    )


__all__ = [
    "APP_ID_RE",
    "ENTRY_POINT_RE",
    "HARNESS_REPO",
    "TOOL_PREFIX",
    "AppOrigin",
    "AppRuntime",
    "AppTrust",
    "CliAppEntry",
    "InstallKind",
    "InstallPlan",
    "plan_install",
]
