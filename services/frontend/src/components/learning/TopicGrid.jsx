// TOPIC_LIST — sınıf seçildiğinde ana alanda gösterilen konu kart grid'i.
//
// İçerik kilidi: Mount olunca GET /api/stats çağrısı yapılır. by_file_name
// objesinden hangi dosyaların yüklü olduğu çıkarılır. Topic id'leri bu
// listede eşleşmiyorsa kart kilitli (opacity-40 + 🔒 + tıklayınca shake).

import { motion } from "framer-motion"
import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { CURRICULUM } from "../../data/curriculum"
import { useLearningStore } from "../../store/learningStore"
import { fetchContentStats } from "../../api/content"

export default function TopicGrid() {
  const grade = useLearningStore((s) => s.selectedGrade)
  const setTopic = useLearningStore((s) => s.setTopic)
  const topics = CURRICULUM[grade]?.topics || []

  // /api/stats — staleTime 60s; cold-cache UI'yi tüm açık göstererek
  // bloklamadan açar (isTopicLoaded fileNames boşsa true döner).
  const { data: stats } = useQuery({
    queryKey: ["content-stats"],
    queryFn: fetchContentStats,
    staleTime: 60_000,
    retry: 1,
  })

  const fileNames = stats?.by_file_name ? Object.keys(stats.by_file_name) : []

  return (
    <div className="mx-auto w-full max-w-5xl">
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
      >
        <p className="text-xs uppercase tracking-widest text-ravel-muted">
          {CURRICULUM[grade]?.label} · {topics.length} konu
        </p>
        <h1 className="mt-1 font-display text-3xl md:text-4xl font-semibold text-ravel-text">
          Hangi konuyu çalışalım?
        </h1>
        <p className="mt-2 text-ravel-muted">
          Bir konuya tıkla — önce kısa bir tanıtım sunarız, sonra çalışma şeklini
          birlikte seçeriz.
        </p>
      </motion.div>

      <div className="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {topics.map((t, i) => (
          <TopicCard
            key={t.id}
            topic={t}
            index={i}
            locked={!isTopicLoaded(t.id, fileNames)}
            onOpen={() => setTopic({ ...t, grade })}
          />
        ))}
      </div>
    </div>
  )
}

// Topic id (örn. "7_rasyonel_sayilar") yüklü file_name'lerden biriyle
// eşleşiyor mu?
//
// Algoritma — kelime tabanlı fuzzy match:
//   1. file_name ve topic_id'yi `_`/boşluk/tire ile token'lara böl, lowercase
//      yap, stopword'leri at ("sinif", "set", "pool", numerik kuyruk vs).
//   2. Sınıf numarası (sadece rakamdan oluşan token, örn. "8") iki tarafta
//      da AYNI olmalı — eşleşmezse direkt false. (8_cebirsel_ifadeler ile
//      8_uslu_ifadeler "8" + "ifadeler" üzerinden yanlış eşleşmesin diye
//      threshold'u da 0.8'e çıkardık ama bu kuralı çift güvence olarak.)
//   3. topic_id'nin token'larından kaç tanesinin file_name token set'inde
//      geçtiğini say.
//   4. eşleşme oranı ≥ 0.8 ise loaded kabul et.
//
// Multi-topic dosya örneği: "7_sinif_tam_sayilar_rasyonel_sayilar" hem
// "7_tam_sayilar" hem "7_rasyonel_sayilar" topic'leri için eşleşir
// (ortak token'lar: 7+tam+sayilar veya 7+rasyonel+sayilar = 3/3 = 1.0).
//
// fileNames boşsa stats henüz gelmedi → true (defansif: kilitli gösterme).

const _STOPWORDS = new Set([
  "sinif", "set", "pool", "test", "ve", "ile", "icin", "the",
])

function _tokenize(s) {
  return String(s)
    .toLowerCase()
    .split(/[_\s\-]+/)
    .map((w) => w.replace(/[^a-z0-9çğıöşü]+/g, ""))
    .filter((w) => w.length > 0 && !_STOPWORDS.has(w))
}

function _gradeToken(tokens) {
  return tokens.find((t) => /^\d+$/.test(t)) || null
}

function isTopicLoaded(topicId, fileNames) {
  if (!fileNames || fileNames.length === 0) return true
  const topicTokens = _tokenize(topicId)
  if (topicTokens.length === 0) return false
  const topicGrade = _gradeToken(topicTokens)
  return fileNames.some((f) => {
    const fileTokens = _tokenize(f)
    const fileGrade = _gradeToken(fileTokens)
    // Sınıf numarası varsa iki tarafta da aynı olmalı.
    if (topicGrade && fileGrade !== topicGrade) return false
    const fileSet = new Set(fileTokens)
    let matches = 0
    for (const t of topicTokens) {
      if (fileSet.has(t)) matches++
    }
    return matches / topicTokens.length >= 0.8
  })
}

function TopicCard({ topic, index, locked, onOpen }) {
  const [shake, setShake] = useState(0)
  const [showHint, setShowHint] = useState(false)

  function onClick() {
    if (locked) {
      setShake((n) => n + 1)
      setShowHint(true)
      setTimeout(() => setShowHint(false), 2000)
      return
    }
    onOpen()
  }

  return (
    <div className="relative">
      <motion.button
        type="button"
        onClick={onClick}
        initial={{ opacity: 0, y: 16 }}
        animate={{
          opacity: locked ? 0.4 : 1,
          y: 0,
          x: shake ? [0, -6, 6, -6, 6, 0] : 0,
        }}
        transition={{
          opacity: { duration: 0.3 },
          y: { duration: 0.4, delay: index * 0.04, ease: "easeOut" },
          x: { duration: 0.45 },
        }}
        whileHover={locked ? undefined : { y: -4, scale: 1.01 }}
        whileTap={locked ? undefined : { scale: 0.98 }}
        aria-disabled={locked}
        className={[
          "group relative overflow-hidden rounded-2xl",
          "bg-ravel-surface/80",
          "px-5 py-5 text-left transition-all duration-300 w-full",
          locked
            ? "border border-white/5 cursor-not-allowed"
            : "border border-white/10 hover:border-ravel-blue/40 hover:shadow-glow",
          "focus:outline-none focus-visible:ring-2 focus-visible:ring-ravel-blue/60",
        ].join(" ")}
      >
        <div className="pointer-events-none absolute -right-10 -top-10 h-28 w-28 rounded-full bg-gradient-to-br from-ravel-blue/15 to-transparent opacity-50 blur-2xl" />

        {locked && (
          <span
            aria-label="İçerik henüz yüklenmedi"
            className="absolute right-3 top-3 text-xs text-ravel-muted"
          >
            🔒
          </span>
        )}

        <div className="flex items-start gap-3">
          <span
            aria-hidden
            className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-ravel-elevated text-2xl"
          >
            {topic.icon}
          </span>
          <div className="min-w-0 flex-1">
            <h3 className="font-display text-base font-semibold text-ravel-text leading-snug">
              {topic.label}
            </h3>
            <p className="mt-1 text-xs text-ravel-muted">{topic.id}</p>
          </div>
        </div>

        <div className="mt-4 flex items-center justify-between text-xs text-ravel-muted">
          <span>Tanıtım → Mod seçimi → Çalış</span>
          <span aria-hidden className="text-ravel-text/60 transition-transform group-hover:translate-x-1">
            →
          </span>
        </div>
      </motion.button>

      {showHint && (
        <motion.p
          key={shake}
          initial={{ opacity: 0, y: -2 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          className="mt-2 text-xs text-ravel-gold text-center"
        >
          ⓘ İçerik henüz yüklenmedi
        </motion.p>
      )}
    </div>
  )
}
