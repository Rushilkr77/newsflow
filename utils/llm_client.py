"""
LLM client wrapper — switches between Anthropic API and local Ollama.

Usage:
  Set USE_LOCAL_LLM=true in .env to use Ollama instead of Anthropic.
  Set LOCAL_LLM_MODEL to choose the model (default: qwen2.5:7b).
  Set OPENROUTER_API_KEY to enable OpenRouter backend.

  from utils.llm_client import chat
  text = chat(
      model_hint="claude-haiku-4-5",   # ignored when USE_LOCAL_LLM=true
      system="You are a classifier...",
      user="Classify this: ...",
  )
"""
import os
import time

import structlog
from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError

log = structlog.get_logger(__name__)

_USE_LOCAL = os.getenv("USE_LOCAL_LLM", "false").lower() == "true"
_LOCAL_MODEL = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:7b")
_LOCAL_BASE_URL = os.getenv("LOCAL_LLM_URL", "http://localhost:11434/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# Models blacklisted for this process lifetime (daily limit hit or spend limit exceeded).
# Shared across all chat() calls so a model that exhausts its quota on call #1
# is silently skipped on calls #2..N instead of burning time on guaranteed failures.
_session_blacklist: set[str] = set()


def _parse_openrouter_error(exc: APIStatusError) -> tuple[bool, bool, float | None]:
    """
    Parse an OpenRouter APIStatusError.
    Returns (is_daily_limit, is_spend_limit, retry_after_seconds).
    """
    body = getattr(exc, "body", None) or {}
    error_obj = body.get("error", {}) if isinstance(body, dict) else {}
    if not isinstance(error_obj, dict):
        error_obj = {}
    msg = error_obj.get("message", "")
    metadata = error_obj.get("metadata", {}) or {}

    is_daily_limit = "free-models-per-day" in msg or "rate-models-per-day" in msg
    is_spend_limit = exc.status_code == 402

    retry_after: float | None = None
    if not is_daily_limit and not is_spend_limit and exc.status_code == 429:
        raw_secs = metadata.get("retry_after_seconds") if isinstance(metadata, dict) else None
        if raw_secs is not None:
            retry_after = min(float(raw_secs), 90.0)
        else:
            response = getattr(exc, "response", None)
            if response is not None:
                ra_header = response.headers.get("Retry-After")
                if ra_header:
                    try:
                        retry_after = min(float(ra_header), 90.0)
                    except (ValueError, TypeError):
                        pass

    return is_daily_limit, is_spend_limit, retry_after

# Lazy-initialised clients
_anthropic_client = None
_openai_client = None
_openrouter_client = None


def _get_anthropic():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        _anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _anthropic_client


def _get_openai():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(base_url=_LOCAL_BASE_URL, api_key="ollama")
    return _openai_client


def _get_openrouter():
    """Lazy-init OpenRouter client. Only call if OPENROUTER_API_KEY is set."""
    global _openrouter_client
    if _openrouter_client is None:
        from openai import OpenAI
        # Free-tier models frequently hang TCP connections for hours before
        # returning 429s. 60s timeout surfaces these as APITimeoutError so the
        # model-fallback loop in chat() can move to the next model immediately.
        _openrouter_client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
            timeout=60.0,
        )
    return _openrouter_client


def chat(
    model_hint: str,
    system: str,
    user: str,
    max_tokens: int = 2048,
    local_model_override: str | None = None,
    openrouter_models: list[str] | None = None,
) -> str:
    """
    Send a single system+user prompt, return the response text.

    Args:
        model_hint: Anthropic model ID (e.g. "claude-haiku-4-5").
                    Ignored when USE_LOCAL_LLM=true.
        system: System prompt text.
        user: User prompt text.
        max_tokens: Maximum response tokens.
        local_model_override: Override the global LOCAL_LLM_MODEL for this call only.
                              Used by agents to select per-task models (e.g. qwen2.5:3b
                              for classification, llama3.2:3b for script writing).
                              Only applies when USE_LOCAL_LLM=true.
        openrouter_models: Ordered list of OpenRouter model IDs to try in sequence.
                           Requires OPENROUTER_API_KEY to be set. Each model is tried
                           in order; on provider error the next model is attempted.
                           Falls back to local/Anthropic only when all models fail.
    """
    # OpenRouter path: try each model in sequence before falling back
    if openrouter_models and OPENROUTER_API_KEY:
        for model in openrouter_models:
            if model in _session_blacklist:
                log.debug("openrouter_model_skipped", model=model, reason="session_blacklist")
                continue

            retried = False
            while True:
                try:
                    return _chat_openrouter(model, system, user, max_tokens)
                except APIStatusError as exc:
                    is_daily, is_spend, retry_after = _parse_openrouter_error(exc)

                    if is_daily:
                        log.warning("openrouter_model_blacklisted", model=model, reason="daily_limit")
                        _session_blacklist.add(model)
                        break

                    if is_spend:
                        log.warning("openrouter_model_blacklisted", model=model, reason="spend_limit")
                        _session_blacklist.add(model)
                        break

                    if exc.status_code == 404:
                        log.warning("openrouter_model_blacklisted", model=model, reason="not_found")
                        _session_blacklist.add(model)
                        break

                    if retry_after is not None and not retried:
                        log.warning("openrouter_model_rate_limited", model=model, retry_after_sec=retry_after)
                        time.sleep(retry_after)
                        retried = True
                        continue

                    log.warning("openrouter_model_failed", model=model, error=str(exc))
                    break

                except APIConnectionError as exc:
                    if not retried:
                        log.warning("openrouter_model_connection_retry", model=model, error=str(exc))
                        time.sleep(2)
                        retried = True
                        continue
                    log.warning("openrouter_model_failed", model=model, error=str(exc))
                    break

                except APITimeoutError as exc:
                    log.warning("openrouter_model_failed", model=model, error=str(exc))
                    break

        log.warning("openrouter_all_failed", models=openrouter_models)
        # Fall through to local/Anthropic path

    if _USE_LOCAL:
        return _chat_ollama(system, user, max_tokens, model=local_model_override)
    return _chat_anthropic(model_hint, system, user, max_tokens)


def _chat_anthropic(model: str, system: str, user: str, max_tokens: int) -> str:
    client = _get_anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    log.debug("anthropic_call", model=model, input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens)
    return response.content[0].text.strip()


def _chat_ollama(system: str, user: str, max_tokens: int, model: str | None = None) -> str:
    client = _get_openai()
    resolved_model = model or _LOCAL_MODEL
    response = client.chat.completions.create(
        model=resolved_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
    )
    log.debug("ollama_call", model=resolved_model)
    return response.choices[0].message.content.strip()


def _chat_openrouter(model: str, system: str, user: str, max_tokens: int) -> str:
    client = _get_openrouter()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
    )
    usage = response.usage
    log.debug(
        "openrouter_call",
        model=model,
        input_tokens=usage.prompt_tokens if usage else None,
        output_tokens=usage.completion_tokens if usage else None,
    )
    if not response.choices:
        raise ValueError(f"OpenRouter {model} returned empty choices")
    content = response.choices[0].message.content
    if not content or not content.strip():
        raise ValueError(f"OpenRouter {model} returned empty content")
    return content.strip()
