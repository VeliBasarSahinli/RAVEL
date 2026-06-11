// Tek paylaşımlı axios instance.
// Token authStore.getState() üzerinden lazy okunur — interceptor "store
// yüklendi mi?" derdine düşmez.

import axios from "axios"
import { useAuthStore } from "../store/authStore"

const baseURL = import.meta.env.VITE_API_URL || ""

export const api = axios.create({
  baseURL,
  timeout: 15000,
})

api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 401 → auth state'i temizle ve "/login"e bırak.
// (Router gerçek redirect'i ProtectedRoute'ta yapıyor; burada sadece store reset.)
api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401) {
      const { token, clear } = useAuthStore.getState()
      if (token) clear()
    }
    return Promise.reject(err)
  },
)
