// Soru + cevap + chat endpoint'leri (Faz 3'te kullanılacak).

import { api } from "./client"

export async function fetchQuestion({ topic, taxonomicLevel }) {
  const r = await api.get("/api/question", {
    params: { topic, taxonomic_level: taxonomicLevel },
  })
  return r.data
}

export async function clearAskedSet({ topic }) {
  const r = await api.delete("/api/question/asked", { params: { topic } })
  return r.data
}

export async function fetchContentStats() {
  // Gateway proxy'si: öğrenci token'ı yeterli, RAG /admin/stats arkada.
  const r = await api.get("/api/stats")
  return r.data
}

export async function appendChatHistory({ role, message, topic }) {
  // Fire-and-forget — caller awaitlemeyebilir. Hata sessiz log.
  try {
    await api.post("/api/chat/history", { role, message, topic })
  } catch (err) {
    console.warn("appendChatHistory failed", err?.response?.status)
  }
}

export async function clearChatHistory({ topic }) {
  try {
    await api.delete("/api/chat/history", { params: { topic } })
  } catch (err) {
    console.warn("clearChatHistory failed", err?.response?.status)
  }
}

export async function submitAnswer(payload) {
  // payload: { question_id, topic, taxonomic_level, student_answer, is_correct, time_spent, explicit_video_request }
  const r = await api.post("/api/answer", payload)
  return r.data
}

export async function sendChatMessage({ message, topic, taxonomicLevel }) {
  const r = await api.post("/api/chat", {
    message,
    topic,
    taxonomic_level: taxonomicLevel,
  })
  return r.data
}
