// Navbar — sol logo + hamburger, orta breadcrumb, sağ rozetler.

import { motion } from "framer-motion"
import { useAuthStore } from "../../store/authStore"
import { useGamificationStore } from "../../store/gamificationStore"
import { useLearningStore } from "../../store/learningStore"
import { useThemeStore } from "../../store/themeStore"
import { CURRICULUM } from "../../data/curriculum"

export default function Navbar({ wsStatus, onToggleSidebar, sidebarOpen, onOpenAdmin, onLogout }) {
  const user = useAuthStore((s) => s.user)
  const isAdmin = user?.role === "admin"
  const theme = useThemeStore((s) => s.theme)
  const toggleTheme = useThemeStore((s) => s.toggleTheme)
  const { xp, streak } = useGamificationStore((s) => ({ xp: s.xp, streak: s.streak }))
  const { selectedGrade, selectedTopic, state: fsmState } =
    useLearningStore((s) => ({
      selectedGrade: s.selectedGrade,
      selectedTopic: s.selectedTopic,
      state: s.state,
    }))

  return (
    <header className="sticky top-0 z-30 border-b border-white/5 bg-ravel-bg/85 backdrop-blur-xl">
      <div className="flex items-center justify-between px-4 py-3 md:px-6">
        {/* Sol: hamburger + logo */}
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onToggleSidebar}
            aria-label={sidebarOpen ? "Konu listesini gizle" : "Konu listesini göster"}
            className="rounded-lg p-2 text-ravel-muted hover:bg-ravel-elevated hover:text-ravel-text transition-colors"
          >
            <Hamburger open={sidebarOpen} />
          </button>
          <span className="font-display text-xl font-bold text-aurora">RAVEL</span>
        </div>

        {/* Orta: breadcrumb */}
        <nav
          aria-label="Breadcrumb"
          className="hidden md:flex items-center gap-1 text-sm text-ravel-muted"
        >
          <Crumb>Ana Sayfa</Crumb>
          {selectedGrade != null && (
            <>
              <Sep />
              <Crumb>{CURRICULUM[selectedGrade]?.label}</Crumb>
            </>
          )}
          {selectedTopic && (
            <>
              <Sep />
              <Crumb highlight>{selectedTopic.label}</Crumb>
            </>
          )}
          {fsmState && fsmState !== "IDLE" && fsmState !== "MODE_SELECT" && (
            <>
              <Sep />
              <Crumb highlight>{stateLabel(fsmState)}</Crumb>
            </>
          )}
        </nav>

        {/* Sağ: rozetler */}
        <div className="flex items-center gap-2">
          <Pill icon="🔥" value={streak} label="streak" />
          <Pill icon="✨" value={xp} label="XP" />

          <ThemeToggle theme={theme} onToggle={toggleTheme} />

          <span className={["hidden sm:inline-flex text-xs px-2.5 py-1 rounded-full border",
            wsStatus === "connected"
              ? "border-ravel-green/40 text-ravel-green bg-ravel-green/10"
              : wsStatus === "connecting"
                ? "border-ravel-gold/40 text-ravel-gold bg-ravel-gold/10"
                : "border-ravel-red/40 text-ravel-red bg-ravel-red/10",
          ].join(" ")}>
            ●
          </span>

          {isAdmin && (
            <button
              type="button"
              onClick={onOpenAdmin}
              className="hidden md:inline-flex items-center gap-1.5 rounded-lg
                         bg-ravel-purple/15 border border-ravel-purple/40 px-3 py-1.5
                         text-sm font-medium text-ravel-purple
                         hover:bg-ravel-purple/25 hover:shadow-glow-purple transition-all"
            >
              ⚙️ Admin
            </button>
          )}

          <UserMenu user={user} onLogout={onLogout} />
        </div>
      </div>
    </header>
  )
}

function ThemeToggle({ theme, onToggle }) {
  const isDark = theme === "dark"
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-label={isDark ? "Açık temaya geç" : "Koyu temaya geç"}
      title={isDark ? "Açık temaya geç" : "Koyu temaya geç"}
      className="rounded-full bg-ravel-elevated/80 px-2.5 py-1 text-base
                 text-ravel-text hover:bg-ravel-elevated transition-colors
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
        {isDark ? "☀️" : "🌙"}
      </motion.span>
    </button>
  )
}

function Pill({ icon, value, label }) {
  return (
    <motion.span
      initial={false}
      animate={{ scale: [1, 1.06, 1] }}
      transition={{ duration: 0.4 }}
      key={value}
      title={label}
      className="inline-flex items-center gap-1.5 rounded-full bg-ravel-elevated/80 px-2.5 py-1 text-sm"
    >
      <span aria-hidden>{icon}</span>
      <span className="font-medium tabular-nums">{value ?? 0}</span>
    </motion.span>
  )
}

function UserMenu({ user, onLogout }) {
  const initials = (user?.display_name || user?.username || "?")
    .split(" ")
    .map((s) => s[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase()
  return (
    <div className="flex items-center gap-2">
      <div
        aria-hidden
        className="grid h-8 w-8 place-items-center rounded-full bg-gradient-to-br from-ravel-blue/40 to-ravel-purple/40 text-xs font-semibold text-ravel-text"
      >
        {initials || "??"}
      </div>
      <button
        type="button"
        onClick={onLogout}
        className="text-sm text-ravel-muted hover:text-ravel-text"
      >
        Çıkış
      </button>
    </div>
  )
}

function Crumb({ children, highlight }) {
  return (
    <span
      className={highlight ? "font-medium text-ravel-text" : ""}
    >
      {children}
    </span>
  )
}

function Sep() {
  return <span className="text-ravel-muted/50">/</span>
}

function Hamburger({ open }) {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
      <motion.path
        d="M3 5h14"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        animate={open ? { d: "M5 5l10 10" } : { d: "M3 5h14" }}
      />
      <motion.path
        d="M3 10h14"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        animate={open ? { opacity: 0 } : { opacity: 1 }}
      />
      <motion.path
        d="M3 15h14"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        animate={open ? { d: "M5 15l10 -10" } : { d: "M3 15h14" }}
      />
    </svg>
  )
}

function stateLabel(s) {
  return {
    TOPIC_LIST:  "Konular",
    TOPIC_INTRO: "Konu Anlatımı",
    QUESTION:    "Soru Çöz",
    VIDEO:       "Video",
    CHAT:        "Soru-Cevap",
  }[s] || s
}
