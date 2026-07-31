import pytest
from app.graph.nodes import validation_node
from app.graph.build_graph import route_after_validation, route_after_diff

def test_validation_node_passed_high_confidence():
    state = {
        "extracted_obligation": {
            "requirement": "Review compliance annually.",
            "frequency": "annual",
            "evidence_type": "Audit report",
            "deadline_rule": "annual",
            "deadline_confidence": 0.98,
            "entity_confidence": 0.97,
            "evidence_confidence": 0.96,
            "overall_confidence": 0.97
        },
        "extraction_retries": 0
    }
    result = validation_node(state)
    assert result["validation_status"] == "passed"
    assert len(result["validation_errors"]) == 0
    assert len(result["validation_warnings"]) == 0
    assert result["overall_confidence"] == 0.97
    assert result["extraction_retries"] == 0


def test_validation_node_passed_warning_confidence():
    state = {
        "extracted_obligation": {
            "requirement": "Review compliance monthly.",
            "frequency": "monthly",
            "evidence_type": "Log file",
            "deadline_rule": "monthly",
            "deadline_confidence": 0.88,
            "entity_confidence": 0.85,
            "evidence_confidence": 0.90,
            "overall_confidence": 0.88
        },
        "extraction_retries": 0
    }
    result = validation_node(state)
    assert result["validation_status"] == "passed"
    assert len(result["validation_errors"]) == 0
    assert len(result["validation_warnings"]) == 1
    assert "between 80% and 95%" in result["validation_warnings"][0]
    assert result["overall_confidence"] == 0.88
    assert result["extraction_retries"] == 0


def test_validation_node_failed_low_confidence():
    state = {
        "extracted_obligation": {
            "requirement": "Review compliance monthly.",
            "frequency": "monthly",
            "evidence_type": "Log file",
            "deadline_rule": "monthly",
            "deadline_confidence": 0.70,
            "entity_confidence": 0.65,
            "evidence_confidence": 0.75,
            "overall_confidence": 0.70
        },
        "extraction_retries": 0
    }
    result = validation_node(state)
    assert result["validation_status"] == "failed"
    assert len(result["validation_errors"]) == 1
    assert "below 80% threshold" in result["validation_errors"][0]
    assert result["overall_confidence"] == 0.70
    assert result["extraction_retries"] == 1


def test_validation_node_failed_pydantic_errors():
    # 1. Missing requirement field
    state_missing = {
        "extracted_obligation": {
            "requirement": "",
            "frequency": "monthly",
            "evidence_type": "Log file",
            "deadline_rule": "monthly",
            "deadline_confidence": 0.95,
            "entity_confidence": 0.95,
            "evidence_confidence": 0.95,
            "overall_confidence": 0.95
        },
        "extraction_retries": 1
    }
    result_missing = validation_node(state_missing)
    assert result_missing["validation_status"] == "failed"
    assert any("requirement" in err for err in result_missing["validation_errors"])
    assert result_missing["extraction_retries"] == 2

    # 2. Invalid frequency value
    state_freq = {
        "extracted_obligation": {
            "requirement": "Must do X",
            "frequency": "bi-weekly",
            "evidence_type": "Log file",
            "deadline_rule": "monthly",
            "deadline_confidence": 0.95,
            "entity_confidence": 0.95,
            "evidence_confidence": 0.95,
            "overall_confidence": 0.95
        },
        "extraction_retries": 0
    }
    result_freq = validation_node(state_freq)
    assert result_freq["validation_status"] == "failed"
    assert any("frequency" in err for err in result_freq["validation_errors"])

    # 3. Invalid deadline rule (not ISO format or frequency keyword)
    state_date = {
        "extracted_obligation": {
            "requirement": "Must do X",
            "frequency": "monthly",
            "evidence_type": "Log file",
            "deadline_rule": "invalid-deadline-string",
            "deadline_confidence": 0.95,
            "entity_confidence": 0.95,
            "evidence_confidence": 0.95,
            "overall_confidence": 0.95
        },
        "extraction_retries": 0
    }
    result_date = validation_node(state_date)
    assert result_date["validation_status"] == "failed"
    assert any("deadline_rule" in err for err in result_date["validation_errors"])


def test_route_after_validation_retry_decisions():
    # First retry decision: failed and retries <= 1 -> routes to extractor
    state_retry_1 = {
        "validation_status": "failed",
        "extraction_retries": 1
    }
    assert route_after_validation(state_retry_1) == "extractor"

    # Second retry decision: failed and retries > 1 -> routes to differ
    state_retry_2 = {
        "validation_status": "failed",
        "extraction_retries": 2
    }
    assert route_after_validation(state_retry_2) == "differ"

    # Passed validation -> routes to differ
    state_passed = {
        "validation_status": "passed",
        "extraction_retries": 1
    }
    assert route_after_validation(state_passed) == "differ"


def test_route_after_diff_with_validation_failures():
    # Failed validation forces human_review
    state_failed_val = {
        "validation_status": "failed",
        "overall_confidence": 0.95,
        "diff_status": "new",
        "confidence": 0.9
    }
    assert route_after_diff(state_failed_val) == "human_review"

    # Low overall confidence (<80%) forces human_review
    state_low_conf = {
        "validation_status": "passed",
        "overall_confidence": 0.75,
        "diff_status": "new",
        "confidence": 0.9
    }
    assert route_after_diff(state_low_conf) == "human_review"

    # Valid run passes normally to mapper
    state_ok = {
        "validation_status": "passed",
        "overall_confidence": 0.96,
        "diff_status": "new",
        "confidence": 0.9
    }
    assert route_after_diff(state_ok) == "mapper"
