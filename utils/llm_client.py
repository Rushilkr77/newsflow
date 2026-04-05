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

import structlog
from openai import APIConnectionError, APIError, APITimeoutError

log = structlog.get_logger(__name__)

_USE_LOCAL = os.getenv("USE_LOCAL_LLM", "false").lower() == "true"
_LOCAL_MODEL = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:7b")
_LOCAL_BASE_URL = os.getenv("LOCAL_LLM_URL", "http://localhost:11434/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

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
        _openrouter_client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY,
        )
    return _openrouter_client


def chat(
    model_hint: str,
    system: str,
    user: str,
    max_tokens: int = 2048,
    local_model_override: str | None = None,
    openrouter_model: str | None = None,
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
        openrouter_model: If set AND OPENROUTER_API_KEY is present, route this call
                          through OpenRouter using the specified model. Falls back to
                          local/Anthropic path if the OpenRouter call fails.
    """
    # OpenRouter path: takes priority over local/Anthropic when explicitly requested
    if openrouter_model and OPENROUTER_API_KEY:
        try:
            return _chat_openrouter(openrouter_model, system, user, max_tokens)
        except (APIError, APIConnectionError, APITimeoutError) as exc:
            log.warning("openrouter_fallback", model=openrouter_model, error=str(exc))
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
        raise ValueError(f"OpenRouter returned empty choices for model {model}")
    return response.choices[0].message.content.strip()
