from deeptutor.services.llm.config import uses_max_completion_tokens


def test_gpt5_series_uses_max_completion_tokens():
    assert uses_max_completion_tokens("gpt-5.6-terra")
    assert uses_max_completion_tokens("gpt-5.6-luna")
    assert uses_max_completion_tokens("gpt-5.6-sol")


def test_o_series_uses_max_completion_tokens():
    assert uses_max_completion_tokens("o1")
    assert uses_max_completion_tokens("o3-mini")


def test_older_models_use_max_tokens():
    assert not uses_max_completion_tokens("deepseek-v4-flash")
    assert not uses_max_completion_tokens("gpt-3.5-turbo")
