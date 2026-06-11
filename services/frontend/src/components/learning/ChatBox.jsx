// CHAT durumu — Sokratik diyalog. Kullanıcı yazar → /api/chat → backend
// student_interactions_stream'e event yazar → Orchestrator qa_dialog modunda
// LLM yanıtı üretir → content_delivery_stream → WS → useWebSocket hook
// (msg.context === "chat") otomatik chatHistory'ye append eder.
//
// Bu bileşen kendi yedek mantığını taşımıyor (önceki sürümde useEffect ile
// pendingTrace eşleştirip ekliyordu; protokol-driven yaklaşımla artık tek
// source of truth = useWebSocket hook).

import { motion, AnimatePresence } from "framer-motion"
import { useEffect, useRef, useState } from "react"
import { sendChatMessage } from "../../api/content"
import Markdown from "./Markdown"
import { useLearningStore, STATES } from "../../store/learningStore"

export default function ChatBox() {
  const topic = useLearningStore((s) => s.selectedTopic)
  const setState = useLearningStore((s) => s.setState)
  const setPendingTrace = useLearningStore((s) => s.setPendingTrace)
  const chatHistory = useLearningStore((s) => s.chatHistory)
  const appendChat = useLearningStore((s) => s.appendChat)

  const [text, setText] = useState("")
  const [error, setError] = useState(null)
  const scrollRef = useRef(null)

  // Typing indicator: son mesaj user ise henüz assistant yanıtı gelmemiş demektir.
  const lastMsg = chatHistory[chatHistory.length - 1]
  const waitingForReply = lastMsg && lastMsg.role === "user"

  // Yeni mesajda otomatik scroll
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [chatHistory.length, waitingForReply])

  async function send(e) {
    e?.preventDefault()
    const message = text.trim()
    if (!message || waitingForReply) return
    setText("")
    setError(null)
    appendChat({ role: "user", content: message, ts: Date.now() })
    try {
      // topic?.id mutlaka dolu olmalı — Backend qa_dialog handler'ı RAG
      // theory aramasını topic üzerinden yapar; boş topic = boş RAG
      // bağlamı = jenerik LLM yanıtı.
      const resp = await sendChatMessage({
        message,
        topic: topic?.id,
        taxonomicLevel: "B1",
      })
      setPendingTrace(resp.trace_id)
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || "Mesaj gönderilemedi.")
    }
  }

  function onKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className="mx-auto flex h-[calc(100vh-9rem)] w-full max-w-3xl flex-col">
      <div className="flex items-center justify-between mb-3">
        <div>
          <p className="text-xs uppercase tracking-widest text-ravel-muted">
            💬 Soru-Cevap
          </p>
          <h2 className="font-display text-2xl font-semibold text-ravel-text">
            {topic?.label || "Öğretmenle Konuş"}
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

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto rounded-3xl border border-white/10 bg-ravel-surface/60 p-5 space-y-3"
      >
        {chatHistory.length === 0 && !waitingForReply && (
          <EmptyState topic={topic} />
        )}

        <AnimatePresence initial={false}>
          {chatHistory.map((m, i) => (
            <Bubble key={`${m.ts}-${i}`} message={m} />
          ))}
          {waitingForReply && (
            <motion.div
              key="typing"
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="flex justify-start"
            >
              <div className="rounded-2xl rounded-tl-md bg-ravel-purple/15 border border-ravel-purple/30 px-4 py-3">
                <TypingDots />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {error && (
        <div className="mt-3 rounded-xl border border-ravel-red/40 bg-ravel-red/10 px-3 py-2 text-sm text-ravel-red">
          {error}
        </div>
      )}

      <form onSubmit={send} className="mt-3 flex gap-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          placeholder={
            topic
              ? `${topic.label} hakkında bir şey sor…`
              : "Aklındakini yaz…"
          }
          disabled={waitingForReply}
          className="flex-1 resize-none rounded-2xl border border-white/10 bg-ravel-elevated/80 px-4 py-3 text-sm text-ravel-text placeholder:text-ravel-muted/60 focus:outline-none focus:ring-2 focus:ring-ravel-blue/50 disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={waitingForReply || !text.trim()}
          className="rounded-2xl bg-ravel-blue px-5 py-3 font-medium text-white hover:bg-ravel-blue/90 hover:shadow-glow transition-all disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {waitingForReply ? "…" : "Gönder"}
        </button>
      </form>
    </div>
  )
}

function Bubble({ message }) {
  const isUser = message.role === "user"
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={`flex ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={[
          "max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed",
          isUser
            ? "rounded-tr-md bg-ravel-blue/20 border border-ravel-blue/30 text-ravel-text whitespace-pre-wrap"
            : "rounded-tl-md bg-ravel-purple/15 border border-ravel-purple/30 text-ravel-text",
        ].join(" ")}
      >
        {isUser ? message.content : <Markdown body={message.content} variant="chat" />}
      </div>
    </motion.div>
  )
}

function TypingDots() {
  return (
    <div className="flex items-center gap-1">
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="inline-block h-2 w-2 rounded-full bg-ravel-purple"
          animate={{ y: [0, -4, 0], opacity: [0.4, 1, 0.4] }}
          transition={{
            duration: 1.0,
            repeat: Infinity,
            delay: i * 0.18,
            ease: "easeInOut",
          }}
        />
      ))}
    </div>
  )
}

function EmptyState({ topic }) {
  const examples = [
    "Bu konunun en zor kısmı ne?",
    "Bana bir günlük hayat örneği verir misin?",
    "İki örnek üzerinden anlatabilir misin?",
  ]
  return (
    <div className="text-center py-10 text-ravel-muted">
      <div className="text-4xl">💬</div>
      <p className="mt-3 text-sm">
        {topic
          ? <>"{topic.label}" hakkında öğretmenine ne sormak istersin?</>
          : "Bir şey yaz, başlayalım."}
      </p>
      <ul className="mt-5 space-y-1.5 text-xs italic">
        {examples.map((q) => (
          <li key={q}>" {q} "</li>
        ))}
      </ul>
    </div>
  )
}

