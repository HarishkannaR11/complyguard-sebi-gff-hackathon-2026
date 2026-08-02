import pytest
from unittest.mock import MagicMock, patch

from app.ingestion.hybrid_parser import (
    is_inside_table,
    table_to_markdown,
    parse_pdf_structured,
    run_legacy_fallback,
)
from app.graph.build_graph import route_after_diff


def test_is_inside_table():
    table_rects = [(10, 10, 100, 100)]
    # Center of this block is at (15, 15) which is inside (10, 10, 100, 100)
    assert is_inside_table((10, 10, 20, 20), table_rects) is True
    # Center is at (150, 150) which is outside
    assert is_inside_table((140, 140, 160, 160), table_rects) is False


def test_table_to_markdown():
    rows = [
        ["Header A", "Header B"],
        ["Val 1", "Val 2"],
        ["Val 3", None]
    ]
    expected = (
        "| Header A | Header B |\n"
        "| --- | --- |\n"
        "| Val 1 | Val 2 |\n"
        "| Val 3 |  |"
    )
    assert table_to_markdown(rows) == expected


@patch("fitz.open")
def test_parse_pdf_structured_hierarchical_extraction(mock_open):
    # Mock document structure
    mock_doc = MagicMock()
    mock_open.return_value = mock_doc
    mock_doc.__len__.return_value = 1
    
    mock_page = MagicMock()
    mock_doc.__iter__.return_value = [mock_page]
    
    # Mock tables
    mock_table = MagicMock()
    mock_table.bbox = (10, 500, 200, 600)
    mock_table.extract.return_value = [["Col 1", "Col 2"], ["Row 1 Val 1", "Row 1 Val 2"]]
    mock_page.find_tables.return_value = [mock_table]
    
    # Mock blocks (x0, y0, x1, y1, text, block_no, block_type)
    mock_page.get_text.return_value = [
        (10, 10, 300, 30, "I. Introduction\n", 0, 0),
        (10, 50, 300, 70, "A. Overview\n", 1, 0),
        (10, 90, 300, 120, "2.3 Specific Obligations\n2.3.1 The intermediary shall appoint a compliance officer.", 2, 0),
        (10, 130, 300, 150, "Continuation text under the clause.", 3, 0),
        # This text block matches the table's bounding box and should be skipped in normal text parsing
        (15, 505, 195, 595, "Col 1\nCol 2\nRow 1 Val 1\nRow 1 Val 2", 4, 0)
    ]
    
    chunks = parse_pdf_structured("dummy_path.pdf")
    
    assert len(chunks) > 0
    
    # Verify section mapping
    sections = [c["section"] for c in chunks if c["type"] == "section"]
    assert "Introduction" in sections or "Overview" in sections
    
    # Verify clause extraction
    clauses = [c for c in chunks if c["clause"] == "2.3.1"]
    assert len(clauses) > 0
    assert clauses[0]["parent"] == "2.3"
    assert clauses[0]["confidence"] == 0.95
    
    # Verify continuation paragraph has correct clause & parent context
    continuations = [c for c in chunks if c["text"].startswith("Continuation")]
    assert len(continuations) == 1
    assert continuations[0]["clause"] == "2.3.1"
    assert continuations[0]["parent"] == "2.3"
    assert continuations[0]["confidence"] == 0.85
    
    # Verify table parsed as md
    tables = [c for c in chunks if c["type"] == "table"]
    assert len(tables) == 1
    assert "| Col 1 | Col 2 |" in tables[0]["text"]
    assert tables[0]["confidence"] == 0.90


@patch("fitz.open", side_effect=Exception("Unreadable PDF format"))
@patch("app.ingestion.hybrid_parser.extract_and_clean", return_value="1. Fallback obligation.")
@patch("app.ingestion.hybrid_parser.split_into_clauses", return_value=["1. Fallback obligation."])
def test_parse_pdf_structured_graceful_fallback(mock_split, mock_clean, mock_open):
    chunks = parse_pdf_structured("invalid.pdf")
    assert len(chunks) == 1
    assert chunks[0]["text"] == "1. Fallback obligation."
    assert chunks[0]["clause"] == "1"
    assert chunks[0]["confidence"] == 0.50


def test_route_after_diff_low_confidence():
    # Low confidence routes directly to human_review
    state_low = {
        "confidence": 0.60,
        "diff_status": "new"
    }
    assert route_after_diff(state_low) == "human_review"

    state_low_unchanged = {
        "confidence": 0.50,
        "diff_status": "unchanged"
    }
    assert route_after_diff(state_low_unchanged) == "human_review"

    # High confidence behaves according to diff_status
    state_high_new = {
        "confidence": 0.85,
        "diff_status": "new"
    }
    assert route_after_diff(state_high_new) == "mapper"

    state_high_unchanged = {
        "confidence": 0.95,
        "diff_status": "unchanged"
    }
    assert route_after_diff(state_high_unchanged) == "finalize"
