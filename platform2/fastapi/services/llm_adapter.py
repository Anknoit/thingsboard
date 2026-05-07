"""
llm_adapter.py — Provider-agnostic LLM interface.

Supported providers (switch via LLM_PROVIDER env var):
  claude  — Anthropic claude-sonnet-4-20250514
  openai  — OpenAI gpt-4o
  ollama  — Self-hosted via Ollama REST API
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import AsyncIterator

from config import settings

logger = logging.getLogger(__name__)


class LLMProviderError(Exception):
    def __init__(self, provider: str, message: str) -> None:
        self.provider = provider
        super().__init__(f"[{provider}] {message}")


class LLMAdapter(ABC):
    """Abstract interface all LLM providers must implement."""

    @abstractmethod
    async def stream_chat(
        self,
        system: str,
        messages: list[dict],
    ) -> AsyncIterator[str]:
        """Yield string tokens as they arrive from the model."""
        ...

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Return a dense embedding vector for the given text."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider API is reachable."""
        ...


# ── Claude ────────────────────────────────────────────────────────────────────

class ClaudeAdapter(LLMAdapter):
    def __init__(self) -> None:
        import anthropic
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.claude_model

    async def stream_chat(
        self,
        system: str,
        messages: list[dict],
    ) -> AsyncIterator[str]:
        try:
            async with self._client.messages.stream(
                model=self._model,
                max_tokens=2048,
                system=system,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception as exc:
            raise LLMProviderError("claude", str(exc)) from exc

    async def embed(self, text: str) -> list[float]:
        # Claude doesn't expose embeddings; fall back to a lightweight model
        # In production, use a dedicated embedding model or OpenAI's text-embedding-3-small
        raise LLMProviderError(
            "claude",
            "Embedding not supported by Claude API. "
            "Set LLM_PROVIDER=openai for embedding, or use a local model.",
        )

    async def health_check(self) -> bool:
        try:
            # Minimal API call — list models is cheap
            await self._client.models.list()
            return True
        except Exception:
            return False


# ── OpenAI ────────────────────────────────────────────────────────────────────

class OpenAIAdapter(LLMAdapter):
    def __init__(self) -> None:
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_model
        self._embed_model = "text-embedding-3-small"

    async def stream_chat(
        self,
        system: str,
        messages: list[dict],
    ) -> AsyncIterator[str]:
        try:
            full_messages = [{"role": "system", "content": system}] + messages
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=full_messages,
                stream=True,
                max_tokens=2048,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as exc:
            raise LLMProviderError("openai", str(exc)) from exc

    async def embed(self, text: str) -> list[float]:
        try:
            response = await self._client.embeddings.create(
                model=self._embed_model,
                input=text,
            )
            return response.data[0].embedding
        except Exception as exc:
            raise LLMProviderError("openai", str(exc)) from exc

    async def health_check(self) -> bool:
        try:
            await self._client.models.list()
            return True
        except Exception:
            return False


# ── Ollama ────────────────────────────────────────────────────────────────────

class OllamaAdapter(LLMAdapter):
    def __init__(self) -> None:
        import httpx
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._model = settings.ollama_model
        self._client = httpx.AsyncClient(timeout=120)

    async def stream_chat(
        self,
        system: str,
        messages: list[dict],
    ) -> AsyncIterator[str]:
        import json
        try:
            full_messages = [{"role": "system", "content": system}] + messages
            async with self._client.stream(
                "POST",
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": full_messages,
                    "stream": True,
                },
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        content = data.get("message", {}).get("content", "")
                        if content:
                            yield content
                        if data.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue
        except Exception as exc:
            raise LLMProviderError("ollama", str(exc)) from exc

    async def embed(self, text: str) -> list[float]:
        import json
        try:
            resp = await self._client.post(
                f"{self._base_url}/api/embeddings",
                json={"model": self._model, "prompt": text},
            )
            resp.raise_for_status()
            return resp.json()["embedding"]
        except Exception as exc:
            raise LLMProviderError("ollama", str(exc)) from exc

    async def health_check(self) -> bool:
        try:
            resp = await self._client.get(f"{self._base_url}/api/tags", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False


# ── Embedding-only fallback ───────────────────────────────────────────────────
# When using Claude (no embed support), we use a lightweight sentence-transformer
# via httpx to the Ollama embed endpoint, or fall back to OpenAI embeddings.

class _EmbedFallback:
    """
    Wraps Claude chat with Ollama/OpenAI embeddings.
    Used when LLM_PROVIDER=claude but embeddings are needed for RAG.
    """
    def __init__(self, chat_adapter: LLMAdapter, embed_adapter: LLMAdapter) -> None:
        self._chat = chat_adapter
        self._embed = embed_adapter

    async def stream_chat(self, system: str, messages: list[dict]) -> AsyncIterator[str]:
        async for token in self._chat.stream_chat(system, messages):
            yield token

    async def embed(self, text: str) -> list[float]:
        return await self._embed.embed(text)

    async def health_check(self) -> bool:
        return await self._chat.health_check()


# ── Factory ───────────────────────────────────────────────────────────────────

_adapter: LLMAdapter | None = None


def get_llm_adapter() -> LLMAdapter:
    """
    Return the configured LLM adapter singleton.
    When LLM_PROVIDER=claude, embeddings are handled by Ollama (if available)
    or raise LLMProviderError (caller should handle).
    """
    global _adapter
    if _adapter is not None:
        return _adapter

    provider = settings.llm_provider.lower()

    if provider == "claude":
        chat = ClaudeAdapter()
        # Try to pair with Ollama for embeddings (RAG); if Ollama not configured,
        # RAG will use chromadb's built-in default embeddings instead.
        try:
            embed = OllamaAdapter()
            _adapter = _EmbedFallback(chat, embed)  # type: ignore[assignment]
        except Exception:
            _adapter = chat
        logger.info("LLM adapter: Claude (%s)", settings.claude_model)

    elif provider == "openai":
        _adapter = OpenAIAdapter()
        logger.info("LLM adapter: OpenAI (%s)", settings.openai_model)

    elif provider == "ollama":
        _adapter = OllamaAdapter()
        logger.info("LLM adapter: Ollama (%s @ %s)", settings.ollama_model, settings.ollama_base_url)

    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER='{provider}'. Must be: claude | openai | ollama"
        )

    return _adapter
