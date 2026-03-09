"""
LLM client wrapper — switches between Anthropic API and local Ollama.

Usage:
  Set USE_LOCAL_LLM=true in .env to use Ollama instead of Anthropic.
  Set LOCAL_LLM_MODEL to choose the model (default: qwen2.5:7b).

  from utils.llm_client import chat
  text = chat(
      model_hint="claude-haiku-4-5",   # ignored when USE_LOCAL_LLM=true
      system="You are a classifier...",
      user="Classify this: ...",
  )
"""
import os

import structlog

log = structlog.get_logger(__name__)

_USE_LOCAL = os.getenv("USE_LOCAL_LLM", "false").lower() == "true"
_LOCAL_MODEL = os.getenv("LOCAL_LLM_MODEL", "qwen2.5:7b")
_LOCAL_BASE_URL = os.getenv("LOCAL_LLM_URL", "http://localhost:11434/v1")

# Lazy-initialised clients
_anthropic_client = None
_openai_client = None


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


def chat(
    model_hint: str,
    system: str,
    user: str,
    max_tokens: int = 2048,
    local_model_override: str | None = None,
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
    """
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
