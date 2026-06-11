// Admin → "Öğrenci Ekle" formu (POST /auth/register).
// MainPage'deki sağdan-açılan admin slide-over'ın bir parçası.
// Faz 4'te bu slide-over içerik yükleme + LLM yönetimi sekmeleriyle genişler.
//
// Adım 8 ek not (Faz 3): grade_level UI'ı kaldırıldı — öğrenci sisteme
// girince sidebar'dan istediği sınıf+konuyu seçer; admin yalnızca
// username/password (+ opsiyonel görünen ad) girer.

import { motion } from "framer-motion"
import { useState } from "react"
import { adminRegister } from "../../api/admin"

export default function StudentRegisterForm() {
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [displayName, setDisplayName] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)

  function reset() {
    setUsername("")
    setPassword("")
    setDisplayName("")
    setError(null)
    setSuccess(null)
  }

  async function onSubmit(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setSuccess(null)
    try {
      const out = await adminRegister({
        username: username.trim(),
        password,
        displayName: displayName.trim() || null,
        role: "student",
        // grade_level gönderilmiyor — backend default 6 yazar (placeholder).
      })
      setSuccess(`Hesap oluşturuldu: ${out.username} (${out.role})`)
      setUsername("")
      setPassword("")
      setDisplayName("")
    } catch (err) {
      const status = err?.response?.status
      const detail = err?.response?.data?.detail
      if (status === 409) setError("Bu kullanıcı adı zaten alınmış.")
      else if (status === 422) {
        const msg = Array.isArray(detail) ? detail[0]?.msg : detail
        setError(msg || "Form verileri geçersiz (en az 6 karakter şifre, 3+ karakter kullanıcı adı).")
      } else if (status === 403) setError("Bu işlem için yönetici yetkisi gerekli.")
      else setError(detail || err?.message || "Kayıt oluşturulamadı.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4" noValidate>
      <div>
        <h3 className="font-display text-lg font-semibold text-ravel-text">
          Öğrenci Hesabı Oluştur
        </h3>
        <p className="mt-1 text-xs text-ravel-muted">
          Öğrenci kullanıcı adıyla giriş yapacak. Sisteme girince istediği
          sınıf ve konuyu sol panelden kendisi seçer — kayıt sırasında sınıf
          belirtmek gerekmez.
        </p>
      </div>

      <Field
        label="Kullanıcı adı"
        type="text"
        autoComplete="off"
        value={username}
        minLength={3}
        maxLength={64}
        required
        onChange={(e) => setUsername(e.target.value.replace(/\s+/g, ""))}
        disabled={busy}
        placeholder="ornek: ayse_y"
      />

      <Field
        label="Şifre"
        type="text"
        autoComplete="off"
        value={password}
        minLength={6}
        maxLength={128}
        required
        onChange={(e) => setPassword(e.target.value)}
        disabled={busy}
        placeholder="en az 6 karakter"
      />

      <Field
        label="Görünen ad (opsiyonel)"
        type="text"
        value={displayName}
        maxLength={128}
        onChange={(e) => setDisplayName(e.target.value)}
        disabled={busy}
        placeholder="Ayşe Y."
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

      {success && (
        <motion.div
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-lg border border-ravel-green/40 bg-ravel-green/10 px-3 py-2 text-sm text-ravel-green"
          role="status"
        >
          {success}
        </motion.div>
      )}

      <div className="flex gap-2 pt-1">
        <button
          type="submit"
          disabled={busy || !username || password.length < 6}
          className={[
            "flex-1 rounded-xl py-2.5 font-medium",
            "bg-ravel-purple text-white hover:bg-ravel-purple/90 hover:shadow-glow-purple",
            "transition-all disabled:opacity-40 disabled:cursor-not-allowed",
          ].join(" ")}
        >
          {busy ? "Oluşturuluyor…" : "Hesabı Oluştur"}
        </button>
        <button
          type="button"
          onClick={reset}
          disabled={busy}
          className="rounded-xl bg-ravel-elevated/80 px-4 py-2.5 text-sm font-medium text-ravel-muted hover:bg-ravel-elevated hover:text-ravel-text transition-all"
        >
          Sıfırla
        </button>
      </div>
    </form>
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
          "px-3.5 py-2.5 text-sm text-ravel-text placeholder:text-ravel-muted/60",
          "focus:outline-none focus:ring-2 focus:ring-ravel-purple/50 focus:border-ravel-purple/50",
          "transition-all",
          rest.disabled ? "opacity-60" : "",
        ].join(" ")}
      />
    </label>
  )
}
