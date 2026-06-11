// Sağdan açılan admin slide-over.
//
// Faz 4: 4 sekme aktif. Panel her zaman mount kalır (transform + opacity ile
// gizlenir) → kapatıp tekrar açınca state korunur (yarım kalan formlar,
// fetch'lenmiş listeler).

import { motion } from "framer-motion"
import { useState } from "react"
import StudentRegisterForm from "./StudentRegisterForm"
import ContentUploadTab from "./ContentUploadTab"
import LLMManagerTab from "./LLMManagerTab"
import StatisticsTab from "./StatisticsTab"

const TABS = [
  { id: "users",   label: "Öğrenci Ekle",   icon: "👤" },
  { id: "content", label: "İçerik Yükleme", icon: "📂" },
  { id: "llm",     label: "LLM Yönetimi",   icon: "🧠" },
  { id: "stats",   label: "İstatistikler",  icon: "📊" },
]

export default function AdminPanel({ open, onClose }) {
  const [active, setActive] = useState("users")

  return (
    <>
      {/* Backdrop — pointer-events kapanınca kapalı */}
      <motion.div
        className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
        initial={false}
        animate={{
          opacity: open ? 1 : 0,
          pointerEvents: open ? "auto" : "none",
        }}
        transition={{ duration: 0.25 }}
        onClick={onClose}
        aria-hidden
      />

      {/* Panel — her zaman mount; sadece x-translate + visibility */}
      <motion.aside
        role="dialog"
        aria-label="Yönetici Paneli"
        aria-hidden={!open}
        className="fixed right-0 top-0 z-50 h-full w-full sm:w-[520px] bg-ravel-surface border-l border-white/10 shadow-elevated flex flex-col"
        initial={false}
        animate={{
          x: open ? 0 : "100%",
          // Kapalıyken klavye odağını dışla; içeride state kalmaya devam eder.
          visibility: open ? "visible" : "hidden",
        }}
        transition={{ type: "tween", duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/10 px-6 py-4">
          <div>
            <h2 className="font-display text-lg font-semibold text-ravel-text">
              ⚙️ Yönetici Paneli
            </h2>
            <p className="text-xs text-ravel-muted">
              Sistemi buradan yönet.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Kapat"
            className="rounded-lg p-2 text-ravel-muted hover:bg-ravel-elevated hover:text-ravel-text transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Tabs */}
        <nav
          className="flex gap-1 border-b border-white/10 px-3 py-2 overflow-x-auto"
          role="tablist"
        >
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={active === t.id}
              onClick={() => setActive(t.id)}
              className={[
                "relative flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm whitespace-nowrap transition-all",
                active === t.id
                  ? "bg-ravel-purple/15 text-ravel-purple"
                  : "text-ravel-muted hover:bg-ravel-elevated hover:text-ravel-text",
              ].join(" ")}
            >
              <span aria-hidden>{t.icon}</span>
              {t.label}
              {active === t.id && (
                <motion.span
                  layoutId="admin-tab-bar"
                  className="absolute -bottom-2 inset-x-0 h-0.5 rounded-full bg-ravel-purple"
                />
              )}
            </button>
          ))}
        </nav>

        {/* Body — tüm panellerin tek anda mount kalmasını istiyoruz
            (state korunsun); sadece görünürlüğü kontrol et. */}
        <div className="relative flex-1 overflow-hidden">
          <PaneWrap visible={active === "users"}>
            <StudentRegisterForm />
          </PaneWrap>
          <PaneWrap visible={active === "content"}>
            <ContentUploadTab />
          </PaneWrap>
          <PaneWrap visible={active === "llm"}>
            <LLMManagerTab />
          </PaneWrap>
          <PaneWrap visible={active === "stats"}>
            <StatisticsTab />
          </PaneWrap>
        </div>
      </motion.aside>
    </>
  )
}

// Tüm sekmeler always-mount; aktif olmayan görünmez ama durumunu korur.
// Görünmeyenleri overflow-hidden ile container dışına itmek yerine
// visibility:hidden + opacity 0 + pointer-events none kullanıyoruz.
function PaneWrap({ visible, children }) {
  return (
    <motion.div
      initial={false}
      animate={{
        opacity: visible ? 1 : 0,
        x: visible ? 0 : 6,
      }}
      transition={{ duration: 0.18, ease: "easeOut" }}
      className={[
        "absolute inset-0 overflow-y-auto px-6 py-6",
        visible ? "" : "pointer-events-none",
      ].join(" ")}
      style={{ visibility: visible ? "visible" : "hidden" }}
      aria-hidden={!visible}
    >
      {children}
    </motion.div>
  )
}
