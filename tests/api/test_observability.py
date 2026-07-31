"""Unit tests for health check and metrics endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app.api.main import app
from app.db.database import get_db
from app.services.metrics import metrics_collector

client = TestClient(app)


def test_health_check_endpoint_success():
    # Mock DB execution and Qdrant collections call to succeed
    mock_db = MagicMock()
    mock_db.execute.return_value = None
    
    mock_qdrant = MagicMock()
    mock_qdrant.get_collections.return_value = MagicMock()
    
    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        with patch("app.api.main.get_client", return_value=mock_qdrant):
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["database"] == "reachable"
            assert data["qdrant"] == "reachable"
    finally:
        app.dependency_overrides.clear()


def test_health_check_endpoint_unhealthy_database():
    mock_db = MagicMock()
    mock_db.execute.side_effect = Exception("DB Connection Lost")
    
    mock_qdrant = MagicMock()
    mock_qdrant.get_collections.return_value = MagicMock()
    
    app.dependency_overrides[get_db] = lambda: mock_db
    try:
        with patch("app.api.main.get_client", return_value=mock_qdrant):
            response = client.get("/health")
            assert response.status_code == 503
            data = response.json()["detail"]
            assert data["status"] == "unhealthy"
            assert "error" in data["database"]
            assert data["qdrant"] == "reachable"
    finally:
        app.dependency_overrides.clear()


def test_metrics_endpoint_prometheus():
    # Record some mock metrics
    metrics_collector.record_processing_time(1.23)
    metrics_collector.record_llm_latency(0.45)
    metrics_collector.record_embedding_latency(0.12)
    metrics_collector.record_vector_search_latency(0.08)
    metrics_collector.increment_validation_failures()
    metrics_collector.increment_retry_count()
    metrics_collector.record_confidence(0.96)
    metrics_collector.record_confidence(0.85)
    metrics_collector.record_confidence(0.70)
    
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    
    assert "regops_clauses_processed_total" in body
    assert "regops_validation_failures_total" in body
    assert "regops_retry_count_total" in body
    assert "regops_avg_processing_time_seconds" in body
    assert "regops_avg_llm_latency_seconds" in body
    assert "regops_avg_embedding_latency_seconds" in body
    assert "regops_avg_vector_search_latency_seconds" in body
    assert 'regops_confidence_distribution_total{bucket="high_95"}' in body


def test_metrics_endpoint_json():
    response = client.get("/metrics?format=json")
    assert response.status_code == 200
    data = response.json()
    
    assert "summary" in data
    assert "latencies_seconds" in data
    assert "confidence_distribution" in data
    assert data["summary"]["validation_failures_total"] > 0
    assert data["confidence_distribution"]["high (>=0.95)"] > 0
