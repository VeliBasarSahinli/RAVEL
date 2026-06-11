// themeStore — açık/koyu tema tercihi.
//
// Persist ile localStorage'a yazılır. App.jsx html elementinin .light
// class'ını yönetir; CSS variable'lar üzerinden tüm bileşenler tek anda
// dönüşür (bkz. src/index.css ve tailwind.config.js).
//
// Varsayılan: "dark". Aksan renkleri (blue/purple/gold) iki temada da
// sabit kalır — sadece arka plan + metin değişir.

import { create } from "zustand"
import { persist, createJSONStorage } from "zustand/middleware"

export const useThemeStore = create(
  persist(
    (set, get) => ({
      // "dark" | "light"
      theme: "dark",

      toggleTheme: () =>
        set({ theme: get().theme === "dark" ? "light" : "dark" }),

      setTheme: (t) => {
        if (t !== "dark" && t !== "light") return
        set({ theme: t })
      },
    }),
    {
      name: "ravel-theme",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ theme: state.theme }),
    },
  ),
)
