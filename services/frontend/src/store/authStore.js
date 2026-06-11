// authStore — JWT + profil. localStorage'da yalnız token saklı.
// (display_name/role JWT'de gömülü; sayfa yenilemede /auth/me ile fresh çekilir.)

import { create } from "zustand"
import { persist, createJSONStorage } from "zustand/middleware"

export const useAuthStore = create(
  persist(
    (set, get) => ({
      token: null,
      // user: { student_id, username?, role, grade_level, display_name? }
      user: null,
      // 'idle' | 'loading' | 'ok' | 'error'
      status: "idle",
      error: null,

      setSession: (token, user) =>
        set({ token, user, status: "ok", error: null }),

      setUser: (user) => set({ user }),

      setError: (msg) => set({ status: "error", error: msg }),

      setLoading: () => set({ status: "loading", error: null }),

      clear: () =>
        set({ token: null, user: null, status: "idle", error: null }),

      // Türeyen yardımcılar (helpers)
      isAuthenticated: () => Boolean(get().token),
      isAdmin: () => get().user?.role === "admin",
    }),
    {
      name: "ravel.auth.v1",
      storage: createJSONStorage(() => localStorage),
      // Hassas/efemer alanları persist etme.
      partialize: (state) => ({ token: state.token, user: state.user }),
    },
  ),
)
