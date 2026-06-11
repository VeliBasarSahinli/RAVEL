// Learning state machine + son backend mesajı.
//
// FSM:
//   IDLE        — kullanıcı henüz sınıf seçmedi
//   TOPIC_LIST  — sınıf seçildi; ana alanda konu kartları
//   TOPIC_INTRO — konu seçildi; LLM'den konu anlatımı bekleniyor / gösteriliyor
//   MODE_SELECT — "Hazırım, Başlayalım!" sonrası 3 mod kartı
//   QUESTION    — RAG soru çözüm akışı
//   VIDEO       — Manim "Konu Öğren"
//   CHAT        — Sokratik diyalog

import { create } from "zustand"

export const STATES = Object.freeze({
  IDLE:        "IDLE",
  TOPIC_LIST:  "TOPIC_LIST",
  TOPIC_INTRO: "TOPIC_INTRO",
  MODE_SELECT: "MODE_SELECT",
  QUESTION:    "QUESTION",
  VIDEO:       "VIDEO",
  CHAT:        "CHAT",
})

export const useLearningStore = create((set) => ({
  // Aktif sınıf + konu
  selectedGrade: null,
  selectedTopic: null,

  // FSM
  state: STATES.IDLE,

  // En son WebSocket mesajı (text_explanation / video / system_message)
  // ve sürmekte olan trace_id (WS yanıtı bunu eşliyor).
  lastDelivery: null,
  lastVideo: null,
  pendingTrace: null,

  // WS bağlantı durumu — useWebSocket hook tarafından güncellenir.
  // "idle" | "connecting" | "connected" | "reconnecting" | "failed"
  // QuestionCard/ChatBox pending text'ini, MainPage banner'ı buna göre.
  wsStatus: "idle",

  // Chat geçmişi (qa_dialog modu)
  chatHistory: [],

  // Sınıf seçimi → TOPIC_LIST. Aynı sınıfı tekrar seçince state'e dokunma
  // (kullanıcının mod ekranındayken sidebar'a tıklaması state'i bozmasın).
  setGrade: (grade) =>
    set((s) => ({
      selectedGrade: grade,
      // sınıf değiştiyse konu seçimini ve içeriği sıfırla
      ...(s.selectedGrade !== grade
        ? {
            selectedTopic: null,
            state: STATES.TOPIC_LIST,
            lastDelivery: null,
            lastVideo: null,
            pendingTrace: null,
            chatHistory: [],   // sınıf değişti → sohbeti yeniden başlat
          }
        : {}),
    })),

  // Konu seçimi → TOPIC_INTRO (LLM konu anlatımını fetch'lemek için).
  // Yeni topic'e geçişte chatHistory de sıfırlanır; server-side Redis
  // history her topic için ayrı key kullandığı için doğal olarak izole.
  setTopic: (topic) =>
    set((s) => {
      const sameTopic = s.selectedTopic?.id === topic?.id
      return {
        selectedTopic: topic,
        state: STATES.TOPIC_INTRO,
        lastDelivery: null,
        lastVideo: null,
        pendingTrace: null,
        ...(sameTopic ? {} : { chatHistory: [] }),
      }
    }),

  setState: (s) => set({ state: s }),

  // Sınıf listesine geri dön
  backToTopicList: () =>
    set({
      selectedTopic: null,
      state: STATES.TOPIC_LIST,
      chatHistory: [],
      lastDelivery: null,
      lastVideo: null,
      pendingTrace: null,
    }),

  setPendingTrace: (traceId) => set({ pendingTrace: traceId }),

  setWsStatus: (s) => set({ wsStatus: s }),
  // pendingTrace'i sıfırlamıyoruz — UI bu trace_id'ye eşleşen delivery'i
  // bulup gösterecek. Yeni cevap submit edilince setPendingTrace yeni bir
  // trace_id atar; eski lastDelivery o yeni trace ile eşleşmediği için
  // doğal olarak gizlenir. (Önceden burada `pendingTrace: null` vardı →
  // matchedDelivery hiçbir zaman eşleşemiyor, açıklama hiç görünmüyordu.)
  receiveDelivery: (msg) => set({ lastDelivery: msg }),
  receiveVideo: (msg) => set({ lastVideo: msg }),

  appendChat: (entry) =>
    set((s) => ({ chatHistory: [...s.chatHistory, entry] })),
  clearChat: () => set({ chatHistory: [] }),

  reset: () => set({
    selectedGrade: null, selectedTopic: null, state: STATES.IDLE,
    lastDelivery: null, lastVideo: null, pendingTrace: null, chatHistory: [],
  }),
}))
