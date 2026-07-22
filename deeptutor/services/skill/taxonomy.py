"""
Skill classification taxonomy
=============================

The single Python source of truth for EduHub's skill classification — the
required ``track`` (one-of) plus the optional faceting dimensions
(``language``, ``domains``, ``stages``, ``forms``, ``audiences``). It mirrors
the eduhub web's ``src/data/taxonomy.ts`` (now maintained in zzhtx258/eduhub,
``packages/eduhub-web``) value-by-value so the interactive
``skill publish`` / ``skill update`` flows can prompt with the same labels the
web upload form and ``/api/v1`` validation use.

Values are the lowercase tokens the API expects; the ``zh``/``en`` labels are
display-only. ``domains`` is a two-level tree: a top-level slug (``arts``) or a
dotted child (``arts.instruments``). Anything finer than a child belongs in
free-form ``tags``, not here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Option:
    """One taxonomy choice: the API token plus bilingual display labels."""

    value: str
    zh: str
    en: str

    def label(self, locale: str = "zh") -> str:
        return self.en if locale == "en" else self.zh


@dataclass(frozen=True, slots=True)
class DomainNode:
    """A top-level domain and its dotted children."""

    value: str
    zh: str
    en: str
    children: tuple[Option, ...] = ()

    def label(self, locale: str = "zh") -> str:
        return self.en if locale == "en" else self.zh


# ── required: track (single-select) ───────────────────────────────────────

TRACK_OPTIONS: tuple[Option, ...] = (
    Option("academics", "学业辅导", "Academics"),
    Option("companions", "成长陪伴", "Companions"),
    Option("skills-interests", "兴趣与技能", "Skills & Interests"),
    Option("educators", "教育者工具", "For Educators"),
)

# ── required: language (single-select, defaults to zh) ─────────────────────

LANGUAGE_OPTIONS: tuple[Option, ...] = (
    Option("zh", "中文", "Chinese"),
    Option("en", "英文", "English"),
    Option("ja", "日文", "Japanese"),
    Option("other", "其他", "Other"),
)

# ── optional: stage (multi-select) ─────────────────────────────────────────

STAGE_OPTIONS: tuple[Option, ...] = (
    Option("preschool", "学前", "Preschool"),
    Option("primary", "小学", "Primary"),
    Option("junior-high", "初中", "Junior High"),
    Option("senior-high", "高中", "Senior High"),
    Option("university", "大学", "University"),
    Option("adult", "成人", "Adult"),
)

# ── optional: form (multi-select) ──────────────────────────────────────────

FORM_OPTIONS: tuple[Option, ...] = (
    Option("tutor", "讲解答疑", "Tutoring"),
    Option("practice", "练习陪练", "Practice"),
    Option("feedback", "批改反馈", "Feedback"),
    Option("assessment", "测评诊断", "Assessment"),
    Option("planning", "规划方法", "Planning"),
    Option("companion", "人格陪伴", "Companion"),
    Option("tool", "实用工具", "Tool"),
    Option("reference", "资料内容", "Reference"),
)

# ── optional: audience (multi-select, empty means learners) ────────────────

AUDIENCE_OPTIONS: tuple[Option, ...] = (
    Option("learner", "学习者", "Learners"),
    Option("teacher", "教师", "Teachers"),
    Option("parent", "家长", "Parents"),
)

# ── optional: domains (multi-select, two-level tree) ───────────────────────


def _domain(value: str, zh: str, en: str, children: list[tuple[str, str, str]]) -> DomainNode:
    return DomainNode(
        value=value,
        zh=zh,
        en=en,
        children=tuple(Option(f"{value}.{c}", czh, cen) for c, czh, cen in children),
    )


DOMAIN_TREE: tuple[DomainNode, ...] = (
    _domain(
        "lang-lit",
        "语言与文学",
        "Languages & Literature",
        [
            ("chinese", "中文", "Chinese"),
            ("english", "英语", "English"),
            ("japanese", "日语", "Japanese"),
            ("korean", "韩语", "Korean"),
            ("french", "法语", "French"),
            ("german", "德语", "German"),
            ("spanish", "西语", "Spanish"),
            ("other-lang", "其他语种", "Other Languages"),
            ("reading", "文学与阅读", "Literature & Reading"),
        ],
    ),
    _domain(
        "math",
        "数学与逻辑",
        "Math & Logic",
        [
            ("arithmetic", "启蒙数学", "Early Math"),
            ("algebra", "代数", "Algebra"),
            ("geometry", "几何", "Geometry"),
            ("calculus", "微积分", "Calculus"),
            ("statistics", "概率统计", "Statistics"),
            ("competition", "竞赛数学", "Competition Math"),
            ("logic", "逻辑思维", "Logic"),
        ],
    ),
    _domain(
        "science",
        "自然科学",
        "Natural Sciences",
        [
            ("physics", "物理", "Physics"),
            ("chemistry", "化学", "Chemistry"),
            ("biology", "生物", "Biology"),
            ("earth-astro", "地球与天文", "Earth & Astronomy"),
        ],
    ),
    _domain(
        "computing",
        "计算机与数据",
        "Computing & Data",
        [
            ("programming", "编程入门", "Programming Basics"),
            ("software", "软件开发", "Software Development"),
            ("data-science", "数据科学", "Data Science"),
            ("ai", "人工智能", "AI"),
            ("security", "网络安全", "Security"),
            ("oi", "信息学竞赛", "Competitive Programming"),
        ],
    ),
    _domain(
        "humanities",
        "人文社科",
        "Humanities & Social Sciences",
        [
            ("history", "历史", "History"),
            ("geography", "地理", "Geography"),
            ("civics", "政治与公民", "Civics"),
            ("philosophy", "哲学", "Philosophy"),
            ("psychology", "心理学", "Psychology"),
            ("economics", "经济学", "Economics"),
            ("law", "法律", "Law"),
        ],
    ),
    _domain(
        "arts",
        "艺术与创意",
        "Arts & Creativity",
        [
            ("music-theory", "乐理", "Music Theory"),
            ("instruments", "器乐", "Instruments"),
            ("vocal", "声乐", "Vocal"),
            ("painting", "绘画", "Painting"),
            ("calligraphy", "书法", "Calligraphy"),
            ("design", "设计", "Design"),
            ("photography", "摄影", "Photography"),
            ("creative-writing", "创意写作", "Creative Writing"),
        ],
    ),
    _domain(
        "general",
        "通识素养",
        "General Skills",
        [
            ("speaking", "演讲口才", "Public Speaking"),
            ("debate", "辩论思辨", "Debate"),
            ("writing", "写作表达", "Writing"),
            ("info-literacy", "信息素养", "Information Literacy"),
            ("memory", "记忆与速读", "Memory & Speed Reading"),
        ],
    ),
    _domain(
        "business",
        "商业与职业",
        "Business & Careers",
        [
            ("office", "办公技能", "Office Skills"),
            ("data-analysis", "数据分析", "Data Analysis"),
            ("media", "新媒体运营", "Digital Media"),
            ("management", "管理领导力", "Management"),
            ("finance", "金融会计", "Finance & Accounting"),
            ("career", "求职面试", "Career & Interviews"),
        ],
    ),
    _domain(
        "life",
        "生活与爱好",
        "Life & Hobbies",
        [
            ("cooking", "烹饪美食", "Cooking"),
            ("fitness", "运动健身", "Fitness"),
            ("crafts", "手工园艺", "Crafts & Gardening"),
            ("games", "棋类与游戏", "Board Games"),
            ("personal-finance", "个人理财", "Personal Finance"),
            ("life-skills", "生活技能", "Life Skills"),
        ],
    ),
    _domain(
        "wellbeing",
        "身心健康",
        "Mind & Wellbeing",
        [
            ("mind", "心理与情绪", "Mental & Emotional"),
            ("mindfulness", "正念冥想", "Mindfulness"),
            ("parenting", "家庭教育", "Parenting"),
            ("communication", "人际沟通", "Communication"),
        ],
    ),
    _domain(
        "engineering",
        "工程与创客",
        "Engineering & Making",
        [
            ("robotics", "机器人", "Robotics"),
            ("electronics", "电子电路", "Electronics"),
            ("printing-3d", "3D打印与建模", "3D Printing & Modeling"),
            ("drones", "无人机与航模", "Drones & Models"),
        ],
    ),
)


# ── lookup / validation helpers ────────────────────────────────────────────

TRACK_VALUES: frozenset[str] = frozenset(o.value for o in TRACK_OPTIONS)
LANGUAGE_VALUES: frozenset[str] = frozenset(o.value for o in LANGUAGE_OPTIONS)
STAGE_VALUES: frozenset[str] = frozenset(o.value for o in STAGE_OPTIONS)
FORM_VALUES: frozenset[str] = frozenset(o.value for o in FORM_OPTIONS)
AUDIENCE_VALUES: frozenset[str] = frozenset(o.value for o in AUDIENCE_OPTIONS)

DOMAIN_VALUES: frozenset[str] = frozenset(
    [node.value for node in DOMAIN_TREE]
    + [child.value for node in DOMAIN_TREE for child in node.children]
)


def is_valid_track(value: str) -> bool:
    return value in TRACK_VALUES


def track_label(value: str, locale: str = "zh") -> str:
    for o in TRACK_OPTIONS:
        if o.value == value:
            return o.label(locale)
    return value


def domain_label(value: str, locale: str = "zh") -> str:
    """Leaf label: ``arts.instruments`` -> 器乐, ``arts`` -> 艺术与创意."""
    root = value.split(".")[0]
    for node in DOMAIN_TREE:
        if node.value == root:
            if node.value == value:
                return node.label(locale)
            for child in node.children:
                if child.value == value:
                    return child.label(locale)
    return value


__all__ = [
    "AUDIENCE_OPTIONS",
    "AUDIENCE_VALUES",
    "DOMAIN_TREE",
    "DOMAIN_VALUES",
    "DomainNode",
    "FORM_OPTIONS",
    "FORM_VALUES",
    "LANGUAGE_OPTIONS",
    "LANGUAGE_VALUES",
    "Option",
    "STAGE_OPTIONS",
    "STAGE_VALUES",
    "TRACK_OPTIONS",
    "TRACK_VALUES",
    "domain_label",
    "is_valid_track",
    "track_label",
]
