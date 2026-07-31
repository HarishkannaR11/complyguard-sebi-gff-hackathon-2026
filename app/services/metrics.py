"""
metrics.py

Central pipeline metrics collector for RegOps AI.
Tracks latencies, error counts, retries, and confidence score distributions.
"""

import time
import threading
from typing import Dict, List, Any


class PipelineMetrics:
    def __init__(self):
        self._lock = threading.Lock()
        self.processing_times: List[float] = []
        self.llm_latencies: List[float] = []
        self.embedding_latencies: List[float] = []
        self.vector_search_latencies: List[float] = []
        self.validation_failures: int = 0
        self.retry_count: int = 0

        # Confidence distribution buckets
        self.confidence_distribution: Dict[str, int] = {
            "high (>=0.95)": 0,
            "medium (0.80-0.95)": 0,
            "low (<0.80)": 0
        }

    def record_processing_time(self, duration: float):
        with self._lock:
            self.processing_times.append(duration)

    def record_llm_latency(self, duration: float):
        with self._lock:
            self.llm_latencies.append(duration)

    def record_embedding_latency(self, duration: float):
        with self._lock:
            self.embedding_latencies.append(duration)

    def record_vector_search_latency(self, duration: float):
        with self._lock:
            self.vector_search_latencies.append(duration)

    def increment_validation_failures(self):
        with self._lock:
            self.validation_failures += 1

    def increment_retry_count(self):
        with self._lock:
            self.retry_count += 1

    def record_confidence(self, score: float):
        with self._lock:
            if score >= 0.95:
                self.confidence_distribution["high (>=0.95)"] += 1
            elif score >= 0.80:
                self.confidence_distribution["medium (0.80-0.95)"] += 1
            else:
                self.confidence_distribution["low (<0.80)"] += 1

    def get_metrics_summary(self) -> Dict[str, Any]:
        with self._lock:
            def avg(lst: List[float]) -> float:
                return round(sum(lst) / len(lst), 4) if lst else 0.0

            return {
                "summary": {
                    "total_clauses_processed": len(self.processing_times),
                    "validation_failures_total": self.validation_failures,
                    "retry_count_total": self.retry_count,
                },
                "latencies_seconds": {
                    "avg_processing_time": avg(self.processing_times),
                    "avg_llm_latency": avg(self.llm_latencies),
                    "avg_embedding_latency": avg(self.embedding_latencies),
                    "avg_vector_search_latency": avg(self.vector_search_latencies),
                    "raw": {
                        "processing_times": self.processing_times[-50:],  # keep last 50
                        "llm_latencies": self.llm_latencies[-50:],
                        "embedding_latencies": self.embedding_latencies[-50:],
                        "vector_search_latencies": self.vector_search_latencies[-50:],
                    }
                },
                "confidence_distribution": self.confidence_distribution
            }

    def get_prometheus_format(self) -> str:
        with self._lock:
            def avg(lst: List[float]) -> float:
                return sum(lst) / len(lst) if lst else 0.0

            lines = [
                "# HELP regops_clauses_processed_total Total number of circular clauses processed.",
                "# TYPE regops_clauses_processed_total counter",
                f"regops_clauses_processed_total {len(self.processing_times)}",

                "# HELP regops_validation_failures_total Total number of Pydantic validation failures.",
                "# TYPE regops_validation_failures_total counter",
                f"regops_validation_failures_total {self.validation_failures}",

                "# HELP regops_retry_count_total Total number of extraction retry loop occurrences.",
                "# TYPE regops_retry_count_total counter",
                f"regops_retry_count_total {self.retry_count}",

                "# HELP regops_avg_processing_time_seconds Average execution time for whole clause pipeline.",
                "# TYPE regops_avg_processing_time_seconds gauge",
                f"regops_avg_processing_time_seconds {avg(self.processing_times)}",

                "# HELP regops_avg_llm_latency_seconds Average response latency of Groq LLM completions.",
                "# TYPE regops_avg_llm_latency_seconds gauge",
                f"regops_avg_llm_latency_seconds {avg(self.llm_latencies)}",

                "# HELP regops_avg_embedding_latency_seconds Average latency to compute Text embeddings.",
                "# TYPE regops_avg_embedding_latency_seconds gauge",
                f"regops_avg_embedding_latency_seconds {avg(self.embedding_latencies)}",

                "# HELP regops_avg_vector_search_latency_seconds Average latency to query historical records from Qdrant.",
                "# TYPE regops_avg_vector_search_latency_seconds gauge",
                f"regops_avg_vector_search_latency_seconds {avg(self.vector_search_latencies)}",

                "# HELP regops_confidence_distribution_total Cumulative count of overall confidence classifications.",
                "# TYPE regops_confidence_distribution_total counter",
                f'regops_confidence_distribution_total{{bucket="high_95"}} {self.confidence_distribution["high (>=0.95)"]}',
                f'regops_confidence_distribution_total{{bucket="medium_80_95"}} {self.confidence_distribution["medium (0.80-0.95)"]}',
                f'regops_confidence_distribution_total{{bucket="low_80"}} {self.confidence_distribution["low (<0.80)"]}',
            ]
            return "\n".join(lines) + "\n"


# Global singleton metrics collector
metrics_collector = PipelineMetrics()
