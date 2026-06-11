// WebSocket bağlantı yöneticisi.
// - Bağlantı: ws(s)://<api>/ws/{student_id}?token=<jwt>
// - Bağlantı koparsa 3 sn sonra reconnect (max 6 deneme).
// - learningStore'a gelen mesajları dağıtır:
//     content_type === "video"             → receiveVideo
//     diğer (text_explanation/system_msg)  → receiveDelivery

import { useEffect, useRef, useState, useCallback } from "react"
import { useAuthStore } from "../store/authStore"
import { useLearningStore } from "../store/learningStore"
import { appendChatHistory } from "../api/content"

const RECONNECT_DELAY_MS = 3000
const MAX_RECONNECTS = 6

function buildWsUrl(studentId, token) {
  // VITE_API_URL set'lı → mutlak; aksi halde sayfanın origin'i (proxy üzerinden).
  const apiBase = import.meta.env.VITE_API_URL
  let base
  if (apiBase) {
    base = apiBase.replace(/^http/, "ws")
  } else {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:"
    base = `${proto}//${window.location.host}`
  }
  return `${base}/ws/${encodeURIComponent(studentId)}?token=${encodeURIComponent(token)}`
}

export function useWebSocket() {
  const token = useAuthStore((s) => s.token)
  const studentId = useAuthStore((s) => s.user?.student_id)

  const receiveDelivery = useLearningStore((s) => s.receiveDelivery)
  const receiveVideo = useLearningStore((s) => s.receiveVideo)
  const appendChat = useLearningStore((s) => s.appendChat)
  const setWsStatus = useLearningStore((s) => s.setWsStatus)

  const [status, setStatus] = useState("idle") // idle | connecting | connected | reconnecting | failed | error
  // Lokal status değişimini learningStore'a yansıt (banner ve pending text)
  useEffect(() => { setWsStatus(status) }, [status, setWsStatus])
  const wsRef = useRef(null)
  const retryRef = useRef(0)
  const timerRef = useRef(null)

  const cleanup = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
    if (wsRef.current) {
      try { wsRef.current.close() } catch { /* ignore */ }
      wsRef.current = null
    }
  }, [])

  const connect = useCallback(() => {
    if (!token || !studentId) return
    cleanup()
    setStatus("connecting")
    const url = buildWsUrl(studentId, token)
    let ws
    try { ws = new WebSocket(url) }
    catch (e) {
      console.error("WS construction failed", e)
      setStatus("error")
      return
    }
    wsRef.current = ws

    ws.onopen = () => {
      retryRef.current = 0
      setStatus("connected")
    }

    ws.onmessage = (evt) => {
      let msg
      try { msg = JSON.parse(evt.data) }
      catch {
        console.warn("WS non-JSON frame", evt.data)
        return
      }
      const ct = msg.content_type
      if (ct === "video") {
        receiveVideo(msg)
        return
      }
      // text_explanation | system_message → delivery + (chat ise history'ye)
      receiveDelivery(msg)
      if (msg?.context === "chat") {
        // qa_dialog yanıtı: backend ContentDeliveryMessage.context="chat"
        // set ediyor → chatHistory'ye append. Sokratik diyalog zinciri için
        // tek source of truth bu hook.
        appendChat({
          role: "assistant",
          content: msg.body_html,
          ts: Date.now(),
          trace: msg.trace_id,
        })
        // Server-side Redis chat geçmişine de assistant cevabını ekle.
        // Fire-and-forget; sonraki kullanıcı mesajında multi-turn bağlam
        // olarak qa_dialog promptuna gidecek.
        const topic = useLearningStore.getState().selectedTopic?.id
        if (topic) {
          appendChatHistory({ role: "assistant", message: msg.body_html, topic })
        }
      }
    }

    ws.onclose = () => {
      // Token hâlâ varsa reconnect dene
      if (useAuthStore.getState().token && retryRef.current < MAX_RECONNECTS) {
        setStatus("reconnecting")
        retryRef.current += 1
        timerRef.current = setTimeout(connect, RECONNECT_DELAY_MS)
      } else if (useAuthStore.getState().token) {
        // Max retry tükendi — kullanıcı uyarılmalı (MainPage banner)
        setStatus("failed")
      } else {
        setStatus("idle")
      }
    }

    ws.onerror = () => {
      // onclose zaten reconnect tetikleyecek
      setStatus("error")
    }
  }, [token, studentId, receiveDelivery, receiveVideo, appendChat, cleanup])

  useEffect(() => {
    if (token && studentId) {
      connect()
      return cleanup
    }
    cleanup()
    setStatus("idle")
  }, [token, studentId, connect, cleanup])

  return { status, reconnect: connect, disconnect: cleanup }
}
