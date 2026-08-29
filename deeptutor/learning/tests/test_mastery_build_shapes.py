"""``mastery_build`` must read the module tree real models actually emit.

The tool schema asks for ``[{name, knowledge_points: [{name, type}]}]``, but
DeepTutor runs on whatever model the learner brings. The variants below were
observed in the wild (#1019) on gemma4, qwen3.5 and gpt-oss; every one of them
used to be dropped silently, leaving an empty path in Learning Space with no
error the learner could see.
"""

from __future__ import annotations

from deeptutor.capabilities.mastery.tools import _parse_modules


def _names(modules) -> list[tuple[str, list[str]]]:
    return [(m.name, [kp.name for kp in m.knowledge_points]) for m in modules]


def test_canonical_shape_is_unchanged() -> None:
    modules, error = _parse_modules(
        [{"name": "Basics", "knowledge_points": [{"name": "Number bases", "type": "memory"}]}],
        "p1",
        0,
    )
    assert error is None
    assert _names(modules) == [("Basics", ["Number bases"])]
    assert modules[0].knowledge_points[0].type.value == "memory"


def test_objectives_key_with_title_instead_of_name() -> None:
    """Variant 1: wrong top-level key, ``title`` rather than ``name``."""
    modules, error = _parse_modules(
        {
            "objectives": [
                {
                    "title": "Layer basics",
                    "objectives": [{"id": "l1", "title": "Layer order", "type": "concept"}],
                }
            ]
        },
        "p1",
        0,
    )
    assert error is None
    assert _names(modules) == [("Layer basics", ["Layer order"])]


def test_knowledge_points_as_bare_strings() -> None:
    """Variant 2: knowledge points arrive as plain strings."""
    modules, error = _parse_modules(
        [{"name": "Frames", "knowledge_points": ["concept_framework", "Data model"]}],
        "p1",
        0,
    )
    assert error is None
    assert _names(modules) == [("Frames", ["Concept Framework", "Data model"])]


def test_knowledge_points_carrying_only_an_id() -> None:
    """Variant 3: knowledge-point dicts with nothing but an id."""
    modules, error = _parse_modules(
        [{"name": "Selection", "knowledge_points": [{"id": "quick-mask"}]}],
        "p1",
        0,
    )
    assert error is None
    assert _names(modules) == [("Selection", ["Quick Mask"])]


def test_flat_objective_list_without_a_module_layer() -> None:
    """Variant 4: no module layer at all — one implicit module holds them."""
    modules, error = _parse_modules(
        [
            {"id": "kp1", "title": "Bit shifting", "type": "procedure"},
            {"id": "kp2", "title": "Two's complement", "type": "concept"},
        ],
        "p1",
        0,
        fallback_module_name="Computer architecture",
    )
    assert error is None
    assert _names(modules) == [("Computer architecture", ["Bit shifting", "Two's complement"])]


def test_cjk_names_are_never_reshaped() -> None:
    """Humanising is for ASCII identifiers only; CJK names pass through."""
    modules, error = _parse_modules(
        [{"name": "数制转换", "knowledge_points": [{"name": "二进制转十六进制"}]}],
        "p1",
        0,
    )
    assert error is None
    assert _names(modules) == [("数制转换", ["二进制转十六进制"])]


def test_ids_are_still_server_generated_and_sequential() -> None:
    modules, _ = _parse_modules(
        [
            {"name": "A", "knowledge_points": ["one", "two"]},
            {"name": "B", "knowledge_points": ["three"]},
        ],
        "path",
        0,
    )
    assert [m.id for m in modules] == ["path_m0", "path_m1"]
    assert [kp.id for kp in modules[0].knowledge_points] == ["path_m0_kp0", "path_m0_kp1"]
    assert [kp.id for kp in modules[1].knowledge_points] == ["path_m1_kp0"]


def test_unreadable_input_explains_the_expected_shape() -> None:
    """The failure must name the schema, not just say 'no valid modules'."""
    modules, error = _parse_modules([], "p1", 0)
    assert modules == []
    assert error is not None
    assert "knowledge_points" in error and "memory|procedure|concept|design" in error


def test_modules_without_any_readable_objective_are_rejected() -> None:
    modules, error = _parse_modules(
        [{"name": "Empty", "knowledge_points": [{"type": "memory"}]}], "p1", 0
    )
    assert modules == []
    assert error is not None


def test_flat_objectives_named_only_by_description() -> None:
    """Variant 4 exactly as reported: description + id + type, no name key."""
    modules, error = _parse_modules(
        [
            {"id": "kp1", "description": "Convert between number bases", "type": "procedure"},
            {"id": "kp2", "description": "Read a truth table", "type": "concept"},
        ],
        "p1",
        0,
        fallback_module_name="Digital logic",
    )
    assert error is None
    assert _names(modules) == [
        ("Digital logic", ["Convert between number bases", "Read a truth table"])
    ]


def test_a_real_name_always_beats_a_description_or_id() -> None:
    modules, _ = _parse_modules(
        [
            {
                "name": "Bases",
                "knowledge_points": [
                    {"name": "Hex", "description": "a much longer explanation", "id": "kp_9"}
                ],
            }
        ],
        "p1",
        0,
    )
    assert _names(modules) == [("Bases", ["Hex"])]
