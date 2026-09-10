"""Tests for GraphRAG pandas compatibility guard."""

import os
import sys
import threading
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
class TestPandasCompatGuard:
    """Test suite for pandas extension type conflict prevention."""

    def test_suppress_pandas_extension_warnings(self):
        """Test that pandas extension warnings are properly suppressed."""
        from deeptutor.services.rag.pipelines.graphrag.pandas_compat import (
            suppress_pandas_extension_warnings,
        )

        suppress_pandas_extension_warnings()
        # No assertion - just ensure it runs without error

    def test_configure_pandas_for_graphrag_sets_env_vars(self):
        """Test that environment variables are set to limit parallelism."""
        from deeptutor.services.rag.pipelines.graphrag.pandas_compat import (
            configure_pandas_for_graphrag,
        )

        # Clear any existing env vars
        for key in [
            "NUMEXPR_MAX_THREADS",
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "MKL_NUM_THREADS",
        ]:
            os.environ.pop(key, None)

        configure_pandas_for_graphrag()

        assert os.environ.get("NUMEXPR_MAX_THREADS") == "1"
        assert os.environ.get("OMP_NUM_THREADS") == "1"
        assert os.environ.get("OPENBLAS_NUM_THREADS") == "1"
        assert os.environ.get("MKL_NUM_THREADS") == "1"

    def test_configure_pandas_is_thread_safe(self):
        """Test that concurrent configuration calls don't cause issues."""
        from deeptutor.services.rag.pipelines.graphrag.pandas_compat import (
            configure_pandas_for_graphrag,
        )

        results = []

        def configure_in_thread():
            try:
                configure_pandas_for_graphrag()
                results.append("success")
            except Exception as e:
                results.append(f"error: {e}")

        threads = [threading.Thread(target=configure_in_thread) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(r == "success" for r in results)
        assert len(results) == 10

    def test_configure_pandas_is_idempotent(self):
        """Test that multiple calls to configure_pandas_for_graphrag are safe."""
        from deeptutor.services.rag.pipelines.graphrag.pandas_compat import (
            configure_pandas_for_graphrag,
        )

        # Should not raise even if called multiple times
        configure_pandas_for_graphrag()
        configure_pandas_for_graphrag()
        configure_pandas_for_graphrag()

    @pytest.mark.asyncio
    async def test_wrap_graphrag_operation_decorator(self):
        """Test that the decorator properly wraps async functions."""
        from deeptutor.services.rag.pipelines.graphrag.pandas_compat import (
            wrap_graphrag_operation,
        )

        called = []

        @wrap_graphrag_operation
        async def test_func(x):
            called.append(x)
            return x * 2

        result = await test_func(5)
        assert result == 10
        assert called == [5]

    def test_configure_handles_pandas_import_error(self):
        """Test graceful handling when pandas is not installed."""
        from deeptutor.services.rag.pipelines.graphrag.pandas_compat import (
            configure_pandas_for_graphrag,
        )

        # Mock pandas import to fail
        with patch.dict(sys.modules, {"pandas": None}):
            # Should not raise even if pandas import fails
            configure_pandas_for_graphrag()

    def test_configure_handles_pandas_extension_error(self):
        """Test graceful handling of pandas extension registration errors."""
        from deeptutor.services.rag.pipelines.graphrag.pandas_compat import (
            configure_pandas_for_graphrag,
        )

        # Create a mock pandas that raises on extension access
        mock_pd = MagicMock()
        mock_pd.DataFrame.side_effect = RuntimeError("Extension already defined")

        with patch.dict(sys.modules, {"pandas": mock_pd}):
            # Should not raise even if extension registration fails
            configure_pandas_for_graphrag()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not pytest.importorskip("graphrag", reason="graphrag not installed"),
    reason="Requires graphrag optional dependency",
)
class TestGraphRAGEngineWithPandasCompat:
    """Integration tests for GraphRAG engine with pandas compatibility."""

    async def test_build_impl_calls_configure_pandas(self):
        """Test that _build_impl calls configure_pandas_for_graphrag before indexing."""
        from deeptutor.services.rag.pipelines.graphrag import engine

        # Mock the configure function and build_index to avoid actual operations
        with (
            patch(
                "deeptutor.services.rag.pipelines.graphrag.pandas_compat.configure_pandas_for_graphrag"
            ) as mock_configure,
            patch("deeptutor.services.rag.pipelines.graphrag.engine._load_config"),
            patch("deeptutor.services.rag.pipelines.graphrag.engine._probe_embedding_model_impl"),
            patch("graphrag.api.build_index") as mock_build_index,
        ):
            mock_build_index.return_value = []

            try:
                from pathlib import Path
                import tempfile

                with tempfile.TemporaryDirectory() as temp_dir:
                    await engine._build_impl(
                        Path(temp_dir), is_update=False, preflight_embedding_model=False
                    )
            except Exception:
                # Expected to fail without proper setup, but configure should have been called
                pass

            # Verify pandas configuration was called
            mock_configure.assert_called_once()

    async def test_resolve_outputs_calls_configure_pandas(self):
        """Test that _resolve_outputs calls configure_pandas_for_graphrag before loading parquet."""
        from deeptutor.services.rag.pipelines.graphrag import engine

        # Mock the configure function and the entire storage chain to avoid actual file operations
        with (
            patch(
                "deeptutor.services.rag.pipelines.graphrag.pandas_compat.configure_pandas_for_graphrag"
            ) as mock_configure,
            patch("graphrag_storage.create_storage") as mock_storage,
            patch(
                "graphrag_storage.tables.table_provider_factory.create_table_provider"
            ) as mock_table_provider,
            patch("graphrag.data_model.data_reader.DataReader") as mock_reader,
        ):
            mock_config = MagicMock()
            mock_config.output_storage = MagicMock()
            mock_config.table_provider = MagicMock()

            mock_reader_instance = MagicMock()
            mock_reader.return_value = mock_reader_instance

            try:
                await engine._resolve_outputs(mock_config, [], [])
            except Exception:
                # Expected to fail without proper setup, but configure should have been called
                pass

            # Verify pandas configuration was called
            mock_configure.assert_called_once()
