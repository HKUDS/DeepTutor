"""MathNet Knowledge Base API Router

Provides access to MathNet problem database with step-by-step solutions
for video generation and tutoring purposes.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from deeptutor.services.config import PROJECT_ROOT, load_config_with_main

logger = logging.getLogger(__name__)
router = APIRouter()

# Try to find mathnet-kb database
# Check multiple possible locations
MATHNET_DB_PATHS = [
    # Local development paths
    PROJECT_ROOT.parent / "mathnet-kb" / "data" / "mathnet-kb.db",
    PROJECT_ROOT.parent.parent / "mathnet-kb" / "data" / "mathnet-kb.db",
    PROJECT_ROOT / "data" / "mathnet-kb.db",
    # Server path
    Path("/root/mathnet-kb/data/mathnet-kb.db"),
]


def _get_mathnet_db_path() -> Path | None:
    """Find the MathNet database file."""
    for path in MATHNET_DB_PATHS:
        if path.exists():
            return path
    return None


# Pydantic models for API responses

class KnowledgePointInfo(BaseModel):
    """Knowledge point associated with a step."""

    id: str
    name_zh: str
    name_en: str
    importance: str  # "core", "supporting", "advanced"


class StepDetail(BaseModel):
    """Detailed step information."""

    id: str
    step_index: int
    title_zh: str
    title_en: str
    text_zh: str
    text_en: str
    explanation_zh: str
    explanation_en: str
    role_in_solution_zh: str
    role_in_solution_en: str
    knowledge_points: list[KnowledgePointInfo]


class StepOutline(BaseModel):
    """Step outline item in architecture."""

    step_index: int
    step_title_en: str
    step_title_zh: str
    step_goal_en: str
    step_goal_zh: str
    brief_content_en: str
    brief_content_zh: str
    depends_on: list[int]


class ArchitectureInfo(BaseModel):
    """Problem architecture (solution strategy)."""

    id: str
    problem_summary_zh: str
    problem_summary_en: str
    solution_strategy_zh: str
    solution_strategy_en: str
    suggested_tier: str  # L1, L2, L3, L4
    tier_reason_zh: str
    prerequisites_zh: list[str]
    prerequisites_en: list[str]
    major_categories: list[str]
    step_count: int
    steps_outline: list[StepOutline]


class ProblemInfo(BaseModel):
    """Basic problem information."""

    id: str
    problem_markdown: str
    problem_zh: str | None
    solution_markdown: list[str]
    solution_zh: list[str] | None
    country: str
    competition: str
    topics: list[str]
    problem_type: str
    final_answer: str | None


class ProblemDetailResponse(BaseModel):
    """Full problem detail with architecture and steps."""

    problem: ProblemInfo
    architecture: ArchitectureInfo | None
    steps: list[StepDetail]


class ProblemListItem(BaseModel):
    """Problem list item for browsing."""

    id: str
    country: str
    competition: str
    topics: list[str]
    tier: str | None
    has_architecture: bool
    step_count: int


class ProblemListResponse(BaseModel):
    """Paginated problem list."""

    total: int
    page: int
    page_size: int
    problems: list[ProblemListItem]


def _get_db_connection() -> sqlite3.Connection:
    """Get connection to MathNet database."""
    db_path = _get_mathnet_db_path()
    if not db_path:
        raise HTTPException(
            status_code=503,
            detail="MathNet database not found. Please ensure mathnet-kb is properly configured.",
        )
    return sqlite3.connect(db_path)


def _parse_json_field(value: str | None) -> list[str] | None:
    """Parse JSON array field from database."""
    if not value:
        return None
    try:
        import json

        result = json.loads(value)
        if isinstance(result, list):
            return result
        return [str(result)]
    except Exception:
        return None


@router.get("/health")
async def health_check() -> dict[str, Any]:
    """Check MathNet database connectivity."""
    db_path = _get_mathnet_db_path()
    if not db_path:
        return {
            "status": "unavailable",
            "error": "MathNet database not found",
            "searched_paths": [str(p) for p in MATHNET_DB_PATHS],
        }

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Get counts
        cursor.execute("SELECT COUNT(*) FROM problems")
        problem_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM architectures")
        architecture_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM steps")
        step_count = cursor.fetchone()[0]

        conn.close()

        return {
            "status": "ok",
            "database_path": str(db_path),
            "statistics": {
                "problems": problem_count,
                "architectures": architecture_count,
                "steps": step_count,
            },
        }
    except Exception as e:
        return {
            "status": "error",
            "database_path": str(db_path),
            "error": str(e),
        }


@router.get("/problems", response_model=ProblemListResponse)
async def list_problems(
    page: int = 1,
    page_size: int = 20,
    tier: str | None = None,
    topic: str | None = None,
    has_architecture: bool | None = None,
    keyword: str | None = None,
    country: str | None = None,
) -> ProblemListResponse:
    """List problems with pagination and filtering."""
    conn = _get_db_connection()
    cursor = conn.cursor()

    # Build query
    where_clauses = []
    params = []

    if tier:
        where_clauses.append("a.suggested_tier = ?")
        params.append(tier)

    if topic:
        where_clauses.append("p.topics_flat LIKE ?")
        params.append(f"%{topic}%")

    if has_architecture is not None:
        if has_architecture:
            where_clauses.append("a.id IS NOT NULL")
        else:
            where_clauses.append("a.id IS NULL")

    if country:
        where_clauses.append("p.country = ?")
        params.append(country)

    if keyword:
        # Search in problem_id, problem_markdown, country, competition
        keyword_pattern = f"%{keyword}%"
        where_clauses.append(
            "(p.id LIKE ? OR p.problem_markdown LIKE ? OR p.country LIKE ? OR p.competition LIKE ?)"
        )
        params.extend([keyword_pattern, keyword_pattern, keyword_pattern, keyword_pattern])

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    # Get total count
    count_sql = f"""
        SELECT COUNT(*)
        FROM problems p
        LEFT JOIN architectures a ON p.id = a.problem_id
        {where_sql}
    """
    cursor.execute(count_sql, params)
    total = cursor.fetchone()[0]

    # Get paginated results
    offset = (page - 1) * page_size
    query_sql = f"""
        SELECT
            p.id,
            p.country,
            p.competition,
            p.topics_flat,
            a.suggested_tier,
            CASE WHEN a.id IS NOT NULL THEN 1 ELSE 0 END as has_architecture,
            COALESCE(a.step_count, 0) as step_count
        FROM problems p
        LEFT JOIN architectures a ON p.id = a.problem_id
        {where_sql}
        ORDER BY p.id
        LIMIT ? OFFSET ?
    """
    cursor.execute(query_sql, params + [page_size, offset])

    problems = []
    for row in cursor.fetchall():
        problems.append(
            ProblemListItem(
                id=row[0],
                country=row[1],
                competition=row[2],
                topics=_parse_json_field(row[3]) or [],
                tier=row[4],
                has_architecture=bool(row[5]),
                step_count=row[6],
            )
        )

    conn.close()

    return ProblemListResponse(
        total=total,
        page=page,
        page_size=page_size,
        problems=problems,
    )


@router.get("/problem/{problem_id}", response_model=ProblemDetailResponse)
async def get_problem_detail(problem_id: str) -> ProblemDetailResponse:
    """Get full problem details including architecture and steps."""
    conn = _get_db_connection()
    cursor = conn.cursor()

    # Get problem
    cursor.execute(
        """
        SELECT
            id,
            problem_markdown,
            problem_zh,
            solution_markdown,
            solution_zh,
            country,
            competition,
            topics_flat,
            problem_type,
            final_answer
        FROM problems
        WHERE id = ?
    """,
        (problem_id,),
    )
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Problem '{problem_id}' not found")

    problem = ProblemInfo(
        id=row[0],
        problem_markdown=row[1],
        problem_zh=row[2],
        solution_markdown=_parse_json_field(row[3]) or [],
        solution_zh=_parse_json_field(row[4]),
        country=row[5],
        competition=row[6],
        topics=_parse_json_field(row[7]) or [],
        problem_type=row[8],
        final_answer=row[9],
    )

    # Get architecture
    cursor.execute(
        """
        SELECT
            id,
            problem_summary_zh,
            problem_summary_en,
            solution_strategy_zh,
            solution_strategy_en,
            suggested_tier,
            tier_reason_zh,
            prerequisites_zh,
            prerequisites_en,
            major_categories,
            step_count,
            steps_outline
        FROM architectures
        WHERE problem_id = ?
    """,
        (problem_id,),
    )
    arch_row = cursor.fetchone()

    architecture = None
    if arch_row:
        architecture = ArchitectureInfo(
            id=arch_row[0],
            problem_summary_zh=arch_row[1],
            problem_summary_en=arch_row[2],
            solution_strategy_zh=arch_row[3],
            solution_strategy_en=arch_row[4],
            suggested_tier=arch_row[5],
            tier_reason_zh=arch_row[6],
            prerequisites_zh=_parse_json_field(arch_row[7]) or [],
            prerequisites_en=_parse_json_field(arch_row[8]) or [],
            major_categories=_parse_json_field(arch_row[9]) or [],
            step_count=arch_row[10],
            steps_outline=_parse_json_field(arch_row[11]) or [],
        )

    # Get steps
    steps = []
    if architecture:
        cursor.execute(
            """
            SELECT
                s.id,
                s.step_index,
                s.step_title_zh,
                s.step_title_en,
                s.step_text_zh,
                s.step_text_en,
                s.explanation_zh,
                s.explanation_en,
                s.role_in_solution_zh,
                s.role_in_solution_en
            FROM steps s
            WHERE s.architecture_id = ?
            ORDER BY s.step_index
        """,
            (architecture.id,),
        )

        for step_row in cursor.fetchall():
            # Get knowledge points for this step
            cursor.execute(
                """
                SELECT
                    kp.id,
                    kp.name_zh,
                    kp.name_en,
                    skp.importance
                FROM step_knowledge_points skp
                JOIN knowledge_points kp ON skp.knowledge_point_id = kp.id
                WHERE skp.step_id = ?
            """,
                (step_row[0],),
            )

            knowledge_points = [
                KnowledgePointInfo(
                    id=kp_row[0],
                    name_zh=kp_row[1],
                    name_en=kp_row[2],
                    importance=kp_row[3],
                )
                for kp_row in cursor.fetchall()
            ]

            steps.append(
                StepDetail(
                    id=step_row[0],
                    step_index=step_row[1],
                    title_zh=step_row[2],
                    title_en=step_row[3],
                    text_zh=step_row[4],
                    text_en=step_row[5],
                    explanation_zh=step_row[6],
                    explanation_en=step_row[7],
                    role_in_solution_zh=step_row[8],
                    role_in_solution_en=step_row[9],
                    knowledge_points=knowledge_points,
                )
            )

    conn.close()

    return ProblemDetailResponse(
        problem=problem,
        architecture=architecture,
        steps=steps,
    )


@router.get("/topics")
async def list_topics() -> list[dict[str, Any]]:
    """List all available topics/categories."""
    conn = _get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT major_categories
        FROM architectures
        WHERE major_categories IS NOT NULL
    """)

    topics = set()
    for row in cursor.fetchall():
        cats = _parse_json_field(row[0])
        if cats:
            topics.update(cats)

    conn.close()

    return [{"name": t} for t in sorted(topics)]


@router.get("/stats")
async def get_statistics() -> dict[str, Any]:
    """Get MathNet database statistics."""
    conn = _get_db_connection()
    cursor = conn.cursor()

    # Overall counts
    cursor.execute("SELECT COUNT(*) FROM problems")
    total_problems = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM architectures")
    total_architectures = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM steps")
    total_steps = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM knowledge_points")
    total_knowledge_points = cursor.fetchone()[0]

    # Tier distribution
    cursor.execute("""
        SELECT suggested_tier, COUNT(*)
        FROM architectures
        WHERE suggested_tier IS NOT NULL
        GROUP BY suggested_tier
    """)
    tier_distribution = {row[0]: row[1] for row in cursor.fetchall()}

    # Top knowledge points
    cursor.execute("""
        SELECT name_zh, occurrence_count
        FROM knowledge_points
        ORDER BY occurrence_count DESC
        LIMIT 10
    """)
    top_knowledge_points = [
        {"name": row[0], "count": row[1]} for row in cursor.fetchall()
    ]

    conn.close()

    return {
        "total_problems": total_problems,
        "total_architectures": total_architectures,
        "total_steps": total_steps,
        "total_knowledge_points": total_knowledge_points,
        "completion_rate": round(total_architectures / total_problems * 100, 2)
        if total_problems > 0
        else 0,
        "tier_distribution": tier_distribution,
        "top_knowledge_points": top_knowledge_points,
    }
