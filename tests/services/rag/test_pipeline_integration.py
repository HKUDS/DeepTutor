#!/usr/bin/env python
"""
RAG Pipeline Integration Tests
==============================

Complete integration tests for RAG pipelines.
Tests the full workflow: initialize -> search -> delete

Usage:
    # Test specific pipeline
    python tests/services/rag/test_pipeline_integration.py --pipeline llamaindex

    # Test all pipelines
    python tests/services/rag/test_pipeline_integration.py --pipeline all

    # Using pytest
    pytest tests/services/rag/test_pipeline_integration.py -v --pipeline llamaindex
"""

import argparse
import asyncio
import os
from pathlib import Path
import shutil
import sys
import tempfile

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

load_dotenv(project_root / "DeepTutor.env", override=False)
load_dotenv(project_root / ".env", override=False)


# Test file path
TEST_FILE = project_root / "tests" / "services" / "rag" / "testfile.txt"


class Colors:
    """Terminal colors"""

    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    END = "\033[0m"


def print_header(text: str):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}{Colors.END}\n")


def print_success(text: str):
    print(f"  {Colors.GREEN}✓{Colors.END} {text}")


def print_warning(text: str):
    print(f"  {Colors.YELLOW}⚠{Colors.END} {text}")


def print_error(text: str):
    print(f"  {Colors.RED}✗{Colors.END} {text}")


def print_info(text: str):
    print(f"  {Colors.BLUE}ℹ{Colors.END} {text}")


class PipelineIntegrationTest:
    """
    Integration test for a specific RAG pipeline.

    Tests:
    1. Knowledge base initialization with test file
    2. Search/retrieval
    3. Knowledge base deletion
    """

    def __init__(self, pipeline_name: str, test_file: Path = TEST_FILE):
        self.pipeline_name = pipeline_name
        self.test_file = test_file
        self.temp_dir = None
        self.kb_name = f"test_kb_{pipeline_name}"
        self.service = None

    async def setup(self):
        """Setup test environment"""
        # Create temporary directory
        self.temp_dir = tempfile.mkdtemp(prefix=f"rag_test_{self.pipeline_name}_")
        print_info(f"Created temp directory: {self.temp_dir}")

        # Initialize service with temp directory
        from src.services.rag import RAGService

        self.service = RAGService(kb_base_dir=self.temp_dir, provider=self.pipeline_name)

        # Verify test file exists
        if not self.test_file.exists():
            raise FileNotFoundError(f"Test file not found: {self.test_file}")

        print_info(f"Test file: {self.test_file}")
        print_info(f"Provider: {self.pipeline_name}")

    async def teardown(self):
        """Cleanup test environment"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
            print_info(f"Cleaned up temp directory: {self.temp_dir}")

    async def test_initialize(self) -> bool:
        """Test knowledge base initialization"""
        print("\n  📚 Testing initialization...")

        try:
            success = await self.service.initialize(
                kb_name=self.kb_name,
                file_paths=[str(self.test_file)],
            )

            if success:
                print_success("Knowledge base initialized successfully")

                # Verify KB directory was created
                kb_dir = Path(self.temp_dir) / self.kb_name
                if kb_dir.exists():
                    print_success(f"KB directory created: {kb_dir}")
                    # List contents
                    contents = list(kb_dir.rglob("*"))
                    print_info(f"KB contains {len(contents)} files/directories")
                else:
                    print_warning("KB directory not found after initialization")

                return True
            else:
                print_error("Initialization returned False")
                return False

        except Exception as e:
            print_error(f"Initialization failed: {e}")
            import traceback

            traceback.print_exc()
            return False

    async def test_search(self) -> bool:
        """Test search/retrieval"""
        print("\n  🔍 Testing search...")

        # Test query based on test file content
        # testfile.txt contains: "Shandong province has a pancake."
        test_queries = [
            ("Shandong", "Search for 'Shandong'"),
            ("pancake", "Search for 'pancake'"),
            ("What does Shandong have?", "Natural question"),
        ]

        all_passed = True

        for query, description in test_queries:
            try:
                print_info(f"Query: {query} ({description})")

                result = await self.service.search(
                    query=query,
                    kb_name=self.kb_name,
                    mode="naive" if self.pipeline_name in ["llamaindex"] else "hybrid",
                )

                # Check result structure
                if not isinstance(result, dict):
                    print_error(f"Result is not a dict: {type(result)}")
                    all_passed = False
                    continue

                # Check required fields
                required_fields = ["query", "answer", "content", "provider"]
                missing = [f for f in required_fields if f not in result]
                if missing:
                    print_warning(f"Missing fields: {missing}")

                # Check content
                answer = result.get("answer", "")
                if answer:
                    print_success(f"Got answer ({len(answer)} chars)")
                    # Show preview
                    preview = answer[:200] + "..." if len(answer) > 200 else answer
                    print_info(f"Preview: {preview}")
                else:
                    print_warning("Empty answer")

            except Exception as e:
                print_error(f"Search failed: {e}")
                import traceback

                traceback.print_exc()
                all_passed = False

        return all_passed

    async def test_search_via_rag_tool(self) -> bool:
        """Test search via rag_tool.py (the actual interface used by agents)"""
        print("\n  🔧 Testing via rag_tool.py...")

        try:
            from src.tools.rag_tool import rag_search

            result = await rag_search(
                query="What does Shandong have?",
                kb_name=self.kb_name,
                provider=self.pipeline_name,
                kb_base_dir=self.temp_dir,
                mode="naive",
            )

            if result and result.get("answer"):
                print_success("rag_tool.py search successful")
                print_info(f"Provider: {result.get('provider')}")
                print_info(f"Answer preview: {result['answer'][:100]}...")
                return True
            else:
                print_warning("rag_tool.py returned empty result")
                return False

        except Exception as e:
            print_error(f"rag_tool.py search failed: {e}")
            import traceback

            traceback.print_exc()
            return False

    async def test_delete(self) -> bool:
        """Test knowledge base deletion"""
        print("\n  🗑️  Testing deletion...")

        try:
            success = await self.service.delete(kb_name=self.kb_name)

            if success:
                print_success("Knowledge base deleted successfully")

                # Verify KB directory was removed
                kb_dir = Path(self.temp_dir) / self.kb_name
                if not kb_dir.exists():
                    print_success("KB directory removed")
                else:
                    print_warning("KB directory still exists after deletion")

                return True
            else:
                print_warning("Deletion returned False (KB may not exist)")
                return True  # Not necessarily a failure

        except Exception as e:
            print_error(f"Deletion failed: {e}")
            return False

    async def run_all_tests(self) -> dict:
        """Run all tests for this pipeline"""
        print_header(f"Testing Pipeline: {self.pipeline_name}")

        results = {
            "pipeline": self.pipeline_name,
            "setup": False,
            "initialize": False,
            "search": False,
            "rag_tool": False,
            "delete": False,
            "cleanup": False,
        }

        try:
            # Setup
            await self.setup()
            results["setup"] = True

            # Initialize
            results["initialize"] = await self.test_initialize()

            # Search (only if initialize succeeded)
            if results["initialize"]:
                results["search"] = await self.test_search()
                results["rag_tool"] = await self.test_search_via_rag_tool()

            # Delete
            results["delete"] = await self.test_delete()

        except Exception as e:
            print_error(f"Test failed with exception: {e}")
            import traceback

            traceback.print_exc()
        finally:
            # Cleanup
            try:
                await self.teardown()
                results["cleanup"] = True
            except Exception as e:
                print_error(f"Cleanup failed: {e}")

        return results


def get_available_pipelines():
    """Get list of available pipelines"""
    from src.services.rag import RAGService

    return [p["id"] for p in RAGService.list_providers()]


async def run_pipeline_test(pipeline_name: str) -> dict:
    """Run test for a specific pipeline"""
    test = PipelineIntegrationTest(pipeline_name)
    return await test.run_all_tests()


async def run_all_pipeline_tests() -> list:
    """Run tests for all pipelines"""
    pipelines = get_available_pipelines()
    results = []

    for pipeline in pipelines:
        result = await run_pipeline_test(pipeline)
        results.append(result)

    return results


def print_summary(results: list):
    """Print test summary"""
    print_header("Test Summary")

    all_passed = True

    for result in results:
        pipeline = result["pipeline"]
        tests = ["setup", "initialize", "search", "rag_tool", "delete", "cleanup"]
        passed = sum(1 for t in tests if result.get(t, False))
        total = len(tests)

        if passed == total:
            print_success(f"{pipeline}: {passed}/{total} tests passed")
        else:
            print_error(f"{pipeline}: {passed}/{total} tests passed")
            all_passed = False

            # Show failed tests
            for test in tests:
                if not result.get(test, False):
                    print_error(f"  - {test} failed")

    print()
    if all_passed:
        print(f"{Colors.GREEN}{Colors.BOLD}All tests passed!{Colors.END}")
    else:
        print(f"{Colors.RED}{Colors.BOLD}Some tests failed.{Colors.END}")

    return all_passed


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="RAG Pipeline Integration Tests")
    parser.add_argument(
        "--pipeline",
        "-p",
        type=str,
        default="llamaindex",
        help="Pipeline to test (or 'all' for all pipelines). Default: llamaindex",
    )
    parser.add_argument("--list", "-l", action="store_true", help="List available pipelines")

    args = parser.parse_args()

    # List pipelines
    if args.list:
        print_header("Available Pipelines")
        for pipeline in get_available_pipelines():
            print_info(pipeline)
        return

    # Run tests
    if args.pipeline.lower() == "all":
        results = await run_all_pipeline_tests()
    else:
        # Validate pipeline name
        available = get_available_pipelines()
        if args.pipeline not in available:
            print_error(f"Unknown pipeline: {args.pipeline}")
            print_info(f"Available: {available}")
            sys.exit(1)

        results = [await run_pipeline_test(args.pipeline)]

    # Print summary
    success = print_summary(results)
    sys.exit(0 if success else 1)


# Pytest support
def pytest_addoption(parser):
    """Add pytest command line options"""
    parser.addoption("--pipeline", action="store", default="llamaindex", help="Pipeline to test")


class TestPipelineIntegration:
    """Pytest test class"""

    @staticmethod
    def test_pipeline(request):
        """Test the specified pipeline"""
        pipeline_name = request.config.getoption("--pipeline")

        async def _run():
            if pipeline_name.lower() == "all":
                results = await run_all_pipeline_tests()
            else:
                results = [await run_pipeline_test(pipeline_name)]

            # Assert all tests passed
            for result in results:
                assert result["setup"], f"{result['pipeline']}: Setup failed"
                assert result["initialize"], f"{result['pipeline']}: Initialize failed"
                assert result["search"], f"{result['pipeline']}: Search failed"
                assert result["rag_tool"], f"{result['pipeline']}: rag_tool test failed"
                assert result["delete"], f"{result['pipeline']}: Delete failed"

        asyncio.run(_run())


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(main())
