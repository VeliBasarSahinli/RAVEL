// MainPage — Faz 3 yeniden yazıldı.
// Layout: Navbar + Sidebar + içerik alanı (state machine).

import { AnimatePresence, motion } from "framer-motion"
import { useEffect, useState } from "react"
import { useAuthStore } from "../store/authStore"
import { useGamificationStore } from "../store/gamificationStore"
import { useLearningStore, STATES } from "../store/learningStore"
import { useWebSocket } from "../hooks/useWebSocket"
import { useAuth } from "../hooks/useAuth"
import { fetchProfile } from "../api/auth"

import Navbar from "../components/layout/Navbar"
import Sidebar from "../components/layout/Sidebar"
import IdleHero from "../components/learning/IdleHero"
import TopicGrid from "../components/learning/TopicGrid"
import TopicIntro from "../components/learning/TopicIntro"
import ModeSelector from "../components/learning/ModeSelector"
import QuestionCard from "../components/learning/QuestionCard"
import VideoCard from "../components/learning/VideoCard"
import ChatBox from "../components/learning/ChatBox"
import AdminPanel from "../components/admin/AdminPanel"

export default function MainPage() {
  const user = useAuthStore((s) => s.user)
  const isAdmin = user?.role === "admin"
  const setGami = useGamificationStore((s) => s.setFromProfile)
  const fsmState = useLearningStore((s) => s.state)
  const selectedTopic = useLearningStore((s) => s.selectedTopic)
  const { logout } = useAuth()
  const { status: wsStatus } = useWebSocket()

  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [adminOpen, setAdminOpen] = useState(false)

  // İlk yükleme: gamification profili çek
  useEffect(() => {
    let alive = true
    fetchProfile()
      .then((p) => alive && setGami(p))
      .catch(() => { /* anonim/cold-start tolere */ })
    return () => { alive = false }
  }, [user?.student_id, setGami])

  // FSM render — sınıf seçilmedikçe IDLE; sınıf seçilince TOPIC_LIST;
  // konu seçilince TOPIC_INTRO → MODE_SELECT → 3 mod.
  const renderContent = () => {
    switch (fsmState) {
      case STATES.IDLE:        return <IdleHero />
      case STATES.TOPIC_LIST:  return <TopicGrid />
      case STATES.TOPIC_INTRO: return selectedTopic ? <TopicIntro /> : <TopicGrid />
      case STATES.MODE_SELECT: return selectedTopic ? <ModeSelector /> : <TopicGrid />
      case STATES.QUESTION:    return selectedTopic ? <QuestionCard /> : <TopicGrid />
      case STATES.VIDEO:       return selectedTopic ? <VideoCard />    : <TopicGrid />
      case STATES.CHAT:        return selectedTopic ? <ChatBox />      : <TopicGrid />
      default:                 return <IdleHero />
    }
  }

  return (
    <div className="flex h-screen flex-col bg-ravel-bg text-ravel-text">
      <Navbar
        wsStatus={wsStatus}
        onToggleSidebar={() => setSidebarOpen((v) => !v)}
        sidebarOpen={sidebarOpen}
        onOpenAdmin={() => setAdminOpen(true)}
        onLogout={logout}
      />

      {wsStatus === "failed" && (
        <div className="bg-ravel-gold/20 border-b border-ravel-gold/30 px-4 py-2 text-sm text-ravel-gold flex items-center gap-2">
          <span>⚠️ Sunucu bağlantısı kesildi. Yanıtlar gecikmeli gelebilir.</span>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="ml-auto underline hover:text-ravel-text"
          >
            Yenile
          </button>
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        <Sidebar open={sidebarOpen} />

        <main className="flex-1 overflow-y-auto">
          <div className="px-4 py-8 md:px-10 md:py-12">
            <AnimatePresence mode="wait">
              <motion.div
                key={`${fsmState}-${selectedTopic?.id || "idle"}`}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.25, ease: "easeOut" }}
              >
                {renderContent()}
              </motion.div>
            </AnimatePresence>
          </div>
        </main>
      </div>

      {isAdmin && <AdminPanel open={adminOpen} onClose={() => setAdminOpen(false)} />}
    </div>
  )
}
