// VIDEO durumu — "Konu Öğren". Backend'e explicit_video_request=true ile
// /api/answer atılır, Bandit kararı + Manim render sürecinden sonra
// content_type=video WS mesajı gelir, video oynatılır.
//
// "Konu öğren" placeholder soru içermediği için /api/answer payload'ında
// question_id, student_answer ve is_correct alanlarını "intro" değerleriyle
// dolduruyoruz; orchestrator video kararı zaten Bandit'ten gelen gerçek
// karara göre Manim akışını tetikleyecek.

import { motion, AnimatePresence } from "framer-motion"
import { useEffect, useRef, useState } from "react"
import { submitAnswer } from "../../api/content"
import { useLearningStore, STATES } from "../../store/learningStore"
import Markdown from "./Markdown"

export default function VideoCard() {
  const topic = useLearningStore((s) => s.selectedTopic)
  const grade = useLearningStore((s) => s.selectedGrade)
  const setState = useLearningStore((s) => s.setState)
  const lastVideo = useLearningStore((s) => s.lastVideo)
  const lastDelivery = useLearningStore((s) => s.lastDelivery)
  const setPendingTrace = useLearningStore((s) => s.setPendingTrace)
  const pendingTrace = useLearningStore((s) => s.pendingTrace)

  const [phase, setPhase] = useState("idle") // idle | requested | rendering | ready | fallback | error
  const [error, setError] = useState(null)
  const [elapsed, setElapsed] = useState(0)
  const tickRef = useRef(null)

  async function requestVideo() {
    setPhase("requested")
    setError(null)
    setElapsed(0)
    try {
      const resp = await submitAnswer({
        // workflow.py event.payload.question_id.startswith("intro") bypass'a
        // uyumlu olması için sade "intro" gönderiyoruz. Önceki "intro_${id}"
        // formatı strict equality'de bypass'a uymuyordu.
        question_id: "intro",
        topic: topic.id,
        taxonomic_level: "A2",
        student_answer: "intro",
        is_correct: false,
        time_spent: 0,
        explicit_video_request: true,
        grade_level: grade,
      })
      setPendingTrace(resp.trace_id)
      setPhase("rendering")
      tickRef.current = setInterval(() => setElapsed((s) => s + 1), 1000)
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || "Video isteği gönderilemedi.")
      setPhase("error")
    }
  }

  useEffect(() => {
    return () => { if (tickRef.current) clearInterval(tickRef.current) }
  }, [])

  // WS'ten video geldiğinde
  useEffect(() => {
    if (phase === "rendering" && lastVideo && lastVideo.trace_id === pendingTrace) {
      if (tickRef.current) clearInterval(tickRef.current)
      setPhase("ready")
    }
  }, [lastVideo, pendingTrace, phase])

  // DLQ fallback (Manim Worker 3 deneme sonrası başarısız → text delivery)
  useEffect(() => {
    if (phase === "rendering" && lastDelivery && lastDelivery.trace_id === pendingTrace) {
      if (tickRef.current) clearInterval(tickRef.current)
      setPhase("fallback")
    }
  }, [lastDelivery, pendingTrace, phase])

  if (!topic) return null

  return (
    <div className="mx-auto w-full max-w-3xl">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-widest text-ravel-muted">
            🎬 Konu Öğren
          </p>
          <h2 className="font-display text-2xl font-semibold text-ravel-text">
            {topic.label}
          </h2>
        </div>
        <button
          type="button"
          onClick={() => setState(STATES.MODE_SELECT)}
          className="rounded-lg bg-ravel-elevated/80 px-3 py-1.5 text-xs text-ravel-muted hover:text-ravel-text"
        >
          Modu Değiştir
        </button>
      </div>

      <div className="rounded-3xl border border-white/10 bg-ravel-surface/80 p-6 md:p-8 shadow-elevated">
        {phase === "idle" && (
          <Intro topicLabel={topic.label} onStart={requestVideo} />
        )}

        {(phase === "requested" || phase === "rendering") && (
          <Rendering elapsed={elapsed} />
        )}

        {phase === "ready" && lastVideo && (
          <Player video={lastVideo} onContinue={() => setState(STATES.MODE_SELECT)} />
        )}

        {phase === "fallback" && lastDelivery && (
          <Fallback body={lastDelivery.body_html} onContinue={() => setState(STATES.MODE_SELECT)} />
        )}

        {phase === "error" && (
          <div className="rounded-xl border border-ravel-red/40 bg-ravel-red/10 px-4 py-3 text-sm text-ravel-red">
            {error}
            <button
              type="button"
              onClick={requestVideo}
              className="ml-3 rounded-lg bg-ravel-red/20 px-3 py-1 text-xs hover:bg-ravel-red/30"
            >
              Tekrar dene
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

function Intro({ topicLabel, onStart }) {
  return (
    <div className="text-center py-6">
      <div className="text-6xl">🎬</div>
      <h3 className="mt-4 font-display text-xl font-semibold text-ravel-text">
        "{topicLabel}" için kısa bir video hazırlayalım
      </h3>
      <p className="mt-2 max-w-lg mx-auto text-sm text-ravel-muted">
        Konuyu görselleştiren 25-40 saniyelik bir Manim animasyonu. Hazırlanması
        bir dakika kadar sürebilir; bittiğinde burada otomatik açılacak.
      </p>
      <button
        type="button"
        onClick={onStart}
        className="mt-7 rounded-xl bg-ravel-purple px-6 py-3 font-medium text-white hover:bg-ravel-purple/90 hover:shadow-glow-purple transition-all"
      >
        Videoyu Hazırla
      </button>
    </div>
  )
}

function Rendering({ elapsed }) {
  const dotsCount = (elapsed % 3) + 1
  return (
    <div className="text-center py-10">
      <motion.div
        className="mx-auto h-16 w-16 rounded-full border-2 border-ravel-purple border-t-transparent"
        animate={{ rotate: 360 }}
        transition={{ duration: 1.4, repeat: Infinity, ease: "linear" }}
      />
      <p className="mt-6 font-display text-lg text-ravel-text">
        Video hazırlanıyor{".".repeat(dotsCount)}
      </p>
      <p className="mt-1 text-xs text-ravel-muted tabular-nums">
        Geçen süre: {elapsed} sn · ortalama 30-60 sn sürer
      </p>
    </div>
  )
}

function Player({ video, onContinue }) {
  return (
    <AnimatePresence>
      <motion.div
        key="player"
        initial={{ opacity: 0, scale: 0.97 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.3 }}
      >
        <video
          src={video.video_url}
          controls
          autoPlay
          className="w-full rounded-2xl bg-black"
          style={{ maxHeight: "60vh" }}
        />
        <div className="mt-3 flex items-center justify-between text-xs text-ravel-muted">
          <span className="tabular-nums">
            {Math.round(video.duration_seconds || 0)} sn ·{" "}
            {Math.round((video.file_size_bytes || 0) / 1024)} KB
          </span>
          <a
            href={video.video_url}
            download
            className="rounded-lg bg-ravel-elevated/80 px-3 py-1 text-ravel-muted hover:text-ravel-text"
          >
            ⬇ İndir
          </a>
        </div>
        <div className="mt-5 flex gap-2">
          <button
            type="button"
            onClick={onContinue}
            className="flex-1 rounded-xl bg-ravel-blue py-3 font-medium text-white hover:bg-ravel-blue/90 hover:shadow-glow transition-all"
          >
            Anladım, Devam Et
          </button>
        </div>
      </motion.div>
    </AnimatePresence>
  )
}

function Fallback({ body, onContinue }) {
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-ravel-gold/40 bg-ravel-gold/10 px-4 py-3 text-sm text-ravel-gold">
        Video şu an hazırlanamadı; metin açıklamayla devam edelim.
      </div>
      <Markdown body={body} variant="card" />
      <button
        type="button"
        onClick={onContinue}
        className="rounded-xl bg-ravel-blue px-5 py-2.5 font-medium text-white hover:bg-ravel-blue/90"
      >
        Devam Et
      </button>
    </div>
  )
}
