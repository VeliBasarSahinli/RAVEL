// MODE_SELECT — üç büyük kart: Soru Çöz / Konu Öğren / Soru-Cevap.
// Hover'da glow efekti; tıklayınca learningStore.state'i hedef duruma alır.

import { motion } from "framer-motion"
import { useLearningStore, STATES } from "../../store/learningStore"

const MODES = [
  {
    state: STATES.QUESTION,
    icon: "📝",
    title: "Soru Çöz",
    subtitle: "Konuya ait sorulardan birini iste, çöz, anında geri bildirim al.",
    accent: "blue",
  },
  {
    state: STATES.VIDEO,
    icon: "🎬",
    title: "Konu Öğren",
    subtitle: "Konuyu adım adım anlatan kısa bir Manim videosu hazırlatalım.",
    accent: "purple",
  },
  {
    state: STATES.CHAT,
    icon: "💬",
    title: "Soru-Cevap",
    subtitle: "Aklındakini sor; öğretmen Sokratik yöntemle yönlendirir.",
    accent: "gold",
  },
]

const ACCENT_CLASSES = {
  blue: {
    bg: "from-ravel-blue/30 to-transparent",
    glow: "hover:shadow-glow",
    border: "hover:border-ravel-blue/50",
    text: "text-ravel-blue",
  },
  purple: {
    bg: "from-ravel-purple/30 to-transparent",
    glow: "hover:shadow-glow-purple",
    border: "hover:border-ravel-purple/50",
    text: "text-ravel-purple",
  },
  gold: {
    bg: "from-ravel-gold/30 to-transparent",
    glow: "hover:shadow-glow-gold",
    border: "hover:border-ravel-gold/50",
    text: "text-ravel-gold",
  },
}

export default function ModeSelector() {
  const setState = useLearningStore((s) => s.setState)
  const topic = useLearningStore((s) => s.selectedTopic)

  return (
    <div className="mx-auto w-full max-w-4xl">
      <motion.h2
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="font-display text-3xl font-semibold text-ravel-text"
      >
        {topic?.label || "Bu konuyu nasıl çalışmak istiyorsun?"}
      </motion.h2>
      <p className="mt-2 text-ravel-muted">
        Çalışma şeklini sen seç — her zaman değiştirebilirsin.
      </p>

      <div className="mt-10 grid grid-cols-1 gap-5 md:grid-cols-3">
        {MODES.map((m, i) => {
          const a = ACCENT_CLASSES[m.accent]
          return (
            <motion.button
              key={m.state}
              type="button"
              onClick={() => setState(m.state)}
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.45, delay: i * 0.08, ease: "easeOut" }}
              whileHover={{ y: -6 }}
              whileTap={{ scale: 0.98 }}
              className={[
                "group relative overflow-hidden rounded-3xl",
                "bg-ravel-surface/90 border border-white/10",
                "px-7 py-9 text-left transition-all duration-300",
                "shadow-elevated",
                a.glow, a.border,
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-ravel-blue/60",
              ].join(" ")}
            >
              <div
                className={`pointer-events-none absolute -right-14 -top-14 h-44 w-44 rounded-full bg-gradient-to-br opacity-50 blur-2xl ${a.bg}`}
              />
              <div className="text-4xl">{m.icon}</div>
              <h3 className={`mt-5 font-display text-xl font-semibold ${a.text}`}>
                {m.title}
              </h3>
              <p className="mt-2 text-sm text-ravel-muted">{m.subtitle}</p>
              <div className="mt-6 flex items-center gap-2 text-xs font-medium text-ravel-text/80 group-hover:text-ravel-text">
                Başla
                <span aria-hidden className="transition-transform group-hover:translate-x-1">→</span>
              </div>
            </motion.button>
          )
        })}
      </div>
    </div>
  )
}
