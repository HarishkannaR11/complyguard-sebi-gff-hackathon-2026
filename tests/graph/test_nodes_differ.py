from unittest.mock import MagicMock, patch
import json

from app.graph.nodes import differ_node


def mock_groq_response(status, confidence=0.9, changes=None, reason="Explanation", matched_id=None):
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps({
        "status": status,
        "confidence": confidence,
        "matched_obligation_id": matched_id,
        "changes": changes or [],
        "reason": reason
    })
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


def test_differ_node_returns_new_when_no_match():
    with (
        patch("app.graph.nodes.get_client", return_value="fake-client"),
        patch("app.graph.nodes.ensure_collection") as mock_ensure,
        patch("app.graph.nodes.search", return_value=[]) as mock_search,
    ):
        result = differ_node({
            "circular_id": "test_circular",
            "clause_id": "c1",
            "raw_clause": "1. Do X.",
            "embedding": [0.1] * 768
        })

    assert result == {
        "diff_status": "new",
        "similarity_match": None,
        "diff_changes": [],
        "diff_reason": "No similar historical clauses found in vector database.",
        "diff_confidence": 1.0
    }
    mock_ensure.assert_called_once_with("fake-client", vector_size=768)
    mock_search.assert_called_once()


def test_differ_node_returns_unchanged_when_match_is_identical_text():
    hit = {"text": "1. Do X.", "score": 0.99, "payload": {"obligation_id": "obl-1"}}
    mock_resp = mock_groq_response("UNCHANGED", confidence=0.99, matched_id="obl-1", reason="Identical requirement")
    
    with (
        patch("app.graph.nodes.get_client", return_value="fake-client"),
        patch("app.graph.nodes.ensure_collection"),
        patch("app.graph.nodes.search", return_value=[hit]),
        patch("app.llm.groq_client.Groq") as mock_groq,
        patch("app.graph.nodes._write_audit_entry") as mock_audit,
    ):
        mock_client = MagicMock()
        mock_groq.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_resp
        
        result = differ_node({
            "circular_id": "test_circular",
            "clause_id": "c1",
            "raw_clause": "1.  Do X.  ",
            "embedding": [0.1] * 768
        })

    assert result == {
        "diff_status": "unchanged",
        "similarity_match": hit,
        "diff_changes": [],
        "diff_reason": "Identical requirement",
        "diff_confidence": 0.99
    }
    mock_audit.assert_called_once()


def test_differ_node_returns_amended_when_match_has_different_text():
    hit = {"text": "1. Do X annually.", "score": 0.9, "payload": {"obligation_id": "obl-1"}}
    mock_resp = mock_groq_response("AMENDED", confidence=0.9, matched_id="obl-1", changes=["frequency"], reason="Frequency updated")
    
    with (
        patch("app.graph.nodes.get_client", return_value="fake-client"),
        patch("app.graph.nodes.ensure_collection"),
        patch("app.graph.nodes.search", return_value=[hit]),
        patch("app.llm.groq_client.Groq") as mock_groq,
        patch("app.graph.nodes._write_audit_entry") as mock_audit,
    ):
        mock_client = MagicMock()
        mock_groq.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_resp
        
        result = differ_node({
            "circular_id": "test_circular",
            "clause_id": "c1",
            "raw_clause": "1. Do X quarterly.",
            "embedding": [0.1] * 768
        })

    assert result == {
        "diff_status": "amended",
        "similarity_match": hit,
        "diff_changes": ["frequency"],
        "diff_reason": "Frequency updated",
        "diff_confidence": 0.9
    }
    mock_audit.assert_called_once()


def test_differ_node_returns_new_when_score_below_threshold():
    hit = {"text": "unrelated clause", "score": 0.5, "payload": {"obligation_id": "obl-old"}}
    mock_resp = mock_groq_response("NEW", confidence=0.95, matched_id=None, reason="Completely new instruction")
    
    with (
        patch("app.graph.nodes.get_client", return_value="fake-client"),
        patch("app.graph.nodes.ensure_collection"),
        patch("app.graph.nodes.search", return_value=[hit]),
        patch("app.llm.groq_client.Groq") as mock_groq,
        patch("app.graph.nodes._write_audit_entry") as mock_audit,
    ):
        mock_client = MagicMock()
        mock_groq.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_resp
        
        result = differ_node({
            "circular_id": "test_circular",
            "clause_id": "c1",
            "raw_clause": "1. Do X.",
            "embedding": [0.1] * 768
        })

    assert result == {
        "diff_status": "new",
        "similarity_match": None,
        "diff_changes": [],
        "diff_reason": "Completely new instruction",
        "diff_confidence": 0.95
    }
    mock_audit.assert_called_once()
