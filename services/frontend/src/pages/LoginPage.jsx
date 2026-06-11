// LoginPage — kullanıcı adı + şifre formu.
// `?role=admin` query'si geldiğinde başlıkta yönetici rozeti gösterir.
// Default admin için "ipucu kart" — credentials .env'de.

import { motion } from "framer-motion"
import { useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { useAuth } from "../hooks/useAuth"
import { useAuthStore } from "../store/authStore"

export default function LoginPage() {
  const [params] = useSearchParams()
  const wantedRole = params.get("role") || "student"
  const isAdmin = wantedRole === "admin"

  const { login } = useAuth()
  const status = useAuthStore((s) => s.status)
  const error = useAuthStore((s) => s.error)
  const loading = status === "loading"

  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")

  async function onSubmit(e) {
    e.preventDefault()
    if (!username || !password) return
    try {
      const user = await login({ username, password })
      // Eğer admin login'i istemiş ama backend role=student dönerse → uyarı
      if (isAdmin && user.role !== "admin") {
        useAuthStore.getState().setError(
          "Bu kullanıcının yönetici yetkisi yok. Yine de oturumun açıldı.",
        )
      }
    } catch {
      /* hata zaten store.error'a yazıldı */
    }
  }

  const accent = isAdmin ? "purple" : "blue"

  return (
    <div className="relative min-h-screen overflow-hidden bg-ravel-bg">
      <div className="pointer-events-none absolute inset-0 bg-gradient-aurora opacity-50" />

      <main className="relative z-10 flex min-h-screen items-center justify-center px-4 py-12">
        <motion.div
          initial={{ opacity: 0, y: 20, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.5, ease: "easeOut" }}
          className="w-full max-w-md rounded-3xl bg-ravel-surface/90 backdrop-blur border border-white/10 shadow-elevated p-8"
        >
          <Link
            to="/"
            className="text-xs uppercase tracking-widest text-ravel-muted hover:text-ravel-text"
          >
            ← Geri
          </Link>

          <div className="mt-4 flex items-center gap-3">
            <div
              className={[
                "h-12 w-12 grid place-items-center rounded-xl text-xl",
                accent === "purple"
                  ? "bg-ravel-purple/20 text-ravel-purple"
                  : "bg-ravel-blue/20 text-ravel-blue",
              ].join(" ")}
            >
              {isAdmin ? "⚙️" : "🎓"}
            </div>
            <div>
              <h1 className="font-display text-2xl font-semibold text-ravel-text">
                {isAdmin ? "Yönetici Girişi" : "Öğrenci Girişi"}
              </h1>
              <p className="text-sm text-ravel-muted">
                Devam etmek için bilgilerini gir.
              </p>
            </div>
          </div>

          <form onSubmit={onSubmit} className="mt-7 space-y-4" noValidate>
            <Field
              label="Kullanıcı adı"
              type="text"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              disabled={loading}
            />
            <Field
              label="Şifre"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={loading}
            />

            {error && (
              <motion.div
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                className="rounded-lg border border-ravel-red/40 bg-ravel-red/10 px-3 py-2 text-sm text-ravel-red"
                role="alert"
              >
                {error}
              </motion.div>
            )}

            <button
              type="submit"
              disabled={loading || !username || !password}
              className={[
                "w-full rounded-xl py-3 font-medium",
                "transition-all duration-200",
                "disabled:opacity-40 disabled:cursor-not-allowed",
                accent === "purple"
                  ? "bg-ravel-purple hover:bg-ravel-purple/90 hover:shadow-glow-purple"
                  : "bg-ravel-blue hover:bg-ravel-blue/90 hover:shadow-glow",
                "text-white",
              ].join(" ")}
            >
              {loading ? "Giriş yapılıyor…" : "Giriş Yap"}
            </button>
          </form>

          {isAdmin && (
            <div className="mt-6 rounded-xl border border-ravel-gold/30 bg-ravel-gold/5 px-4 py-3 text-xs text-ravel-muted">
              <span className="font-medium text-ravel-gold">İlk kurulum: </span>
              Varsayılan yönetici <code className="text-ravel-text">admin</code> /
              <code className="text-ravel-text"> ravel_admin_2025</code>.
              Sistem hazır olduktan sonra şifreyi değiştir.
            </div>
          )}

          {!isAdmin && (
            <div className="mt-6 rounded-xl border border-white/10 bg-white/[0.03] px-4 py-3 text-xs text-ravel-muted">
              <span className="font-medium text-ravel-text">Hesabın yok mu? </span>
              Öğrenci hesapları yöneticin tarafından oluşturulur.
              Öğretmenine veya okul yöneticine başvur.
              <Link
                to="/login?role=admin"
                className="ml-1 inline-flex items-center gap-1 text-ravel-purple hover:text-ravel-purple/80"
              >
                Yönetici girişi <span aria-hidden>→</span>
              </Link>
            </div>
          )}
        </motion.div>
      </main>
    </div>
  )
}

function Field({ label, ...rest }) {
  return (
    <label className="block">
      <span className="text-xs uppercase tracking-widest text-ravel-muted">
        {label}
      </span>
      <input
        {...rest}
        className={[
          "mt-1.5 w-full rounded-xl bg-ravel-elevated/80 border border-white/10",
          "px-4 py-3 text-sm text-ravel-text placeholder:text-ravel-muted",
          "focus:outline-none focus:ring-2 focus:ring-ravel-blue/50 focus:border-ravel-blue/50",
          "transition-all",
          rest.disabled ? "opacity-60" : "",
        ].join(" ")}
      />
    </label>
  )
}
