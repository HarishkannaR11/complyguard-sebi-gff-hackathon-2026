import os

# Tests never talk to a real Postgres; allow the in-memory LangGraph checkpointer.
os.environ.setdefault("ALLOW_MEMORY_CHECKPOINTER", "1")
# Node tests mock the Groq client but still need a key to get past the guard.
os.environ.setdefault("GROQ_API_KEY", "test-key")

import pytest


@pytest.fixture(autouse=True)
def _reset_groq_client():
    from app.llm.groq_client import reset_groq_client

    reset_groq_client()
    yield
    reset_groq_client()
