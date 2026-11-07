#!/usr/bin/env python
"""
Multi-KB RAG Query Tool - Query multiple knowledge bases with reranking

This tool provides:
1. Parallel querying of multiple knowledge bases
2. Result merging and reranking via API
3. Flexible output formats (simple or detailed)
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import aiohttp

# Add parent directory to path
project_root = Path(__file__).parent.parent.parent

from dotenv import load_dotenv
from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc
from raganything import RAGAnything, RAGAnythingConfig

from src.core.core import get_embedding_config, get_llm_config, get_rerank_config, load_config_with_main
from src.core.logging import LightRAGLogContext, get_logger
from src.knowledge.manager import KnowledgeBaseManager

# Load environment variables
load_dotenv(project_root / "DeepTutor.env", override=False)
load_dotenv(project_root / ".env", override=False)

# Initialize logger
config = load_config_with_main("solve_config.yaml", project_root)
log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get("log_dir")
logger = get_logger("MultiKBRAG", level="INFO", log_dir=log_dir)


def _get_multi_kb_config() -> dict:
    """Get multi-KB RAG configuration from main.yaml"""
    try:
        config = load_config_with_main("solve_config.yaml", project_root)
        return config.get("multi_kb_rag", {})
    except Exception:
        return {}


async def _query_single_kb(
    query: str,
    kb_name: str,
    top_k: int,
    mode: str,
    llm_model_func,
    embedding_func,
    kb_base_dir: str,
) -> dict:
    """
    Query a single knowledge base and return raw context chunks.
    
    Args:
        query: Query text
        kb_name: Knowledge base name
        top_k: Number of results to retrieve
        mode: Query mode (hybrid, naive, etc.)
        llm_model_func: LLM model function
        embedding_func: Embedding function
        kb_base_dir: Knowledge base base directory
        
    Returns:
        dict with kb_name, chunks, and any errors
    """
    try:
        kb_manager = KnowledgeBaseManager(kb_base_dir)
        working_dir = str(kb_manager.get_rag_storage_path(kb_name))
        
        config = RAGAnythingConfig(
            working_dir=working_dir,
            enable_image_processing=True,
            enable_table_processing=True,
            enable_equation_processing=True,
        )
        
        with LightRAGLogContext(scene="multi_kb_rag"):
            rag = RAGAnything(
                config=config,
                llm_model_func=llm_model_func,
                embedding_func=embedding_func,
                lightrag_kwargs={"top_k": top_k},
            )
            
            await rag._ensure_lightrag_initialized()
            
            # Get raw context without LLM processing
            answer = await rag.aquery(query, mode=mode, only_need_context=True)
            
            return {
                "kb_name": kb_name,
                "content": answer if isinstance(answer, str) else str(answer),
                "success": True,
                "error": None,
            }
            
    except Exception as e:
        logger.warning(f"Failed to query KB '{kb_name}': {e}")
        return {
            "kb_name": kb_name,
            "content": "",
            "success": False,
            "error": str(e),
        }


def _parse_context_to_chunks(content: str, kb_name: str) -> list[dict]:
    """
    Parse context string into individual chunks with metadata.
    
    Args:
        content: Raw context string from RAG
        kb_name: Source knowledge base name
        
    Returns:
        List of chunk dictionaries
    """
    if not content or not content.strip():
        return []
    
    chunks = []
    
    # Try to split by common separators used in LightRAG output
    # LightRAG typically returns chunks separated by newlines or specific markers
    separators = ["\n---\n", "\n\n---\n\n", "\n========\n"]
    
    parts = [content]
    for sep in separators:
        if sep in content:
            parts = content.split(sep)
            break
    
    # If no separator found, try splitting by double newlines
    if len(parts) == 1 and "\n\n" in content:
        parts = content.split("\n\n")
    
    for i, part in enumerate(parts):
        part = part.strip()
        if part:
            chunks.append({
                "content": part,
                "source_kb": kb_name,
                "chunk_index": i,
                "original_score": 1.0 - (i * 0.01),  # Approximate score based on order
            })
    
    return chunks


async def _call_rerank_api(
    query: str,
    chunks: list[dict],
    rerank_model: str | None = None,
    rerank_api_url: str | None = None,
    rerank_api_key: str | None = None,
    timeout: int = 30,
) -> list[dict]:
    """
    Call external rerank API to reorder chunks by relevance.
    
    Supports multiple API formats:
    - DashScope/Qwen rerank API (qwen3-rerank)
    - OpenAI-compatible rerank API
    - Generic rerank API
    
    Args:
        query: Query text
        chunks: List of chunk dictionaries with 'content' field
        rerank_model: Rerank model name (e.g., "qwen3-rerank")
        rerank_api_url: Rerank API endpoint URL
        rerank_api_key: API key for authentication
        timeout: Request timeout in seconds
        
    Returns:
        Reranked list of chunks with rerank_score added
    """
    if not chunks:
        return []
    
    # Try to get config from environment if not provided
    if not rerank_api_url or not rerank_api_key:
        try:
            rerank_config = get_rerank_config()
            if not rerank_model:
                rerank_model = rerank_config.get("model", "qwen3-rerank")
            if not rerank_api_key:
                rerank_api_key = rerank_config.get("api_key")
            if not rerank_api_url:
                # Use the full URL from config (RERANK_BINDING_HOST should be complete URL)
                rerank_api_url = rerank_config.get("base_url")
        except Exception as e:
            logger.warning(f"Failed to get rerank config: {e}")
    
    if not rerank_api_url:
        logger.warning("No rerank API URL configured, returning original order")
        for chunk in chunks:
            chunk["rerank_score"] = chunk.get("original_score", 0.5)
        return chunks
    
    try:
        # Prepare request payload based on API type
        documents = [chunk["content"] for chunk in chunks]
        
        # DashScope/OpenAI-compatible rerank format
        payload = {
            "model": rerank_model or "qwen3-rerank",
            "query": query,
            "documents": documents,
            "top_n": len(documents),  # Return all with scores
            "return_documents": False,  # Only need indices and scores
        }
        
        headers = {
            "Content-Type": "application/json",
        }
        if rerank_api_key:
            headers["Authorization"] = f"Bearer {rerank_api_key}"
        
        logger.debug(f"Calling rerank API: {rerank_api_url}, model={rerank_model}")
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                rerank_api_url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Rerank API error: {response.status} - {error_text}")
                    # Fallback: return original order with original scores
                    for chunk in chunks:
                        chunk["rerank_score"] = chunk.get("original_score", 0.5)
                    return chunks
                
                result = await response.json()
                logger.debug(f"Rerank API response keys: {result.keys() if isinstance(result, dict) else 'list'}")
                
                # Parse response - support common rerank API formats
                # Format 1 (DashScope/Qwen): {"results": [{"index": 0, "relevance_score": 0.9}, ...]}
                # Format 2: {"results": [{"index": 0, "score": 0.9}, ...]}
                # Format 3: {"scores": [0.9, 0.8, ...]}
                # Format 4: [{"index": 0, "relevance_score": 0.9}, ...]
                
                if "results" in result:
                    # Sort by score descending
                    ranked_results = sorted(
                        result["results"],
                        key=lambda x: x.get("relevance_score", x.get("score", 0)),
                        reverse=True,
                    )
                    reranked_chunks = []
                    for r in ranked_results:
                        idx = r.get("index", r.get("document_index", 0))
                        if 0 <= idx < len(chunks):
                            chunk = chunks[idx].copy()
                            chunk["rerank_score"] = r.get("relevance_score", r.get("score", 0.5))
                            reranked_chunks.append(chunk)
                    logger.info(f"Reranked {len(reranked_chunks)} chunks")
                    return reranked_chunks
                
                elif "scores" in result:
                    scores = result["scores"]
                    for i, chunk in enumerate(chunks):
                        if i < len(scores):
                            chunk["rerank_score"] = scores[i]
                        else:
                            chunk["rerank_score"] = 0.0
                    # Sort by rerank score
                    return sorted(chunks, key=lambda x: x["rerank_score"], reverse=True)
                
                elif isinstance(result, list):
                    # Direct list response
                    ranked_results = sorted(
                        result,
                        key=lambda x: x.get("relevance_score", x.get("score", 0)),
                        reverse=True,
                    )
                    reranked_chunks = []
                    for r in ranked_results:
                        idx = r.get("index", r.get("document_index", 0))
                        if 0 <= idx < len(chunks):
                            chunk = chunks[idx].copy()
                            chunk["rerank_score"] = r.get("relevance_score", r.get("score", 0.5))
                            reranked_chunks.append(chunk)
                    return reranked_chunks
                
                else:
                    logger.warning(f"Unknown rerank API response format: {result}")
                    for chunk in chunks:
                        chunk["rerank_score"] = chunk.get("original_score", 0.5)
                    return chunks
                    
    except asyncio.TimeoutError:
        logger.error(f"Rerank API timeout after {timeout}s")
        for chunk in chunks:
            chunk["rerank_score"] = chunk.get("original_score", 0.5)
        return chunks
    except Exception as e:
        logger.error(f"Rerank API call failed: {e}")
        for chunk in chunks:
            chunk["rerank_score"] = chunk.get("original_score", 0.5)
        return chunks


def _format_merged_context(chunks: list[dict], max_length: int | None = None) -> str:
    """
    Format chunks into a merged context string.
    
    Args:
        chunks: List of chunk dictionaries
        max_length: Optional maximum length for output
        
    Returns:
        Merged context string
    """
    if not chunks:
        return ""
    
    parts = []
    for i, chunk in enumerate(chunks):
        kb_name = chunk.get("source_kb", "unknown")
        content = chunk.get("content", "")
        score = chunk.get("rerank_score", chunk.get("original_score", 0))
        
        # Format: [source_kb] content
        part = f"[{kb_name}] {content}"
        parts.append(part)
    
    merged = "\n\n---\n\n".join(parts)
    
    if max_length and len(merged) > max_length:
        merged = merged[:max_length] + "..."
    
    return merged


async def multi_kb_rag_search(
    query: str,
    kb_names: list[str] | None = None,
    top_k_per_kb: int | None = None,
    final_top_k: int | None = None,
    mode: str = "hybrid",
    rerank_api_url: str | None = None,
    rerank_api_key: str | None = None,
    return_detailed: bool = False,
    kb_base_dir: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    **kwargs,
) -> dict:
    """
    Query multiple knowledge bases with reranking.
    
    This function:
    1. Queries all specified knowledge bases in parallel
    2. Merges all results
    3. Calls rerank API to reorder by relevance
    4. Returns top results
    
    Args:
        query: Query text
        kb_names: List of knowledge base names (None = all available)
        top_k_per_kb: Number of results per KB (default: from config or 20)
        final_top_k: Final number of results after reranking (default: from config or 10)
        mode: Query mode ("local", "global", "hybrid", "naive")
        rerank_api_url: Rerank API endpoint URL
        rerank_api_key: Rerank API key (optional)
        return_detailed: If True, return detailed results with scores
        kb_base_dir: Knowledge base base directory
        api_key: LLM API key (optional)
        base_url: LLM API base URL (optional)
        **kwargs: Additional query parameters
        
    Returns:
        dict: Query results
            Simple format (return_detailed=False):
            {
                "query": str,
                "answer": str,  # Merged context
                "mode": str,
                "source_kbs": list[str]
            }
            
            Detailed format (return_detailed=True):
            {
                "query": str,
                "results": [
                    {
                        "content": str,
                        "source_kb": str,
                        "rerank_score": float,
                        "original_score": float
                    },
                    ...
                ],
                "source_kbs": list[str]
            }
    """
    # Load configuration
    multi_kb_config = _get_multi_kb_config()
    
    # Apply defaults from config
    if top_k_per_kb is None:
        top_k_per_kb = multi_kb_config.get("default_top_k_per_kb", 20)
    if final_top_k is None:
        final_top_k = multi_kb_config.get("default_final_top_k", 10)
    if rerank_api_url is None:
        rerank_api_url = multi_kb_config.get("rerank_api_url")
    if rerank_api_key is None:
        rerank_api_key = multi_kb_config.get("rerank_api_key")
    
    # Get LLM configuration
    try:
        llm_config = get_llm_config()
    except ValueError as e:
        raise ValueError(f"LLM configuration error: {e}")
    
    # Get Embedding configuration
    try:
        embedding_config = get_embedding_config()
    except ValueError as e:
        raise ValueError(f"Embedding configuration error: {e}")
    
    # Override with provided parameters
    llm_api_key = api_key or llm_config["api_key"]
    llm_base_url = base_url or llm_config["base_url"]
    llm_model = llm_config["model"]
    
    embedding_api_key = embedding_config["api_key"]
    embedding_base_url = embedding_config["base_url"]
    embedding_model = embedding_config["model"]
    embedding_dim = embedding_config["dim"]
    embedding_max_tokens = embedding_config["max_tokens"]
    
    # Determine KB base directory
    if kb_base_dir is None:
        try:
            config = load_config_with_main("solve_config.yaml", project_root)
            kb_base_dir = config.get("paths", {}).get("knowledge_bases_dir")
            if kb_base_dir:
                kb_base_dir = str(project_root / kb_base_dir)
        except Exception:
            pass
        
        if kb_base_dir is None:
            kb_base_dir = str(project_root / "data" / "knowledge_bases")
    
    # Get knowledge base list
    kb_manager = KnowledgeBaseManager(kb_base_dir)
    
    if kb_names is None:
        kb_names = kb_manager.list_knowledge_bases()
        logger.info(f"Searching all {len(kb_names)} knowledge bases")
    else:
        # Validate KB names
        available_kbs = set(kb_manager.list_knowledge_bases())
        invalid_kbs = [kb for kb in kb_names if kb not in available_kbs]
        if invalid_kbs:
            logger.warning(f"Unknown knowledge bases will be skipped: {invalid_kbs}")
            kb_names = [kb for kb in kb_names if kb in available_kbs]
    
    if not kb_names:
        return {
            "query": query,
            "answer": "" if not return_detailed else None,
            "results": [] if return_detailed else None,
            "mode": mode,
            "source_kbs": [],
            "error": "No valid knowledge bases found",
        }
    
    logger.info(f"Multi-KB search: query='{query[:50]}...', kbs={kb_names}, mode={mode}")
    
    # Define LLM function
    def llm_model_func(prompt, system_prompt=None, history_messages=[], **kw):
        return openai_complete_if_cache(
            llm_model,
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
            api_key=llm_api_key,
            base_url=llm_base_url,
            **kw,
        )
    
    # Define embedding function
    embedding_func = EmbeddingFunc(
        embedding_dim=embedding_dim,
        max_token_size=embedding_max_tokens,
        func=lambda texts: openai_embed.func(
            texts,
            model=embedding_model,
            api_key=embedding_api_key,
            base_url=embedding_base_url,
        ),
    )
    
    # Parallel query all knowledge bases
    tasks = [
        _query_single_kb(
            query=query,
            kb_name=kb_name,
            top_k=top_k_per_kb,
            mode=mode,
            llm_model_func=llm_model_func,
            embedding_func=embedding_func,
            kb_base_dir=kb_base_dir,
        )
        for kb_name in kb_names
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Collect all chunks from successful queries
    all_chunks = []
    successful_kbs = []
    
    for result in results:
        if isinstance(result, Exception):
            logger.warning(f"Query task exception: {result}")
            continue
        
        if result.get("success"):
            successful_kbs.append(result["kb_name"])
            chunks = _parse_context_to_chunks(result["content"], result["kb_name"])
            all_chunks.extend(chunks)
        else:
            logger.warning(f"KB query failed: {result.get('kb_name')} - {result.get('error')}")
    
    logger.info(f"Collected {len(all_chunks)} chunks from {len(successful_kbs)} KBs")
    
    # Rerank all chunks (will auto-load config from env if not provided)
    if all_chunks:
        logger.info("Calling rerank API...")
        reranked_chunks = await _call_rerank_api(
            query=query,
            chunks=all_chunks,
            rerank_model=None,  # Will be loaded from config
            rerank_api_url=rerank_api_url,
            rerank_api_key=rerank_api_key,
        )
    else:
        # No chunks to rerank
        reranked_chunks = all_chunks
    
    # Take top results
    top_chunks = reranked_chunks[:final_top_k]
    
    # Format output
    if return_detailed:
        return {
            "query": query,
            "results": [
                {
                    "content": chunk["content"],
                    "source_kb": chunk["source_kb"],
                    "rerank_score": chunk.get("rerank_score", 0),
                    "original_score": chunk.get("original_score", 0),
                }
                for chunk in top_chunks
            ],
            "source_kbs": successful_kbs,
            "mode": mode,
        }
    else:
        merged_context = _format_merged_context(top_chunks)
        return {
            "query": query,
            "answer": merged_context,
            "mode": mode,
            "source_kbs": successful_kbs,
        }


# Synchronous wrapper for convenience
def multi_kb_rag_search_sync(
    query: str,
    kb_names: list[str] | None = None,
    **kwargs,
) -> dict:
    """Synchronous wrapper for multi_kb_rag_search"""
    return asyncio.run(multi_kb_rag_search(query, kb_names, **kwargs))


if __name__ == "__main__":
    import sys
    
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    
    # Test
    async def test():
        result = await multi_kb_rag_search(
            query="What is machine learning?",
            kb_names=None,  # Search all
            top_k_per_kb=10,
            final_top_k=5,
            mode="naive",
            return_detailed=True,
        )
        
        print(f"Query: {result['query']}")
        print(f"Source KBs: {result['source_kbs']}")
        if "results" in result:
            print(f"Results ({len(result['results'])}):")
            for r in result["results"]:
                print(f"  [{r['source_kb']}] score={r['rerank_score']:.3f}: {r['content'][:100]}...")
        else:
            print(f"Answer: {result['answer'][:500]}...")
    
    asyncio.run(test())
