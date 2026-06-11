import asyncio
import json
import logging
import random
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import httpx

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware

from .auth import create_access_token, decode_access_token, hash_password, verify_password
from .config import Settings, get_settings
from .db1_io import DB1Client
from .db2_io import DB2ReadClient
from .kafka_io import KafkaConsumer, KafkaProducer, ensure_topics
from .question_parser import parse_question_chunk
from .redis_io import RedisIO
from .schemas import (
    AnswerRequest,
    ChatAck,
    ChatRequest,
    GamificationProfile,
    LoginRequest,
    LoginResponse,
    ProfileResponse,
    QuestionExhaustedResponse,
    QuestionResponse,
    RegisterRequest,
    RegisterResponse,
)
from .websocket_manager import ConnectionManager

logger = logging.getLogger("api_gateway")

settings = get_settings()
redis_io = RedisIO(settings.redis_url)
producer = KafkaProducer(settings.kafka_bootstrap_servers)
manager = ConnectionManager()

# Adım 8a/8j — DB clients (lifespan tarafından başlatılır)
db1: Optional[DB1Client] = DB1Client(settings.db1_dsn) if settings.db1_dsn else None
db2: Optional[DB2ReadClient] = DB2ReadClient(settings.db2_dsn) if settings.db2_dsn else None

PRODUCED_TOPICS = [settings.topic_student_interactions, settings.topic_session_lifecycle]
CONSUMED_TOPICS = [settings.topic_content_delivery, settings.topic_video_ready]

consumer = KafkaConsumer(
    settings.kafka_bootstrap_servers,
    CONSUMED_TOPICS,
    group_id="api_gateway",
)

# Adım 8j — content_retrieval_responses dinleyicisi (ayrı consumer group;
# orchestrator-responses ile çakışmaz). RAG bir soru chunk'ı döndürdüğünde
# correlation_id eşleşince GET /api/question'ın bekleyen future'unu çözer.
question_responses_consumer = KafkaConsumer(
    settings.kafka_bootstrap_servers,
    [settings.topic_content_retrieval_responses],
    group_id="api_gateway-questions",
)


class PendingFutureRegistry:
    """correlation_id → asyncio.Future. Orchestrator pattern'inin Gateway kopyası."""

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    async def register(self, correlation_id: str) -> asyncio.Future:
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        async with self._lock:
            self._pending[correlation_id] = future
        return future

    async def deliver(self, correlation_id: str, response: dict) -> None:
        async with self._lock:
            future = self._pending.pop(correlation_id, None)
        if future is None:
            return
        if not future.done():
            future.set_result(response)

    async def cancel(self, correlation_id: str) -> None:
        async with self._lock:
            self._pending.pop(correlation_id, None)


question_registry = PendingFutureRegistry()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_trace_id() -> str:
    return f"trace_{uuid.uuid4().hex[:12]}"


def _new_event_id() -> str:
    return f"e_{uuid.uuid4().hex}"


def _extract_target_student(msg: dict) -> str | None:
    """Downstream messages may put student_id at the top level or inside payload."""
    return msg.get("student_id") or (msg.get("payload") or {}).get("student_id")


async def consumer_handler(topic: str, msg: dict) -> None:
    student_id = _extract_target_student(msg)
    if not student_id:
        logger.warning("dropping %s message without student_id", topic)
        return
    sent = await manager.send_to(student_id, msg)
    if sent:
        return
    # Student offline (or owned by another Gateway instance — fan-out TODO).
    # Persist for up to N seconds; will be drained on next WebSocket connect.
    await redis_io.push_pending(student_id, json.dumps(msg), settings.pending_message_ttl_seconds)
    logger.info("queued pending %s message for %s", topic, student_id)


async def question_response_handler(topic: str, msg: dict) -> None:
    corr = msg.get("correlation_id")
    if not corr:
        return
    await question_registry.deliver(corr, msg)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("api_gateway starting")

    await ensure_topics(
        settings.kafka_bootstrap_servers,
        PRODUCED_TOPICS + CONSUMED_TOPICS + [
            settings.topic_content_retrieval_requests,
            settings.topic_content_retrieval_responses,
        ],
        num_partitions=settings.kafka_topic_partitions,
        replication_factor=settings.kafka_topic_replication,
    )
    await redis_io.start()
    await producer.start()
    await consumer.start(consumer_handler)
    await question_responses_consumer.start(question_response_handler)

    if db1 is not None:
        try:
            await db1.start()
            logger.info("DB-1 client connected (auth + profile)")
        except Exception:
            logger.exception("DB-1 connect failed; auth endpoints will 503")
    if db2 is not None:
        try:
            await db2.start()
            logger.info("DB-2 read client connected (gamification)")
        except Exception:
            logger.exception("DB-2 connect failed; gamification will return zeros")

    logger.info("api_gateway ready")
    yield

    logger.info("api_gateway shutting down")
    await consumer.stop()
    await question_responses_consumer.stop()
    await producer.stop()
    if db2 is not None:
        await db2.stop()
    if db1 is not None:
        await db1.stop()
    await redis_io.stop()


app = FastAPI(title="RAVEL API Gateway", lifespan=lifespan)

# Adım 8j — CORS: dev frontend (Vite, port 5173) ve prod nginx (port 8080).
_origins = [o.strip() for o in (settings.frontend_origin or "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Trace-Id"],
)


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-Id") or _new_trace_id()
    request.state.trace_id = trace_id
    response = await call_next(request)
    response.headers["X-Trace-Id"] = trace_id
    return response


def get_current_student(
    authorization: str = Header(...),
    settings: Settings = Depends(get_settings),
) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="invalid Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return decode_access_token(token, settings)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e


# ────────────────────────── HTTP endpoints ──────────────────────────


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest, settings: Settings = Depends(get_settings)) -> LoginResponse:
    """İki mod (Adım 8a):
      a) username + password → DB lookup, bcrypt verify, role/display_name JWT'ye gömülür
      b) grade_level only    → legacy anonim akış (test scriptleri + Adım 2a)
    """
    if req.username and req.password:
        if db1 is None:
            raise HTTPException(status_code=503, detail="auth db unavailable")
        user = await db1.get_user_by_username(req.username)
        if user is None or not verify_password(req.password, user["password_hash"] or ""):
            # Same error for unknown user vs wrong password (don't leak existence).
            raise HTTPException(status_code=401, detail="invalid credentials")
        student_id = user["student_id"]
        grade_level = user["grade_level"]
        token = create_access_token(
            student_id, grade_level, settings,
            role=user["role"], username=user["username"],
            display_name=user["display_name"],
        )
        return LoginResponse(
            access_token=token,
            expires_in=settings.jwt_expiration_seconds,
            student_id=uuid.UUID(student_id),
            role=user["role"] or "student",
            display_name=user["display_name"],
        )

    # Legacy path: anonymous student / admin token via role param
    if req.grade_level is None:
        raise HTTPException(status_code=400, detail="grade_level required for anonymous login")
    student_id = str(req.student_id) if req.student_id else str(uuid.uuid4())
    token = create_access_token(
        student_id, req.grade_level, settings, role=req.role,
    )
    return LoginResponse(
        access_token=token,
        expires_in=settings.jwt_expiration_seconds,
        student_id=uuid.UUID(student_id),
        role=req.role or "student",
    )


@app.post("/auth/register", response_model=RegisterResponse)
async def register(
    req: RegisterRequest,
    payload: dict = Depends(get_current_student),
) -> RegisterResponse:
    """Admin-only — yeni öğrenci hesabı oluşturur."""
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    if db1 is None:
        raise HTTPException(status_code=503, detail="auth db unavailable")
    pw_hash = hash_password(req.password)
    created = await db1.create_user(
        username=req.username,
        password_hash=pw_hash,
        grade_level=req.grade_level,
        display_name=req.display_name,
        role=req.role,
    )
    if created is None:
        raise HTTPException(status_code=409, detail=f"username already exists: {req.username}")
    return RegisterResponse(
        student_id=uuid.UUID(created["student_id"]),
        username=req.username,
        role=req.role,
    )


@app.get("/auth/me", response_model=ProfileResponse)
async def auth_me(payload: dict = Depends(get_current_student)) -> ProfileResponse:
    """JWT'den profil. DB-1'de hesap varsa fresh çek, yoksa JWT'den döndür."""
    student_id = payload["sub"]
    if db1 is not None:
        prof = await db1.get_profile(student_id)
        if prof is not None:
            return ProfileResponse(
                student_id=uuid.UUID(prof["student_id"]),
                username=prof["username"],
                role=prof["role"],
                grade_level=prof["grade_level"],
                display_name=prof["display_name"],
            )
    # Anonim öğrenci — JWT'den oluştur.
    return ProfileResponse(
        student_id=uuid.UUID(student_id),
        username=payload.get("username"),
        role=payload.get("role", "student"),
        grade_level=payload["grade_level"],
        display_name=payload.get("display_name"),
    )


@app.get("/auth/verify")
async def verify(payload: dict = Depends(get_current_student)) -> dict:
    return {
        "valid": True,
        "student_id": payload["sub"],
        "grade_level": payload["grade_level"],
        "role": payload.get("role", "student"),
        "exp": payload["exp"],
    }


@app.post("/auth/logout")
async def logout(payload: dict = Depends(get_current_student)) -> dict:
    """Stateless JWT — token client tarafından silinir.
    Sunucu tarafı: Redis session entry'sini drop et."""
    await redis_io.delete_session(payload["sub"])
    return {"status": "ok"}


@app.get("/api/profile", response_model=GamificationProfile)
async def api_profile(payload: dict = Depends(get_current_student)) -> GamificationProfile:
    """ProfileResponse + XP/streak/today_correct (DB-2'den derive)."""
    student_id = payload["sub"]
    base: dict
    if db1 is not None:
        prof = await db1.get_profile(student_id)
        base = prof or {}
    else:
        base = {}
    grade_level = base.get("grade_level") or payload["grade_level"]
    role = base.get("role") or payload.get("role", "student")
    username = base.get("username") or payload.get("username")
    display_name = base.get("display_name") or payload.get("display_name")

    stats = {"xp": 0, "streak": 0, "today_correct": 0,
             "correct_total": 0, "total_attempts": 0, "success_rate": 0.0}
    if db2 is not None:
        # Redis cache (gstats:<sid>, 30s) — öğrenci aktif çözerken
        # güncel görür; 5000 paralel öğrencide DB sorgusu ~30x azalır.
        cache_key = f"gstats:{student_id}"
        cached = None
        try:
            raw = await redis_io.client.get(cache_key)
            if raw:
                cached = json.loads(raw)
        except Exception:
            logger.warning("gstats cache get failed", exc_info=True)
        if cached:
            stats = cached
        else:
            try:
                stats = await db2.gamification_stats(student_id)
                try:
                    await redis_io.client.set(cache_key, json.dumps(stats), ex=30)
                except Exception:
                    logger.warning("gstats cache set failed", exc_info=True)
            except Exception:
                logger.exception("[%s] gamification_stats failed; returning zeros", student_id)

    return GamificationProfile(
        student_id=uuid.UUID(student_id),
        username=username,
        role=role,
        grade_level=grade_level,
        display_name=display_name,
        **stats,
    )


def _question_id_from_metadata(md: dict, fallback_topic: str) -> str:
    return "_".join([
        str(md.get("file_name") or fallback_topic),
        str(md.get("question_number") or md.get("test_no") or "q"),
    ])


@app.get("/api/stats")
async def api_stats(
    payload: dict = Depends(get_current_student),
) -> dict:
    """RAG /admin/stats proxy — öğrenci token'ıyla erişilebilir.

    RAG `/admin/stats` admin role JWT bekliyor. Frontend'in TopicGrid'i
    kilitli konuları belirlemek için aynı veriye ihtiyaç duyuyor (hangi
    file_name'lerde chunk var). Gateway server-side admin JWT mint edip
    RAG'a forwardlar; öğrenci token'ından admin yetkisi sızdırılmaz."""
    student_id = payload["sub"]
    grade_level = int(payload.get("grade_level") or 6)
    admin_jwt = create_access_token(
        student_id=student_id, grade_level=grade_level,
        settings=settings, role="admin",
    )
    url = f"{settings.rag_internal_url}/admin/stats"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url, headers={"Authorization": f"Bearer {admin_jwt}"})
        if r.status_code != 200:
            logger.warning("rag /admin/stats returned %d: %s", r.status_code, r.text[:200])
            raise HTTPException(status_code=r.status_code, detail="rag stats unavailable")
        return r.json()
    except httpx.RequestError as e:
        logger.exception("rag /admin/stats request failed: %s", e)
        raise HTTPException(status_code=503, detail="rag service unreachable")


@app.get("/api/question")
async def api_question(
    topic: str,
    taxonomic_level: str,
    request: Request,
    payload: dict = Depends(get_current_student),
):
    """RAG'a content_retrieval_request gönder, top_k chunk arasından
    daha önce sorulmamış olanlardan rastgele birini döndür.

    asked-set Redis'te (öğrenci, konu) bazında tutulur; aynı oturumda
    tekrar gelmesin. Tüm aday'lar daha önce sorulmuşsa endpoint
    QuestionExhaustedResponse döner (HTTP 200, exhausted=true) —
    frontend tek contract'ta parse etsin. Asked-set'i temizlemek için
    DELETE /api/question/asked endpoint'i kullanılır.

    Dönüş tipleri:
      QuestionResponse           → exhausted=false (varsayılan)
      QuestionExhaustedResponse  → exhausted=true
    """
    correlation_id = f"qreq_{uuid.uuid4().hex[:12]}"
    trace_id = request.state.trace_id
    student_id = payload["sub"]

    future = await question_registry.register(correlation_id)
    req_payload = {
        "correlation_id": correlation_id,
        "trace_id": trace_id,
        "student_id": student_id,
        "query": {
            "subject": topic,
            "taxonomic_level": taxonomic_level,
            "content_type": "question",
            "context": "Frontend question request",
        },
        "top_k": settings.question_top_k,
        "timestamp": _now_iso(),
    }
    await producer.send(
        settings.topic_content_retrieval_requests,
        req_payload,
        key=student_id,
    )

    try:
        resp = await asyncio.wait_for(
            future, timeout=settings.question_request_timeout_seconds,
        )
    except asyncio.TimeoutError:
        await question_registry.cancel(correlation_id)
        raise HTTPException(status_code=504, detail="RAG timeout")

    chunks = resp.get("chunks") or []
    if not chunks:
        raise HTTPException(status_code=404, detail="no question available for topic")

    asked = await redis_io.get_asked(student_id, topic)
    fresh: list[tuple[str, dict]] = []
    for c in chunks:
        parsed = parse_question_chunk(c.get("text", ""), c.get("metadata") or {})
        qid = _question_id_from_metadata(parsed["metadata"], topic)
        if qid not in asked:
            fresh.append((qid, parsed))

    if not fresh:
        # asked-set chunk havuzunu kapsıyor — öğrenciye "tamamladın"
        # ekranı göstermek için exhausted yanıtı dön. Set'i otomatik
        # temizleme; kullanıcı "Konuyu tekrar çalış" derse DELETE
        # endpoint'iyle reset eder.
        logger.info(
            "asked-set exhausted for student=%s topic=%s total=%d — returning exhausted",
            student_id, topic, len(asked),
        )
        return QuestionExhaustedResponse(
            topic=topic,
            taxonomic_level=taxonomic_level,
            total_asked=len(asked),
        )

    chosen_qid, chosen_parsed = random.choice(fresh)
    await redis_io.add_asked(
        student_id, topic, chosen_qid, settings.asked_questions_ttl_seconds,
    )

    md = chosen_parsed["metadata"]
    return QuestionResponse(
        question_id=chosen_qid,
        topic=topic,
        taxonomic_level=taxonomic_level,
        question_text=chosen_parsed["question_text"],
        options=chosen_parsed["options"],
        answer_key=chosen_parsed["answer_key"],
        metadata=md,
        exhausted=False,
    )


@app.delete("/api/question/asked")
async def api_clear_asked(
    topic: str,
    payload: dict = Depends(get_current_student),
) -> dict:
    """Öğrencinin (topic) asked-set'ini sıfırla — 'Konuyu tekrar çalış'
    butonu için. Bundan sonraki /api/question çağrıları tüm chunk
    havuzundan seçim yapmaya yeniden başlar."""
    student_id = payload["sub"]
    await redis_io.clear_asked(student_id, topic)
    logger.info("asked-set cleared by student=%s topic=%s", student_id, topic)
    return {"status": "cleared", "topic": topic}


@app.post("/api/chat", response_model=ChatAck)
async def api_chat(
    req: ChatRequest,
    request: Request,
    payload: dict = Depends(get_current_student),
) -> ChatAck:
    """qa_dialog için Kafka event üret. Yanıt WebSocket üzerinden gelir.

    Sokratik diyalog için chat geçmişini Redis'te tutuyoruz (1 saat TTL,
    her turn 2 mesaj — son 10 turn). Önce kullanıcı mesajını append et,
    sonra geçmişi event payload'una göm: orchestrator qa_dialog promptuna
    multi-turn bağlam aktarır."""
    student_id = payload["sub"]
    trace_id = request.state.trace_id
    grade_level = req.grade_level if req.grade_level is not None else payload["grade_level"]
    topic = req.topic or ""

    await redis_io.append_chat_history(student_id, topic, "user", req.message)
    history = await redis_io.get_chat_history(student_id, topic)

    event = {
        "event_id": _new_event_id(),
        "trace_id": trace_id,
        "student_id": student_id,
        "grade_level": grade_level,
        "event_type": "chat_message",
        "payload": {
            "message": req.message,
            "topic": topic,
            "taxonomic_level": req.taxonomic_level or "",
            "question_id": "qa_dialog",
            "student_answer": req.message,
            "is_correct": False,
            "time_spent": 0,
            "explicit_video_request": False,
            "question_text": "",
            "correct_answer": "",
            "conversation_history": history,
        },
        "timestamp": _now_iso(),
    }
    await producer.send(settings.topic_student_interactions, event, key=student_id)
    return ChatAck(status="accepted", trace_id=trace_id, message=req.message)


# ── Chat history yardımcı endpoint'leri (qa_dialog Sokratik diyalog) ──
# Frontend WS hook assistant cevabı geldiğinde bunu çağırarak history'ye
# ekler (Orchestrator'dan Gateway'e callback yerine pragmatik fire-and-forget).
# Topic değişince DELETE ile temizlenir.

@app.post("/api/chat/history")
async def api_chat_history_append(
    req: dict,
    payload: dict = Depends(get_current_student),
) -> dict:
    student_id = payload["sub"]
    role = (req.get("role") or "").strip()
    if role not in ("user", "assistant"):
        raise HTTPException(status_code=400, detail="role must be user|assistant")
    message = (req.get("message") or "")[:4000]
    topic = (req.get("topic") or "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="topic required")
    await redis_io.append_chat_history(student_id, topic, role, message)
    return {"status": "ok"}


@app.delete("/api/chat/history")
async def api_chat_history_clear(
    topic: str,
    payload: dict = Depends(get_current_student),
) -> dict:
    student_id = payload["sub"]
    await redis_io.clear_chat_history(student_id, topic)
    return {"status": "cleared", "topic": topic}


@app.post("/api/answer")
async def submit_answer(
    req: AnswerRequest,
    request: Request,
    payload: dict = Depends(get_current_student),
) -> dict:
    student_id = payload["sub"]
    trace_id = request.state.trace_id
    # Adım 8: per-request grade_level override (sidebar aktif sınıfı). JWT
    # default'u "kayıt sınıfı" placeholder; öğrenci farklı bir sınıftan
    # konu çözüyorsa onu yansıt.
    grade_level = req.grade_level if req.grade_level is not None else payload["grade_level"]
    event = {
        "event_id": _new_event_id(),
        "trace_id": trace_id,
        "student_id": student_id,
        "grade_level": grade_level,
        "event_type": "question_answered",
        "payload": req.model_dump(),
        "timestamp": _now_iso(),
    }
    await producer.send(settings.topic_student_interactions, event, key=student_id)
    return {"status": "accepted", "trace_id": trace_id, "event_id": event["event_id"]}


# ────────────────────────── WebSocket ──────────────────────────


@app.websocket("/ws/{student_id}")
async def websocket_endpoint(websocket: WebSocket, student_id: str) -> None:
    # Browsers don't allow custom headers on the WebSocket handshake, so
    # the JWT comes in as a query parameter: /ws/{student_id}?token=...
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008, reason="missing token")
        return
    try:
        payload = decode_access_token(token, settings)
    except ValueError:
        await websocket.close(code=1008, reason="invalid token")
        return
    if payload["sub"] != student_id:
        await websocket.close(code=1008, reason="token student mismatch")
        return

    await websocket.accept()
    await manager.connect(student_id, websocket)

    await redis_io.set_session(
        student_id,
        {
            "student_id": student_id,
            "grade_level": payload["grade_level"],
            "connected_at": _now_iso(),
        },
        settings.session_ttl_seconds,
    )

    # Replay any messages that arrived while the student was offline.
    for raw in await redis_io.drain_pending(student_id):
        try:
            await websocket.send_text(raw)
        except Exception:
            logger.exception("failed to replay pending msg for %s", student_id)
            break

    await producer.send(
        settings.topic_session_lifecycle,
        {
            "event_id": _new_event_id(),
            "trace_id": _new_trace_id(),
            "student_id": student_id,
            "event_type": "session_started",
            "timestamp": _now_iso(),
        },
        key=student_id,
    )

    try:
        while True:
            # We don't yet expose any client→server WS commands; just keep
            # the socket alive. receive_text raises WebSocketDisconnect on close.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(student_id, websocket)
        await redis_io.delete_session(student_id)
        try:
            await producer.send(
                settings.topic_session_lifecycle,
                {
                    "event_id": _new_event_id(),
                    "trace_id": _new_trace_id(),
                    "student_id": student_id,
                    "event_type": "session_ended",
                    "timestamp": _now_iso(),
                },
                key=student_id,
            )
        except Exception:
            logger.exception("failed to emit session_ended for %s", student_id)
