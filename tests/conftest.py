import pytest


@pytest.fixture(autouse=True)
def _no_ollama(monkeypatch):
    """Tests must never reach a real Ollama server; use FakeEmbedder instead."""

    class _Forbidden:
        def __init__(self, *args, **kwargs):
            raise AssertionError("tests must not contact Ollama; use rag.embed.FakeEmbedder")

    import ollama

    monkeypatch.setattr(ollama, "Client", _Forbidden)
