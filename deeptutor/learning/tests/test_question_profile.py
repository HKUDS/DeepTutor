from deeptutor.learning.question_profile import (
    classify_question,
    summarize_questions,
)


def test_classify_definition_question():
    assert "definition" in classify_question("什么是递归？")


def test_classify_mechanism_question():
    kinds = classify_question("为什么递归过深会栈溢出？")
    assert "mechanism" in kinds


def test_classify_debugging_question_keeps_both_signals():
    kinds = classify_question("这段代码报错了，为什么？")
    assert "debugging" in kinds
    assert "mechanism" in kinds


def test_classify_comparison_question():
    assert "comparison" in classify_question("事件驱动和自由循环有什么区别？")


def test_classify_confusion_statement_without_question_mark():
    assert "confusion" in classify_question("没听懂，再讲一遍")


def test_classify_ignores_plain_chatter():
    assert classify_question("好的") == []
    assert classify_question("继续") == []


def test_summarize_counts_and_signals():
    samples = [
        {"kinds": ["definition"], "text": "什么是 A"},
        {"kinds": ["definition"], "text": "A 是什么意思"},
        {"kinds": ["definition"], "text": "B 的定义"},
    ]
    profile = summarize_questions(samples)
    assert profile["total"] == 3
    assert profile["counts"] == {"definition": 3}
    assert profile["dominant"] == ["definition"]
    assert "define_terms" in profile["signals"]
    assert profile["recent"][0]["text"] == "B 的定义"


def test_summarize_holds_back_on_thin_history():
    profile = summarize_questions([{"kinds": ["definition"], "text": "什么是 A"}])
    assert profile["signals"] == []
