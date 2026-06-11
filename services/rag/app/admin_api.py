"""FastAPI admin API — content upload + reindex + stats + LLM config (Adım 7e).

Auth: aynı JWT_SECRET_KEY (Gateway ile), token payload'ında
role="admin" claim'i aranır. Token üretmek için scripts/generate_admin_token.sh.
"""
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
    Header,
)
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from .config import Settings
from .crypto import ApiKeyCipher, CryptoError
from .ingestion_pipeline import IngestionPipeline
from .llm_configs_repo import LLMConfig, LLMConfigsRepo
from .llm_test_helper import test_provider
from .qdrant_io import QdrantIO
from .schemas import CollectionStats, IngestionResult, UploadResponse


SUPPORTED_PROVIDERS = ("anthropic", "openai", "gemini", "openrouter", "ollama", "custom")

logger = logging.getLogger(__name__)


def _check_admin_token(authorization: Optional[str], settings: Settings) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing or invalid Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"invalid token: {e}") from e
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return payload


def _validate_config_payload(p: "LLMConfigUpsert") -> None:
    if p.provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"unsupported provider: {p.provider}")
    if p.provider in ("ollama", "custom") and not p.endpoint_url:
        raise HTTPException(status_code=400, detail=f"{p.provider}: endpoint_url required")
    # ollama dışındaki yönetilen sağlayıcılar key zorunlu
    if p.provider in ("anthropic", "openai", "gemini", "openrouter") and not p.api_key:
        raise HTTPException(status_code=400, detail=f"{p.provider}: api_key required")


# ─── Admin payload modelleri ─────────────────────────────────────────

class LLMConfigUpsert(BaseModel):
    agent_name: str
    provider: str
    model_name: str
    api_key: Optional[str] = None
    endpoint_url: Optional[str] = None
    max_tokens: int = Field(default=1024, ge=1, le=32768)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    is_active: bool = True


class LLMConfigPatch(BaseModel):
    """PUT için: sadece dolu alanlar güncellenir.
    api_key None ve clear_api_key=True ise mevcut key NULL'a set edilir.
    """
    provider: Optional[str] = None
    model_name: Optional[str] = None
    api_key: Optional[str] = None
    clear_api_key: bool = False
    endpoint_url: Optional[str] = None
    clear_endpoint: bool = False
    max_tokens: Optional[int] = Field(default=None, ge=1, le=32768)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    is_active: Optional[bool] = None


def _config_to_dict(cfg: LLMConfig) -> dict[str, Any]:
    """Plaintext key DÖNDÜRME — sadece maskeli prefix."""
    masked = ""
    if cfg.api_key_blob is not None:
        # Repo blob bazında çalışır; gerçek key decrypt edilmez burada — sadece "var" işareti
        masked = "****"
    return {
        "config_id": cfg.config_id,
        "agent_name": cfg.agent_name,
        "provider": cfg.provider,
        "model_name": cfg.model_name,
        "api_key_set": cfg.api_key_blob is not None,
        "api_key_masked": masked,
        "endpoint_url": cfg.endpoint_url,
        "max_tokens": cfg.max_tokens,
        "temperature": cfg.temperature,
        "is_active": cfg.is_active,
    }


def build_admin_app(
    settings: Settings,
    pipeline: IngestionPipeline,
    qdrant: QdrantIO,
    llm_repo: Optional[LLMConfigsRepo] = None,
    cipher: Optional[ApiKeyCipher] = None,
    redis_client: Optional[Redis] = None,
) -> FastAPI:
    app = FastAPI(title="RAVEL RAG Admin", version="1.0")
    router = APIRouter(prefix="/admin")

    def admin_required(authorization: Optional[str] = Header(None)) -> dict:
        return _check_admin_token(authorization, settings)

    # ─── Health (auth-free) ─────────────────────────────────────────
    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    # ─── Excel index ────────────────────────────────────────────────
    @router.post("/upload/excel", response_model=UploadResponse)
    async def upload_excel(
        file: UploadFile = File(...),
        _: dict = Depends(admin_required),
    ) -> UploadResponse:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name
        try:
            result = pipeline.ingest_excel_index(tmp_path)
            return UploadResponse(
                file_name=file.filename or "index.xlsx",
                rows_or_chunks=result["rows"],
                message=f"Excel index loaded: {len(result['file_names'])} unique files indexed",
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    # ─── Question file upload ──────────────────────────────────────
    @router.post("/upload/questions", response_model=IngestionResult)
    async def upload_questions(
        file: UploadFile = File(...),
        file_type: str = Form(...),
        grade_level: int = Form(...),
        subject: str = Form(...),
        _: dict = Depends(admin_required),
    ) -> IngestionResult:
        if pipeline.excel_index_size == 0:
            raise HTTPException(status_code=400, detail="Excel index is empty. Upload it first via /admin/upload/excel")
        ft = file_type.lower()
        if ft not in ("pdf", "docx"):
            raise HTTPException(status_code=400, detail="file_type must be 'pdf' or 'docx'")
        if not (5 <= grade_level <= 8):
            raise HTTPException(status_code=400, detail="grade_level must be 5..8")
        subject = subject.strip()
        if not subject:
            raise HTTPException(status_code=400, detail="subject required")

        # Orijinal dosya adını koruyoruz (tempfile.NamedTemporaryFile rastgele
        # isim verir; bu Excel index ile (file_name, question_number) eşleşmesini
        # bozar). Path.stem'den de orijinal file_name çıkmalı.
        original_name = Path(file.filename or f"upload.{ft}").name
        tmp_dir = tempfile.mkdtemp(prefix="ravel_upload_")
        tmp_path = os.path.join(tmp_dir, original_name)
        with open(tmp_path, "wb") as out:
            shutil.copyfileobj(file.file, out)
        try:
            return await pipeline.ingest_question_file(
                tmp_path, ft, grade_level=grade_level, subject=subject,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)
            try:
                os.rmdir(tmp_dir)
            except OSError:
                pass

    # ─── Theory file upload ─────────────────────────────────────────
    @router.post("/upload/theory", response_model=IngestionResult)
    async def upload_theory(
        file: UploadFile = File(...),
        file_type: str = Form(...),
        grade_level: int = Form(...),
        subject: str = Form(...),
        _: dict = Depends(admin_required),
    ) -> IngestionResult:
        ft = file_type.lower()
        if ft not in ("pdf", "docx"):
            raise HTTPException(status_code=400, detail="file_type must be 'pdf' or 'docx'")
        if not (5 <= grade_level <= 8):
            raise HTTPException(status_code=400, detail="grade_level must be 5..8")
        original_name = Path(file.filename or f"upload.{ft}").name
        tmp_dir = tempfile.mkdtemp(prefix="ravel_upload_")
        tmp_path = os.path.join(tmp_dir, original_name)
        with open(tmp_path, "wb") as out:
            shutil.copyfileobj(file.file, out)
        try:
            return await pipeline.ingest_theory_file(tmp_path, ft, grade_level, subject)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
            try:
                os.rmdir(tmp_dir)
            except OSError:
                pass

    # ─── Delete + Reindex ───────────────────────────────────────────
    @router.delete("/content/{file_name}")
    async def delete_content(file_name: str, _: dict = Depends(admin_required)) -> dict:
        deleted = await qdrant.delete_by_source(file_name)
        return {"file_name": file_name, "deleted_chunks": deleted}

    # ─── LLM Config Management (Adım 7e) ───────────────────────────

    def _llm_required():
        if llm_repo is None:
            raise HTTPException(
                status_code=503,
                detail="LLM admin disabled: DB-1 client not available",
            )

    async def _invalidate_cache(agent_name: str) -> None:
        if redis_client is not None:
            try:
                await redis_client.delete(f"llm_config:{agent_name}")
            except Exception:
                logger.exception("Redis cache invalidation failed for %s", agent_name)

    @router.get("/llm/providers")
    async def list_providers(_: dict = Depends(admin_required)) -> dict:
        return {"providers": list(SUPPORTED_PROVIDERS)}

    @router.get("/llm/configs")
    async def list_configs(_: dict = Depends(admin_required)) -> dict:
        _llm_required()
        cfgs = await llm_repo.list_all()
        return {"configs": [_config_to_dict(c) for c in cfgs]}

    @router.post("/llm/config")
    async def upsert_config(
        body: LLMConfigUpsert, _: dict = Depends(admin_required),
    ) -> dict:
        _llm_required()
        _validate_config_payload(body)

        api_key_blob: Optional[bytes] = None
        if body.api_key:
            if cipher is None:
                raise HTTPException(status_code=503, detail="ENCRYPTION_KEY not configured")
            try:
                api_key_blob = cipher.encrypt(body.api_key)
            except CryptoError as e:
                raise HTTPException(status_code=500, detail=f"encrypt failed: {e}") from e

        cfg = await llm_repo.upsert(
            agent_name=body.agent_name,
            provider=body.provider,
            model_name=body.model_name,
            api_key_blob=api_key_blob,
            endpoint_url=body.endpoint_url,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
            is_active=body.is_active,
        )
        await _invalidate_cache(body.agent_name)
        # Response'ta plaintext api_key sızdırma; sadece prefix maskele
        prefix = ApiKeyCipher.mask(body.api_key, keep_prefix=4) if body.api_key else ""
        out = _config_to_dict(cfg)
        out["api_key_masked"] = prefix or out["api_key_masked"]
        return out

    @router.put("/llm/config/{agent_name}")
    async def patch_config(
        agent_name: str, body: LLMConfigPatch, _: dict = Depends(admin_required),
    ) -> dict:
        _llm_required()

        api_key_blob: Optional[bytes] = None
        if body.api_key:
            if cipher is None:
                raise HTTPException(status_code=503, detail="ENCRYPTION_KEY not configured")
            try:
                api_key_blob = cipher.encrypt(body.api_key)
            except CryptoError as e:
                raise HTTPException(status_code=500, detail=f"encrypt failed: {e}") from e

        cfg = await llm_repo.update_partial(
            agent_name,
            provider=body.provider,
            model_name=body.model_name,
            api_key_blob=api_key_blob,
            clear_api_key=body.clear_api_key,
            endpoint_url=body.endpoint_url,
            clear_endpoint=body.clear_endpoint,
            max_tokens=body.max_tokens,
            temperature=body.temperature,
            is_active=body.is_active,
        )
        if cfg is None:
            raise HTTPException(status_code=404, detail=f"agent_name={agent_name} not found")
        await _invalidate_cache(agent_name)
        return _config_to_dict(cfg)

    @router.delete("/llm/config/{agent_name}")
    async def delete_config(
        agent_name: str, _: dict = Depends(admin_required),
    ) -> dict:
        _llm_required()
        deleted = await llm_repo.delete(agent_name)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"agent_name={agent_name} not found")
        await _invalidate_cache(agent_name)
        return {"agent_name": agent_name, "deleted": True}

    @router.post("/llm/test/{agent_name}")
    async def test_config(
        agent_name: str, _: dict = Depends(admin_required),
    ) -> dict:
        _llm_required()
        cfg = await llm_repo.get_active(agent_name)
        if cfg is None:
            raise HTTPException(status_code=404, detail=f"agent_name={agent_name} not active")
        api_key: Optional[str] = None
        if cfg.api_key_blob:
            if cipher is None:
                raise HTTPException(status_code=503, detail="ENCRYPTION_KEY not configured")
            try:
                api_key = cipher.decrypt(cfg.api_key_blob)
            except CryptoError as e:
                raise HTTPException(status_code=500, detail="api_key decrypt failed") from e
        result = await test_provider(
            cfg.provider, cfg.model_name, api_key, cfg.endpoint_url,
        )
        # api_key plaintext'i hiçbir log'a / response'a sızdırma
        return {
            "agent_name": agent_name,
            "provider": cfg.provider,
            "model_name": cfg.model_name,
            "ok": result.ok,
            "latency_ms": result.latency_ms,
            "sample_text": result.sample_text,
            "error": result.error,
        }

    # ─── Stats ──────────────────────────────────────────────────────
    @router.get("/stats", response_model=CollectionStats)
    async def stats(_: dict = Depends(admin_required)) -> CollectionStats:
        info = await qdrant.get_collection_stats()
        by_type = await qdrant.count_by_payload("content_type")
        by_grade = await qdrant.count_by_payload("grade_level")
        by_file = await qdrant.count_by_payload("file_name")  # Faz 4 bar chart
        return CollectionStats(
            total_chunks=int(info["vectors_count"]),
            by_content_type=by_type,
            by_grade_level=by_grade,
            by_file_name=by_file,
            collection_name=str(info["name"]),
            vector_dim=int(info["vector_dim"]),
        )

    app.include_router(router)
    return app
