// IDLE durumu — kullanıcı henüz konu seçmedi.

import { motion } from "framer-motion"
import { useAuthStore } from "../../store/authStore"
import { useGamificationStore } from "../../store/gamificationStore"

export default function IdleHero() {
  const user = useAuthStore((s) => s.user)
  const isAdmin = user?.role === "admin"
  const { xp, streak, correctTotal, totalAttempts } =
    useGamificationStore((s) => ({
      xp: s.xp, streak: s.streak,
      correctTotal: s.correctTotal, totalAttempts: s.totalAttempts,
    }))

  const successPct = totalAttempts > 0
    ? Math.round((correctTotal / totalAttempts) * 100)
    : null

  return (
    <div className="mx-auto w-full max-w-3xl">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="rounded-3xl border border-white/10 bg-ravel-surface/80 p-8 md:p-10"
      >
        <p className="text-xs uppercase tracking-widest text-ravel-muted">
          {isAdmin ? "Yönetici görünümü" : "Hoşgeldin"}
        </p>
        <h1 className="mt-2 font-display text-3xl md:text-4xl font-semibold text-ravel-text">
          {user?.display_name
            ? `Selam, ${user.display_name}`
            : "Bugün ne çalışmak istersin?"}
        </h1>
        <p className="mt-3 text-ravel-muted">
          Sol panelden bir <span className="text-ravel-text">sınıf ve konu</span>{" "}
          seç — hangi sınıfta kayıtlı olduğun fark etmez. Her konuda dilediğin
          modu (soru, video, sohbet) deneyebilirsin.
        </p>

        {!isAdmin && (
          <dl className="mt-8 grid grid-cols-2 gap-4 sm:grid-cols-4 text-center">
            <Stat label="🔥 Streak" value={streak} />
            <Stat label="✨ XP" value={xp} />
            <Stat label="✅ Doğru" value={correctTotal} />
            <Stat
              label="🎯 Başarı"
              value={successPct == null ? "—" : `%${successPct}`}
            />
          </dl>
        )}

        {isAdmin && (
          <div className="mt-6 rounded-xl border border-ravel-purple/30 bg-ravel-purple/5 px-4 py-3 text-sm text-ravel-muted">
            <span className="font-medium text-ravel-purple">⚙️ Yönetici: </span>
            Üstteki <code className="text-ravel-text">⚙️ Admin</code> düğmesinden
            öğrenci hesabı oluşturabilir, içerik yükleyebilir ve LLM ayarlarını
            düzenleyebilirsin.
          </div>
        )}
      </motion.div>
    </div>
  )
}

function Stat({ label, value }) {
  return (
    <div className="rounded-2xl bg-ravel-elevated/60 px-3 py-4">
      <dt className="text-[10px] uppercase tracking-widest text-ravel-muted">
        {label}
      </dt>
      <dd className="mt-1 font-display text-2xl font-semibold text-ravel-text tabular-nums">
        {value ?? 0}
      </dd>
    </div>
  )
}
