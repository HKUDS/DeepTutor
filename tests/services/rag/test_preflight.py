from deeptutor.services.rag.preflight import engine_preflight


def test_ima_preflight_explains_per_kb_credentials_without_network() -> None:
    report = engine_preflight("ima")

    assert report["ok"] is True
    assert report["checks"] == [
        {
            "key": "per_kb_credentials",
            "label": "Credentials supplied when connecting a knowledge base",
            "ok": True,
            "detail": "Enter the IMA Client ID and API key in the link-existing flow.",
            "optional": False,
        }
    ]
