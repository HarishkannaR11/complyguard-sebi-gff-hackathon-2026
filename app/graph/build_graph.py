import os
from contextlib import ExitStack

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, StateGraph

from . import nodes
from .state import ComplianceState

_exit_stack = ExitStack()
_checkpointer = None


def _get_checkpointer():
    global _checkpointer
    if _checkpointer is None:
        conn_string = os.environ.get(
            "DATABASE_URL", "postgresql://regops:regops@localhost:5433/regops"
        )
        if conn_string.startswith("sqlite"):
            from langgraph.checkpoint.memory import MemorySaver
            _checkpointer = MemorySaver()
        else:
            try:
                _checkpointer = _exit_stack.enter_context(
                    PostgresSaver.from_conn_string(conn_string)
                )
                _checkpointer.setup()
            except Exception:
                from langgraph.checkpoint.memory import MemorySaver
                _checkpointer = MemorySaver()
    return _checkpointer


def route_after_validation(state: ComplianceState) -> str:
    if state.get("validation_status") == "failed":
        if (state.get("extraction_retries") or 0) <= 1:
            return "extractor"
    return "differ"


def route_after_diff(state: ComplianceState) -> str:
    # V2 Feature 3: Route to review if validation failed or confidence < 80%
    if state.get("validation_status") == "failed":
        return "human_review"
    if state.get("overall_confidence", 1.0) < 0.8:
        return "human_review"
        
    if state.get("confidence", 1.0) < 0.7:
        return "human_review"
    if state["diff_status"] in ("amended", "superseded"):
        return "human_review"
    if state["diff_status"] == "unchanged":
        return "finalize"
    return "mapper"


def route_after_evidence(state: ComplianceState) -> str:
    if state["evidence_status"] == "missing":
        return "gap_engine"
    if state["evidence_status"] == "invalid":
        return "human_review"
    return "finalize"


def build_graph(checkpointer=None):
    g = StateGraph(ComplianceState)
    g.add_node("chunker", nodes.chunker_node)
    g.add_node("embedder", nodes.embedder_node)
    g.add_node("extractor", nodes.extractor_node)
    g.add_node("validation", nodes.validation_node)
    g.add_node("differ", nodes.differ_node)
    g.add_node("human_review", nodes.human_review_node)
    g.add_node("mapper", nodes.mapper_node)
    g.add_node("evidence_check", nodes.evidence_node)
    g.add_node("gap_engine", nodes.gap_engine_node)
    g.add_node("finalize", nodes.finalize_node)

    g.set_entry_point("chunker")
    g.add_edge("chunker", "embedder")
    g.add_edge("embedder", "extractor")
    g.add_edge("extractor", "validation")
    g.add_conditional_edges("validation", route_after_validation,
        {"extractor": "extractor", "differ": "differ"})
    g.add_conditional_edges("differ", route_after_diff,
        {"human_review": "human_review", "mapper": "mapper", "finalize": "finalize"})
    g.add_edge("human_review", "mapper")
    g.add_edge("mapper", "evidence_check")
    g.add_conditional_edges("evidence_check", route_after_evidence,
        {"gap_engine": "gap_engine", "human_review": "human_review", "finalize": "finalize"})
    g.add_edge("gap_engine", "finalize")
    g.add_edge("finalize", END)

    return g.compile(checkpointer=checkpointer or _get_checkpointer())
