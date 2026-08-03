from deeptutor.runtime.launcher import _apply_single_user_allocator_env


def test_single_user_allocator_defaults_reduce_fragmentation() -> None:
    env: dict[str, str] = {}

    _apply_single_user_allocator_env(env)

    assert env["MALLOC_ARENA_MAX"] == "2"
    assert env["MALLOC_TRIM_THRESHOLD_"] == "131072"


def test_single_user_allocator_preserves_operator_overrides() -> None:
    env = {"MALLOC_ARENA_MAX": "4", "MALLOC_TRIM_THRESHOLD_": "262144"}

    _apply_single_user_allocator_env(env)

    assert env == {"MALLOC_ARENA_MAX": "4", "MALLOC_TRIM_THRESHOLD_": "262144"}
