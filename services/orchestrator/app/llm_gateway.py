"""LLMGateway — model-agnostic provider router (Adım 7).

Akış:
  1. agent_name → llm_configs (DB-1)            ← 5 dk Redis cache
  2. provider switch:
       anthropic / openai / openrouter / gemini / ollama / custom
  3. system_prompt + user_prompt (templates'ten gelir, içinde
     <düşünce>...</düşünce> CoT blokları olabilir).
  4. Provider yanıtından <düşünce> bloklarını **kesinlikle** temizle —
     öğrenciye gösterilmeyecek (system reminder'dan).
  5. Hata varsa LLMError fırlat; mock fallback YAPMA. Caller (Orchestrator)
     fallback metnini kendi üretir.

LLM_MOCK_MODE=true ise gateway DB'ye gitmez ve sabit Türkçe pedagojik
mock döner — testlerde ve yeni kurulumda işe yarar.

Cache invalidation:
  Redis key: `llm_config:{agent_name}` (TTL 5 dk)
  Admin paneli config değişince DEL eder (admin_api.py 7e'de).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Optional

import httpx

from .crypto import ApiKeyCipher, CryptoError
from .llm_configs_repo import LLMConfig, LLMConfigsRepo
from .redis_io import RedisIO

logger = logging.getLogger(__name__)


CACHE_TTL_SECONDS = 5 * 60          # 5 dk
DEFAULT_TIMEOUT_SECONDS = 60.0      # tek bir LLM çağrısı

# Türkçe CoT etiketi — system promptlarında birebir kullanılıyor.
_COT_RE = re.compile(r"<düşünce>.*?</düşünce>", re.DOTALL | re.IGNORECASE)
# Bazı modeller İngilizce <thinking> etiketi de döndürür — onu da temizle.
_COT_RE_EN = re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE)

MOCK_RESPONSE = (
    "Bu konuyu birlikte inceleyelim. "
    "[MOCK LLM YANITI — ENCRYPTION_KEY ile yapılandırılmış gerçek bir provider "
    "config eklendiğinde gerçek yanıt buradan döner.]"
)
MOCK_MANIM_CODE = (
    "from manim import *\n"
    "class RavelLesson(Scene):\n"
    "    def construct(self):\n"
    "        title = Text(\"Konu Anlatimi\", font_size=36)\n"
    "        self.play(Write(title))\n"
    "        self.wait(0.5)\n"
    "        body = Text(\"[MOCK - gerçek LLM config'i bekleniyor]\", font_size=24)\n"
    "        body.next_to(title, DOWN)\n"
    "        self.play(FadeIn(body))\n"
    "        self.wait(1)\n"
)


class LLMError(Exception):
    """Provider çağrısı, decrypt veya config eksikliği. Mesajda api_key sızdırma."""


def _strip_chain_of_thought(text: str) -> str:
    """LLM yanıtından <düşünce> ve <thinking> bloklarını çıkar.

    Defansif: bazı modeller blokları açıp kapatmayı becermez; o durumda
    yalnızca ilk </düşünce>'den sonrasını al, hiç kapanmazsa metni olduğu
    gibi döndür (LLM gerçekten cevabını bu blokların içine yazıyorsa
    hiçbir şey döndürmemek daha kötü).
    """
    cleaned = _COT_RE.sub("", text)
    cleaned = _COT_RE_EN.sub("", cleaned)
    # Açık ama kapanmamış <düşünce>: ilk </düşünce> sonrası biten kısmı al
    if cleaned == text and ("<düşünce>" in text.lower() or "<thinking>" in text.lower()):
        for end_tag in ("</düşünce>", "</Düşünce>", "</thinking>", "</Thinking>"):
            idx = text.find(end_tag)
            if idx >= 0:
                return text[idx + len(end_tag):].strip()
    return cleaned.strip()


# ─── Gateway ────────────────────────────────────────────────────────

class LLMGateway:
    def __init__(
        self,
        repo: LLMConfigsRepo,
        cipher: Optional[ApiKeyCipher],
        redis_io: RedisIO,
        mock_mode: bool = False,
        request_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.repo = repo
        self.cipher = cipher
        self.redis_io = redis_io
        self.mock_mode = mock_mode
        self.timeout = request_timeout_seconds
        self._http: Optional[httpx.AsyncClient] = None

    async def start(self) -> None:
        # Tek paylaşımlı HTTP client — connection pool reuse.
        self._http = httpx.AsyncClient(timeout=self.timeout)

    async def stop(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ─── Public API ─────────────────────────────────────────────────

    async def generate(
        self,
        agent_name: str,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """Provider'a istek at, CoT temizle, dönen metni döndür.

        Mock mode aktifse: agent_name'e göre sabit yanıt veya mock manim kodu döner.
        Hata: LLMError fırlat.
        """
        if self.mock_mode:
            logger.debug("[mock] LLMGateway returning canned response for agent=%s", agent_name)
            return self._mock_for(agent_name)

        cfg = await self._get_config_cached(agent_name)
        if cfg is None:
            raise LLMError(f"no active llm_config for agent={agent_name}")

        api_key = self._decrypt_key(cfg)

        provider = cfg.provider
        try:
            if provider == "anthropic":
                raw = await self._call_anthropic(cfg, api_key, system_prompt, user_prompt)
            elif provider in ("openai", "openrouter"):
                raw = await self._call_openai_compat(cfg, api_key, system_prompt, user_prompt)
            elif provider == "gemini":
                raw = await self._call_gemini(cfg, api_key, system_prompt, user_prompt)
            elif provider in ("ollama", "custom"):
                raw = await self._call_ollama(cfg, system_prompt, user_prompt)
            else:
                raise LLMError(f"unsupported provider: {provider}")
        except LLMError:
            raise
        except httpx.HTTPError as e:
            raise LLMError(f"{provider}: HTTP error: {e}") from e
        except Exception as e:
            raise LLMError(f"{provider}: unexpected error: {type(e).__name__}: {e}") from e

        if not raw:
            raise LLMError(f"{provider}: empty response")
        return _strip_chain_of_thought(raw)

    async def invalidate_cache(self, agent_name: str) -> None:
        await self.redis_io.client.delete(_cache_key(agent_name))

    # ─── Cache / config ────────────────────────────────────────────

    async def _get_config_cached(self, agent_name: str) -> Optional[LLMConfig]:
        key = _cache_key(agent_name)
        cached = await self.redis_io.client.get(key)
        if cached:
            try:
                d = json.loads(cached)
                return LLMConfig(
                    config_id=d["config_id"],
                    agent_name=d["agent_name"],
                    provider=d["provider"],
                    model_name=d["model_name"],
                    api_key_blob=bytes.fromhex(d["api_key_hex"]) if d.get("api_key_hex") else None,
                    endpoint_url=d.get("endpoint_url"),
                    max_tokens=d["max_tokens"],
                    temperature=d["temperature"],
                    is_active=d["is_active"],
                )
            except Exception:
                logger.warning("[%s] cached config corrupted, refetching", agent_name)

        cfg = await self.repo.get_active(agent_name)
        if cfg is None:
            return None
        await self.redis_io.client.set(
            key,
            json.dumps({
                "config_id": cfg.config_id,
                "agent_name": cfg.agent_name,
                "provider": cfg.provider,
                "model_name": cfg.model_name,
                "api_key_hex": cfg.api_key_blob.hex() if cfg.api_key_blob else None,
                "endpoint_url": cfg.endpoint_url,
                "max_tokens": cfg.max_tokens,
                "temperature": cfg.temperature,
                "is_active": cfg.is_active,
            }),
            ex=CACHE_TTL_SECONDS,
        )
        return cfg

    def _decrypt_key(self, cfg: LLMConfig) -> Optional[str]:
        """Ollama key gerektirmez; aksi halde decrypt et veya LLMError."""
        if cfg.provider == "ollama":
            return None
        if not cfg.api_key_blob:
            if cfg.provider == "custom":
                # custom provider için key opsiyonel
                return None
            raise LLMError(f"{cfg.provider}: api_key missing in config (agent={cfg.agent_name})")
        if self.cipher is None:
            raise LLMError("ENCRYPTION_KEY not configured; cannot decrypt api_key")
        try:
            return self.cipher.decrypt(cfg.api_key_blob)
        except CryptoError as e:
            raise LLMError(f"api_key decrypt failed for agent={cfg.agent_name}") from e

    # ─── Provider calls ────────────────────────────────────────────
    # Hepsi: system + user → raw text. Lazy-import provider SDK'ları:
    # OpenAI/Anthropic/Gemini SDK'ları image'a yüklü olsa bile her LLM
    # request'inde import etmek pahalı; bir kez yüklenince modül cache'lenir.

    async def _call_anthropic(
        self,
        cfg: LLMConfig,
        api_key: Optional[str],
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        # Anthropic SDK senkron client'ı executor'da çalıştır (aiohttp/anthropic
        # async var ama global lock'a karışmamak için thread'a gönderiyoruz).
        from anthropic import Anthropic

        def _sync_call() -> str:
            client = Anthropic(api_key=api_key)
            msg = client.messages.create(
                model=cfg.model_name,
                max_tokens=cfg.max_tokens,
                temperature=cfg.temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            # content is a list of TextBlock; concatenate text fields.
            parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
            return "".join(parts)

        return await asyncio.to_thread(_sync_call)

    async def _call_openai_compat(
        self,
        cfg: LLMConfig,
        api_key: Optional[str],
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """OpenAI + OpenRouter aynı SDK ile (base_url farkı). Async client kullan."""
        from openai import AsyncOpenAI

        base_url = None
        if cfg.provider == "openrouter":
            base_url = "https://openrouter.ai/api/v1"
        # OpenAI managed: base_url None → SDK default
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        try:
            resp = await client.chat.completions.create(
                model=cfg.model_name,
                max_tokens=cfg.max_tokens,
                temperature=cfg.temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
            )
        finally:
            await client.close()
        if not resp.choices:
            raise LLMError(f"{cfg.provider}: empty choices")
        return resp.choices[0].message.content or ""

    async def _call_gemini(
        self,
        cfg: LLMConfig,
        api_key: Optional[str],
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """google-generativeai SDK senkron — executor'da çağır."""
        import google.generativeai as genai

        def _sync_call() -> str:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(
                model_name=cfg.model_name,
                system_instruction=system_prompt,
            )
            resp = model.generate_content(
                user_prompt,
                generation_config={
                    "max_output_tokens": cfg.max_tokens,
                    "temperature": cfg.temperature,
                },
            )
            return resp.text or ""

        return await asyncio.to_thread(_sync_call)

    async def _call_ollama(
        self,
        cfg: LLMConfig,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """Ollama / custom — POST /api/chat. endpoint_url zorunlu."""
        if not cfg.endpoint_url:
            raise LLMError(f"{cfg.provider}: endpoint_url required")
        if self._http is None:
            raise LLMError("LLMGateway not started")
        url = cfg.endpoint_url.rstrip("/") + "/api/chat"
        body = {
            "model": cfg.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            "stream": False,
            "options": {
                "temperature": cfg.temperature,
                "num_predict": cfg.max_tokens,
            },
        }
        r = await self._http.post(url, json=body)
        r.raise_for_status()
        data = r.json()
        # Ollama: {"message": {"role": "assistant", "content": "..."}}
        msg = data.get("message", {})
        return msg.get("content", "") or ""

    # ─── Mock helper ──────────────────────────────────────────────

    @staticmethod
    def _mock_for(agent_name: str) -> str:
        if agent_name in ("orchestrator_manim", "orchestrator_correction"):
            return MOCK_MANIM_CODE
        return MOCK_RESPONSE


def _cache_key(agent_name: str) -> str:
    return f"llm_config:{agent_name}"
