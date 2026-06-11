import { useEffect } from "react"
import { Navigate, Route, Routes } from "react-router-dom"
import LandingPage from "./pages/LandingPage"
import LoginPage from "./pages/LoginPage"
import MainPage from "./pages/MainPage"
import NotFound from "./pages/NotFound"
import { useAuthStore } from "./store/authStore"
import { useThemeStore } from "./store/themeStore"

/**
 * ProtectedRoute — token yoksa landing'e gönder.
 * adminOnly: role !== "admin" ise main'e gönder (yetki yetmedi mesajı login'de).
 */
function ProtectedRoute({ children, adminOnly = false }) {
  const token = useAuthStore((s) => s.token)
  const role = useAuthStore((s) => s.user?.role)
  if (!token) return <Navigate to="/" replace />
  if (adminOnly && role !== "admin") return <Navigate to="/app" replace />
  return children
}

export default function App() {
  // Tema persist'ini html elementine yansıt; .light yokken :root (dark)
  // varsayılanı geçerli olur.
  const theme = useThemeStore((s) => s.theme)
  useEffect(() => {
    const root = document.documentElement
    if (theme === "light") root.classList.add("light")
    else root.classList.remove("light")
  }, [theme])

  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/app"
        element={
          <ProtectedRoute>
            <MainPage />
          </ProtectedRoute>
        }
      />
      {/* Faz 4'te /app/admin route'u dolacak; şimdilik admin kullanıcılar
          /app'e gider, sağdan slide-over panelde admin paneli açılır. */}
      <Route path="*" element={<NotFound />} />
    </Routes>
  )
}
