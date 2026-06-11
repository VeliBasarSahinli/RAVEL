// Sidebar — minimalist sınıf seçici. Yalnızca 5/6/7/8 büyük dikey
// kartlar; konu listesi ana içerik alanında (TopicGrid) gösterilir.
//
// Sınıf değiştiğinde learningStore.setGrade FSM'i TOPIC_LIST'e çeker;
// MainPage o duruma göre TopicGrid'i render eder.

import { motion, AnimatePresence } from "framer-motion"
import { GRADES, CURRICULUM } from "../../data/curriculum"
import { useLearningStore } from "../../store/learningStore"

const ACCENTS = {
  5: { ring: "ring-ravel-blue/40",   text: "text-ravel-blue",   bar: "bg-ravel-blue",   glow: "hover:shadow-glow",        bg: "from-ravel-blue/15" },
  6: { ring: "ring-ravel-purple/40", text: "text-ravel-purple", bar: "bg-ravel-purple", glow: "hover:shadow-glow-purple", bg: "from-ravel-purple/15" },
  7: { ring: "ring-ravel-gold/40",   text: "text-ravel-gold",   bar: "bg-ravel-gold",   glow: "hover:shadow-glow-gold",   bg: "from-ravel-gold/15" },
  8: { ring: "ring-ravel-green/40",  text: "text-ravel-green",  bar: "bg-ravel-green",  glow: "hover:shadow-glow",        bg: "from-ravel-green/15" },
}

export default function Sidebar({ open }) {
  const selectedGrade = useLearningStore((s) => s.selectedGrade)
  const setGrade = useLearningStore((s) => s.setGrade)

  return (
    <AnimatePresence initial={false}>
      {open && (
        <motion.aside
          key="sidebar"
          initial={{ width: 0, opacity: 0 }}
          animate={{ width: 288, opacity: 1 }}
          exit={{ width: 0, opacity: 0 }}
          transition={{ type: "tween", duration: 0.25, ease: "easeOut" }}
          className="shrink-0 overflow-hidden border-r border-white/5 bg-ravel-surface/70 backdrop-blur"
        >
          <div className="flex h-full w-72 flex-col">
            <div className="border-b border-white/5 px-5 py-4">
              <p className="text-xs uppercase tracking-widest text-ravel-muted">
                Sınıf Seç
              </p>
              <p className="mt-1 text-xs text-ravel-muted/70 leading-relaxed">
                Hangi seviyede çalışmak istediğini seç — kayıtlı olduğun sınıfla
                sınırlı değilsin.
              </p>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-3">
              {GRADES.map((g) => {
                const a = ACCENTS[g]
                const active = selectedGrade === g
                const topicCount = CURRICULUM[g]?.topics?.length || 0
                return (
                  <motion.button
                    key={g}
                    type="button"
                    onClick={() => setGrade(g)}
                    whileHover={{ x: active ? 0 : 4 }}
                    whileTap={{ scale: 0.98 }}
                    className={[
                      "relative w-full overflow-hidden rounded-2xl border px-5 py-5 text-left",
                      "transition-all duration-300",
                      active
                        ? `border-transparent bg-ravel-elevated ring-2 ${a.ring} shadow-elevated`
                        : "border-white/10 bg-ravel-elevated/40 hover:bg-ravel-elevated/70 hover:border-white/20",
                      a.glow,
                    ].join(" ")}
                  >
                    <div
                      className={[
                        "pointer-events-none absolute -right-10 -top-10 h-32 w-32 rounded-full bg-gradient-to-br opacity-50 blur-2xl",
                        a.bg,
                      ].join(" ")}
                    />
                    <div className="flex items-baseline justify-between">
                      <span className={`font-display text-3xl font-bold ${a.text}`}>
                        {g}
                      </span>
                      <span className="text-[10px] uppercase tracking-widest text-ravel-muted">
                        sınıf
                      </span>
                    </div>
                    <p className="mt-2 text-sm font-medium text-ravel-text">
                      {CURRICULUM[g]?.label}
                    </p>
                    <p className="mt-1 text-xs text-ravel-muted">
                      {topicCount} konu
                    </p>
                    {active && (
                      <motion.span
                        layoutId="grade-indicator"
                        className={`absolute left-0 inset-y-0 h-full w-1 rounded-r ${a.bar}`}
                      />
                    )}
                  </motion.button>
                )
              })}
            </div>

            <div className="border-t border-white/5 px-5 py-3 text-[10px] uppercase tracking-widest text-ravel-muted/60">
              MEB matematik müfredatı
            </div>
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  )
}
