// QUESTION durumu — RAG'dan soru çek, A-E butonlarıyla göster, cevabı
// /api/answer'a yolla, doğru/yanlış geri bildirim + WS'ten gelen LLM
// açıklamasını ya da videoyu ekrana getir.
//
// Cevap sırası:
//   1) /api/question?topic=&taxonomic_level=A1 → soru + answer_key
//      (taxonomic_level cold-start sabit "A1"; Bandit zamanla seviyeyi
//       öğrenip /api/answer üzerinden kendi kararını verir, frontend bu
//       karara müdahale etmez)
//   2) Kullanıcı şıkka tıkladığında is_correct = (cevap === answer_key)
//   3) /api/answer + grade_level (sidebar override) gönderilir
//   4) Doğruysa: confetti + "+15 XP" → "Sonraki Soru" / "Modu Değiştir"
//      Yanlışsa: kırmızı feedback + WS yanıtı bekleyerek ek açıklama göster
//      (lastDelivery / lastVideo store'dan gelir).

import { motion, AnimatePresence } from "framer-motion"
import { useEffect, useRef, useState } from "react"
import confetti from "canvas-confetti"
import { fetchQuestion, submitAnswer, clearAskedSet } from "../../api/content"
import Markdown from "./Markdown"
import { useLearningStore, STATES } from "../../store/learningStore"
import { useGamificationStore } from "../../store/gamificationStore"

// Cold-start seviye — Bandit'in karar uzayında.
const COLD_START_TAX_LEVEL = "A1"

export default function QuestionCard() {
  const topic = useLearningStore((s) => s.selectedTopic)
  const grade = useLearningStore((s) => s.selectedGrade)
  const setState = useLearningStore((s) => s.setState)
  const lastDelivery = useLearningStore((s) => s.lastDelivery)
  const lastVideo = useLearningStore((s) => s.lastVideo)
  const setPendingTrace = useLearningStore((s) => s.setPendingTrace)
  const pendingTrace = useLearningStore((s) => s.pendingTrace)
  const wsStatus = useLearningStore((s) => s.wsStatus)
  const { addXP, bumpCorrect } = useGamificationStore()

  const [question, setQuestion] = useState(null)
  // exhausted: tüm sorular tamamlandı bilgisini taşır (totalAsked sayısı dahil)
  const [exhausted, setExhausted] = useState(null)
  const [phase, setPhase] = useState("loading") // loading | answering | submitted | reviewed | error | exhausted
  const [error, setError] = useState(null)
  const [picked, setPicked] = useState(null)
  const [isCorrect, setIsCorrect] = useState(null)
  const startedAt = useRef(0)

  async function load() {
    setPhase("loading")
    setError(null)
    setQuestion(null)
    setExhausted(null)
    setPicked(null)
    setIsCorrect(null)
    try {
      const q = await fetchQuestion({
        topic: topic.id,
        taxonomicLevel: COLD_START_TAX_LEVEL,
      })
      if (q && q.exhausted) {
        setExhausted({ totalAsked: q.total_asked || 0, message: q.message })
        setPhase("exhausted")
        return
      }
      setQuestion(q)
      setPhase("answering")
      startedAt.current = Date.now()
    } catch (err) {
      const status = err?.response?.status
      if (status === 404) setError("Bu konu için henüz soru yüklenmedi. Yöneticin içeriği eklediğinde burada görürsün.")
      else if (status === 504) setError("Soru servisi yavaş yanıt veriyor — tekrar dene.")
      else setError(err?.response?.data?.detail || err?.message || "Soru yüklenemedi.")
      setPhase("error")
    }
  }

  async function restartTopic() {
    try {
      await clearAskedSet({ topic: topic.id })
    } catch (err) {
      // cleanup başarısızsa load() yine boş dönmez — backend'de set yoksa
      // 200 OK ile geçer; yine de log için yakalıyoruz.
      console.warn("clearAskedSet failed, retrying load anyway", err)
    }
    await load()
  }

  // "Yeni soru" butonu — phase'e göre davranış:
  //  - answering : kullanıcı henüz cevap vermedi; onay isteyip skip event'i
  //                gönder (is_correct=false, student_answer="skipped"),
  //                sonra yeni soru yükle.
  //  - reviewed/error/exhausted : direkt load() (eski soruyu tüketildi say)
  //  - submitted/loading : disabled (UX guard)
  async function handleNewQuestion() {
    if (phase === "loading" || phase === "submitted") return
    if (phase === "answering" && question) {
      const ok = window.confirm("Bu soruyu atlamak istiyor musun?")
      if (!ok) return
      try {
        await submitAnswer({
          question_id: question.question_id,
          topic: topic.id,
          taxonomic_level: COLD_START_TAX_LEVEL,
          student_answer: "skipped",
          is_correct: false,
          time_spent: 0,
          explicit_video_request: false,
          grade_level: grade,
          question_text: question.question_text || "",
          correct_answer: (question.answer_key || "").toUpperCase(),
        })
      } catch (err) {
        console.warn("skip submitAnswer failed (continuing)", err)
      }
    }
    await load()
  }

  useEffect(() => {
    if (topic) load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topic?.id])

  async function pick(option) {
    if (phase !== "answering" || !question) return
    setPicked(option.key)
    const correct = (question.answer_key || "").toUpperCase() === option.key.toUpperCase()
    setIsCorrect(correct)
    const timeSpent = Math.round((Date.now() - startedAt.current) / 1000)
    setPhase("submitted")

    try {
      const resp = await submitAnswer({
        question_id: question.question_id,
        topic: topic.id,
        taxonomic_level: COLD_START_TAX_LEVEL,
        student_answer: option.key,
        is_correct: correct,
        time_spent: timeSpent,
        explicit_video_request: false,
        grade_level: grade,
        // LLM bağlamı için: hangi soru, hangi doğru cevap. Gateway bunları
        // student_interactions_stream payload'ına ekler; orchestrator
        // error_explanation prompt'unda {{ question_text }} +
        // {{ correct_answer }} olarak kullanır.
        question_text: question.question_text || "",
        correct_answer: (question.answer_key || "").toUpperCase(),
      })
      setPendingTrace(resp.trace_id)
      if (correct) {
        addXP(15)
        bumpCorrect()
        confetti({
          particleCount: 90, spread: 75, origin: { y: 0.7 },
          colors: ["#3B82F6", "#8B5CF6", "#F59E0B", "#10B981", "#F9FAFB"],
        })
      }
      setPhase("reviewed")
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || "Cevap gönderilemedi.")
      setPhase("error")
    }
  }

  // WS yanıtı geldiğinde (yanlış cevap için açıklama / video URL)
  // pendingTrace ile aynı ise göster.
  const matchedDelivery =
    lastDelivery && lastDelivery.trace_id === pendingTrace ? lastDelivery : null
  const matchedVideo =
    lastVideo && lastVideo.trace_id === pendingTrace ? lastVideo : null

  if (!topic) return null

  return (
    <div className="mx-auto w-full max-w-3xl">
      {/* Üst aksiyon barı — seviye seçici yok; Bandit kararı kullanır */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs uppercase tracking-widest text-ravel-muted">
          📝 Soru Çöz · {topic?.label}
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleNewQuestion}
            disabled={phase === "loading" || phase === "submitted"}
            className="rounded-lg bg-ravel-elevated/80 px-3 py-1 text-xs text-ravel-muted hover:text-ravel-text transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            ↻ Yeni soru
          </button>
          <button
            type="button"
            onClick={() => setState(STATES.MODE_SELECT)}
            className="rounded-lg bg-ravel-elevated/80 px-3 py-1 text-xs text-ravel-muted hover:text-ravel-text transition-colors"
          >
            Modu Değiştir
          </button>
        </div>
      </div>

      <div className="rounded-3xl border border-white/10 bg-ravel-surface/80 p-6 md:p-8 shadow-elevated">
        {phase === "loading" && (
          <Skeleton />
        )}

        {phase === "exhausted" && exhausted && (
          <ExhaustedScreen
            totalAsked={exhausted.totalAsked}
            onRestart={restartTopic}
            onVideo={() => setState(STATES.VIDEO)}
            onChat={() => setState(STATES.CHAT)}
          />
        )}

        {phase === "error" && (
          <div className="rounded-xl border border-ravel-red/40 bg-ravel-red/10 px-4 py-4 text-sm text-ravel-red">
            {error}
            <button
              onClick={load}
              type="button"
              className="ml-3 rounded-lg bg-ravel-red/20 px-3 py-1 text-xs text-ravel-red hover:bg-ravel-red/30"
            >
              Tekrar dene
            </button>
          </div>
        )}

        {(phase === "answering" || phase === "submitted" || phase === "reviewed") && question && (
          <>
            <h2 className="font-display text-xl md:text-2xl font-semibold leading-relaxed text-ravel-text">
              {question.question_text}
            </h2>

            <div className="mt-6 grid gap-3 sm:grid-cols-2">
              {(question.options?.length ? question.options : []).map((opt) => {
                const state =
                  picked == null
                    ? "default"
                    : picked === opt.key
                      ? isCorrect ? "correct" : "wrong"
                      : (question.answer_key || "").toUpperCase() === opt.key.toUpperCase() && phase === "reviewed"
                        ? "reveal"
                        : "default"
                return (
                  <AnswerButton
                    key={opt.key}
                    option={opt}
                    state={state}
                    disabled={phase !== "answering"}
                    onClick={() => pick(opt)}
                  />
                )
              })}
            </div>

            {/* Şık parse edilemediyse fallback */}
            {(!question.options || question.options.length === 0) && (
              <p className="mt-4 text-sm text-ravel-muted">
                Bu soruda otomatik şık ayrıştırılamadı. Cevabını sohbet
                modundan paylaşabilirsin.
              </p>
            )}
          </>
        )}

        {/* Geri bildirim */}
        <AnimatePresence>
          {phase === "reviewed" && isCorrect && (
            <motion.div
              key="correct-banner"
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="mt-6 rounded-xl border border-ravel-green/40 bg-ravel-green/10 px-4 py-3 text-sm text-ravel-green flex items-center gap-2"
            >
              <span className="text-lg">🎉</span>
              <span>Tebrikler! Doğru cevap. <strong>+15 XP</strong></span>
              <button
                onClick={load}
                type="button"
                className="ml-auto rounded-lg bg-ravel-green/20 px-3 py-1 text-xs hover:bg-ravel-green/30"
              >
                Sonraki Soru →
              </button>
            </motion.div>
          )}

          {phase === "reviewed" && isCorrect === false && (
            <motion.div
              key="wrong-banner"
              initial={{ opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="mt-6 rounded-xl border border-ravel-red/40 bg-ravel-red/10 px-4 py-3 text-sm text-ravel-red flex items-center gap-2"
            >
              <span className="font-medium">Doğru cevap: </span>
              <strong>{(question.answer_key || "?").toUpperCase()}</strong>.
              {!matchedDelivery && !matchedVideo && (
                <span className="ml-2 inline-flex items-center gap-1.5 text-ravel-muted">
                  <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-ravel-red" />
                  {wsStatus === "reconnecting" || wsStatus === "failed"
                    ? "Yeniden bağlanılıyor…"
                    : "Açıklama hazırlanıyor…"}
                </span>
              )}
              {/* Sonraki Soru: yalnızca açıklama (veya video) geldikten sonra
                  aktif. Aksi halde disabled + "Açıklama bekleniyor…" */}
              <button
                type="button"
                onClick={load}
                disabled={!matchedDelivery && !matchedVideo}
                className={[
                  "ml-auto rounded-lg px-3 py-1 text-xs transition-colors",
                  matchedDelivery || matchedVideo
                    ? "bg-ravel-blue/20 text-ravel-blue hover:bg-ravel-blue/30"
                    : "bg-ravel-elevated/60 text-ravel-muted cursor-not-allowed",
                ].join(" ")}
              >
                {matchedDelivery || matchedVideo ? "Sonraki Soru →" : "Açıklama bekleniyor…"}
              </button>
            </motion.div>
          )}
        </AnimatePresence>

        {/* WS yanıtı (yanlış cevap → text_explanation veya video) */}
        {phase === "reviewed" && matchedDelivery && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="mt-5 rounded-xl bg-ravel-elevated/70 border border-white/10 px-5 py-4"
          >
            <div className="text-xs uppercase tracking-widest text-ravel-purple mb-2">
              Öğretmen Açıklaması
            </div>
            <Markdown body={matchedDelivery.body_html} variant="card" />
          </motion.div>
        )}

        {phase === "reviewed" && matchedVideo && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="mt-5 rounded-xl bg-ravel-elevated/70 border border-white/10 px-5 py-4"
          >
            <div className="text-xs uppercase tracking-widest text-ravel-purple mb-2">
              Görsel Açıklama
            </div>
            <video
              src={matchedVideo.video_url}
              controls
              className="w-full rounded-xl"
            />
          </motion.div>
        )}
      </div>
    </div>
  )
}

function AnswerButton({ option, state, onClick, disabled }) {
  const cls = {
    default:
      "border-white/10 bg-ravel-elevated/60 hover:bg-ravel-elevated hover:border-ravel-blue/40",
    correct:
      "border-ravel-green/60 bg-ravel-green/15 text-ravel-green ring-1 ring-ravel-green/40",
    wrong:
      "border-ravel-red/60 bg-ravel-red/15 text-ravel-red ring-1 ring-ravel-red/40 animate-shake",
    reveal:
      "border-ravel-green/40 bg-ravel-green/5 text-ravel-green",
  }[state]
  return (
    <motion.button
      type="button"
      onClick={onClick}
      disabled={disabled}
      whileHover={!disabled ? { y: -2 } : undefined}
      whileTap={!disabled ? { scale: 0.98 } : undefined}
      className={[
        "rounded-2xl border px-4 py-3.5 text-left transition-all",
        "disabled:cursor-not-allowed",
        cls,
      ].join(" ")}
    >
      <span className="font-display text-sm font-semibold mr-2 opacity-70">
        {option.key.toUpperCase()})
      </span>
      <span className="text-sm">{option.text}</span>
    </motion.button>
  )
}

function ExhaustedScreen({ totalAsked, onRestart, onVideo, onChat }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="text-center py-6"
    >
      <div className="text-5xl">🎉</div>
      <h2 className="mt-3 font-display text-2xl font-semibold text-ravel-text">
        Bu konudaki tüm soruları tamamladın!
      </h2>
      <p className="mt-2 text-sm text-ravel-muted">
        {totalAsked > 0
          ? `${totalAsked} soru çözdün — harika iş çıkardın.`
          : "Harika iş çıkardın."}
      </p>

      <div className="mt-7 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <ActionTile
          icon="🔁"
          label="Konuyu tekrar çalış"
          desc="Sorular yeniden açılır"
          accent="purple"
          onClick={onRestart}
        />
        <ActionTile
          icon="🎬"
          label="Konu Öğren"
          desc="Video ile pekiştir"
          accent="blue"
          onClick={onVideo}
        />
        <ActionTile
          icon="💬"
          label="Soru-Cevap"
          desc="Öğretmenle konuş"
          accent="gold"
          onClick={onChat}
        />
      </div>
    </motion.div>
  )
}

function ActionTile({ icon, label, desc, accent, onClick }) {
  const ring = {
    purple: "hover:border-ravel-purple/60 hover:shadow-glow-purple",
    blue:   "hover:border-ravel-blue/60 hover:shadow-glow",
    gold:   "hover:border-ravel-gold/60 hover:shadow-glow-gold",
  }[accent] || "hover:border-white/30"
  return (
    <motion.button
      type="button"
      onClick={onClick}
      whileHover={{ y: -3 }}
      whileTap={{ scale: 0.98 }}
      className={[
        "rounded-2xl border border-white/10 bg-ravel-elevated/60 px-4 py-5",
        "text-left transition-all", ring,
      ].join(" ")}
    >
      <div className="text-2xl">{icon}</div>
      <p className="mt-2 font-display text-sm font-semibold text-ravel-text">
        {label}
      </p>
      <p className="mt-0.5 text-xs text-ravel-muted">{desc}</p>
    </motion.button>
  )
}

function Skeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-6 rounded bg-ravel-elevated/80 w-3/4" />
      <div className="h-4 rounded bg-ravel-elevated/60 w-2/3" />
      <div className="grid grid-cols-2 gap-3 mt-6">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-14 rounded-2xl bg-ravel-elevated/60" />
        ))}
      </div>
    </div>
  )
}

