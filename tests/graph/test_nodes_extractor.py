from unittest.mock import MagicMock, patch

import pytest

from app.graph.nodes import extractor_node


def _make_fake_groq_response(content: str):
    message = MagicMock(content=content)
    choice = MagicMock(message=message)
    return MagicMock(choices=[choice])


def test_extractor_node_parses_json_response(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    fake_response = _make_fake_groq_response(
        '{"requirement": "Appoint a compliance officer", "frequency": "one-time", '
        '"evidence_type": "board resolution", "deadline_rule": "2026-06-30"}'
    )
    with patch("app.llm.groq_client.Groq") as mock_groq_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = fake_response
        mock_groq_cls.return_value = mock_client

        result = extractor_node({"raw_clause": "1. Appoint a compliance officer by 2026-06-30."})

    assert result == {
        "extracted_obligation": {
            "requirement": "Appoint a compliance officer",
            "frequency": "one-time",
            "evidence_type": "board resolution",
            "deadline_rule": "2026-06-30",
        }
    }


def test_extractor_node_strips_markdown_code_fences(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    fake_response = _make_fake_groq_response(
        '```json\n{"requirement": "Do X", "frequency": "annual", '
        '"evidence_type": "policy doc", "deadline_rule": "annual"}\n```'
    )
    with patch("app.llm.groq_client.Groq") as mock_groq_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = fake_response
        mock_groq_cls.return_value = mock_client

        result = extractor_node({"raw_clause": "2. Do X annually."})

    assert result["extracted_obligation"]["requirement"] == "Do X"


def test_extractor_node_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        extractor_node({"raw_clause": "1. Do X."})
