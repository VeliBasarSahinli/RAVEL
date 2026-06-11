// LandingPage — koyu uzay teması, yüzen matematik sembolleri, iki rol kartı.
//
// Tasarım tercihi: spec'in dayattığı palet içinde "yıldız geçidi"
// (deep navy + neon mavi/mor) hissi. Kart hover'da yukarı kalkar +
// glow, arka planda 14 sembol Framer Motion ile yavaş animate.

import { motion } from "framer-motion"
import { useNavigate } from "react-router-dom"
import { useEffect } from "react"
import { useAuthStore } from "../store/authStore"
import { useThemeStore } from "../store/themeStore"

const SYMBOLS = [
  "∑", "π", "√", "∫", "∞", "%", "÷", "×", "θ", "Δ", "Φ", "≈", "²", "f(x)",
]

// Sayfa açılışında bir kez seed edilen pozisyon/rotasyon listesi
const PLACEMENTS = SYMBOLS.map((s, i) => ({
  symbol: s,
  // 6×3 viewport grid içine deterministik dağıt
  top: 8 + ((i * 53) % 80),
  left: 4 + ((i * 91) % 92),
  size: 48 + ((i * 17) % 96),
  rotate: ((i * 37) % 60) - 30,
  duration: 18 + (i % 6) * 2,
  delay: -(i * 1.3),
}))

export default function LandingPage() {
  const navigate = useNavigate()
  const isAuthed = useAuthStore((s) => Boolean(s.token))
  const theme = useThemeStore((s) => s.theme)
  const toggleTheme = useThemeStore((s) => s.toggleTheme)

  useEffect(() => {
    if (isAuthed) navigate("/app", { replace: true })
  }, [isAuthed, navigate])

  return (
    <div className="relative min-h-screen overflow-hidden bg-ravel-bg text-ravel-text">
      {/* Aurora glow */}
      <div className="pointer-events-none absolute inset-0 bg-gradient-aurora opacity-60" />

      {/* Sağ üstte tema toggle — login öncesi de tercih değiştirilebilir */}
      <button
        type="button"
        onClick={toggleTheme}
        aria-label={theme === "dark" ? "Açık temaya geç" : "Koyu temaya geç"}
        title={theme === "dark" ? "Açık temaya geç" : "Koyu temaya geç"}
        className="absolute top-5 right-5 z-20 rounded-full
                   bg-ravel-surface/80 backdrop-blur border border-white/10
                   px-3 py-1.5 text-base text-ravel-text
                   hover:border-ravel-purple/40 transition-colors
                   focus:outline-none focus-visible:ring-2 focus-visible:ring-ravel-purple/50"
      >
        <motion.span
          key={theme}
          initial={{ rotate: -90, opacity: 0 }}
          animate={{ rotate: 0, opacity: 1 }}
          transition={{ duration: 0.25 }}
          className="inline-block"
          aria-hidden
        >
          {theme === "dark" ? "☀️" : "🌙"}
        </motion.span>
      </button>

      {/* Floating math symbols */}
      <div className="pointer-events-none absolute inset-0 select-none">
        {PLACEMENTS.map((p, i) => (
          <motion.span
            key={i}
            className="absolute font-display font-semibold text-ravel-text/[0.05]"
            style={{
              top: `${p.top}%`,
              left: `${p.left}%`,
              fontSize: `${p.size}px`,
            }}
            initial={{ rotate: p.rotate, y: 0 }}
            animate={{ y: [-12, 12, -12], rotate: [p.rotate, p.rotate + 6, p.rotate] }}
            transition={{
              duration: p.duration,
              repeat: Infinity,
              ease: "easeInOut",
              delay: p.delay,
            }}
          >
            {p.symbol}
          </motion.span>
        ))}
      </div>

      {/* Scanline grid (very subtle) */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.05]"
        style={{
          backgroundImage:
            "linear-gradient(rgba(255,255,255,0.5) 1px, transparent 1px)," +
            "linear-gradient(90deg, rgba(255,255,255,0.5) 1px, transparent 1px)",
          backgroundSize: "64px 64px",
        }}
      />

      <main className="relative z-10 flex min-h-screen flex-col items-center justify-center px-6 py-16">
        <motion.h1
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: "easeOut" }}
          className="text-aurora font-display text-6xl md:text-7xl font-bold tracking-tight"
        >
          RAVEL
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.2, ease: "easeOut" }}
          className="mt-3 text-lg md:text-xl text-ravel-muted font-medium"
        >
          Matematik öğrenmenin en zeki yolu.
        </motion.p>

        <div className="mt-14 grid w-full max-w-3xl grid-cols-1 gap-6 md:grid-cols-2">
          <RoleCard
            role="student"
            title="Öğrenciyim"
            subtitle="Konularımı keşfet, sorularımı çöz."
            accent="blue"
            onClick={() => navigate("/login?role=student")}
            delay={0.35}
          />
          <RoleCard
            role="admin"
            title="Yöneticiyim"
            subtitle="İçerik yükle, modelleri yönet."
            accent="purple"
            onClick={() => navigate("/login?role=admin")}
            delay={0.45}
          />
        </div>

        <p className="mt-12 text-xs text-ravel-muted/70">
          Sürüm 0.8 · Ortaokul matematik · 5–8. sınıf
        </p>
      </main>
    </div>
  )
}

function RoleCard({ title, subtitle, accent, onClick, delay = 0 }) {
  const accentMap = {
    blue: {
      glow: "hover:shadow-glow",
      border: "hover:border-ravel-blue/60",
      ring: "from-ravel-blue/30 to-transparent",
      icon: "🎓",
    },
    purple: {
      glow: "hover:shadow-glow-purple",
      border: "hover:border-ravel-purple/60",
      ring: "from-ravel-purple/30 to-transparent",
      icon: "⚙️",
    },
  }
  const a = accentMap[accent]

  return (
    <motion.button
      type="button"
      onClick={onClick}
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, delay, ease: "easeOut" }}
      whileHover={{ y: -6 }}
      whileTap={{ scale: 0.98 }}
      className={[
        "relative overflow-hidden rounded-3xl",
        "bg-ravel-surface/90 backdrop-blur",
        "border border-white/10",
        "px-7 py-9 text-left transition-all duration-300",
        "shadow-elevated",
        a.glow,
        a.border,
        "group focus:outline-none focus-visible:ring-2 focus-visible:ring-ravel-blue/60",
      ].join(" ")}
    >
      {/* Top-right gradient ring */}
      <div
        className={`pointer-events-none absolute -right-12 -top-12 h-40 w-40 rounded-full bg-gradient-to-br opacity-50 blur-2xl ${a.ring}`}
      />

      <div className="text-4xl">{a.icon}</div>
      <h3 className="mt-5 font-display text-2xl font-semibold text-ravel-text">
        {title}
      </h3>
      <p className="mt-2 text-sm text-ravel-muted">{subtitle}</p>

      <div className="mt-6 flex items-center gap-2 text-sm font-medium text-ravel-text/80 group-hover:text-ravel-text">
        Devam et
        <span aria-hidden className="transition-transform group-hover:translate-x-1">→</span>
      </div>
    </motion.button>
  )
}
