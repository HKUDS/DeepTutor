#!/usr/bin/env python
"""
CitationManager - Citation management system
Responsible for extracting citation information from tool calls and managing citation JSON files
"""

import asyncio
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from deeptutor.services.path_service import get_path_service


class CitationManager:
    """Citation manager with global ID management"""

    def __init__(self, research_id: str, cache_dir: Path | None = None):
        """
        Initialize citation manager

        Args:
            research_id: Research task ID
            cache_dir: Cache directory path, if None uses default path
        """
        self.research_id = research_id
        if cache_dir is None:
            cache_dir = get_path_service().get_task_workspace("deep_research", research_id)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.citations_file = self.cache_dir / "citations.json"
        self._citations: dict[str, dict[str, Any]] = {}

        # Global citation ID counters
        self._plan_counter = 0  # For PLAN-XX format (planning stage)
        self._block_counters: dict[str, int] = {}  # For CIT-X-XX format (research stage)

        # Reference number mapping (citation_id -> ref_number for in-text citations)
        self._ref_number_map: dict[str, int] = {}

        # Lock for thread-safe operations in parallel mode
        self._lock = asyncio.Lock()

        self._load_citations()

    def generate_plan_citation_id(self) -> str:
        """
        Generate a new citation ID for planning stage (PLAN-XX format)

        Returns:
            Citation ID in PLAN-XX format
        """
        self._plan_counter += 1
        return f"PLAN-{self._plan_counter:02d}"

    def generate_research_citation_id(self, block_id: str) -> str:
        """
        Generate a new citation ID for research stage (CIT-X-XX format)

        Args:
            block_id: Block ID (e.g., "block_3")

        Returns:
            Citation ID in CIT-X-XX format
        """
        # Extract block number from block_id
        block_num = 0
        try:
            if block_id and "_" in block_id:
                block_num = int(block_id.split("_")[1])
        except (ValueError, IndexError):
            block_num = 0

        # Increment counter for this block
        block_key = str(block_num)
        if block_key not in self._block_counters:
            self._block_counters[block_key] = 0
        self._block_counters[block_key] += 1

        return f"CIT-{block_num}-{self._block_counters[block_key]:02d}"

    def get_next_citation_id(self, stage: str = "research", block_id: str = "") -> str:
        """
        Get the next available citation ID

        Args:
            stage: "planning" or "research"
            block_id: Block ID (required for research stage)

        Returns:
            Next available citation ID
        """
        if stage == "planning":
            return self.generate_plan_citation_id()
        return self.generate_research_citation_id(block_id)

    def citation_exists(self, citation_id: str) -> bool:
        """
        Check if a citation ID already exists

        Args:
            citation_id: Citation ID to check

        Returns:
            True if citation exists, False otherwise
        """
        return citation_id in self._citations

    def _load_citations(self):
        """Load citation information from JSON file and restore counters"""
        if self.citations_file.exists():
            try:
                with open(self.citations_file, encoding="utf-8") as f:
                    data = json.load(f)
                    self._citations = data.get("citations", {})

                    # Try to restore counters from saved state first
                    counters = data.get("counters", {})
                    if counters:
                        self._plan_counter = counters.get("plan_counter", 0)
                        self._block_counters = counters.get("block_counters", {})
                    else:
                        # Fallback: restore counters from existing citations
                        self._restore_counters_from_citations()
            except Exception as e:
                print(f"⚠️ Failed to load citation file: {e}")
                self._citations = {}
        else:
            self._citations = {}

    def _restore_counters_from_citations(self):
        """Restore citation counters from existing citations to avoid ID conflicts"""
        for citation_id in self._citations.keys():
            if citation_id.startswith("PLAN-"):
                try:
                    num = int(citation_id.replace("PLAN-", ""))
                    self._plan_counter = max(self._plan_counter, num)
                except ValueError:
                    pass
            elif citation_id.startswith("CIT-"):
                try:
                    parts = citation_id.replace("CIT-", "").split("-")
                    if len(parts) == 2:
                        block_num = parts[0]
                        seq_num = int(parts[1])
                        if block_num not in self._block_counters:
                            self._block_counters[block_num] = 0
                        self._block_counters[block_num] = max(
                            self._block_counters[block_num], seq_num
                        )
                except (ValueError, IndexError):
                    pass

    def _save_citations(self):
        """Save citation information to JSON file"""
        try:
            data = {
                "research_id": self.research_id,
                "updated_at": datetime.now().isoformat(),
                "citations": self._citations,
                "counters": {
                    "plan_counter": self._plan_counter,
                    "block_counters": self._block_counters,
                },
            }
            with open(self.citations_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ Failed to save citation file: {e}")

    def validate_citation_references(self, text: str) -> dict[str, Any]:
        """
        Validate citation references in text and identify invalid ones

        Args:
            text: Text containing citation references like [[CIT-X-XX]]

        Returns:
            Dictionary with validation results:
            {
                "valid_citations": [...],
                "invalid_citations": [...],
                "is_valid": bool
            }
        """
        import re

        # Find all citation references in the text
        pattern = r"\[\[([A-Z]+-\d+-?\d*)\]\]"
        found_refs = re.findall(pattern, text)

        valid = []
        invalid = []

        for ref in found_refs:
            if self.citation_exists(ref):
                valid.append(ref)
            else:
                invalid.append(ref)

        return {
            "valid_citations": valid,
            "invalid_citations": invalid,
            "is_valid": len(invalid) == 0,
            "total_found": len(found_refs),
        }

    def fix_invalid_citations(self, text: str) -> str:
        """
        Remove or mark invalid citation references in text

        Args:
            text: Text containing citation references

        Returns:
            Text with invalid citations removed or marked
        """
        import re

        pattern = r"\[\[([A-Z]+-\d+-?\d*)\]\]\(#ref-[a-z]+-\d+-?\d*\)"

        def replace_invalid(match):
            citation_id = match.group(1)
            if self.citation_exists(citation_id):
                return match.group(0)  # Keep valid citations
            return ""  # Remove invalid citations

        return re.sub(pattern, replace_invalid, text)

    def add_citation(
        self,
        citation_id: str,
        tool_type: str,
        tool_trace: Any,
        raw_answer: str,  # Raw answer JSON string
    ) -> bool:
        """
        Add citation information

        Args:
            citation_id: Citation ID
            tool_type: Tool type
            tool_trace: ToolTrace object
            raw_answer: Raw answer (JSON string)

        Returns:
            Whether addition was successful
        """
        try:
            tool_type_lower = tool_type.lower()

            if tool_type_lower in ("rag", "rag_naive", "rag_hybrid"):
                citation_info = self._extract_rag_citation(
                    citation_id, "rag", raw_answer, tool_trace
                )
            elif tool_type_lower == "web_search":
                citation_info = self._extract_web_citation(
                    citation_id, tool_type, raw_answer, tool_trace
                )
            elif tool_type_lower == "paper_search":
                citation_info = self._extract_paper_citation(
                    citation_id, tool_type, raw_answer, tool_trace
                )
            elif tool_type_lower == "run_code":
                citation_info = self._extract_code_citation(citation_id, tool_type, tool_trace)
            else:
                # Unknown tool type, use generic format
                citation_info = self._extract_generic_citation(citation_id, tool_type, tool_trace)

            if citation_info:
                self._citations[citation_id] = citation_info
                self._save_citations()
                return True
            return False
        except Exception as e:
            print(f"⚠️ Failed to add citation (citation_id={citation_id}): {e}")
            return False

    def _extract_rag_citation(
        self, citation_id: str, tool_type: str, raw_answer: str, tool_trace: Any
    ) -> dict[str, Any]:
        """Extract citation information for RAG retrieval with source documents"""
        citation_info = {
            "citation_id": citation_id,
            "tool_type": tool_type,
            "query": tool_trace.query,
            "summary": tool_trace.summary,
            "timestamp": tool_trace.timestamp,
            "sources": [],  # List of source documents
        }

        try:
            # Parse raw_answer to extract source information
            answer_data = json.loads(raw_answer)

            # Extract source documents if available
            # Common fields in RAG responses: chunks, documents, sources, context
            sources = []

            # Try different field names for source documents
            for field_name in ["chunks", "documents", "sources", "context", "retrieved_docs"]:
                if field_name in answer_data:
                    source_list = answer_data[field_name]
                    if isinstance(source_list, list):
                        for i, doc in enumerate(source_list[:5]):  # Limit to 5 sources
                            source_info = {}
                            if isinstance(doc, dict):
                                source_info["title"] = doc.get("title", doc.get("doc_title", ""))
                                source_info["content_preview"] = doc.get(
                                    "content", doc.get("text", "")
                                )[:200]
                                source_info["source_file"] = doc.get(
                                    "source", doc.get("file_path", doc.get("filename", ""))
                                )
                                source_info["page"] = doc.get("page", doc.get("page_number", ""))
                                source_info["chunk_id"] = doc.get("chunk_id", doc.get("id", i))
                                source_info["score"] = doc.get("score", doc.get("similarity", ""))
                            elif isinstance(doc, str):
                                source_info["content_preview"] = doc[:200]
                            if source_info:
                                sources.append(source_info)
                    break

            # Also extract kb_name if available
            citation_info["kb_name"] = answer_data.get("kb_name", "")
            citation_info["sources"] = sources
            citation_info["total_sources"] = len(sources)

        except (json.JSONDecodeError, Exception) as e:
            # If parsing fails, still return basic citation info
            print(f"⚠️ Failed to parse RAG source info: {e}")

        return citation_info

    def _extract_web_citation(
        self, citation_id: str, tool_type: str, raw_answer: str, tool_trace: Any
    ) -> dict[str, Any]:
        """Extract citation information for web search with URLs"""
        citation_info = {
            "citation_id": citation_id,
            "tool_type": tool_type,
            "query": tool_trace.query,
            "summary": tool_trace.summary,
            "timestamp": tool_trace.timestamp,
            "web_sources": [],  # List of web sources with URLs
        }

        try:
            # Parse raw_answer to extract web source information
            answer_data = json.loads(raw_answer)

            web_sources = []

            # Try different field names for web results
            for field_name in ["results", "web_results", "search_results", "urls"]:
                if field_name in answer_data:
                    result_list = answer_data[field_name]
                    if isinstance(result_list, list):
                        for result in result_list[:5]:  # Limit to 5 sources
                            if isinstance(result, dict):
                                web_source = {
                                    "title": result.get("title", ""),
                                    "url": result.get("url", result.get("link", "")),
                                    "snippet": result.get("snippet", result.get("description", ""))[
                                        :200
                                    ],
                                    "domain": result.get("domain", ""),
                                }
                                if web_source["url"]:  # Only add if URL exists
                                    web_sources.append(web_source)
                    break

            citation_info["web_sources"] = web_sources
            citation_info["total_sources"] = len(web_sources)

        except (json.JSONDecodeError, Exception) as e:
            # If parsing fails, still return basic citation info
            print(f"⚠️ Failed to parse web source info: {e}")

        return citation_info

    def _extract_paper_citation(
        self, citation_id: str, tool_type: str, raw_answer: str, tool_trace: Any
    ) -> dict[str, Any]:
        """Extract citation information for paper search - supports multiple papers"""
        citation_info = {
            "citation_id": citation_id,
            "tool_type": tool_type,
            "query": tool_trace.query,
            "summary": tool_trace.summary,
            "timestamp": tool_trace.timestamp,
            "papers": [],  # Store all papers, not just the first one
        }

        try:
            # Parse raw_answer JSON
            answer_data = json.loads(raw_answer)
            papers = answer_data.get("papers", [])

            if not papers:
                # If no papers, return basic info
                return citation_info

            # Process ALL papers (up to 5 for practicality)
            processed_papers = []
            for paper in papers[:5]:
                # Format authors
                authors = paper.get("authors", [])
                author_str = ", ".join(authors[:3])  # Display at most 3 authors
                if len(authors) > 3:
                    author_str += " et al."

                paper_info = {
                    "title": paper.get("title", ""),
                    "authors": author_str,
                    "authors_list": authors,
                    "year": paper.get("year", ""),
                    "url": paper.get("url", ""),
                    "arxiv_id": paper.get("arxiv_id", ""),
                    "abstract": paper.get("abstract", "")[:300],  # Truncate abstract
                    "doi": paper.get("doi", ""),
                    "venue": paper.get("venue", paper.get("journal", "")),
                }
                processed_papers.append(paper_info)

            citation_info["papers"] = processed_papers
            citation_info["total_papers"] = len(processed_papers)

            if processed_papers:
                primary = processed_papers[0]
                citation_info["title"] = primary["title"]
                citation_info["authors"] = primary["authors"]
                citation_info["authors_list"] = primary["authors_list"]
                citation_info["year"] = primary["year"]
                citation_info["url"] = primary["url"]
                citation_info["arxiv_id"] = primary["arxiv_id"]

            return citation_info
        except Exception as e:
            print(f"⚠️ Failed to parse paper citation: {e}")
            # Still return the basic citation info
            return citation_info

    def _extract_code_citation(
        self, citation_id: str, tool_type: str, tool_trace: Any
    ) -> dict[str, Any]:
        """Extract citation information for code execution"""
        return {
            "citation_id": citation_id,
            "tool_type": tool_type,
            "query": tool_trace.query,  # Code content
            "summary": tool_trace.summary,
            "timestamp": tool_trace.timestamp,
        }

    def _extract_generic_citation(
        self, citation_id: str, tool_type: str, tool_trace: Any
    ) -> dict[str, Any]:
        """Extract generic citation information (unknown tool type)"""
        return {
            "citation_id": citation_id,
            "tool_type": tool_type,
            "query": tool_trace.query,
            "summary": tool_trace.summary,
            "timestamp": tool_trace.timestamp,
        }

    def get_citation(self, citation_id: str) -> dict[str, Any] | None:
        """Get citation information for specified citation ID"""
        return self._citations.get(citation_id)

    def get_all_citations(self) -> dict[str, dict[str, Any]]:
        """Get all citation information"""
        return self._citations.copy()

    def get_citations_file_path(self) -> Path:
        """Get citation JSON file path"""
        return self.citations_file

    def format_citation_for_report(self, citation_id: str) -> str | None:
        """
        Format citation information for report display

        Args:
            citation_id: Citation ID

        Returns:
            Formatted citation string, or None if not found
        """
        citation = self.get_citation(citation_id)
        if not citation:
            return None

        tool_type = citation.get("tool_type", "").lower()

        if tool_type == "paper_search":
            # Standard academic citation format
            title = citation.get("title", "")
            authors = citation.get("authors", "")
            year = citation.get("year", "")
            url = citation.get("url", "")
            arxiv_id = citation.get("arxiv_id", "")

            # Build citation string
            parts = []
            if authors:
                parts.append(authors)
            if year:
                parts.append(f"({year})")
            if title:
                parts.append(f'"{title}"')
            if arxiv_id:
                parts.append(f"arXiv:{arxiv_id}")
            if url:
                parts.append(f"<{url}>")

            # Add note about additional papers if available
            total_papers = citation.get("total_papers", 1)
            if total_papers > 1:
                parts.append(f"[+{total_papers - 1} more papers]")

            return " ".join(parts) if parts else None

        if tool_type in ("rag", "rag_naive", "rag_hybrid"):
            query = citation.get("query", "")
            kb_name = citation.get("kb_name", "")
            sources = citation.get("sources", [])

            parts = [f"RAG: {query}"]
            if kb_name:
                parts.append(f"[KB: {kb_name}]")
            if sources:
                source_titles = [s.get("title", s.get("source_file", "")) for s in sources[:3] if s]
                source_titles = [t for t in source_titles if t]
                if source_titles:
                    parts.append(f"[Sources: {', '.join(source_titles)}]")

            return " ".join(parts)

        if tool_type == "web_search":
            # Web search with URLs
            query = citation.get("query", "")
            web_sources = citation.get("web_sources", [])

            parts = [f"Web Search: {query}"]
            if web_sources:
                urls = [s.get("url", "") for s in web_sources[:3] if s.get("url")]
                if urls:
                    parts.append(f"[URLs: {', '.join(urls)}]")

            return " ".join(parts)

        # Other types of citation formats
        tool_type_display = {
            "run_code": "Code Execution",
        }.get(tool_type, tool_type)

        query = citation.get("query", "")
        return f"{tool_type_display}: {query}"

    # ========== Reference Number Mapping Methods ==========

    def _get_citation_dedup_key(self, citation: dict, paper: dict = None) -> str:
        """
        Generate unique key for citation deduplication

        Deduplication is ONLY applied to paper_search citations where the same paper
        (title + first author) is cited multiple times. All other citation types
        get unique ref_numbers based on their citation_id.

        Args:
            citation: The citation dict
            paper: Optional paper dict for paper_search citations

        Returns:
            Unique string key for deduplication
        """
        tool_type = citation.get("tool_type", "").lower()
        citation_id = citation.get("citation_id", "")

        if tool_type == "paper_search" and paper:
            # For papers: use title + first author (normalized) - allow dedup for same paper
            title = paper.get("title", "").lower().strip()
            authors = paper.get("authors", "").lower().strip()
            # Extract first author if multiple
            first_author = authors.split(",")[0].strip() if authors else ""
            if title:  # Only dedup if we have a title
                return f"paper:{title}|{first_author}"
            # No title? Use citation_id to ensure unique
            return f"unique:{citation_id}"
        elif tool_type == "paper_search":
            # Fallback for paper_search without paper dict
            title = citation.get("title", "").lower().strip()
            authors = citation.get("authors", "").lower().strip()
            first_author = authors.split(",")[0].strip() if authors else ""
            if title:  # Only dedup if we have a title
                return f"paper:{title}|{first_author}"
            return f"unique:{citation_id}"
        else:
            # For RAG/web_search/etc: each citation gets unique ref_number
            # Use citation_id to ensure each citation is unique
            return f"unique:{citation_id}"

    def _extract_citation_sort_key(self, citation_id: str) -> tuple:
        """
        Extract numeric sort key from citation ID for ordering

        Args:
            citation_id: Citation ID (e.g., "PLAN-01", "CIT-1-02")

        Returns:
            Tuple for sorting (stage, block_num, seq_num)
        """
        try:
            if citation_id.startswith("PLAN-"):
                # PLAN-XX format: put at the beginning
                num = int(citation_id.replace("PLAN-", ""))
                return (0, 0, num)
            # CIT-X-XX format
            parts = citation_id.replace("CIT-", "").split("-")
            if len(parts) == 2:
                return (1, int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            pass
        return (999, 999, 999)

    def build_ref_number_map(self) -> dict[str, int]:
        """
        Build citation_id to reference number mapping with deduplication.
        This is the single source of truth for ref_number assignment.

        Returns:
            Dictionary mapping citation_id to reference number (1-based)
        """
        if not self._citations:
            self._ref_number_map = {}
            return self._ref_number_map

        # Sort all citation IDs by their numeric parts
        sorted_citation_ids = sorted(self._citations.keys(), key=self._extract_citation_sort_key)

        # Track seen dedup keys and their assigned ref_numbers
        seen_keys: dict[str, int] = {}
        ref_idx = 0
        ref_map: dict[str, int] = {}

        for citation_id in sorted_citation_ids:
            citation = self._citations.get(citation_id)
            if not citation:
                continue

            tool_type = citation.get("tool_type", "").lower()

            if tool_type == "paper_search":
                # paper_search may have multiple papers - each paper gets a separate ref_number
                papers = citation.get("papers", [])
                if papers:
                    for paper_idx, paper in enumerate(papers):
                        # Check for duplicate using dedup key
                        dedup_key = self._get_citation_dedup_key(citation, paper)

                        if dedup_key in seen_keys:
                            # Map to existing ref_number
                            existing_ref = seen_keys[dedup_key]
                            if paper_idx == 0:
                                ref_map[citation_id] = existing_ref
                            ref_map[f"{citation_id}-{paper_idx + 1}"] = existing_ref
                        else:
                            # New unique citation
                            ref_idx += 1
                            seen_keys[dedup_key] = ref_idx
                            if paper_idx == 0:
                                ref_map[citation_id] = ref_idx
                            ref_map[f"{citation_id}-{paper_idx + 1}"] = ref_idx
                else:
                    # Paper search without papers array
                    dedup_key = self._get_citation_dedup_key(citation)
                    if dedup_key in seen_keys:
                        ref_map[citation_id] = seen_keys[dedup_key]
                    else:
                        ref_idx += 1
                        seen_keys[dedup_key] = ref_idx
                        ref_map[citation_id] = ref_idx
            else:
                # Non-paper citations
                dedup_key = self._get_citation_dedup_key(citation)
                if dedup_key in seen_keys:
                    ref_map[citation_id] = seen_keys[dedup_key]
                else:
                    ref_idx += 1
                    seen_keys[dedup_key] = ref_idx
                    ref_map[citation_id] = ref_idx

        self._ref_number_map = ref_map
        return ref_map

    def get_ref_number(self, citation_id: str) -> int:
        """
        Get the reference number for a citation ID.
        If the map hasn't been built yet, build it first.

        Args:
            citation_id: Citation ID

        Returns:
            Reference number (1-based), or 0 if not found
        """
        if not self._ref_number_map:
            self.build_ref_number_map()
        return self._ref_number_map.get(citation_id, 0)

    def get_ref_number_map(self) -> dict[str, int]:
        """
        Get the full reference number map.
        If the map hasn't been built yet, build it first.

        Returns:
            Dictionary mapping citation_id to reference number
        """
        if not self._ref_number_map:
            self.build_ref_number_map()
        return self._ref_number_map.copy()

    # ========== Async thread-safe methods for parallel mode ==========

    async def generate_plan_citation_id_async(self) -> str:
        """
        Thread-safe async version of generate_plan_citation_id for parallel mode

        Returns:
            Citation ID in PLAN-XX format
        """
        async with self._lock:
            return self.generate_plan_citation_id()

    async def generate_research_citation_id_async(self, block_id: str) -> str:
        """
        Thread-safe async version of generate_research_citation_id for parallel mode

        Args:
            block_id: Block ID (e.g., "block_3")

        Returns:
            Citation ID in CIT-X-XX format
        """
        async with self._lock:
            return self.generate_research_citation_id(block_id)

    async def get_next_citation_id_async(self, stage: str = "research", block_id: str = "") -> str:
        """
        Thread-safe async version of get_next_citation_id for parallel mode

        Args:
            stage: "planning" or "research"
            block_id: Block ID (required for research stage)

        Returns:
            Next available citation ID
        """
        async with self._lock:
            return self.get_next_citation_id(stage, block_id)

    async def add_citation_async(
        self,
        citation_id: str,
        tool_type: str,
        tool_trace: Any,
        raw_answer: str,
    ) -> bool:
        """
        Thread-safe async version of add_citation for parallel mode

        Args:
            citation_id: Citation ID
            tool_type: Tool type
            tool_trace: ToolTrace object
            raw_answer: Raw answer (JSON string)

        Returns:
            Whether addition was successful
        """
        async with self._lock:
            return self.add_citation(citation_id, tool_type, tool_trace, raw_answer)


__all__ = ["CitationManager"]
