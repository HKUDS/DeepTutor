#!/usr/bin/env python3
"""
Quick embedding smoke test.

Usage examples:
  python3 src/tools/test_embedding.py --text "hello world"
  python3 src/tools/test_embedding.py --text "test" --repeat 3 --show-config
  python3 src/tools/test_embedding.py --direct
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Make project imports work when run as a script
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / "DeepTutor.env", override=False)
load_dotenv(PROJECT_ROOT / ".env", override=False)

from src.services.embedding.client import get_embedding_client, reset_embedding_client
from src.services.embedding.config import get_embedding_config


def _mask_key(key: str) -> str:
    if not key:
        return "(empty)"
    if len(key) <= 10:
        return "*" * len(key)
    return f"{key[:6]}...{key[-4:]}"


async def run_client_test(text: str, repeat: int) -> None:
    reset_embedding_client()
    client = get_embedding_client()
    cfg = get_embedding_config()

    inputs = [f"{text} #{i+1}" if repeat > 1 else text for i in range(repeat)]
    print("[ClientTest] Calling EmbeddingClient.embed(...)")
    vectors = await client.embed(inputs)

    dim = len(vectors[0]) if vectors else 0
    print(f"[ClientTest] OK: vectors={len(vectors)}, dim={dim}, model={cfg.model}")
    if vectors:
        preview = vectors[0][:8]
        print(f"[ClientTest] First vector preview (8 dims): {preview}")


async def run_direct_test(text: str) -> None:
    cfg = get_embedding_config()
    url = f"{(cfg.base_url or '').rstrip('/')}/embeddings"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg.api_key}",
    }
    payload = {
        "input": [text],
        "model": cfg.model,
        "encoding_format": "float",
    }
    if cfg.dim:
        payload["dimensions"] = cfg.dim

    print(f"[DirectTest] POST {url}")
    async with httpx.AsyncClient(timeout=cfg.request_timeout) as client:
        resp = await client.post(url, headers=headers, json=payload)
    print(f"[DirectTest] status={resp.status_code}")

    body_text = resp.text.strip()
    try:
        body_json = resp.json()
        print("[DirectTest] JSON response:")
        print(json.dumps(body_json, ensure_ascii=False, indent=2)[:4000])
    except Exception:
        print("[DirectTest] Non-JSON response:")
        print(body_text[:2000])


async def main() -> None:
    parser = argparse.ArgumentParser(description="Quick embedding smoke test")
    parser.add_argument("--text", default="hello world", help="Input text for embedding")
    parser.add_argument("--repeat", type=int, default=1, help="How many inputs to send")
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Print effective embedding config before testing",
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Also directly call /embeddings endpoint and print raw response",
    )
    args = parser.parse_args()

    cfg = get_embedding_config()
    if args.show_config:
        print("[Config]")
        print(f"  binding={cfg.binding}")
        print(f"  host={cfg.base_url}")
        print(f"  model={cfg.model}")
        print(f"  dim={cfg.dim}")
        print(f"  timeout={cfg.request_timeout}")
        print(f"  batch_size={cfg.batch_size}")
        print(f"  api_key={_mask_key(cfg.api_key)}")

    try:
        await run_client_test(args.text, max(1, args.repeat))
    except Exception as e:
        print(f"[ClientTest] FAILED: {type(e).__name__}: {e}")

    if args.direct:
        try:
            await run_direct_test(args.text)
        except Exception as e:
            print(f"[DirectTest] FAILED: {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
