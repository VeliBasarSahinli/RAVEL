// TOPIC_INTRO — konu seçildiğinde LLM'den metin tanıtımı çek + göster.
//
// Akış:
//   1) Mount olunca /api/answer'a question_id="intro", is_correct=false,
//      explicit_video_request=false ile event yolla.
//   2) WS'ten gelen content_type=text_explanation mesajı pendingTrace
//      ile eşleşince yanıtı göster.
//   3) Backend Orchestrator workflow.py: question_id == "intro" görürse
//      mode = "topic_teaching" zorlanır → spec'teki konu anlatımı tonu.

import { motion, AnimatePresence } from "framer-motion"
import { useEffect, useState } from "react"
import { submitAnswer } from "../../api/content"
import { useLearningStore, STATES } from "../../store/learningStore"
import Markdown from "./Markdown"

export default function TopicIntro() {
  const topic = useLearningStore((s) => s.selectedTopic)
  const grade = useLearningStore((s) => s.selectedGrade)
  const setState = useLearningStore((s) => s.setState)
  const backToTopicList = useLearningStore((s) => s.backToTopicList)
  const lastDelivery = useLearningStore((s) => s.lastDelivery)
  const setPendingTrace = useLearningStore((s) => s.setPendingTrace)
  const pendingTrace = useLearningStore((s) => s.pendingTrace)

  const [phase, setPhase] = useState("requesting") // requesting | streaming | ready | error
  const [error, setError] = useState(null)
  const [traceId, setTraceId] = useState(null)

  useEffect(() => {
    if (!topic) return
    let cancelled = false
    async function run() {
      setPhase("requesting")
      setError(null)
      setTraceId(null)
      try {
        const resp = await submitAnswer({
          question_id: "intro",
          topic: topic.id,
          taxonomic_level: "A1",          // cold-start; Bandit zaten kararı kendi verecek
          student_answer: "",
          is_correct: false,
          time_spent: 0,
          explicit_video_request: false,
          grade_level: grade,
        })
        if (cancelled) return
        setTraceId(resp.trace_id)
        setPendingTrace(resp.trace_id)
        setPhase("streaming")
      } catch (err) {
        if (cancelled) return
        setError(err?.response?.data?.detail || err?.message || "Konu tanıtımı istenemedi.")
        setPhase("error")
      }
    }
    run()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topic?.id, grade])

  // WS yanıtı geldiğinde
  useEffect(() => {
    if (phase === "streaming" && lastDelivery && lastDelivery.trace_id === traceId) {
      setPhase("ready")
    }
  }, [lastDelivery, traceId, phase])

  if (!topic) return null

  const matchedDelivery =
    lastDelivery && lastDelivery.trace_id === traceId ? lastDelivery : null

  return (
    <div className="mx-auto w-full max-w-3xl">
      <div className="mb-3 flex items-center justify-between">
        <button
          type="button"
          onClick={backToTopicList}
          className="text-xs uppercase tracking-widest text-ravel-muted hover:text-ravel-text"
        >
          ← Konu listesine dön
        </button>
      </div>

      <div className="rounded-3xl border border-white/10 bg-ravel-surface/80 p-7 md:p-9 shadow-elevated">
        <div className="flex items-start gap-4">
          <span
            aria-hidden
            className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-ravel-elevated text-3xl"
          >
            {topic.icon}
          </span>
          <div>
            <p className="text-xs uppercase tracking-widest text-ravel-muted">
              Konu Tanıtımı · {grade}. sınıf
            </p>
            <h2 className="mt-1 font-display text-3xl font-semibold text-ravel-text">
              {topic.label}
            </h2>
          </div>
        </div>

        <div className="mt-7">
          <AnimatePresence mode="wait">
            {(phase === "requesting" || phase === "streaming") && (
              <motion.div
                key="loading"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="space-y-3"
              >
                <ShimmerLine width="92%" />
                <ShimmerLine width="80%" />
                <ShimmerLine width="88%" />
                <ShimmerLine width="60%" />
                <p className="mt-4 inline-flex items-center gap-2 text-xs text-ravel-muted animate-pulse-soft">
                  <span className="inline-block h-1.5 w-1.5 rounded-full bg-ravel-purple" />
                  Öğretmen konuyu hazırlıyor…
                </p>
              </motion.div>
            )}

            {phase === "ready" && matchedDelivery && (
              <motion.div
                key="ready"
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
              >
                <Markdown body={matchedDelivery.body_html} variant="intro" />
              </motion.div>
            )}

            {phase === "error" && (
              <motion.div
                key="err"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="rounded-xl border border-ravel-red/40 bg-ravel-red/10 px-4 py-3 text-sm text-ravel-red"
              >
                {error}
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {phase === "ready" && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="mt-8 flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between"
          >
            <button
              type="button"
              onClick={backToTopicList}
              className="text-sm text-ravel-muted hover:text-ravel-text"
            >
              Başka bir konu seçeyim
            </button>
            <button
              type="button"
              onClick={() => setState(STATES.MODE_SELECT)}
              className="rounded-xl bg-ravel-blue px-6 py-3 font-medium text-white hover:bg-ravel-blue/90 hover:shadow-glow transition-all"
            >
              Hazırım, Başlayalım! →
            </button>
          </motion.div>
        )}
      </div>
    </div>
  )
}

function ShimmerLine({ width = "100%" }) {
  return (
    <div
      style={{ width }}
      className="h-3 rounded bg-gradient-to-r from-ravel-elevated via-white/10 to-ravel-elevated bg-[length:200%_100%] animate-shimmer"
    />
  )
}

