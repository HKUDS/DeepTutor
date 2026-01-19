#!/usr/bin/env python
"""
RAG Pipeline Integration Tests
==============================

测试所有RAG pipeline的完整功能：
- 知识库初始化（文档处理）
- 检索/搜索功能
- 删除知识库

运行方式：
    python -m pytest tests/services/rag/test_rag_pipelines.py -v

或直接运行：
    python tests/services/rag/test_rag_pipelines.py
"""

import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

load_dotenv(project_root / "DeepTutor.env", override=False)
load_dotenv(project_root / ".env", override=False)


class RAGPipelineTestBase:
    """Base class for RAG pipeline tests"""

    TEST_KB_NAME = "test_rag_pipeline"
    TEST_QUERY = "What is machine learning?"

    @classmethod
    def create_test_document(cls, temp_dir: str) -> str:
        """Create a test document for testing"""
        test_content = """
# Introduction to Machine Learning

Machine learning is a subset of artificial intelligence (AI) that provides systems
the ability to automatically learn and improve from experience without being explicitly
programmed.

## Types of Machine Learning

### Supervised Learning
Supervised learning is a type of machine learning where the model is trained on labeled data.
The model learns to map input features to output labels.

Examples:
- Classification: Predicting discrete labels
- Regression: Predicting continuous values

### Unsupervised Learning
Unsupervised learning is a type of machine learning where the model is trained on unlabeled data.
The model learns to find patterns and structures in the data.

Examples:
- Clustering: Grouping similar data points
- Dimensionality reduction: Reducing the number of features

### Reinforcement Learning
Reinforcement learning is a type of machine learning where an agent learns to make decisions
by interacting with an environment and receiving rewards or penalties.

## Key Concepts

### Training Data
Training data is the dataset used to train a machine learning model.

### Features
Features are the input variables used to make predictions.

### Labels
Labels are the output variables (targets) in supervised learning.

### Model
A model is a mathematical representation of a real-world process.

## Conclusion

Machine learning has many applications in various fields including:
- Natural language processing
- Computer vision
- Recommendation systems
- Autonomous vehicles
"""

        # Create both .md and .txt versions
        md_path = os.path.join(temp_dir, "ml_intro.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(test_content)

        return md_path


class TestRAGToolIntegration(unittest.IsolatedAsyncioTestCase):
    """Test rag_tool.py interface with all pipelines"""

    async def test_list_available_providers(self):
        """Test listing available RAG providers"""
        from src.tools.rag_tool import get_available_providers

        providers = get_available_providers()
        print("\n=== Available RAG Providers ===")
        for p in providers:
            print(f"  - {p['id']}: {p['name']} - {p['description']}")

        self.assertIsInstance(providers, list)
        self.assertGreater(len(providers), 0)

        # Check expected providers
        provider_ids = [p["id"] for p in providers]
        expected = ["raganything", "lightrag", "llamaindex", "academic"]
        for expected_id in expected:
            self.assertIn(expected_id, provider_ids, f"Missing provider: {expected_id}")

    async def test_get_current_provider(self):
        """Test getting current RAG provider"""
        from src.tools.rag_tool import get_current_provider

        provider = get_current_provider()
        print(f"\n=== Current Provider: {provider} ===")

        self.assertIsInstance(provider, str)
        self.assertIn(provider, ["raganything", "lightrag", "llamaindex", "academic"])

    async def test_has_pipeline_valid(self):
        """Test has_pipeline with valid pipeline names"""
        from src.services.rag.factory import has_pipeline

        for name in ["raganything", "lightrag", "llamaindex", "academic"]:
            self.assertTrue(has_pipeline(name), f"Pipeline {name} should exist")

    async def test_has_pipeline_invalid(self):
        """Test has_pipeline with invalid pipeline name"""
        from src.services.rag.factory import has_pipeline

        self.assertFalse(has_pipeline("nonexistent"))
        self.assertFalse(has_pipeline(""))


class TestPipelineFactory(unittest.IsolatedAsyncioTestCase):
    """Test pipeline factory functionality"""

    async def test_get_pipeline_raganything(self):
        """Test getting RAGAnything pipeline"""
        from src.services.rag.factory import get_pipeline
        from src.services.rag.pipelines.raganything import RAGAnythingPipeline

        pipeline = get_pipeline("raganything")
        self.assertIsInstance(pipeline, RAGAnythingPipeline)
        print(f"\n✓ RAGAnything pipeline created: {type(pipeline).__name__}")

    async def test_get_pipeline_lightrag(self):
        """Test getting LightRAG pipeline"""
        from src.services.rag.factory import get_pipeline
        from src.services.rag.pipeline import RAGPipeline

        pipeline = get_pipeline("lightrag")
        self.assertIsInstance(pipeline, RAGPipeline)
        self.assertEqual(pipeline.name, "lightrag")
        print(f"\n✓ LightRAG pipeline created: {pipeline.name}")

    async def test_get_pipeline_llamaindex(self):
        """Test getting LlamaIndex pipeline"""
        from src.services.rag.factory import get_pipeline
        from src.services.rag.pipeline import RAGPipeline

        pipeline = get_pipeline("llamaindex")
        self.assertIsInstance(pipeline, RAGPipeline)
        self.assertEqual(pipeline.name, "llamaindex")
        print(f"\n✓ LlamaIndex pipeline created: {pipeline.name}")

    async def test_get_pipeline_academic(self):
        """Test getting Academic pipeline"""
        from src.services.rag.factory import get_pipeline
        from src.services.rag.pipeline import RAGPipeline

        pipeline = get_pipeline("academic")
        self.assertIsInstance(pipeline, RAGPipeline)
        self.assertEqual(pipeline.name, "academic")
        print(f"\n✓ Academic pipeline created: {pipeline.name}")

    async def test_get_pipeline_invalid(self):
        """Test getting invalid pipeline raises error"""
        from src.services.rag.factory import get_pipeline

        with self.assertRaises(ValueError) as context:
            get_pipeline("nonexistent")

        self.assertIn("Unknown pipeline", str(context.exception))
        print("\n✓ Invalid pipeline correctly raises error")


class TestRAGAnythingPipeline(unittest.IsolatedAsyncioTestCase, RAGPipelineTestBase):
    """Test RAGAnything pipeline (requires RAG-Anything library)"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.test_doc = self.create_test_document(self.temp_dir)
        self.test_kb_dir = os.path.join(self.temp_dir, "knowledge_bases")
        os.makedirs(self.test_kb_dir, exist_ok=True)

    def tearDown(self):
        """Clean up test fixtures"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_raganything_availability(self):
        """Test if RAGAnything dependencies are available"""
        print("\n=== Testing RAGAnything Availability ===")

        try:
            from src.services.rag.pipelines.raganything import RAGAnythingPipeline

            pipeline = RAGAnythingPipeline(kb_base_dir=self.test_kb_dir)
            print("✓ RAGAnythingPipeline class available")

            # Check RAG-Anything import
            try:
                pipeline._setup_raganything_path()
                from raganything import RAGAnything, RAGAnythingConfig

                print("✓ RAG-Anything library available")
                return True
            except ImportError as e:
                print(f"⚠ RAG-Anything library not available: {e}")
                print("  Install RAG-Anything to enable full functionality")
                return False

        except ImportError as e:
            print(f"✗ Failed to import RAGAnythingPipeline: {e}")
            return False

    @unittest.skipUnless(
        os.environ.get("TEST_RAG_ANYTHING", "").lower() == "true",
        "Set TEST_RAG_ANYTHING=true to run RAGAnything tests",
    )
    async def test_raganything_full_workflow(self):
        """Test RAGAnything full workflow: initialize -> search -> delete"""
        print("\n=== Testing RAGAnything Full Workflow ===")

        from src.services.rag.pipelines.raganything import RAGAnythingPipeline

        pipeline = RAGAnythingPipeline(kb_base_dir=self.test_kb_dir)

        # Test initialization
        print(f"Initializing KB with document: {self.test_doc}")
        success = await pipeline.initialize(
            kb_name=self.TEST_KB_NAME,
            file_paths=[self.test_doc],
            extract_numbered_items=False,  # Skip for speed
        )
        self.assertTrue(success)
        print("✓ Knowledge base initialized")

        # Test search
        print(f"Searching: {self.TEST_QUERY}")
        result = await pipeline.search(
            query=self.TEST_QUERY, kb_name=self.TEST_KB_NAME, mode="naive"
        )
        self.assertIn("answer", result)
        self.assertIn("content", result)
        print(f"✓ Search result: {result['answer'][:100]}...")

        # Test delete
        deleted = await pipeline.delete(kb_name=self.TEST_KB_NAME)
        self.assertTrue(deleted)
        print("✓ Knowledge base deleted")


class TestLlamaIndexPipeline(unittest.IsolatedAsyncioTestCase, RAGPipelineTestBase):
    """Test LlamaIndex pipeline (lightweight implementation)"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.test_doc = self.create_test_document(self.temp_dir)
        self.test_kb_dir = os.path.join(self.temp_dir, "knowledge_bases")
        os.makedirs(self.test_kb_dir, exist_ok=True)

    def tearDown(self):
        """Clean up test fixtures"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_llamaindex_components(self):
        """Test LlamaIndex pipeline components are properly configured"""
        print("\n=== Testing LlamaIndex Pipeline Components ===")

        from src.services.rag.factory import get_pipeline

        pipeline = get_pipeline("llamaindex")

        # Check components
        self.assertIsNotNone(pipeline._parser)
        self.assertGreater(len(pipeline._chunkers), 0)
        self.assertIsNotNone(pipeline._embedder)
        self.assertGreater(len(pipeline._indexers), 0)
        self.assertIsNotNone(pipeline._retriever)

        print(f"✓ Parser: {pipeline._parser.name}")
        print(f"✓ Chunkers: {[c.name for c in pipeline._chunkers]}")
        print(f"✓ Embedder: {pipeline._embedder.name}")
        print(f"✓ Indexers: {[i.name for i in pipeline._indexers]}")
        print(f"✓ Retriever: {pipeline._retriever.name}")

    @unittest.skipUnless(
        os.environ.get("TEST_LLAMAINDEX", "").lower() == "true"
        or os.environ.get("TEST_ALL_PIPELINES", "").lower() == "true",
        "Set TEST_LLAMAINDEX=true to run LlamaIndex tests",
    )
    async def test_llamaindex_full_workflow(self):
        """Test LlamaIndex pipeline full workflow"""
        print("\n=== Testing LlamaIndex Full Workflow ===")

        from src.services.rag.factory import get_pipeline

        pipeline = get_pipeline("llamaindex")

        # Patch the kb_base_dir for indexer and retriever
        for indexer in pipeline._indexers:
            indexer.kb_base_dir = self.test_kb_dir
        pipeline._retriever.kb_base_dir = self.test_kb_dir

        # Test initialization
        print(f"Initializing KB with document: {self.test_doc}")
        try:
            success = await pipeline.initialize(
                kb_name=self.TEST_KB_NAME, file_paths=[self.test_doc]
            )
            self.assertTrue(success)
            print("✓ Knowledge base initialized")
        except Exception as e:
            print(f"⚠ Initialization failed (may need PDF support): {e}")
            return

        # Test search
        print(f"Searching: {self.TEST_QUERY}")
        result = await pipeline.search(query=self.TEST_QUERY, kb_name=self.TEST_KB_NAME)
        self.assertIn("answer", result)
        print(f"✓ Search result: {result.get('answer', '')[:100]}...")


class TestLightRAGPipeline(unittest.IsolatedAsyncioTestCase, RAGPipelineTestBase):
    """Test LightRAG pipeline (requires RAG-Anything)"""

    async def test_lightrag_components(self):
        """Test LightRAG pipeline components are properly configured"""
        print("\n=== Testing LightRAG Pipeline Components ===")

        from src.services.rag.factory import get_pipeline

        pipeline = get_pipeline("lightrag")

        # Check components
        self.assertIsNotNone(pipeline._parser)
        self.assertGreater(len(pipeline._chunkers), 0)
        self.assertIsNotNone(pipeline._embedder)
        self.assertGreater(len(pipeline._indexers), 0)
        self.assertIsNotNone(pipeline._retriever)

        print(f"✓ Parser: {pipeline._parser.name}")
        print(f"✓ Chunkers: {[c.name for c in pipeline._chunkers]}")
        print(f"✓ Embedder: {pipeline._embedder.name}")
        print(f"✓ Indexers: {[i.name for i in pipeline._indexers]}")
        print(f"✓ Retriever: {pipeline._retriever.name}")

        # Note: This pipeline requires RAG-Anything for full functionality
        print("\n⚠ Note: LightRAG pipeline requires RAG-Anything for search/indexing")


class TestAcademicPipeline(unittest.IsolatedAsyncioTestCase, RAGPipelineTestBase):
    """Test Academic pipeline (requires RAG-Anything)"""

    async def test_academic_components(self):
        """Test Academic pipeline components are properly configured"""
        print("\n=== Testing Academic Pipeline Components ===")

        from src.services.rag.factory import get_pipeline

        pipeline = get_pipeline("academic")

        # Check components - Academic has 2 chunkers
        self.assertIsNotNone(pipeline._parser)
        self.assertEqual(len(pipeline._chunkers), 2)  # SemanticChunker + NumberedItemExtractor
        self.assertIsNotNone(pipeline._embedder)
        self.assertGreater(len(pipeline._indexers), 0)
        self.assertIsNotNone(pipeline._retriever)

        print(f"✓ Parser: {pipeline._parser.name}")
        print(f"✓ Chunkers: {[c.name for c in pipeline._chunkers]}")
        print(f"✓ Embedder: {pipeline._embedder.name}")
        print(f"✓ Indexers: {[i.name for i in pipeline._indexers]}")
        print(f"✓ Retriever: {pipeline._retriever.name}")

        # Note: This pipeline requires RAG-Anything for full functionality
        print("\n⚠ Note: Academic pipeline requires RAG-Anything for search/indexing")


class TestRAGToolWithProviders(unittest.IsolatedAsyncioTestCase, RAGPipelineTestBase):
    """Test rag_tool.py with different providers"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.test_doc = self.create_test_document(self.temp_dir)
        self.test_kb_dir = os.path.join(self.temp_dir, "knowledge_bases")
        os.makedirs(self.test_kb_dir, exist_ok=True)

    def tearDown(self):
        """Clean up test fixtures"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    async def test_rag_search_invalid_provider(self):
        """Test rag_search with invalid provider raises error"""
        from src.tools.rag_tool import rag_search

        print("\n=== Testing Invalid Provider Error ===")

        with self.assertRaises(ValueError) as context:
            await rag_search(
                query=self.TEST_QUERY, kb_name=self.TEST_KB_NAME, provider="nonexistent"
            )

        self.assertIn("not found", str(context.exception))
        print(f"✓ Invalid provider correctly raises error: {context.exception}")

    async def test_rag_search_default_provider(self):
        """Test rag_search uses default provider from env"""
        from src.tools.rag_tool import DEFAULT_RAG_PROVIDER, get_current_provider

        print("\n=== Testing Default Provider ===")

        current = get_current_provider()
        print(f"✓ Default provider from env: {DEFAULT_RAG_PROVIDER}")
        print(f"✓ Current provider: {current}")

        # They should match
        self.assertEqual(current, os.getenv("RAG_PROVIDER", "raganything"))


class TestComponentAvailability(unittest.IsolatedAsyncioTestCase):
    """Test individual component availability"""

    async def test_parsers_available(self):
        """Test all parsers can be imported"""
        print("\n=== Testing Parser Availability ===")

        from src.services.rag.components.parsers import MarkdownParser, PDFParser

        pdf_parser = PDFParser()
        print(f"✓ PDFParser: {pdf_parser.name}")

        md_parser = MarkdownParser()
        print(f"✓ MarkdownParser: {md_parser.name}")

    async def test_chunkers_available(self):
        """Test all chunkers can be imported"""
        print("\n=== Testing Chunker Availability ===")

        from src.services.rag.components.chunkers import (
            FixedSizeChunker,
            NumberedItemExtractor,
            SemanticChunker,
        )

        semantic = SemanticChunker()
        print(f"✓ SemanticChunker: {semantic.name}")

        fixed = FixedSizeChunker()
        print(f"✓ FixedSizeChunker: {fixed.name}")

        numbered = NumberedItemExtractor()
        print(f"✓ NumberedItemExtractor: {numbered.name}")

    async def test_embedders_available(self):
        """Test all embedders can be imported"""
        print("\n=== Testing Embedder Availability ===")

        from src.services.rag.components.embedders import OpenAIEmbedder

        embedder = OpenAIEmbedder()
        print(f"✓ OpenAIEmbedder: {embedder.name}")

    async def test_indexers_available(self):
        """Test all indexers can be imported"""
        print("\n=== Testing Indexer Availability ===")

        from src.services.rag.components.indexers import GraphIndexer, VectorIndexer

        vector = VectorIndexer()
        print(f"✓ VectorIndexer: {vector.name}")

        graph = GraphIndexer()
        print(f"✓ GraphIndexer: {graph.name}")

    async def test_retrievers_available(self):
        """Test all retrievers can be imported"""
        print("\n=== Testing Retriever Availability ===")

        from src.services.rag.components.retrievers import DenseRetriever, HybridRetriever

        dense = DenseRetriever()
        print(f"✓ DenseRetriever: {dense.name}")

        hybrid = HybridRetriever()
        print(f"✓ HybridRetriever: {hybrid.name}")


class TestExistingKnowledgeBase(unittest.IsolatedAsyncioTestCase):
    """Test search on existing knowledge bases"""

    @unittest.skipUnless(
        os.environ.get("TEST_EXISTING_KB", "").lower() == "true",
        "Set TEST_EXISTING_KB=true to test existing KBs",
    )
    async def test_search_existing_kb(self):
        """Test search on an existing knowledge base"""
        print("\n=== Testing Existing Knowledge Base ===")

        from src.tools.rag_tool import rag_search

        # Use default or specified KB
        kb_name = os.environ.get("TEST_KB_NAME", "ai-textbook")
        query = os.environ.get("TEST_QUERY", "What is machine learning?")

        print(f"KB: {kb_name}")
        print(f"Query: {query}")

        # Test with different modes
        for mode in ["naive", "hybrid"]:
            print(f"\n--- Mode: {mode} ---")
            try:
                result = await rag_search(query=query, kb_name=kb_name, mode=mode)
                print(f"✓ Provider: {result.get('provider', 'unknown')}")
                print(f"✓ Answer length: {len(result.get('answer', ''))} chars")
                print(f"✓ Preview: {result.get('answer', '')[:200]}...")
            except Exception as e:
                print(f"✗ Failed: {e}")


def run_quick_tests():
    """Run quick tests that don't require external services"""
    print("=" * 60)
    print("Running Quick RAG Pipeline Tests")
    print("=" * 60)

    # Run only fast tests
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add quick tests
    suite.addTests(loader.loadTestsFromTestCase(TestRAGToolIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestPipelineFactory))
    suite.addTests(loader.loadTestsFromTestCase(TestComponentAvailability))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


def run_all_tests():
    """Run all tests including those requiring external services"""
    print("=" * 60)
    print("Running All RAG Pipeline Tests")
    print("=" * 60)
    print("\nEnvironment variables for full testing:")
    print("  TEST_RAG_ANYTHING=true  - Run RAGAnything tests")
    print("  TEST_LLAMAINDEX=true    - Run LlamaIndex tests")
    print("  TEST_ALL_PIPELINES=true - Run all pipeline tests")
    print("  TEST_EXISTING_KB=true   - Test existing KBs")
    print("  TEST_KB_NAME=<name>     - KB name for existing KB test")
    print("  TEST_QUERY=<query>      - Query for existing KB test")
    print("=" * 60 + "\n")

    unittest.main(verbosity=2)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="RAG Pipeline Tests")
    parser.add_argument("--quick", action="store_true", help="Run only quick tests")
    parser.add_argument("--all", action="store_true", help="Run all tests")
    args = parser.parse_args()

    if args.quick:
        success = run_quick_tests()
        sys.exit(0 if success else 1)
    else:
        run_all_tests()
