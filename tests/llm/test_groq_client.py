from unittest.mock import MagicMock, patch

import httpx
import pytest
from groq import APIConnectionError, APIStatusError, RateLimitError

from app.llm import groq_client
from app.llm.groq_client import backoff_delay, chat_completion, is_retryable


def _status_error(cls, code):
    request = httpx.Request("POST", "https://api.groq.com/x")
    response = httpx.Response(code, request=request, headers={"retry-after": "2"})
    return cls("boom", response=response, body=None)


def _ok(content="{}"):
    return MagicMock(choices=[MagicMock(message=MagicMock(content=content))])


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    with patch("app.llm.groq_client.Groq") as cls:
        inst = MagicMock()
        cls.return_value = inst
        yield inst


def test_returns_content_and_requests_json_mode(client):
    client.chat.completions.create.return_value = _ok('{"a": 1}')
    assert chat_completion("hi") == '{"a": 1}'
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["temperature"] == 0


def test_retries_rate_limit_then_succeeds(client):
    client.chat.completions.create.side_effect = [
        _status_error(RateLimitError, 429),
        _ok("done"),
    ]
    sleeps = []
    assert chat_completion("hi", sleep=sleeps.append) == "done"
    assert len(sleeps) == 1


def test_retries_5xx_but_not_4xx(client):
    client.chat.completions.create.side_effect = [_status_error(APIStatusError, 503), _ok("x")]
    assert chat_completion("hi", sleep=lambda s: None) == "x"

    client.chat.completions.create.side_effect = _status_error(APIStatusError, 400)
    with pytest.raises(APIStatusError):
        chat_completion("hi", sleep=lambda s: None)


def test_gives_up_after_max_retries(client):
    client.chat.completions.create.side_effect = APIConnectionError(
        request=httpx.Request("POST", "https://x")
    )
    with pytest.raises(APIConnectionError):
        chat_completion("hi", max_retries=3, sleep=lambda s: None)
    assert client.chat.completions.create.call_count == 3


def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        chat_completion("hi")


def test_client_is_cached(client):
    assert groq_client.get_groq_client() is groq_client.get_groq_client()


def test_backoff_grows_and_honours_retry_after():
    assert backoff_delay(0) < backoff_delay(3)
    assert 2 <= backoff_delay(0, _status_error(RateLimitError, 429)) <= 2.5
    assert is_retryable(_status_error(RateLimitError, 429))
