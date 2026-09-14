"""判分1.5 等价类：集合无序 / 多解答案 / 区间并集。

教研审计『每卷必有』级缺口：``grade_answer`` 对集合、多解、区间并集这类
答案形态只能按字符串比较，顺序不同的等价答案被判错。本文件验证归一化层
新增的三类等价类（等价对 + 不等价对），并守护既有语义不被破坏：

1. 集合无序 ``{1,2}`` vs ``{2,1}``；``{1,2}`` vs ``{1,3}`` 必须判错。
2. 多解答案 ``±2`` / ``'+2或-2'`` / ``'-2或+2'`` / ``'-1,2'`` / ``'2,-1'``；
   ``±2`` vs ``2`` 必须判错。
3. 区间并集 ``(-∞,1)∪(3,+∞)`` vs ``'x<1或x>3'``。

所有断言与 tests/learning/test_grading_math_equivalence.py 的既有语义一致
（fail-closed：识别不了的形态继续走旧字符串/相似度路径）。
"""

from __future__ import annotations

import pytest

from deeptutor.learning.grading import _normalize_math_answer, grade_answer


class TestBracedSetUnordered:
    """① 集合无序：{a, b, c} 元素归一后排序比较。"""

    def test_reversed_order_is_equal(self):
        assert grade_answer("{1,2}", "{2,1}", "short") is True
        assert grade_answer("{2,1}", "{1,2}", "short") is True

    def test_element_normalization_inside_braces(self):
        # 元素走既有 _normalize_math_answer：1/2 与 0.5 在集合内也等价。
        assert grade_answer("{1, 1/2}", "{0.5, 1}", "short") is True

    def test_three_element_rotation(self):
        assert grade_answer("{1,2,3}", "{3,1,2}", "short") is True

    def test_fullwidth_braces_and_commas(self):
        assert grade_answer("｛1，2｝", "{2,1}", "short") is True

    def test_empty_set(self):
        assert grade_answer("{}", "{}", "short") is True

    def test_non_equivalent_elements(self):
        # 教研审计硬性要求：{1,2} vs {1,3} 必须判错。
        assert grade_answer("{1,2}", "{1,3}", "short") is False
        assert grade_answer("{1,2,3}", "{1,2}", "short") is False

    def test_duplicates_not_collapsed(self):
        # 多重集语义：不折叠重复元素（fail-closed）。
        assert grade_answer("{1,1,2}", "{1,2}", "short") is False

    def test_braced_set_not_equal_to_bare_number(self):
        assert grade_answer("{1}", "1", "short") is False

    def test_set_builder_not_claimed_yet(self):
        # TODO(判分1.5)：{x|x>1} 与区间 (1,+∞) 暂不做语义等价。
        assert grade_answer("{x|x>1}", "(1,+∞)", "short") is False
        assert _normalize_math_answer("{x|x>1}")[0] != "set"


class TestMultiSolutionAnswers:
    """② 多解答案：识别分隔符（，,、或 空格）和 ± 前缀，拆解集合排序比较。"""

    def test_audit_pm_cluster(self):
        # ± 前缀与 或/正负号拼写的等价簇：{2, -2}。
        forms = ["±2", "+2或-2", "-2或+2", "2,-2", "-2,2"]
        for expected in forms:
            for user in forms:
                assert grade_answer(user, expected, "short") is True, (
                    f"{user!r} should equal {expected!r}"
                )

    def test_audit_comma_list_order(self):
        # 逗号分隔的解列表顺序无关：'-1,2' vs '2,-1'（元素 -1 与 2）。
        assert grade_answer("-1,2", "2,-1", "short") is True
        assert grade_answer("2,-1", "-1,2", "short") is True

    def test_other_separators(self):
        assert grade_answer("2、-2", "±2", "short") is True
        assert grade_answer("2 -2", "±2", "short") is True
        assert grade_answer("1,2", "2,1", "short") is True

    def test_plus_minus_fraction(self):
        assert grade_answer("±1/2", "-0.5或0.5", "short") is True

    def test_algebra_wrapper_before_split(self):
        assert grade_answer("x=1或x=2", "2,1", "short") is True

    def test_plus_minus_vs_single_value_is_wrong(self):
        # 教研审计硬性要求：±2 vs 2 必须判错。
        assert grade_answer("±2", "2", "short") is False
        assert grade_answer("2", "±2", "short") is False

    def test_different_solution_sets_are_wrong(self):
        assert grade_answer("±2", "±3", "short") is False
        assert grade_answer("-1,2", "1,2", "short") is False

    def test_duplicates_not_collapsed(self):
        assert grade_answer("1,1,2", "1,2", "short") is False

    def test_slash_is_fraction_bar_not_separator(self):
        # 回归守卫："/" 是分数线，绝不能把 1/2 拆成解集 {1,2}。
        assert grade_answer("1/2", "0.5", "short") is True
        assert grade_answer("1/2", "1/3", "short") is False

    def test_unparseable_element_rejects_claim(self):
        # 任一解元素无法归一 → 不认领 → 走旧路径（fail-closed）。
        assert grade_answer("1或x", "1", "short") is False


class TestIntervalUnion:
    """③ 区间并集：∪ 连接区间串 与 或 分隔不等式组 比较。"""

    def test_union_vs_inequality_group(self):
        assert grade_answer("(-∞,1)∪(3,+∞)", "x<1或x>3", "short") is True
        assert grade_answer("x<1或x>3", "(-∞,1)∪(3,+∞)", "short") is True

    def test_reversed_branch_order(self):
        assert grade_answer("(3,+∞)∪(-∞,1)", "x<1或x>3", "short") is True

    def test_closed_bounds(self):
        assert grade_answer("(-∞,1]∪(3,+∞)", "x≤1或x>3", "short") is True
        assert grade_answer("(-∞,1)∪[3,+∞)", "x<1或x≥3", "short") is True

    def test_interval_joined_with_or(self):
        assert grade_answer("(-∞,1)或(3,+∞)", "x<1或x>3", "short") is True

    def test_non_equivalent_branches(self):
        assert grade_answer("(-∞,1)∪(3,+∞)", "x<1或x<3", "short") is False
        assert grade_answer("(-∞,1)∪(3,+∞)", "(-∞,2)∪(3,+∞)", "short") is False

    def test_missing_branch_is_wrong(self):
        assert grade_answer("(-∞,1)∪(3,+∞)", "(-∞,1)", "short") is False
        assert grade_answer("x<1或x>3", "x<1", "short") is False

    def test_single_inequality_stays_expression(self):
        # 单支不等式不进并集类，保持旧路径（x<1 仍是 expr）。
        assert _normalize_math_answer("x<1") == ("expr", "x<1")
        assert grade_answer("x<1", "x<1", "short") is True

    def test_or_list_of_numbers_not_a_union(self):
        # 或 分隔的纯数字列表落到多解类，而不是并集类。
        assert grade_answer("1或2", "2,1", "short") is True


class TestCollectionFailClosedGuards:
    """④ 守护：新增等价类不改变既有语义（fail-closed/fail-open 方向不变）。"""

    @pytest.mark.parametrize(
        ("user", "expected", "want"),
        [
            ("1/2", "0.5", True),          # 分数
            ("√2/2", "二分之√2", True),     # 根式
            ("y=2x+1", "2x+1", True),      # 代数
            ("1<x<2", "(1,2)", True),      # 区间
            ("photosynthesis", "photosynthesis", True),  # 非数学走旧路径
            ("half of one", "0.5", False),  # 仅一侧是数学 → 判错
            ("{1,2}", "1,2", False),        # 集合形态与裸列表不混同
            ("±2", "±2", True),             # 两侧同为多解 → 等
        ],
    )
    def test_existing_semantics_unchanged(self, user: str, expected: str, want: bool):
        assert grade_answer(user, expected, "short") is want
