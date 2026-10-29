import os

from deeptutor.tools import prompting


def test_hint_cache_reuses_parsing_but_not_mutable_objects(monkeypatch, tmp_path):
    monkeypatch.setattr(prompting, "__file__", str(tmp_path / "__init__.py"))
    root = tmp_path / "hints" / "en"
    root.mkdir(parents=True)
    path = root / "example.yaml"
    path.write_text("short_description: first\naliases:\n  - name: alias\n")
    prompting._read_hint_data.cache_clear()
    one = prompting.load_prompt_hints("example")
    one.aliases[0].name = "mutated"
    two = prompting.load_prompt_hints("example")
    assert two.aliases[0].name == "alias"
    assert prompting._read_hint_data.cache_info().hits == 1
    previous = path.stat().st_mtime_ns
    path.write_text("short_description: revised\n")
    os.utime(path, ns=(previous + 1, previous + 1))
    assert prompting.load_prompt_hints("example").short_description == "revised"
