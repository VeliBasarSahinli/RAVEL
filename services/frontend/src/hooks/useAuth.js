// Auth helper'ları — login / logout / me. Hata mesajlarını Türkçe'ye çevirir.

import { useNavigate } from "react-router-dom"
import * as authApi from "../api/auth"
import { useAuthStore } from "../store/authStore"
import { useGamificationStore } from "../store/gamificationStore"
import { useLearningStore } from "../store/learningStore"

function tr(err) {
  const code = err?.response?.status
  const detail = err?.response?.data?.detail
  if (code === 401) return "Kullanıcı adı veya şifre hatalı."
  if (code === 403) return "Bu işlem için yetkin yok."
  if (code === 409) return detail || "Bu kullanıcı adı zaten kayıtlı."
  if (code === 503) return "Sunucu şu an erişilebilir değil. Birazdan tekrar dene."
  if (code === 422) return detail?.[0]?.msg || "Form verileri geçersiz."
  if (err?.code === "ERR_NETWORK") return "Sunucuya ulaşılamıyor. Bağlantını kontrol et."
  return detail || err?.message || "Beklenmeyen bir hata oluştu."
}

export function useAuth() {
  const navigate = useNavigate()
  const setSession = useAuthStore((s) => s.setSession)
  const setLoading = useAuthStore((s) => s.setLoading)
  const setError = useAuthStore((s) => s.setError)
  const clear = useAuthStore((s) => s.clear)
  const resetGami = useGamificationStore((s) => s.reset)
  const resetLearn = useLearningStore((s) => s.reset)

  async function login(args) {
    setLoading()
    try {
      const data = await authApi.login(args)
      const user = {
        student_id: data.student_id,
        username: args.username || null,
        role: data.role || "student",
        grade_level: args.gradeLevel ?? data.grade_level ?? 6,
        display_name: data.display_name || null,
      }
      setSession(data.access_token, user)
      // Auth sonrası fresh /auth/me ile profili kapat
      try {
        const me = await authApi.fetchMe()
        useAuthStore.getState().setUser({
          student_id: me.student_id,
          username: me.username,
          role: me.role,
          grade_level: me.grade_level,
          display_name: me.display_name,
        })
      } catch {
        /* /auth/me opsiyonel — login token zaten oturum için yeterli */
      }
      navigate("/app")
      return user
    } catch (err) {
      setError(tr(err))
      throw err
    }
  }

  async function logout() {
    await authApi.logout()
    clear()
    resetGami()
    resetLearn()
    navigate("/")
  }

  return { login, logout, formatError: tr }
}
