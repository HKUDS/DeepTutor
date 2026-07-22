import json
from pathlib import Path

from deeptutor.services.config.model_catalog import ModelCatalogService


def test_load_creates_empty_catalog_without_dotenv_hydration(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "LLM_MODEL=legacy-model\nLLM_API_KEY=legacy-key\nEMBEDDING_MODEL=legacy-embedding\n",
        encoding="utf-8",
    )
    catalog_path = tmp_path / "model_catalog.json"

    catalog = ModelCatalogService(path=catalog_path).load()

    assert catalog["services"]["llm"]["profiles"] == []
    assert catalog["services"]["embedding"]["profiles"] == []
    assert catalog["services"]["search"]["profiles"] == []


def test_load_does_not_sync_existing_active_profiles_from_dotenv(tmp_path: Path):
    (tmp_path / ".env").write_text(
        "LLM_MODEL=qwen3.5-plus\nEMBEDDING_MODEL=text-embedding-v4\n",
        encoding="utf-8",
    )
    catalog_path = tmp_path / "model_catalog.json"
    catalog_path.write_text(
        """{
  "version": 1,
  "services": {
    "llm": {
      "active_profile_id": "llm-profile-default",
      "active_model_id": "llm-model-default",
      "profiles": [
        {
          "id": "llm-profile-default",
          "name": "Default LLM Endpoint",
          "binding": "openai",
          "base_url": "https://old-llm.example/v1",
          "api_key": "old-llm-key",
          "api_version": "",
          "extra_headers": {},
          "models": [
            {"id": "llm-model-default", "name": "old-model", "model": "old-model"}
          ]
        }
      ]
    },
    "embedding": {
      "active_profile_id": "embedding-profile-default",
      "active_model_id": "embedding-model-default",
      "profiles": [
        {
          "id": "embedding-profile-default",
          "name": "Default Embedding Endpoint",
          "binding": "openai",
          "base_url": "https://old-emb.example/v1",
          "api_key": "old-emb-key",
          "api_version": "",
          "extra_headers": {},
          "models": [
            {
              "id": "embedding-model-default",
              "name": "old-embedding",
              "model": "old-embedding",
              "dimension": "3072"
            }
          ]
        }
      ]
    },
    "search": {"active_profile_id": null, "profiles": []}
  }
}
""",
        encoding="utf-8",
    )

    service = ModelCatalogService(path=catalog_path)
    catalog = service.load()

    llm_profile = catalog["services"]["llm"]["profiles"][0]
    llm_model = llm_profile["models"][0]
    emb_profile = catalog["services"]["embedding"]["profiles"][0]
    emb_model = emb_profile["models"][0]

    assert llm_profile["binding"] == "openai"
    assert llm_profile["base_url"] == "https://old-llm.example/v1"
    assert llm_profile["api_key"] == "old-llm-key"
    assert llm_model["model"] == "old-model"
    assert llm_model["name"] == "old-model"
    assert emb_profile["binding"] == "openai"
    assert emb_profile["base_url"] == "https://old-emb.example/v1/embeddings"
    assert emb_profile["api_key"] == "old-emb-key"
    assert emb_model["model"] == "old-embedding"
    assert emb_model["name"] == "old-embedding"
    assert emb_model["dimension"] == "3072"


def test_load_recovers_invalid_catalog_with_defaults(tmp_path: Path):
    catalog_path = tmp_path / "model_catalog.json"
    catalog_path.write_text("{not-json", encoding="utf-8")

    catalog = ModelCatalogService(path=catalog_path).load()

    expected_services = {
        "llm",
        "embedding",
        "search",
        "tts",
        "stt",
        "imagegen",
        "videogen",
    }
    assert set(catalog["services"]) == expected_services
    saved = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert set(saved["services"]) == expected_services


def test_load_persists_normalized_active_ids(tmp_path: Path):
    catalog_path = tmp_path / "model_catalog.json"
    catalog_path.write_text(
        json.dumps(
            {
                "services": {
                    "llm": {
                        "active_profile_id": "missing-profile",
                        "active_model_id": "missing-model",
                        "profiles": [
                            {
                                "id": "llm-profile-a",
                                "name": "A",
                                "binding": "openai",
                                "base_url": "https://example.test/v1",
                                "api_key": "sk",
                                "models": [
                                    {
                                        "id": "llm-model-a",
                                        "name": "gpt",
                                        "model": "gpt-test",
                                    }
                                ],
                            }
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    ModelCatalogService(path=catalog_path).load()

    saved = json.loads(catalog_path.read_text(encoding="utf-8"))
    llm = saved["services"]["llm"]
    assert llm["active_profile_id"] == "llm-profile-a"
    assert llm["active_model_id"] == "llm-model-a"
    assert saved["services"]["embedding"]["profiles"] == []
    assert saved["services"]["search"]["profiles"] == []
