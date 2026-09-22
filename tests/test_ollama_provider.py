"""Tests for selecting and calling the local Ollama provider."""

import os
import unittest
from unittest.mock import patch

from simulation.llm_providers import ollama_provider
from simulation.run_llm_comparison import selected_provider_config


class OllamaProviderTest(unittest.TestCase):
    def test_ollama_config_does_not_require_api_key(self):
        environment = {
            "LLM_PROVIDER": "ollama",
            "OLLAMA_MODEL": "gemma3:1b",
        }
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(selected_provider_config(), ("ollama", "gemma3:1b"))

    def test_openai_config_still_requires_api_key(self):
        environment = {
            "LLM_PROVIDER": "openai",
            "OPENAI_MODEL": "gpt-4.1-mini",
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
                selected_provider_config()

    def test_provider_sends_graph_and_json_schema_to_ollama(self):
        graph = {"type": "FeatureCollection", "features": []}
        response = {
            "message": {
                "content": '{"path": [1, 2], "reported_total_distance": 1.0}'
            }
        }
        with patch.object(ollama_provider.ollama, "Client") as client_class:
            client_class.return_value.chat.return_value = response
            provider = ollama_provider.OllamaPathProvider(
                model="gemma3:1b", host="http://localhost:11434"
            )
            result = provider.compute_shortest_path(graph, 1, 2)

        client_class.assert_called_once_with(host="http://localhost:11434")
        call = client_class.return_value.chat.call_args
        self.assertEqual(call.kwargs["model"], "gemma3:1b")
        self.assertEqual(call.kwargs["format"], provider.OUTPUT_SCHEMA)
        self.assertIn('"start_node": 1', call.kwargs["messages"][1]["content"])
        self.assertEqual(result["path"], [1, 2])

    def test_empty_ollama_response_is_rejected(self):
        with patch.object(ollama_provider.ollama, "Client") as client_class:
            client_class.return_value.chat.return_value = {
                "message": {"content": ""}
            }
            provider = ollama_provider.OllamaPathProvider(model="gemma3:1b")
            with self.assertRaisesRegex(RuntimeError, "응답이 비어"):
                provider.compute_shortest_path({}, 1, 2)


if __name__ == "__main__":
    unittest.main()
