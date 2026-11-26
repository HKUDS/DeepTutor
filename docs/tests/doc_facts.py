"""Static readers for the facts the documentation asserts.

The doc contract tests compare pages under ``docs/`` against the source tree.
Everything here is parsed with :mod:`ast` and plain JSON rather than by
importing DeepTutor, because the docs CI job does not install the project's
runtime dependencies (Typer, FastAPI, the LLM SDKs). Parsing also keeps the
checks honest about one thing: they assert what the code *declares*, not what
happens to be enabled in the current environment.

Nothing here enforces policy. Each reader returns a plain set so the test can
decide what to compare and how to report it.
"""

from __future__ import annotations

import ast
import json
import re
from functools import cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_ROOT = REPO_ROOT / "docs" / "src" / "content" / "docs"
CLI_ROOT = REPO_ROOT / "deeptutor_cli"
MANIFEST_ROOT = REPO_ROOT / "deeptutor" / "modules" / "manifests"


@cache
def documentation_pages(locale: str = "en") -> list[Path]:
    """Every Markdown page, optionally restricted to one locale."""
    pages = sorted(
        path for pattern in ("*.md", "*.mdx") for path in DOCS_ROOT.rglob(pattern)
    )
    if locale == "zh":
        return [page for page in pages if "zh-cn" in page.relative_to(DOCS_ROOT).parts]
    return [page for page in pages if "zh-cn" not in page.relative_to(DOCS_ROOT).parts]


def page_text(page: Path) -> str:
    """Page source with frontmatter and fenced code blocks removed.

    Documentation deliberately shows commands that do not exist in every
    install ("run this after enabling the module"). Those belong in fenced
    examples, which readers understand as illustrative. Prose is where a stale
    name is an error, so the contract checks only see prose.

    Frontmatter is stripped because its ``description`` is a sentence for
    search engines, not a command reference: "Common deeptutor commands" would
    otherwise be read as a ``deeptutor commands`` invocation.
    """
    text = page.read_text(encoding="utf-8")
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.DOTALL)
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


# ── CLI commands ────────────────────────────────────────────────────────────


def _typer_names(path: Path) -> set[str]:
    """Command and group names registered by one module.

    Covers the three shapes the CLI uses:

    * ``app.add_typer(group, name="kb")``            → ``kb``
    * ``@app.command("book")``                       → ``book``
    * ``@app.command()`` on ``def stop``             → ``stop`` (Typer's default)
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        attribute = func.attr if isinstance(func, ast.Attribute) else None

        if attribute == "add_typer":
            for keyword in node.keywords:
                if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                    names.add(str(keyword.value.value))
        elif attribute == "command":
            literal = next(
                (
                    argument
                    for argument in node.args
                    if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
                ),
                None,
            )
            if literal is not None:
                names.add(str(literal.value))

    # A bare ``@app.command()`` decorator takes its name from the function, so
    # walk the module body rather than only the decorator calls.
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if not isinstance(func, ast.Attribute) or func.attr != "command":
                continue
            if not decorator.args and not decorator.keywords:
                names.add(node.name.replace("_", "-"))
            else:
                names.add(node.name.replace("_", "-"))

    return names


@cache
def cli_groups() -> set[str]:
    """Top-level ``deeptutor <group>`` names.

    Three sources count as top-level:

    * ``add_typer(group, name="kb")`` in ``main.py``
    * commands declared under ``commands`` in a module manifest
    * ``register_X(app)`` in ``main.py``, where the imported ``register``
      function declares its commands on the root app (``init``, ``doctor``)

    Group modules also define their own subcommands, which must not leak into
    this set — otherwise ``deeptutor add-md`` looks like a valid invocation.
    """
    groups = _typer_names(CLI_ROOT / "main.py")
    groups |= _register_function_commands(CLI_ROOT / "main.py")

    for manifest in MANIFEST_ROOT.glob("*.json"):
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        for command in payload.get("commands", []):
            name = command.get("name")
            if name:
                groups.add(str(name))

    return groups


def _register_function_commands(main_module: Path) -> set[str]:
    """Commands that ``main.py`` attaches to the root app via ``register_*``.

    ``register_init(app)`` and ``register_doctor(app)`` are the two cases: the
    imported module's ``register`` function calls ``app.command("init")`` on the
    Typer app it is handed, so the name lives in that module, not in ``main.py``.
    """
    tree = ast.parse(main_module.read_text(encoding="utf-8"))

    imported: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            # ``main.py`` uses relative imports (``from .init_cmd import
            # register``), so the module name is relative to ``deeptutor_cli``
            # when ``level`` is 1.
            if node.level:
                module = f"{main_module.parent.name}.{node.module}"
            else:
                module = node.module
            for alias in node.names:
                if alias.name == "register":
                    imported[alias.asname or alias.name] = module

    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Name) or not imported.get(func.id):
            continue
        # ``register_init(app)`` targets the root app only when the argument is
        # the module-level ``app``; the group registrations pass a sub-app.
        if not node.args or not isinstance(node.args[0], ast.Name):
            continue
        if node.args[0].id != "app":
            continue
        module = imported[func.id]
        target = REPO_ROOT / (module.replace(".", "/") + ".py")
        if target.is_file():
            names |= _typer_names(target)

    return names


@cache
def cli_subcommands(group: str) -> set[str] | None:
    """Subcommands of ``group``, or ``None`` when they cannot be determined.

    ``None`` is not "no subcommands": it means this reader has no static view
    (the group is mounted from a module manifest, or lives in a file whose
    registration shape is not one of the recognised forms). Callers must skip
    rather than fail, so an unknown shape never produces a false positive.
    """
    module = CLI_ROOT / f"{group}.py"
    candidates = [module, CLI_ROOT / f"{group}_cmd.py", CLI_ROOT / f"{group}s.py"]
    for candidate in candidates:
        if candidate.is_file():
            found = _typer_names(candidate)
            # ``add_typer`` names in a group module are its subcommands, but a
            # module may also register a top-level group of its own.
            return found - {group} or None
    return None


# ── HTTP routes ─────────────────────────────────────────────────────────────


def _router_prefix(path: Path) -> str:
    """``APIRouter(prefix="/api/memory")`` for one router module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "APIRouter"):
            continue
        for keyword in node.keywords:
            if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant):
                return str(keyword.value.value)
    return ""


def _declared_paths(path: Path) -> set[str]:
    """Paths from ``@router.get("/x")``-style decorators in one module."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    verbs = {"get", "post", "put", "patch", "delete", "head", "options", "websocket"}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if not isinstance(func, ast.Attribute) or func.attr not in verbs:
                continue
            for argument in decorator.args:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    found.add(argument.value)
    return found


@cache
def api_paths() -> set[str]:
    """Every HTTP path the backend mounts, prefix included.

    Prefixes live either on ``APIRouter(prefix=...)`` in the router module or
    in the module manifests that ``module_routes.py`` mounts. Both are read so
    the set matches what FastAPI actually serves.
    """
    router_dir = REPO_ROOT / "deeptutor" / "api" / "routers"
    paths: set[str] = set()

    for path in router_dir.glob("*.py"):
        prefix = _router_prefix(path)
        for declared in _declared_paths(path):
            paths.add(_join(prefix, declared))

    # Manifests mount routers with their own prefix, which can differ from the
    # router module's (``/api/settings`` vs ``/api/settings/mcp``). The declared
    # paths still come from the router module the reference names, so join the
    # manifest prefix with that module's own paths.
    for manifest in MANIFEST_ROOT.glob("*.json"):
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        for route in payload.get("routes", []):
            options = route.get("options") or {}
            prefix = options.get("prefix")
            if not isinstance(prefix, str) or not prefix.startswith("/"):
                continue
            reference = str(route.get("reference", ""))
            module_name = reference.split(":", 1)[0]
            module_path = REPO_ROOT / (module_name.replace(".", "/") + ".py")
            if module_path.is_file():
                for declared in _declared_paths(module_path):
                    paths.add(_join(prefix, declared))
            else:
                # Keep the bare prefix so a documented page-level path still
                # matches even when the router module cannot be located.
                paths.add(prefix)

    return paths


def _join(prefix: str, suffix: str) -> str:
    if not prefix:
        return suffix or "/"
    if not suffix or suffix == "/":
        return prefix
    return prefix.rstrip("/") + "/" + suffix.lstrip("/")


def matches_api_path(documented: str, known: set[str]) -> bool:
    """Whether a documented path could be served by one of ``known``.

    A documented path may use a placeholder that spans several segments
    (``/api/plugins/{plugin_id}/{plugin_path}`` where the router mounts
    ``/api/plugins/{plugin_id}/pages/{extension_id}``), so a trailing ``{...}``
    is allowed to absorb the remainder on either side.
    """
    """Whether a path written in the docs could be served by one of ``known``.

    Path parameters in prose are placeholder text (``{kb_name}``, ``{id}``), and
    a documented path may name a sub-resource the router declares as a parameter
    (``/api/partners/{partner_id}/channels``). Match segment by segment, letting
    any ``{...}`` on either side absorb the other's segment.
    """
    documented_segments = [segment for segment in documented.split("/") if segment]
    for candidate in known:
        known_segments = [segment for segment in candidate.split("/") if segment]
        if _path_matches(documented_segments, known_segments):
            return True
    return False


def _path_matches(documented: list[str], known: list[str]) -> bool:
    """Segment-by-segment match, where ``{...}`` absorbs exactly one segment.

    A placeholder normally stands for one path parameter. Documentation also
    abbreviates a deeper resource with a single placeholder
    (``/api/plugins/{plugin_id}/{plugin_path}`` for a router that mounts
    ``/api/plugins/{plugin_id}/pages/{extension_id}``); that is allowed only
    when the placeholder is the *final* documented segment, and only the
    documented side is abbreviated — a real extra segment such as ``v1`` in
    ``/api/v1/...`` never matches a shorter known path.
    """
    if len(documented) <= len(known):
        return len(documented) == len(known) and all(
            _segment_matches(left, right)
            for left, right in zip(documented, known)
        )
    # Documented is longer than any known path: only acceptable when its tail is
    # a single placeholder standing in for the remaining known segments.
    head = documented[: len(known)]
    if not all(_segment_matches(left, right) for left, right in zip(head, known)):
        return False
    tail = documented[len(known) :]
    return len(tail) == 1 and tail[0].startswith("{")


def _segment_matches(documented: str, known: str) -> bool:
    if documented == known:
        return True
    if documented.startswith("{") and documented.endswith("}"):
        return True
    if known.startswith("{") and known.endswith("}"):
        return True
    return False


# ── Versions ────────────────────────────────────────────────────────────────


@cache
def project_version() -> str:
    """``__version__`` from `deeptutor/__version__.py`."""
    module = REPO_ROOT / "deeptutor" / "__version__.py"
    tree = ast.parse(module.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in node.targets
        ):
            if isinstance(node.value, ast.Constant):
                return str(node.value.value)
    raise RuntimeError("deeptutor/__version__.py does not define __version__")
