"""Skill 掌握度门禁软校验（方案 B，悦学 fork 新增）。

在 assistant 完整回复生成后、落库前做一次软校验：
如果回复出现了"夸奖"或"换题"话术但没有报分，判定为 ⑧NEXT 结算被跳过，
追加一条 system 补救消息让模型补报分（不重跑整轮）。

设计要点（对齐 HS 方案 B 细则）：
- 只检查 assistant 角色的回复
- 触发：命中夸奖(PRAISE)或换题(NEXT)正则
- 校验：同回复是否命中分数(SCORE)正则
- 补救：追加 system 消息重新生成 1 次（最多 1 次），第 2 次放行 + 打日志
- 宿主端记录三个事实（example_skipped / max_hint_level / low_confidence），
  补救时喂回模型，掌握度不再依赖模型记忆。

仅当会话 settings 里启用了该门禁（gate_enabled=true）才生效，
不影响其它 skill 的正常对话。
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# 只在 assistant 回复上启用该门禁的 skill 标识（会话 settings.gate_skill）
GATE_SKILL = "khan-academy-shell"

# ---------------------------------------------------------------------------
# 正则（方案 B 3.1 / 3.2）
# ---------------------------------------------------------------------------

# 夸奖类
PRAISE = re.compile(
    r"(太棒了|做得(非常)?好|完全正确|很好|不错|完美|漂亮|厉害)"
)
# 换题类（匹配回复末尾的换题话术）
NEXT = re.compile(
    r"(下一(道|题|个)|下面(这|一)道|再来一道|挑战一道|进入下一个|我们来看.{0,6}题目\s*\d)"
)
# 分数模式：任一命中即算已报分
SCORE = re.compile(
    r"(\d{1,3}\s*分)|(合计\s*\d{1,3})|(达线|没达线|未达线)|(正确性\s*\d+)|(独立度\s*\d+)"
)

# 宿主端三个事实的学生消息命中词
SKIP_EXAMPLE_RE = re.compile(r"(例题.*(别|不用|跳过|不讲)|直接出题|跳例题)")
LOW_CONFIDENCE_RE = re.compile(r"(我猜的|不确定|大概是吧|瞎选|蒙的)")
# 求提示类消息（含口语化表达）—— 用于累加 max_hint_level，硬否决②依赖它
HINT_REQUEST_RE = re.compile(
    r"(提示|给我点提示|给个提示|再具体(一点|点|些)?|再提示|提示一下|帮我一下|"
    r"不知道怎么(做|写)|不会(做|写)|卡住|下一步怎么|然后呢|再讲(一点|些)?|"
    r"看不明白|没听懂|不太懂|还是不会|再给点)"
)

# 补救消息模板（方案 B 3.4）
REMEDY_TEMPLATE = (
    "你刚才夸奖了学生 / 出了下一题，但没有报本轮得分。\n"
    "按 khan-academy-shell 的 ⑧NEXT 规则重说一遍这段话：\n"
    "先报四维得分（正确性/独立度/说理/迁移）和合计分，说明达线或没达线，再继续。\n"
    "注意：本轮 example_skipped={example_skipped}，学生用到的最高提示级别={max_hint_level}。"
)


# ---------------------------------------------------------------------------
# 声明式门禁（HS 方案：skill frontmatter 声明 gates[]，DT 装载自动挂）
# ---------------------------------------------------------------------------
# frontmatter 中 gates[] 的示例结构：
#   gates:
#     - id: khan_next_step_v1
#       trigger: { match_role: assistant, match_keywords: ["太棒了", "下一题"] }
#       require_in_same_message: "\\d+\\s*分|合计\\s*\\d+|达线|没达线"
#       on_miss: regenerate_with_hint
#       max_retries: 1

# 内建门禁注册表：id -> 校验规则（SCORE 缺省用全局 SCORE）
BUILTIN_GATES: dict[str, dict[str, Any]] = {
    "khan_next_step_v1": {
        "trigger_keywords": ["太棒了", "做得非常好", "完全正确", "很好", "不错", "完美", "漂亮", "厉害", "下一题", "挑战一道", "进入下一个", "再来一道"],
        "require_pattern": SCORE,
        "tail_only": True,  # 换题话术只在回复末尾匹配
    },
    "khan_hint_level_v1": {
        "trigger_keywords": ["提示", "试试看", "可以先"],
        "require_pattern": re.compile(r"第\s*[1-4]\s*级|独立度\s*\d+"),
        "tail_only": False,
    },
}


def parse_gates_from_frontmatter(frontmatter: dict[str, Any]) -> list[dict[str, Any]]:
    """从 skill frontmatter 的 gates[] 解析出门禁清单（声明式）。

    只返回注册表里存在的门禁 id（DT 不知道的忽略，不报错）。
    """
    raw_gates = frontmatter.get("gates") or []
    if not isinstance(raw_gates, list):
        return []
    resolved: list[dict[str, Any]] = []
    for g in raw_gates:
        if not isinstance(g, dict):
            continue
        gid = str(g.get("id") or "")
        if gid not in BUILTIN_GATES:
            logger.debug("[skill_gate] 忽略未注册门禁 id=%s", gid)
            continue
        spec = dict(BUILTIN_GATES[gid])
        # 允许 frontmatter 覆盖 trigger/require/on_miss/max_retries
        trigger = g.get("trigger") or {}
        if isinstance(trigger, dict):
            kw = trigger.get("match_keywords")
            if isinstance(kw, list) and kw:
                spec["trigger_keywords"] = [str(k) for k in kw]
        req = g.get("require_in_same_message")
        if req:
            spec["require_pattern"] = re.compile(str(req))
        spec["id"] = gid
        spec["on_miss"] = g.get("on_miss") or "regenerate_with_hint"
        spec["max_retries"] = int(g.get("max_retries") or spec.get("max_retries") or 1)
        resolved.append(spec)
    return resolved


def _default_gate_state() -> dict[str, Any]:
    return {
        "example_skipped": False,
        "max_hint_level": 0,
        "low_confidence": False,
        "remedy_used": False,  # 本轮是否已补救过一次
    }


def init_gate_state() -> dict[str, Any]:
    """初始化宿主端记账状态。"""
    return _default_gate_state()


def update_gate_state(state: dict[str, Any], user_message: str) -> None:
    """根据学生消息更新宿主端三个事实。

    - example_skipped: 学生要求跳例题
    - max_hint_level: 学生每求一次提示 +1（硬否决②依赖，识别口语化"再具体点"等）
    - low_confidence: 学生说"我猜的/不确定"
    """
    if not state:
        return
    if SKIP_EXAMPLE_RE.search(user_message):
        state["example_skipped"] = True
    if HINT_REQUEST_RE.search(user_message):
        state["max_hint_level"] = int(state.get("max_hint_level") or 0) + 1
    if LOW_CONFIDENCE_RE.search(user_message):
        state["low_confidence"] = True


def needs_gate(session_settings: dict[str, Any] | None) -> bool:
    """当前会话是否启用该门禁。"""
    return bool(session_settings and session_settings.get("gate_skill") == GATE_SKILL)


def _hit_trigger(gate_spec: dict[str, Any], full_response: str) -> bool:
    """检查回复是否命中 gate 的 trigger 关键词。"""
    keywords = gate_spec.get("trigger_keywords") or []
    if not keywords:
        return False
    text = full_response
    if gate_spec.get("tail_only"):
        text = full_response[-200:]
    return any(kw in text for kw in keywords)


def check_gate(
    gate_spec: dict[str, Any],
    full_response: str,
    state: dict[str, Any],
) -> str | None:
    """按声明式 gate 校验，违规返回补救消息，否则 None。"""
    if not _hit_trigger(gate_spec, full_response):
        return None
    require = gate_spec.get("require_pattern")
    if require and require.search(full_response):
        return None  # 已满足（已报分）

    # 违规，走补救（最多 max_retries 次）
    max_retries = int(gate_spec.get("max_retries") or 1)
    if int(state.get("remedy_used") or 0) >= max_retries:
        logger.info("[skill_gate] gate_missing: %s 补救超限，放行", gate_spec.get("id"))
        return None
    state["remedy_used"] = int(state.get("remedy_used") or 0) + 1
    remedy = REMEDY_TEMPLATE.format(
        example_skipped=state.get("example_skipped", False),
        max_hint_level=state.get("max_hint_level", 0),
    )
    logger.info(
        "[skill_gate] %s 违规拦截 → 补救（example_skipped=%s）",
        gate_spec.get("id"),
        state.get("example_skipped"),
    )
    return remedy


def check_and_remedy(
    full_response: str,
    state: dict[str, Any],
    gates: list[dict[str, Any]] | None = None,
) -> tuple[str | None, str | None]:
    """校验 assistant 回复，需要补救时返回 (补救消息, 可见消息)。

    gates 为空时回退到默认的 khan_next_step_v1（向后兼容硬编码）。
    """
    if not gates:
        gates = [dict(BUILTIN_GATES["khan_next_step_v1"], id="khan_next_step_v1")]
    for gate in gates:
        remedy = check_gate(gate, full_response, state)
        if remedy is not None:
            return remedy, remedy
    return None, None


__all__ = [
    "BUILTIN_GATES",
    "GATE_SKILL",
    "check_and_remedy",
    "check_gate",
    "init_gate_state",
    "needs_gate",
    "parse_gates_from_frontmatter",
    "update_gate_state",
]
