"""KP-Map 自动推导器（vendored：源 kp_auto_map.py 在悦学工作区 ~/yuedu/scripts/，不在本仓；本文件为仓内唯一事实源，stdlib only）.

从教材结构树（KB 的 doc_tree/doc_intel，节点含 node_id/title/children）与
题库 JSON（question_banks/<book_id>.json，扁平 questions 数组带
chapter/chapter_id）推导 chapter_id -> kp_id 映射，供挂载段使用。

匹配策略：标题精确命中优先；否则 difflib.SequenceMatcher 相似度 >= 阈值
（默认 0.6）取最高；多个 KP 同分命中取遍历首个并在报告中列出歧义项；低于
阈值进入 unmapped。本模块为纯函数、零三方依赖，便于在后台线程与测试中复用。
"""

from __future__ import annotations

import difflib
from typing import Any

DEFAULT_THRESHOLD = 0.6
SCORE_EPS = 1e-9


def normalize_title(title: Any) -> str:
    """标题归一化：非字符串置空，去首尾/折叠内部空白。"""
    if not isinstance(title, str):
        return ""
    return " ".join(title.split()).strip()


def _node_id(node: dict[str, Any]) -> str:
    nid = node.get("node_id") or node.get("id") or node.get("kp_id")
    return str(nid) if nid else ""


def unwrap_tree(obj: Any) -> Any:
    """容忍 doc_tree/doc_intel 外层包装，返回真正的树节点（dict 或 list）。"""
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for key in ("doc_tree", "tree", "root", "data", "structure"):
            inner = obj.get(key)
            if isinstance(inner, (dict, list)):
                return inner
        if "children" in obj or "node_id" in obj or "title" in obj:
            return obj
    return obj


def extract_kps(
    tree: Any,
    path: list[str] | None = None,
    out: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """递归抽取结构树全部节点，返回 [{id, title, path}]（path 为标题全路径）。"""
    if out is None:
        out = []
    if path is None:
        path = []
    if isinstance(tree, list):
        for node in tree:
            extract_kps(node, path, out)
        return out
    if not isinstance(tree, dict):
        return out

    title = normalize_title(tree.get("title"))
    current_path = path + [title] if title else path
    nid = _node_id(tree)
    if nid and title:
        out.append({"id": nid, "title": title, "path": " > ".join(current_path)})

    children = tree.get("children")
    if isinstance(children, list):
        for child in children:
            extract_kps(child, current_path, out)
    return out


def extract_leaf_chapters(
    tree: Any,
    path: list[str] | None = None,
    out: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """抽取结构树的叶子节点作为出题章节（无 children 的节点）。

    叶子对应教材最具体的节/知识点，与可挂载 KP 粒度一致；返回 [{id,title,path}]。
    """
    if out is None:
        out = []
    if path is None:
        path = []
    if isinstance(tree, list):
        for node in tree:
            extract_leaf_chapters(node, path, out)
        return out
    if not isinstance(tree, dict):
        return out

    title = normalize_title(tree.get("title"))
    current_path = path + [title] if title else path
    nid = _node_id(tree)
    children = tree.get("children")
    has_children = isinstance(children, list) and len(children) > 0

    if not has_children and nid and title:
        out.append({"id": nid, "title": title, "path": " > ".join(current_path)})

    if has_children:
        for child in children:
            extract_leaf_chapters(child, current_path, out)
    return out


def count_tree_nodes(tree: Any) -> int:
    """结构树就绪检查用：含 node_id + title 的节点总数。"""
    return len(extract_kps(unwrap_tree(tree)))


def extract_chapters(bank: dict[str, Any]) -> list[dict[str, str]]:
    """从题库 questions 数组按 chapter_id 去重抽取章节（保留首次出现顺序）。"""
    titles: dict[str, str] = {}
    order: list[str] = []
    for q in bank.get("questions", []):
        if not isinstance(q, dict):
            continue
        cid = q.get("chapter_id")
        title = normalize_title(q.get("chapter"))
        if not cid or not title:
            continue
        cid = str(cid)
        if cid not in titles:
            titles[cid] = title
            order.append(cid)
    return [{"id": cid, "title": titles[cid]} for cid in order]


def _candidate(kp: dict[str, str], score: float) -> dict[str, Any]:
    return {
        "kp_id": kp["id"],
        "kp_title": kp["title"],
        "kp_path": kp["path"],
        "score": round(score, 4),
    }


def match_chapter(
    chapter_title: str, kps: list[dict[str, str]], threshold: float
) -> dict[str, Any]:
    """单章匹配：先精确，再模糊取最高，返回 match_type=exact/fuzzy/none。"""
    exact = [kp for kp in kps if kp["title"] == chapter_title]
    if exact:
        candidates = [_candidate(kp, 1.0) for kp in exact]
        return {
            "match_type": "exact",
            "kp": candidates[0],
            "ambiguous_with": candidates[1:],
            "best_candidate": candidates[0],
        }

    scored = [
        _candidate(kp, difflib.SequenceMatcher(None, chapter_title, kp["title"]).ratio())
        for kp in kps
    ]
    scored.sort(key=lambda c: c["score"], reverse=True)
    best = scored[0] if scored else None

    if best and best["score"] >= threshold:
        top = best["score"]
        tied = [c for c in scored if abs(c["score"] - top) <= SCORE_EPS]
        return {
            "match_type": "fuzzy",
            "kp": tied[0],
            "ambiguous_with": tied[1:],
            "best_candidate": best,
        }

    return {
        "match_type": "none",
        "kp": None,
        "ambiguous_with": [],
        "best_candidate": best,
    }


def build_map(
    tree_obj: Any, bank_obj: dict[str, Any], threshold: float = DEFAULT_THRESHOLD
) -> tuple[dict[str, str], dict[str, Any]]:
    """推导映射，返回 (mapping {chapter_id: kp_id}, report dict)。"""
    kps = extract_kps(unwrap_tree(tree_obj))
    chapters = extract_chapters(bank_obj)

    mapping: dict[str, str] = {}
    mappings: list[dict[str, Any]] = []
    unmapped: list[dict[str, Any]] = []

    for ch in chapters:
        res = match_chapter(ch["title"], kps, threshold)
        if res["match_type"] in ("exact", "fuzzy"):
            kp = res["kp"]
            mapping[ch["id"]] = kp["kp_id"]
            mappings.append(
                {
                    "chapter_id": ch["id"],
                    "chapter_title": ch["title"],
                    "kp_id": kp["kp_id"],
                    "kp_title": kp["kp_title"],
                    "kp_path": kp["kp_path"],
                    "score": kp["score"],
                    "match_type": res["match_type"],
                    "ambiguous_with": res["ambiguous_with"],
                }
            )
        else:
            unmapped.append(
                {
                    "chapter_id": ch["id"],
                    "chapter_title": ch["title"],
                    "best_candidate": res["best_candidate"],
                }
            )

    report = {
        "summary": {
            "kp_nodes": len(kps),
            "total_chapters": len(chapters),
            "mapped": len(mappings),
            "exact": sum(1 for e in mappings if e["match_type"] == "exact"),
            "fuzzy": sum(1 for e in mappings if e["match_type"] == "fuzzy"),
            "ambiguous": sum(1 for e in mappings if e["ambiguous_with"]),
            "unmapped": len(unmapped),
            "threshold": threshold,
        },
        "mappings": mappings,
        "unmapped": unmapped,
    }
    return mapping, report


def _kp_entry(kp: Any) -> dict[str, str]:
    """归一化单条 KP（dict 或 KnowledgePoint 兼容对象）→ {id,title,node}。"""
    if not isinstance(kp, dict):
        dump = getattr(kp, "model_dump", None)
        kp = dump() if callable(dump) else {}
    if not isinstance(kp, dict):
        return {"id": "", "title": "", "node": ""}
    return {
        "id": str(kp.get("kp_id") or kp.get("id") or ""),
        "title": normalize_title(kp.get("name") or kp.get("title")),
        "node": str(kp.get("textbook_node_id") or ""),
    }


def map_question_to_kp(
    question_kw: str,
    kps: list[Any],
    threshold: float = DEFAULT_THRESHOLD,
) -> dict[str, Any] | None:
    """KP 级单题映射（B2-b）：题目关键词 → KP（精确优先，模糊兜底）。

    与 :func:`build_map`（chapter_id → 树节点）互补：这里的目标是既有的
    KP 列表（dict 或 pydantic KnowledgePoint，读 id/name/textbook_node_id）。
    kw 与 KP 名归一化后精确命中优先；否则 difflib 相似度 >= 阈值（默认
    0.6）取最高，同分取遍历首个。低于阈值或无可匹配时返回 None。

    返回 ``{"kp_id", "textbook_node_id", "match_type", "score"}`` 或 ``None``。
    """
    kw = normalize_title(question_kw)
    if not kw:
        return None

    entries = [_kp_entry(kp) for kp in kps or []]
    entries = [e for e in entries if e["id"] and e["title"]]

    exact = next((e for e in entries if e["title"] == kw), None)
    if exact is not None:
        return {
            "kp_id": exact["id"],
            "textbook_node_id": exact["node"],
            "match_type": "exact",
            "score": 1.0,
        }

    best: dict[str, Any] | None = None
    best_score = 0.0
    for entry in entries:
        score = difflib.SequenceMatcher(None, kw, entry["title"]).ratio()
        if best is None or score > best_score + SCORE_EPS:
            best, best_score = entry, score
    if best is not None and best_score >= threshold:
        return {
            "kp_id": best["id"],
            "textbook_node_id": best["node"],
            "match_type": "fuzzy",
            "score": round(best_score, 4),
        }
    return None
