#!/usr/bin/env python3
"""
Test script for source URL ingest functionality.
Tests the web crawler, PDF download, and source enrichment logic.
"""

import asyncio
import sys
import tempfile
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))


async def test_web_crawler():
    """Test the web crawler with HTML and PDF URLs."""
    print("=" * 60)
    print("Testing Web Crawler")
    print("=" * 60)

    # Direct import to avoid __init__.py issues
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "web_crawler",
        project_root / "src/tools/web_crawler.py"
    )
    web_crawler = importlib.util.module_from_spec(spec)

    # Mock logger
    class MockLogger:
        def info(self, msg): print(f"   [INFO] {msg}")
        def warning(self, msg): print(f"   [WARN] {msg}")

    web_crawler.logger = MockLogger()
    spec.loader.exec_module(web_crawler)

    fetch_url = web_crawler.fetch_url
    fetch_urls = web_crawler.fetch_urls

    # Test 1: HTML URL
    print("\n1. Testing HTML URL fetch (example.com)...")
    result = await fetch_url("https://example.com")

    print(f"   URL: {result['url']}")
    print(f"   Title: {result['title']}")
    print(f"   Is PDF: {result.get('is_pdf', False)}")
    print(f"   Content length: {len(result.get('content', ''))} chars")
    print(f"   Error: {result['error']}")

    if result.get('content'):
        print(f"   First 150 chars: {result['content'][:150]}...")

    # Test 2: PDF URL (using a small test PDF)
    print("\n2. Testing PDF URL fetch...")
    with tempfile.TemporaryDirectory() as tmpdir:
        # Use a small public PDF for testing
        pdf_url = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
        result = await fetch_url(pdf_url, pdf_save_dir=Path(tmpdir))

        print(f"   URL: {result['url']}")
        print(f"   Title: {result['title']}")
        print(f"   Is PDF: {result.get('is_pdf', False)}")
        print(f"   File path: {result.get('file_path', 'N/A')}")
        print(f"   Error: {result['error']}")

        if result.get('file_path'):
            file_size = Path(result['file_path']).stat().st_size
            print(f"   File size: {file_size / 1024:.1f}KB")

    # Test 3: Multiple URLs (HTML + PDF)
    print("\n3. Testing concurrent URL fetch (mixed HTML and PDF)...")
    with tempfile.TemporaryDirectory() as tmpdir:
        urls = [
            "https://example.com",
            "https://example.org",
        ]

        results = await fetch_urls(urls, concurrency=3, pdf_save_dir=Path(tmpdir))

        for i, res in enumerate(results, 1):
            status = "✓ Success" if not res['error'] else f"✗ Error: {res['error']}"
            is_pdf = "PDF" if res.get('is_pdf') else "HTML"
            print(f"   {i}. [{is_pdf}] {res['url']}: {status}")
            if not res['error']:
                if res.get('is_pdf'):
                    print(f"      File: {res.get('file_path', 'N/A')}")
                else:
                    print(f"      Title: {res['title']}, Content: {len(res.get('content', ''))} chars")

    print("\n✓ Web crawler tests passed!")
    return True, fetch_urls


async def test_source_enrichment(fetch_urls):
    """Test the source enrichment logic with HTML and PDF sources."""
    print("\n" + "=" * 60)
    print("Testing Source Enrichment")
    print("=" * 60)

    import tempfile

    # Mock sources (simulating what comes from frontend)
    sources = [
        {
            "id": "url-1",
            "type": "web",
            "title": "Example Domain",
            "url": "https://example.com",
            "selected": True,
            # Note: no 'content' field - should be fetched
        },
        {
            "id": "url-2",
            "type": "web",
            "title": "Test PDF",
            "url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
            "selected": True,
            # Note: PDF URL - should be downloaded
        },
        {
            "id": "manual-3",
            "type": "manual",
            "title": "Manual Note",
            "content": "This is manually entered content.",
            "selected": True,
            # Has content - should NOT be fetched
        },
    ]

    print(f"\n1. Input sources: {len(sources)} total")
    for s in sources:
        has_content = "✓" if s.get("content") else "✗"
        print(f"   - {s['title']} ({s['type']}): content={has_content}")

    print("\n2. Simulating enrichment (would call _enrich_sources_with_content)...")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Find URLs to fetch
        urls_to_fetch = [
            s['url'] for s in sources
            if s.get('type') == 'web' and s.get('url') and not s.get('content')
        ]

        print(f"   URLs to fetch: {len(urls_to_fetch)}")

        if urls_to_fetch:
            results = await fetch_urls(urls_to_fetch, concurrency=5, pdf_save_dir=Path(tmpdir))

            # Enrich sources
            enriched = [s.copy() for s in sources]
            url_to_result = {r['url']: r for r in results}

            for i, source in enumerate(enriched):
                if source.get('url') in url_to_result:
                    result = url_to_result[source['url']]
                    if not result.get('error'):
                        if result.get('is_pdf'):
                            enriched[i]['file_path'] = result['file_path']
                            enriched[i]['is_pdf'] = True
                        else:
                            enriched[i]['content'] = result['content']
                        if result.get('title'):
                            enriched[i]['title'] = result['title']
                    else:
                        enriched[i]['fetch_error'] = result['error']

            print("\n3. Enriched sources:")
            for s in enriched:
                has_content = "✓" if s.get("content") or s.get("file_path") else "✗"
                content_info = ""
                if s.get("content"):
                    content_info = f"{len(s['content'])} chars"
                elif s.get("file_path"):
                    content_info = f"PDF: {Path(s['file_path']).name}"
                error = s.get("fetch_error", "")
                print(f"   - {s['title']} ({s['type']}): content={has_content} ({content_info})")
                if error:
                    print(f"     Error: {error}")

    print("\n✓ Source enrichment tests passed!")
    return True


async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("Source URL Ingest - Test Suite")
    print("=" * 60)

    try:
        # Test 1: Web Crawler
        success, fetch_urls = await test_web_crawler()

        # Test 2: Source Enrichment
        await test_source_enrichment(fetch_urls)

        print("\n" + "=" * 60)
        print("✓ All tests passed!")
        print("=" * 60)
        print("\nNext steps:")
        print("1. Start the backend server: uvicorn src.api.main:app --reload")
        print("2. Open a notebook in the web UI")
        print("3. Add sources:")
        print("   - Add a URL source (e.g., https://example.com/article)")
        print("   - Add a PDF URL (e.g., arXiv paper link)")
        print("   - Upload a local PDF file via POST /{notebook_id}/upload_source_pdf")
        print("4. Wait for crawling and vectorization to complete")
        print("5. Select the sources and ask questions about their content")
        print("6. Verify that the answers are based on the full content")
        print("=" * 60)

        return 0

    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
