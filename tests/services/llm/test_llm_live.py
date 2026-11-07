"""
Live LLM connectivity test.

Run directly to verify your .env / config is working:

    python tests/services/llm/test_llm_live.py
    python tests/services/llm/test_llm_live.py --stream    # also test streaming
    python tests/services/llm/test_llm_live.py --model gpt-4o --base-url https://api.openai.com/v1 --api-key sk-xxx
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

# ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
RED = "\033[31m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RESET = "\033[0m"
CHECK = f"{GREEN}✓{RESET}"
CROSS = f"{RED}✗{RESET}"


def _mask(secret: str | None, visible: int = 8) -> str:
    if not secret:
        return "(empty)"
    if len(secret) <= visible:
        return secret
    return secret[:visible] + "…"


async def run_test(
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    binding: str | None = None,
    test_stream: bool = False,
) -> bool:
    from src.services.llm import config as config_module
    from src.services.llm.config import LLMConfig, get_llm_config

    config_module._LLM_CONFIG_CACHE = None
    cfg = get_llm_config()

    effective_model = model or cfg.model
    effective_key = api_key if api_key is not None else cfg.api_key
    effective_url = base_url or cfg.base_url
    effective_binding = binding or cfg.binding

    print(f"\n{BOLD}{'═' * 60}{RESET}")
    print(f"  {BOLD}{CYAN}LLM Configuration Test{RESET}")
    print(f"{BOLD}{'═' * 60}{RESET}")
    print(f"  Binding:   {effective_binding}")
    print(f"  Model:     {effective_model}")
    print(f"  Base URL:  {effective_url}")
    print(f"  API Key:   {_mask(effective_key)}")
    print(f"{BOLD}{'─' * 60}{RESET}")

    ok = True

    # --- Test 1: completion ---
    print(f"\n  {BOLD}[1/{'2' if test_stream else '1'}] Completion{RESET}", end=" ", flush=True)
    try:
        from src.services.llm.factory import complete

        t0 = time.perf_counter()
        resp = await complete(
            "Reply with exactly: HELLO_DEEPTUTOR",
            system_prompt="You are a test bot. Follow instructions exactly.",
            model=effective_model,
            api_key=effective_key,
            base_url=effective_url,
            binding=effective_binding,
            temperature=0.0,
            max_tokens=64,
            max_retries=1,
        )
        elapsed = time.perf_counter() - t0
        print(f"{CHECK}  {DIM}{elapsed:.2f}s{RESET}")
        preview = resp.strip().replace("\n", " ")
        if len(preview) > 120:
            preview = preview[:120] + "…"
        print(f"  {DIM}Response: {preview}{RESET}")
    except Exception as exc:
        print(f"{CROSS}")
        print(f"  {RED}Error: {exc}{RESET}")
        ok = False

    # --- Test 2: streaming (optional) ---
    if test_stream:
        print(f"\n  {BOLD}[2/2] Streaming{RESET}", end=" ", flush=True)
        try:
            from src.services.llm.factory import stream

            chunks: list[str] = []
            t0 = time.perf_counter()
            first_chunk_time: float | None = None
            async for chunk in stream(
                "Count from 1 to 5, one number per line.",
                system_prompt="You are a test bot.",
                model=effective_model,
                api_key=effective_key,
                base_url=effective_url,
                binding=effective_binding,
                temperature=0.0,
                max_tokens=64,
                max_retries=1,
            ):
                if first_chunk_time is None:
                    first_chunk_time = time.perf_counter() - t0
                chunks.append(chunk)
            elapsed = time.perf_counter() - t0
            full = "".join(chunks).strip().replace("\n", " ")
            if len(full) > 120:
                full = full[:120] + "…"
            ttft = first_chunk_time if first_chunk_time is not None else elapsed
            print(f"{CHECK}  {DIM}{elapsed:.2f}s (TTFT {ttft:.2f}s, {len(chunks)} chunks){RESET}")
            print(f"  {DIM}Response: {full}{RESET}")
        except Exception as exc:
            print(f"{CROSS}")
            print(f"  {RED}Error: {exc}{RESET}")
            ok = False

    # --- Summary ---
    print(f"\n{BOLD}{'═' * 60}{RESET}")
    if ok:
        print(f"  {CHECK} {GREEN}All tests passed{RESET}")
    else:
        print(f"  {CROSS} {RED}Some tests failed{RESET}")
    print(f"{BOLD}{'═' * 60}{RESET}\n")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="Test LLM configuration connectivity")
    parser.add_argument("--model", help="Override model name")
    parser.add_argument("--base-url", help="Override base URL")
    parser.add_argument("--api-key", help="Override API key")
    parser.add_argument("--binding", help="Override provider binding")
    parser.add_argument("--stream", action="store_true", help="Also test streaming")
    args = parser.parse_args()

    ok = asyncio.run(
        run_test(
            model=args.model,
            api_key=args.api_key,
            base_url=args.base_url,
            binding=args.binding,
            test_stream=args.stream,
        )
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
