"""P7【1】chapters_from_kp_tree: canonical KP tree → chapters converter."""

from __future__ import annotations

from deeptutor.services.mastery import chapters_from_kp_tree

# 三章 + 节/目层级：第六章有节、目；第七章直挂目；第八章空章（无子节点）。
KP_TREE = {
    "title": "人教A数学选择性必修第三册",
    "children": [
        {
            "title": "第六章 计数原理",
            "struct_path": "第六章 计数原理",
            "node_id": "ch6",
            "children": [
                {
                    "title": "6.1 分类加法计数原理",
                    "struct_path": "第六章 计数原理/6.1",
                    "node_id": "61",
                    "children": [
                        {
                            "title": "6.1.1 基本计数原理",
                            "struct_path": "第六章 计数原理/6.1/6.1.1",
                            "node_id": "611",
                            "type": "mu",
                        },
                        {
                            "title": "6.1.2 排列数公式",
                            "struct_path": "第六章 计数原理/6.1/6.1.2",
                            "node_id": "612",
                            "type": "mu",
                        },
                    ],
                },
                {
                    "title": "6.2 排列与组合",
                    "struct_path": "第六章 计数原理/6.2",
                    "node_id": "62",
                    "children": [
                        {
                            "title": "6.2.1 组合数",
                            "struct_path": "第六章 计数原理/6.2/6.2.1",
                            "node_id": "621",
                            "type": "mu",
                        },
                    ],
                },
            ],
        },
        {
            "title": "第七章 随机变量及其分布",
            "struct_path": "第七章 随机变量及其分布",
            "node_id": "ch7",
            "children": [
                {
                    "title": "7.1 条件概率",
                    "struct_path": "第七章 随机变量及其分布/7.1",
                    "node_id": "71",
                    "type": "mu",
                },
                {
                    "title": "7.2 离散型随机变量",
                    "struct_path": "第七章 随机变量及其分布/7.2",
                    "node_id": "72",
                    "type": "mu",
                },
            ],
        },
        # 空章：没有子树 → KP 列表为空，仍输出一章（import 侧以章名兜底）。
        {
            "title": "第八章 成对数据的统计分析",
            "struct_path": "第八章 成对数据的统计分析",
            "node_id": "ch8",
        },
        # 非章节点：只作容器，不成为章。
        {
            "title": "附录",
            "struct_path": "附录",
            "node_id": "appendix",
            "children": [
                {"title": "常用公式", "node_id": "appendix_1"},
            ],
        },
    ],
}


class _FakeStorage:
    def __init__(self, tree):
        self._tree = tree

    def load_canonical_kp_tree(self, book_id):
        return self._tree


def test_chapter_nodes_become_chapters_with_subtree_kps() -> None:
    chapters = chapters_from_kp_tree("bk_x", storage=_FakeStorage(KP_TREE))

    assert [c.title for c in chapters] == [
        "第六章 计数原理",
        "第七章 随机变量及其分布",
        "第八章 成对数据的统计分析",
    ]
    # 第六章：整棵子树的标题（节 + 目）按遍历顺序成为 KP。
    assert chapters[0].knowledge_points == [
        "6.1 分类加法计数原理",
        "6.1.1 基本计数原理",
        "6.1.2 排列数公式",
        "6.2 排列与组合",
        "6.2.1 组合数",
    ]
    # 第七章：目直挂章。
    assert chapters[1].knowledge_points == ["7.1 条件概率", "7.2 离散型随机变量"]
    assert chapters[2].knowledge_points == []


def test_chapters_carry_textbook_tree_bridge() -> None:
    chapters = chapters_from_kp_tree("bk_x", storage=_FakeStorage(KP_TREE))

    assert chapters[0].struct_path == "第六章 计数原理"
    assert chapters[0].textbook_node_id == "ch6"
    assert chapters[1].textbook_node_id == "ch7"


def test_nested_chapter_under_unit_is_found() -> None:
    # 单元 → 章 嵌套：容器不匹配章模式，继续向下找。
    tree = {
        "title": "某个分册",
        "children": [
            {
                "title": "第一单元 函数",
                "node_id": "u1",
                "children": [
                    {
                        "title": "第一章 集合与常用逻辑用语",
                        "struct_path": "第一单元 函数/第一章 集合与常用逻辑用语",
                        "node_id": "ch1",
                        "children": [{"title": "1.1 集合", "node_id": "11"}],
                    }
                ],
            }
        ],
    }

    chapters = chapters_from_kp_tree("bk_x", storage=_FakeStorage(tree))

    assert [c.title for c in chapters] == ["第一章 集合与常用逻辑用语"]
    assert chapters[0].knowledge_points == ["1.1 集合"]
    assert chapters[0].textbook_node_id == "ch1"


def test_chapter_consumes_its_subtree_no_double_count() -> None:
    # 章内的嵌套章只作为标题被收进 KP，不再单独成章（避免同一子树重复导入）。
    tree = {
        "title": "root",
        "children": [
            {
                "title": "第一章 总论",
                "node_id": "ch1",
                "children": [
                    {
                        "title": "第二章 分论",
                        "node_id": "ch2",
                        "children": [{"title": "2.1 细则", "node_id": "21"}],
                    }
                ],
            }
        ],
    }

    chapters = chapters_from_kp_tree("bk_x", storage=_FakeStorage(tree))

    assert [c.title for c in chapters] == ["第一章 总论"]
    assert chapters[0].knowledge_points == ["第二章 分论", "2.1 细则"]


def test_chapter_kp_list_capped_at_60() -> None:
    tree = {
        "title": "root",
        "children": [
            {
                "title": "第一章 很多目",
                "node_id": "ch1",
                "children": [{"title": f"1.{i} 目", "node_id": f"m{i}"} for i in range(1, 71)],
            }
        ],
    }

    chapters = chapters_from_kp_tree("bk_x", storage=_FakeStorage(tree))

    assert len(chapters[0].knowledge_points) == 60


def test_missing_or_treeless_book_yields_no_chapters() -> None:
    assert chapters_from_kp_tree("bk_none", storage=_FakeStorage(None)) == []
    # 有树但没有章级节点 → 转换器不编造章。
    flat = {"title": "r", "children": [{"title": "1.1 节", "node_id": "11"}]}
    assert chapters_from_kp_tree("bk_flat", storage=_FakeStorage(flat)) == []


def test_nodes_without_titles_are_skipped() -> None:
    tree = {
        "title": "root",
        "children": [
            {
                "title": "第一章 有杂项",
                "node_id": "ch1",
                "children": [
                    {"node_id": "no_title"},
                    {"title": "", "node_id": "empty"},
                    {"title": "1.1 有名字", "node_id": "11"},
                    None,
                ],
            }
        ],
    }

    chapters = chapters_from_kp_tree("bk_x", storage=_FakeStorage(tree))

    assert chapters[0].knowledge_points == ["1.1 有名字"]
