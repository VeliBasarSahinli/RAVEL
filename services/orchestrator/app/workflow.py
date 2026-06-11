"""Orchestrator workflow — sistemin beyni (Step 4 versiyonu).

Step 3'te Default-to-Text override hard-coded'di. Step 4'te:
  - bandit_decision_requests'e karar isteği atılır
  - bandit_decision_responses'tan yanıt beklenir (200 ms timeout)
  - timeout veya hata → Default-to-Text fallback
  - Önceki interaction'ın reward'ı hesaplanıp Bandit Learner'a yollanır
  - Yeni interaction "pending" olarak Redis'te bırakılır

CLAUDE.md context vector kuralı (x_1..x_12) `_build_context_vector`'da.
Şimdilik öğrencinin geçmişi (DB-2 sorguları) henüz hesaplanmadığından
çoğu boyut placeholder; Adım 5+'da DB-2 üzerinden gerçek değerler
gelecek.
"""
import asyncio
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from .circuit_breaker import CircuitOpenError, RAGCircuitBreaker
from .config import Settings
from .db_io import DB1Client
from .db2_io import DB2ReadClient, StudentTopicStats
from .kafka_io import KafkaProducer
from .llm_client import LLMClient
from .llm_gateway import LLMError, MOCK_MANIM_CODE, MOCK_RESPONSE
from .prompt_engine import PromptEngine
from .redis_io import RedisIO
from .schemas import (
    BanditDecisionPayload,
    BanditDecisionRequest,
    BanditDecisionResponse,
    ContentDeliveryMessage,
    ContentRetrievalQuery,
    ContentRetrievalRequest,
    ContentRetrievalResponse,
    ManimRenderTask,
    QACorrectionRequest,
    RewardLogPayload,
    StudentInteractionEvent,
)

logger = logging.getLogger(__name__)

ACTION_NAMES = ["text", "step_by_step", "video"]
ACTION_INDEX = {name: i for i, name in enumerate(ACTION_NAMES)}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _now_epoch() -> float:
    return time.time()


# Markdown code fence ve önek metin regex'leri.
# LLM'ler Manim kodunu sıkça ```python ... ``` ile sarıyor; bazen "İşte kod:" gibi
# açıklayıcı önek de ekliyor. AST parse line 1'de fence görürse syntax error.
_CODE_FENCE_OPEN_RE = re.compile(r"^\s*```(?:python|py)?\s*\n", re.IGNORECASE)
_CODE_FENCE_CLOSE_RE = re.compile(r"\n```\s*$")
_CODE_LINE_PREFIX = ("from ", "import ", "class ", "def ", "@", "#", "if __name__")


def _strip_code_fence(text: str) -> str:
    """LLM'in döndürdüğü Manim kodunu sandbox-uygun hale getir.

    Adımlar:
      1. Trim baş/son boşluk
      2. Açılış ```python (veya ```py / ```) fence'ini at
      3. Kapanış ``` fence'ini at
      4. Önekteki açıklayıcı metni at — ilk Python kodu satırına kadar
         (from/import/class/def/@dekoratör/# yorumu/__name__ kontrolü)
    """
    if not text:
        return text
    s = text.strip()

    s = _CODE_FENCE_OPEN_RE.sub("", s, count=1)
    s = _CODE_FENCE_CLOSE_RE.sub("", s)
    s = s.strip()

    lines = s.splitlines()
    code_start = 0
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if not stripped:
            continue
        if stripped.startswith(_CODE_LINE_PREFIX):
            code_start = i
            break
    else:
        code_start = 0
    if code_start > 0:
        s = "\n".join(lines[code_start:])
    return s.strip()


# ─── Generic Kafka request-response registry ────────────────────────

class PendingResponseRegistry:
    """correlation_id → asyncio.Future. Used for both RAG and Bandit."""

    def __init__(self, name: str) -> None:
        self.name = name
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
            logger.warning("[%s] response with unknown correlation_id=%s",
                           self.name, correlation_id)
            return
        if not future.done():
            future.set_result(response)

    async def cancel(self, correlation_id: str) -> None:
        async with self._lock:
            self._pending.pop(correlation_id, None)


# ─── Workflow ──────────────────────────────────────────────────────

class OrchestrationWorkflow:
    def __init__(
        self,
        settings: Settings,
        db: DB1Client,
        redis_io: RedisIO,
        producer: KafkaProducer,
        llm: LLMClient,
        breaker: RAGCircuitBreaker,
        rag_registry: PendingResponseRegistry,
        bandit_registry: PendingResponseRegistry,
        prompt_engine: Optional[PromptEngine] = None,
        db2: Optional[DB2ReadClient] = None,
    ):
        self.settings = settings
        self.db = db
        self.redis_io = redis_io
        self.producer = producer
        self.llm = llm                                    # legacy LLMClient — fallback
        self.breaker = breaker
        self.rag_registry = rag_registry
        self.bandit_registry = bandit_registry
        # Adım 7: lifespan tarafından attach edilir.
        self.llm_gateway = None  # type: ignore[assignment]
        self.prompt_engine = prompt_engine
        self.db2 = db2                                    # opsiyonel DB-2 read client

    # ─── Public entry point ─────────────────────────────────────────

    async def process_interaction(self, event: StudentInteractionEvent) -> None:
        trace_id = event.trace_id
        student_id = event.student_id

        logger.info(
            "[%s] processing student=%s topic=%s correct=%s",
            trace_id, student_id, event.payload.topic, event.payload.is_correct,
        )

        # 1) Profil — yoksa cold-start upsert
        profile = await self.db.get_student_profile(student_id)
        if profile is None:
            await self.db.upsert_student(student_id, event.grade_level)
            profile = {"grade_level": event.grade_level, "learning_style_vector": [0.5, 0.5]}
            logger.info("[%s] cold-start: created student profile", trace_id)

        # ── TOPIC_INTRO bypass (Adım 8 frontend "Konu Anlatımı" akışı) ──
        # question_id "intro" prefix'iyle başlıyorsa → kullanıcı kasıtlı
        # konu tanıtımı istedi. Defansif startswith: önceki client'lar
        # "intro_<topic>" gibi suffix'li göndermiş olabilir.
        if event.payload.question_id.startswith("intro"):
            await self._handle_topic_intro(event, profile)
            return

        # ── QA_DIALOG bypass (Adım 8 frontend Sokratik sohbet akışı) ──
        # Gateway /api/chat → question_id="qa_dialog". Bandit/reward atla,
        # RAG'dan theory + qa_dialog promptu + LLM ile Sokratik yanıt üret.
        if event.payload.question_id.startswith("qa_dialog"):
            await self._handle_qa_dialog(event, profile)
            return

        # 2) Önceki interaction varsa, reward'ı hesaplayıp Learner'a yolla
        await self._maybe_emit_reward(event)

        # 3) Bandit'e karar isteği — context vector ile
        context = self._build_context_vector(profile, event)
        decision = await self._get_bandit_decision(student_id, trace_id, context)
        action_idx = ACTION_INDEX.get(decision.intervention_type, 0)

        # 4) RAG isteği + yanıt bekleme (Step 5 ile zenginleştirildi:
        #    Bandit kararına göre content_type belirlenir — text/step_by_step
        #    için "question", video için "theory")
        rag_content_type = "theory" if decision.intervention_type == "video" else "question"
        rag_text = await self._retrieve_or_fallback(
            event, trace_id, student_id, profile, rag_content_type,
        )

        # 5) Karar branch'ı — video ise Manim akışını tetikle, dön.
        #    video_ready_events Gateway'e ayrı bir Kafka mesajıdır;
        #    bu fonksiyon orada bitmez (Manim Worker async), text delivery
        #    YAPILMAZ (kullanıcıya ya video ya da DLQ fallback'i gelecek).
        if decision.intervention_type == "video":
            await self._dispatch_manim_render(
                trace_id=trace_id,
                student_id=student_id,
                rag_text=rag_text,
                profile=profile,
                event=event,
            )
            await self._save_pending(event, action_idx, context)
            return

        # 6) Text/step_by_step yolu — LLM Gateway üzerinden (Adım 7d)
        body = await self._generate_text_intervention(
            event=event, profile=profile, decision=decision, rag_text=rag_text,
        )

        # 7) Delivery
        delivery = ContentDeliveryMessage(
            trace_id=trace_id,
            student_id=student_id,
            content_type="text_explanation",
            body_html=body,
            next_action="wait_for_student",
            timestamp=_now_iso(),
        )
        await self.producer.send(
            self.settings.topic_content_delivery,
            delivery.model_dump(),
            key=student_id,
        )
        logger.info("[%s] delivered text intervention to %s (action=%s, conf=%.3f)",
                    trace_id, student_id, decision.intervention_type, decision.confidence_score)

        # 8) Yeni pending — bir sonraki event'te bu reward'ı hesaplayacağız
        await self._save_pending(event, action_idx, context)

    # ─── Step 4 helpers ──────────────────────────────────────────────

    def _build_context_vector(self, profile: dict, event: StudentInteractionEvent) -> list[float]:
        """CLAUDE.md x_t (12-dim). Çoğu alan placeholder — Adım 5+'da
        DB-2 sorgularından gerçek değerler gelecek.
        """
        grade_level = float(profile.get("grade_level", event.grade_level))
        lsv = profile.get("learning_style_vector", [0.5, 0.5])
        if len(lsv) < 2:
            lsv = [0.5, 0.5]
        return [
            grade_level / 8.0,                                         # x1: normalized grade
            float(lsv[0]),                                             # x2: visual weight
            float(lsv[1]),                                             # x3: verbal weight
            1.0,                                                       # x4: success rate (placeholder)
            0.0,                                                       # x5: consecutive errors (placeholder)
            0.0,                                                       # x6: video completion rate
            0.0,                                                       # x7: time z-score
            0.0,                                                       # x8: stress index
            1.0 if event.payload.explicit_video_request else 0.0,      # x9: explicit video request
            0.0,                                                       # x10: prev action history
            0.5,                                                       # x11: global topic difficulty
            0.0,                                                       # x12: cognitive fatigue
        ]

    async def _get_bandit_decision(
        self,
        student_id: str,
        trace_id: str,
        context: list[float],
    ) -> BanditDecisionPayload:
        """Bandit'e karar sor. Timeout'ta Default-to-Text fallback."""
        correlation_id = f"bdt_{uuid.uuid4().hex[:12]}"
        future = await self.bandit_registry.register(correlation_id)
        req = BanditDecisionRequest(
            correlation_id=correlation_id,
            trace_id=trace_id,
            student_id=student_id,
            context_vector=context,
        )
        await self.producer.send(
            self.settings.topic_bandit_decision_requests,
            req.model_dump(),
            key=student_id,
        )

        try:
            timeout = self.settings.bandit_request_timeout_ms / 1000.0
            raw = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            await self.bandit_registry.cancel(correlation_id)
            logger.warning("[%s] Bandit timeout — Default-to-Text fallback", trace_id)
            return BanditDecisionPayload(
                intervention_type="text",
                difficulty_adjustment="B1",
                confidence_score=0.0,
            )
        except Exception:
            await self.bandit_registry.cancel(correlation_id)
            logger.exception("[%s] Bandit request failed — Default-to-Text fallback", trace_id)
            return BanditDecisionPayload(
                intervention_type="text",
                difficulty_adjustment="B1",
                confidence_score=0.0,
            )

        try:
            response = BanditDecisionResponse(**raw)
            return response.decision
        except Exception:
            logger.exception("[%s] Bandit response invalid — fallback", trace_id)
            return BanditDecisionPayload(
                intervention_type="text",
                difficulty_adjustment="B1",
                confidence_score=0.0,
            )

    async def _save_pending(
        self,
        event: StudentInteractionEvent,
        action_idx: int,
        context: list[float],
    ) -> None:
        """Bir sonraki event'te reward hesaplamak için bağlamı sakla."""
        await self.redis_io.set_pending_interaction(
            event.student_id,
            {
                "trace_id": event.trace_id,
                "correlation_id": f"rew_{uuid.uuid4().hex[:12]}",
                "context_vector": context,
                "action_taken": action_idx,
                "topic_id": event.payload.topic,
                "taxonomic_level": event.payload.taxonomic_level,
                "t_baseline": self.settings.bandit_t_baseline_seconds,
                "started_at": _now_epoch(),
            },
            ttl=self.settings.pending_interaction_ttl_seconds,
        )

    async def _maybe_emit_reward(self, event: StudentInteractionEvent) -> None:
        """Önceki interaction varsa reward hesaplayıp Learner'a yolla."""
        prev = await self.redis_io.pop_pending_interaction(event.student_id)
        if prev is None:
            return

        # T_actual: önceki event'in cevap üretildiği andan şimdiye kadar.
        # Pratikte: pending'in started_at'ten şu ana kadarki saniyeler.
        t_actual = max(_now_epoch() - float(prev.get("started_at", _now_epoch())), 0.0)
        # C_t: yeni event'in is_correct'i, önceki müdahalenin başarısını ölçüyor.
        c_t = 1.0 if event.payload.is_correct else -1.0
        # S_t: anket yok, neutral
        s_t = 0.0

        reward_log = RewardLogPayload(
            correlation_id=prev.get("correlation_id", f"rew_{uuid.uuid4().hex[:12]}"),
            trace_id=prev.get("trace_id", event.trace_id),
            student_id=event.student_id,
            context_vector=list(prev.get("context_vector", [0.5] * 12)),
            action_taken=int(prev.get("action_taken", 0)),
            c_t=c_t,
            t_baseline=float(prev.get("t_baseline", self.settings.bandit_t_baseline_seconds)),
            t_actual=t_actual,
            s_t=s_t,
            topic_id=str(prev.get("topic_id", event.payload.topic)),
            taxonomic_level=str(prev.get("taxonomic_level", event.payload.taxonomic_level)),
            is_correct=event.payload.is_correct,
            frustration_index=0.0,
            timestamp=_now_iso(),
        )
        await self.producer.send(
            self.settings.topic_reward_logs,
            reward_log.model_dump(),
            key=event.student_id,
        )
        logger.info(
            "[%s] reward emitted (prev_action=%s, c_t=%+.1f, t_actual=%.1fs)",
            event.trace_id, ACTION_NAMES[reward_log.action_taken], c_t, t_actual,
        )

    # ─── Adım 8: TOPIC_INTRO bypass ────────────────────────────────

    async def _handle_topic_intro(
        self,
        event: StudentInteractionEvent,
        profile: dict,
    ) -> None:
        """Frontend'den question_id='intro' (prefix) geldi: Bandit/reward atla.

        Sub-akışlar:
          - explicit_video_request=True → "Videoyu Hazırla" butonu →
            _dispatch_manim_render(forced=True) ile video pipeline'ı.
          - Aksi → topic_teaching modunda LLM metni + content_delivery.

        Bu özel akış pending_interaction yazmaz; öğrencinin gerçek soru
        çözümleri zinciri bozulmaz.
        """
        trace_id = event.trace_id
        student_id = event.student_id

        # ── Explicit video isteği → deterministik render (Bandit'siz) ──
        if event.payload.explicit_video_request:
            # RAG theory için video kontekstini de besleyebilmek için aynı
            # retrieve helper'ı; başarısızsa boş string ile devam.
            try:
                rag_text = await self._retrieve_or_fallback(
                    event, trace_id, student_id, profile, rag_content_type="theory",
                )
            except Exception:
                logger.exception("[%s] forced video RAG failed — empty rag", trace_id)
                rag_text = ""
            await self._dispatch_manim_render(
                trace_id=trace_id, student_id=student_id, rag_text=rag_text,
                profile=profile, event=event, forced=True,
            )
            return

        # RAG: theory content'i ara (yoksa fallback)
        rag_text = await self._retrieve_or_fallback(
            event, trace_id, student_id, profile, rag_content_type="theory",
        )

        # Sahte bir text decision — _generate_text_intervention prompt
        # mode'unu seçerken question_id=='intro' override'ı topic_teaching
        # döndürecek (bkz. _pick_text_mode).
        decision = BanditDecisionPayload(
            intervention_type="text",
            difficulty_adjustment="A1",
            confidence_score=1.0,
        )
        body = await self._generate_text_intervention(
            event=event, profile=profile, decision=decision, rag_text=rag_text,
        )

        delivery = ContentDeliveryMessage(
            trace_id=trace_id,
            student_id=student_id,
            content_type="text_explanation",
            body_html=body,
            next_action="wait_for_student",
            timestamp=_now_iso(),
        )
        await self.producer.send(
            self.settings.topic_content_delivery,
            delivery.model_dump(),
            key=student_id,
        )
        logger.info(
            "[%s] TOPIC_INTRO delivered (topic=%s len=%d)",
            trace_id, event.payload.topic, len(body),
        )

    async def _handle_qa_dialog(
        self,
        event: StudentInteractionEvent,
        profile: dict,
    ) -> None:
        """Frontend /api/chat (question_id='qa_dialog'): Sokratik diyalog.
        Bandit/reward atla; RAG theory + qa_dialog.yaml prompt + LLM."""
        trace_id = event.trace_id
        student_id = event.student_id
        student_message = event.payload.student_answer or ""

        # RAG theory — topic boş veya RAG erişilemezse boş string fallback
        rag_text = ""
        if event.payload.topic:
            try:
                rag_text = await self._retrieve_or_fallback(
                    event, trace_id, student_id, profile,
                    rag_content_type="theory",
                )
            except Exception:
                logger.exception("[%s] qa_dialog RAG failed — empty fallback", trace_id)

        # Conversation history Gateway tarafından Redis'te tutuluyor;
        # event.payload.conversation_history list[dict] olarak geliyor.
        # Prompt'a okunabilir Türkçe diyalog formatında render ediyoruz.
        # Boşsa (ilk mesaj) sadece son mesajı koyuyoruz — eski davranış.
        history_lines = []
        for h in (event.payload.conversation_history or []):
            role = h.get("role", "user")
            content = (h.get("content") or "").strip()
            if not content:
                continue
            label = "Öğrenci" if role == "user" else "Öğretmen"
            history_lines.append(f"{label}: {content}")
        history_text = "\n".join(history_lines) if history_lines else student_message

        body = MOCK_RESPONSE
        if self.llm_gateway is not None and self.prompt_engine is not None:
            ctx = {
                "grade_level": event.grade_level,
                "subject": event.payload.topic or "",
                "taxonomic_level": event.payload.taxonomic_level or "A1",
                "frustration_index": float(profile.get("frustration_index", 0.0)),
                "conversation_history": history_text,
                "student_message": student_message,
                "rag_content": rag_text,
            }
            try:
                pair = self.prompt_engine.render("qa_dialog", ctx)
                body = await self.llm_gateway.generate(
                    "orchestrator_text", pair.system_prompt, pair.user_prompt,
                )
                logger.info(
                    "[%s] qa_dialog LLM ok: topic=%s msg_len=%d resp_len=%d",
                    trace_id, event.payload.topic, len(student_message), len(body),
                )
            except LLMError as e:
                logger.warning("[%s] qa_dialog LLM failed (%s) — mock fallback", trace_id, e)
            except Exception:
                logger.exception("[%s] qa_dialog prompt/gateway error — mock fallback", trace_id)

        delivery = ContentDeliveryMessage(
            trace_id=trace_id,
            student_id=student_id,
            content_type="text_explanation",
            body_html=body,
            context="chat",  # frontend useWebSocket hook chatHistory'ye append eder
            next_action="wait_for_student",
            timestamp=_now_iso(),
        )
        await self.producer.send(
            self.settings.topic_content_delivery,
            delivery.model_dump(),
            key=student_id,
        )
        logger.info(
            "[%s] QA_DIALOG delivered (topic=%s len=%d)",
            trace_id, event.payload.topic, len(body),
        )

    # ─── Adım 6: Manim akışı ────────────────────────────────────────

    async def _dispatch_manim_render(
        self,
        trace_id: str,
        student_id: str,
        rag_text: str,
        profile: dict,
        event: StudentInteractionEvent,
        forced: bool = False,
    ) -> None:
        """Manim render dispatch.

        Normal yolda Bandit 'video' kararı verince çağrılır. `forced=True`
        durumunda kullanıcı explicit_video_request gönderdi (TOPIC_INTRO
        Videoyu Hazırla); Bandit kararı bypass'lanmış olur. Her iki yolda
        da kod üretimi + Kafka send pipeline'ı aynı.
        """
        video_purpose = "intro" if forced else "explanation"
        manim_code = await self._generate_manim_code(
            event=event, profile=profile, rag_text=rag_text, video_purpose=video_purpose,
        )
        task_id = f"mtask_{uuid.uuid4().hex[:12]}"
        correlation_id = f"mrt_{uuid.uuid4().hex[:12]}"

        task = ManimRenderTask(
            task_id=task_id,
            correlation_id=correlation_id,
            trace_id=trace_id,
            student_id=student_id,
            manim_code=manim_code,
            render_quality=self.settings.manim_video_quality,           # type: ignore[arg-type]
            timeout_seconds=self.settings.manim_render_timeout_seconds,
            attempt_number=1,
        )
        await self.producer.send(
            self.settings.topic_manim_render_tasks,
            task.model_dump(),
            key=student_id,
        )
        logger.info(
            "[%s] manim render dispatched: task=%s attempt=1 quality=%s forced=%s",
            trace_id, task_id, self.settings.manim_video_quality, forced,
        )

    async def handle_qa_correction(self, raw: dict) -> None:
        """qa_correction_loop'tan gelen mesajı işle.

        Akış:
          - error_type'ı logla
          - LLM Gateway 'orchestrator_correction' ajanına düzeltme attır
            (Adım 7d). Gateway başarısız olursa eski mock'a düş.
          - attempt_number+1 ile manim_render_tasks'a yeniden yaz.
            Manim Worker max_retries kontrolünü kendisi yapıyor (>=3'te DLQ).
        """
        try:
            qa = QACorrectionRequest(**raw)
        except Exception:
            logger.exception("invalid QACorrectionRequest payload: %s", raw)
            return

        logger.info(
            "[%s] QA correction received: task=%s attempt=%d type=%s msg=%s",
            qa.trace_id, qa.task_id, qa.attempt_number, qa.error_type,
            (qa.error_message or "")[:200],
        )

        new_code = await self._correct_manim_code(
            prev_code=qa.manim_code,
            error_type=qa.error_type,
            error_message=qa.error_message or "",
        )

        next_attempt = qa.attempt_number + 1
        retry = ManimRenderTask(
            task_id=qa.task_id,
            correlation_id=qa.correlation_id,
            trace_id=qa.trace_id,
            student_id=qa.student_id,
            manim_code=new_code,
            render_quality=self.settings.manim_video_quality,           # type: ignore[arg-type]
            timeout_seconds=self.settings.manim_render_timeout_seconds,
            attempt_number=next_attempt,
        )
        await self.producer.send(
            self.settings.topic_manim_render_tasks,
            retry.model_dump(),
            key=qa.student_id,
        )
        logger.info(
            "[%s] manim retry dispatched: task=%s attempt=%d (after %s)",
            qa.trace_id, qa.task_id, next_attempt, qa.error_type,
        )

    async def handle_dlq(self, raw: dict) -> None:
        """dead_letter_queue_ravel'i tüket — fallback metin teslimi.

        3 deneme tükendi, video üretilemedi. Kullanıcıya boşluk bırakmamak
        için anlık metin yanıt göndeririz (CLAUDE.md fallback ilkesi).
        """
        student_id = raw.get("student_id")
        trace_id = raw.get("trace_id", "trace_unknown")
        if not student_id:
            logger.warning("DLQ message without student_id: %s", raw)
            return

        logger.error(
            "[%s] DLQ fallback: source=%s reason=%s last=%s",
            trace_id,
            raw.get("source_topic"),
            raw.get("reason"),
            raw.get("last_error_type"),
        )

        delivery = ContentDeliveryMessage(
            trace_id=trace_id,
            student_id=str(student_id),
            content_type="text_explanation",
            body_html=(
                "Video şu an hazırlanamadı, sana metin açıklamayla devam edelim. "
                "[DLQ FALLBACK — Adım 7'de gerçek LLM ile bu metin zenginleşecek]"
            ),
            next_action="wait_for_student",
            timestamp=_now_iso(),
        )
        await self.producer.send(
            self.settings.topic_content_delivery,
            delivery.model_dump(),
            key=str(student_id),
        )
        logger.info("[%s] DLQ fallback text delivered to %s", trace_id, student_id)

    # ─── Step 3 RAG path (değişmedi) ────────────────────────────────

    async def _retrieve_or_fallback(
        self,
        event: StudentInteractionEvent,
        trace_id: str,
        student_id: str,
        profile: dict,
        rag_content_type: str = "question",
    ) -> str:
        correlation_id = f"rag_{uuid.uuid4().hex[:12]}"

        async def _do() -> ContentRetrievalResponse:
            future = await self.rag_registry.register(correlation_id)
            # Step 5b: grade_level artık RAG isteğinde gönderilmiyor; filter
            # taxonomic_level + subject üzerinden yapılır (ADR-015 son notu).
            req = ContentRetrievalRequest(
                correlation_id=correlation_id,
                trace_id=trace_id,
                student_id=student_id,
                query=ContentRetrievalQuery(
                    subject=event.payload.topic,
                    taxonomic_level=event.payload.taxonomic_level,
                    content_type=rag_content_type,
                    context=(
                        f"Öğrenci '{event.payload.student_answer}' yanıtını verdi "
                        f"({'doğru' if event.payload.is_correct else 'yanlış'})."
                    ),
                ),
                top_k=self.settings.rag_top_k,
                timestamp=_now_iso(),
            )
            await self.producer.send(
                self.settings.topic_content_retrieval_requests,
                req.model_dump(),
                key=student_id,
            )
            try:
                raw = await asyncio.wait_for(future, timeout=self.settings.rag_request_timeout_seconds)
            except asyncio.TimeoutError:
                await self.rag_registry.cancel(correlation_id)
                raise
            return ContentRetrievalResponse(**raw)

        try:
            response = await self.breaker.call(_do)
            chunks_text = "\n\n".join(c.text for c in response.chunks) or self.breaker.fallback_text
            logger.info("[%s] RAG returned %d chunks", trace_id, len(response.chunks))
            return chunks_text
        except (asyncio.TimeoutError, CircuitOpenError) as e:
            logger.warning("[%s] RAG unavailable (%s) — using fallback", trace_id, type(e).__name__)
            return self.breaker.fallback_text
        except Exception:
            logger.exception("[%s] RAG call failed — using fallback", trace_id)
            return self.breaker.fallback_text

    # ─── Adım 7d: LLM Gateway integration ───────────────────────────

    @staticmethod
    def _learning_style_text(profile: dict) -> str:
        """Profil [vis, verbal] vector'ünden insan-okunur etiket çıkar."""
        lsv = profile.get("learning_style_vector") or [0.5, 0.5]
        try:
            vis, verb = float(lsv[0]), float(lsv[1])
        except Exception:
            return "dengeli"
        if vis - verb >= 0.2:
            return "görsel"
        if verb - vis >= 0.2:
            return "sözel"
        return "dengeli"

    @staticmethod
    def _compute_frustration(consec_err: int, time_spent: int, t_baseline: float) -> float:
        """Heuristik: ardışık hata + zaman aşımı → 0.0–1.0 stres skoru.

        Adım 8'de gerçek bir scorer (anket + dwell-time) gelinceye kadar
        bu basit doğrusal kombinasyon prompt'taki "duygusal zeka" kurallarını
        besler.
        """
        f = 0.0
        if consec_err >= 3:
            f += 0.4
        elif consec_err >= 2:
            f += 0.25
        elif consec_err >= 1:
            f += 0.10
        if t_baseline > 0:
            ratio = time_spent / t_baseline
            if ratio >= 2.0:
                f += 0.30
            elif ratio >= 1.5:
                f += 0.15
        return min(round(f, 2), 1.0)

    async def _student_topic_stats(self, student_id: str, topic_id: str) -> StudentTopicStats:
        """DB-2 down ise (0,0) — workflow yine de çalışır."""
        if self.db2 is None:
            return StudentTopicStats(consecutive_errors=0, success_rate=0.0)
        try:
            return await self.db2.stats(student_id, topic_id)
        except Exception:
            logger.exception("DB-2 stats failed; using zero defaults")
            return StudentTopicStats(consecutive_errors=0, success_rate=0.0)

    def _pick_text_mode(
        self,
        decision: BanditDecisionPayload,
        event: StudentInteractionEvent,
    ) -> str:
        # Frontend "Konuyu Öğret" akışı: question_id "intro" prefix'iyle gelir.
        # Bu bir hata değil, konu açılışı — error_explanation yerine
        # topic_teaching modu kullan.
        if event.payload.question_id.startswith("intro"):
            return "topic_teaching"
        if decision.intervention_type == "step_by_step":
            return "step_by_step"
        # text → genelde yanlışta error_explanation, doğruda topic_teaching
        return "error_explanation" if not event.payload.is_correct else "topic_teaching"

    async def _build_pedagogy_context(
        self,
        event: StudentInteractionEvent,
        profile: dict,
        rag_text: str,
    ) -> dict:
        stats = await self._student_topic_stats(event.student_id, event.payload.topic)
        frustration = self._compute_frustration(
            stats.consecutive_errors,
            event.payload.time_spent,
            self.settings.bandit_t_baseline_seconds,
        )
        return {
            "grade_level": profile.get("grade_level", event.grade_level),
            "subject": event.payload.topic,
            "taxonomic_level": event.payload.taxonomic_level,
            "consecutive_errors": stats.consecutive_errors,
            "success_rate": round(stats.success_rate, 2),
            "learning_style": self._learning_style_text(profile),
            "frustration_index": frustration,
            # Gateway artık /api/answer body'sinde question_text + correct_answer
            # taşıyor (Düzeltme 1). Yoksa eski client'lar için id'ye düşeriz —
            # bu durumda LLM yine RAG content'ine güvenir; ancak normal akışta
            # gerçek metin gelir ve prompt {{ question_text }} ile değiştirilir.
            "question_text": event.payload.question_text or event.payload.question_id,
            "student_answer": event.payload.student_answer,
            # Hem answer_key (mevcut prompt) hem correct_answer (yeni isim) —
            # prompt template her iki adla referans alabilsin.
            "answer_key": event.payload.correct_answer or "",
            "correct_answer": event.payload.correct_answer or "",
            "rag_content": rag_text or "",
        }

    async def _generate_text_intervention(
        self,
        event: StudentInteractionEvent,
        profile: dict,
        decision: BanditDecisionPayload,
        rag_text: str,
    ) -> str:
        """Gateway + prompt_engine ile pedagojik metin üret. Hata → mock fallback."""
        if self.llm_gateway is None or self.prompt_engine is None:
            # 7'den önceki path — geri dönüş garantisi
            return await self.llm.generate_text_intervention({
                "profile": profile,
                "event": event.payload.model_dump(),
                "rag": rag_text,
                "decision": decision.model_dump(),
            })

        mode = self._pick_text_mode(decision, event)
        ctx = await self._build_pedagogy_context(event, profile, rag_text)
        try:
            pair = self.prompt_engine.render(mode, ctx)
        except Exception:
            logger.exception("[%s] prompt render failed for mode=%s", event.trace_id, mode)
            return MOCK_RESPONSE

        try:
            text = await self.llm_gateway.generate(
                "orchestrator_text", pair.system_prompt, pair.user_prompt,
            )
            logger.info(
                "[%s] LLM text intervention: mode=%s frustration=%.2f cons_err=%d len=%d",
                event.trace_id, mode, ctx["frustration_index"],
                ctx["consecutive_errors"], len(text),
            )
            return text
        except LLMError as e:
            logger.warning("[%s] LLMGateway text failed (%s) — fallback", event.trace_id, e)
            return MOCK_RESPONSE

    async def _generate_manim_code(
        self,
        event: StudentInteractionEvent,
        profile: dict,
        rag_text: str,
        video_purpose: str = "explanation",
    ) -> str:
        if self.llm_gateway is None or self.prompt_engine is None:
            return await self.llm.generate_manim_code({
                "profile": profile,
                "event": event.payload.model_dump(),
                "rag": rag_text,
            })

        ctx = {
            "grade_level": profile.get("grade_level", event.grade_level),
            "subject": event.payload.topic,
            "taxonomic_level": event.payload.taxonomic_level,
            "video_purpose": video_purpose,
            "learning_style": self._learning_style_text(profile),
            "rag_content": rag_text or "",
        }
        try:
            pair = self.prompt_engine.render("manim_code", ctx)
            raw = await self.llm_gateway.generate(
                "orchestrator_manim", pair.system_prompt, pair.user_prompt,
            )
            code = _strip_code_fence(raw)
            logger.info(
                "[%s] LLM manim code generated raw_len=%d clean_len=%d",
                event.trace_id, len(raw), len(code),
            )
            return code
        except LLMError as e:
            logger.warning("[%s] LLMGateway manim failed (%s) — mock fallback", event.trace_id, e)
            return MOCK_MANIM_CODE
        except Exception:
            logger.exception("[%s] manim prompt/gateway error — mock fallback", event.trace_id)
            return MOCK_MANIM_CODE

    async def _correct_manim_code(
        self,
        prev_code: str,
        error_type: str,
        error_message: str,
    ) -> str:
        if self.llm_gateway is None or self.prompt_engine is None:
            return await self.llm.correct_manim_code(prev_code, error_context={
                "error_type": error_type,
                "error_message": error_message,
            })
        try:
            pair = self.prompt_engine.render(
                "manim_correction",
                {"manim_code": prev_code, "error_type": error_type, "error_message": error_message},
            )
            raw = await self.llm_gateway.generate(
                "orchestrator_correction", pair.system_prompt, pair.user_prompt,
            )
            return _strip_code_fence(raw)
        except LLMError as e:
            logger.warning("manim correction LLMGateway failed (%s) — mock fallback", e)
            return MOCK_MANIM_CODE
        except Exception:
            logger.exception("manim correction error — mock fallback")
            return MOCK_MANIM_CODE
