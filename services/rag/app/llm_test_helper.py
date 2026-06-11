"""Adım 7e: provider'a "Merhaba" test mesajı atan minimal yardımcı.

RAG container'a anthropic/openai/google-generativeai SDK'larını
yüklemek istemiyoruz (orchestrator'a ait). Bu yüzden test endpoint
SDK kullanmadan direkt provider REST endpoint'lerine `httpx` ile
gider. Sadece "responsiveness" doğrulaması için yeterli.

Production trafiği Orchestrator'ın tam-özellikli LLMGateway'inden
geçer; bu helper YALNIZCA admin paneli "Test bağlantısı" düğmesinin
HTTP kanaldan canlılık doğrulamasıdır.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    ok: bool
    latency_ms: int
    sample_text: str
    error: Optional[str] = None


# Çok küçük bir prompt — bütçe maliyetini minimize et.
_TEST_USER_PROMPT = "Merhaba"
_TEST_SYSTEM_PROMPT = "Türkçe konuşan yardımsever bir asistansın. Kısa ve nazik cevap ver."
_MAX_TOKENS = 32
_DEFAULT_TIMEOUT = 15.0


async def test_provider(
    provider: str,
    model_name: str,
    api_key: Optional[str],
    endpoint_url: Optional[str],
    timeout_seconds: float = _DEFAULT_TIMEOUT,
) -> TestResult:
    """Provider'a tek bir 'Merhaba' isteği at. SDK kullanmaz."""
    import time

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            if provider == "anthropic":
                text = await _call_anthropic(client, model_name, api_key)
            elif provider == "openai":
                text = await _call_openai_compat(
                    client, model_name, api_key, base_url="https://api.openai.com/v1",
                )
            elif provider == "openrouter":
                text = await _call_openai_compat(
                    client, model_name, api_key, base_url="https://openrouter.ai/api/v1",
                )
            elif provider == "gemini":
                text = await _call_gemini(client, model_name, api_key)
            elif provider in ("ollama", "custom"):
                if not endpoint_url:
                    return TestResult(False, 0, "", "endpoint_url required")
                text = await _call_ollama(client, model_name, endpoint_url)
            else:
                return TestResult(False, 0, "", f"unsupported provider: {provider}")
        latency = int((time.perf_counter() - start) * 1000)
        return TestResult(True, latency, (text or "")[:120])
    except httpx.HTTPError as e:
        latency = int((time.perf_counter() - start) * 1000)
        return TestResult(False, latency, "", f"HTTP error: {e}")
    except Exception as e:
        latency = int((time.perf_counter() - start) * 1000)
        return TestResult(False, latency, "", f"{type(e).__name__}: {e}")


# ─── Provider call helpers (REST) ───────────────────────────────────

async def _call_anthropic(client: httpx.AsyncClient, model: str, api_key: Optional[str]) -> str:
    if not api_key:
        raise ValueError("anthropic: api_key required")
    r = await client.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": _MAX_TOKENS,
            "system": _TEST_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": _TEST_USER_PROMPT}],
        },
    )
    r.raise_for_status()
    data = r.json()
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "".join(parts)


async def _call_openai_compat(
    client: httpx.AsyncClient,
    model: str,
    api_key: Optional[str],
    base_url: str,
) -> str:
    if not api_key:
        raise ValueError("api_key required")
    r = await client.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "max_tokens": _MAX_TOKENS,
            "messages": [
                {"role": "system", "content": _TEST_SYSTEM_PROMPT},
                {"role": "user",   "content": _TEST_USER_PROMPT},
            ],
        },
    )
    r.raise_for_status()
    data = r.json()
    choices = data.get("choices") or []
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "") or ""


async def _call_gemini(client: httpx.AsyncClient, model: str, api_key: Optional[str]) -> str:
    if not api_key:
        raise ValueError("gemini: api_key required")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    r = await client.post(
        url,
        headers={"Content-Type": "application/json"},
        json={
            "contents": [{"role": "user", "parts": [{"text": _TEST_USER_PROMPT}]}],
            "systemInstruction": {"parts": [{"text": _TEST_SYSTEM_PROMPT}]},
            "generationConfig": {"maxOutputTokens": _MAX_TOKENS},
        },
    )
    r.raise_for_status()
    data = r.json()
    cands = data.get("candidates") or []
    if not cands:
        return ""
    parts = cands[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts)


async def _call_ollama(client: httpx.AsyncClient, model: str, endpoint_url: str) -> str:
    url = endpoint_url.rstrip("/") + "/api/chat"
    r = await client.post(
        url,
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": _TEST_SYSTEM_PROMPT},
                {"role": "user",   "content": _TEST_USER_PROMPT},
            ],
            "stream": False,
            "options": {"num_predict": _MAX_TOKENS},
        },
    )
    r.raise_for_status()
    return r.json().get("message", {}).get("content", "") or ""
