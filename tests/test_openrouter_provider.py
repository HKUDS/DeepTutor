import unittest
from unittest.mock import MagicMock, patch

from deeptutor.services.search.providers.openrouter import OpenRouterProvider
from deeptutor.services.search.types import WebSearchResponse


class TestOpenRouterProvider(unittest.TestCase):
    def setUp(self):
        self.api_key = "test-key"
        # Mock openai module
        self.mock_openai = MagicMock()
        self.mock_client = MagicMock()
        self.mock_openai.OpenAI.return_value = self.mock_client

        # Patch import
        self.patcher = patch.dict("sys.modules", {"openai": self.mock_openai})
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_search_success_root_citations(self):
        """Test search with citations in root response (standard OpenRouter Perplexity)"""
        provider = OpenRouterProvider(api_key=self.api_key)
        # Mock response
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = "Test answer"
        mock_completion.choices[0].finish_reason = "stop"
        mock_completion.model = "perplexity/sonar"
        mock_completion.usage.prompt_tokens = 10
        mock_completion.usage.completion_tokens = 20
        mock_completion.usage.total_tokens = 30

        # model_dump return value
        mock_completion.model_dump.return_value = {
            "citations": ["https://example.com/1", {"url": "https://example.com/2"}]
        }

        self.mock_client.chat.completions.create.return_value = mock_completion

        result = provider.search("test query")

        self.assertIsInstance(result, WebSearchResponse)
        self.assertEqual(result.answer, "Test answer")
        self.assertEqual(len(result.citations), 2)
        self.assertEqual(result.citations[0].url, "https://example.com/1")
        self.assertEqual(result.citations[1].url, "https://example.com/2")
        self.assertEqual(result.provider, "openrouter")

    def test_search_success_choice_citations(self):
        """Test search with citations in choice (alternative format)"""
        provider = OpenRouterProvider(api_key=self.api_key)

        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = "Test answer"

        mock_completion.model_dump.return_value = {
            "choices": [{"citations": ["https://example.com/choice"]}]
        }

        self.mock_client.chat.completions.create.return_value = mock_completion

        result = provider.search("test query")

        self.assertEqual(len(result.citations), 1)
        self.assertEqual(result.citations[0].url, "https://example.com/choice")


if __name__ == "__main__":
    unitest.main()
