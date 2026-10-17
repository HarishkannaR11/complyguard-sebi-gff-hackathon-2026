"""Shared Groq client: one cached instance plus a retrying chat-completion helper."""
import logging
import os
import random
import time

from groq import APIConnectionError, APIStatusError, APITimeoutError, Groq, RateLimitError

logger = logging.getLogger(__name__)

MAX_RETRIES = 4
BASE_DELAY_SECONDS = 1.5
MAX_DELAY_SECONDS = 30.0

_client: Groq | None = None
_client_key: str | None = None


def get_model() -> str:
    return os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")


def get_groq_client() -> Groq:
    """Return a process-wide Groq client, rebuilt only if the API key changes."""
    global _client, _client_key
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY environment variable is not set")
    if _client is None or _client_key != api_key:
        _client = Groq(api_key=api_key)
        _client_key = api_key
    return _client


def reset_groq_client() -> None:
    global _client, _client_key
    _client = None
    _client_key = None


def is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (APIConnectionError, APITimeoutError, RateLimitError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code >= 500
    return False


def _retry_after(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    try:
        return float(headers.get("retry-after"))
    except (TypeError, ValueError):
        return None


def backoff_delay(attempt: int, exc: Exception | None = None) -> float:
    """Exponential backoff with jitter; honours a Retry-After header if present."""
    hinted = _retry_after(exc) if exc is not None else None
    delay = hinted if hinted is not None else BASE_DELAY_SECONDS * (2 ** attempt)
    delay = min(delay, MAX_DELAY_SECONDS)
    return delay + random.uniform(0, delay * 0.25)


def chat_completion(
    prompt: str,
    *,
    max_tokens: int = 800,
    json_mode: bool = True,
    max_retries: int = MAX_RETRIES,
    sleep=time.sleep,
) -> str:
    """Send a single-turn prompt and return the message content.

    Retries connection errors, timeouts, rate limits and 5xx responses with
    exponential backoff; any other error is raised immediately.
    """
    client = get_groq_client()
    kwargs = {
        "model": get_model(),
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content
        except Exception as exc:
            if not is_retryable(exc) or attempt == max_retries - 1:
                raise
            delay = backoff_delay(attempt, exc)
            logger.warning(
                "Groq call failed (%s); retry %d/%d in %.1fs",
                type(exc).__name__, attempt + 1, max_retries - 1, delay,
            )
            sleep(delay)
    raise RuntimeError("unreachable")  # pragma: no cover
