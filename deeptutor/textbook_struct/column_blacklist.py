"""Closed vocabulary of textbook feature-column names (layer 0).

These are recurring textbook activity/column names — MinerU often classifies
them as ``title`` blocks, but they are never chapter headings. The list is
closed on purpose: no fuzzy matching, to avoid swallowing real titles.
Append new names as new textbook editions introduce new column types.
"""

COLUMN_BLACKLIST: frozenset[str] = frozenset(
    {
        # civics / politics
        "探究与分享",
        "相关链接",
        "专家点评",
        "名词点击",
        "观点一",
        "观点二",
        "观点三",
        # Chinese / English
        "学习提示",
        "单元导语",
        "思考与探究",
        # math / physics / chemistry / biology
        "思考",
        "探究",
        "实验",
        "练习",
        "习题",
        "复习与巩固",
        "本章小结",
        "信息技术应用",
        "阅读与思考",
        "观察与思考",
        # geography / history
        "问题研究",
        "自学窗",
        "活动",
        "案例",
        "知识窗",
    }
)
