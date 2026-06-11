// RAVEL frontend — Vite config (Adım 8)
//
// Dev mode (vite dev): /api/*, /auth/*, /ws/* localhost:8000'e proxy edilir.
// Prod mode (nginx multi-stage): nginx aynı path'leri api_gateway:8000'e
// upstream proxy yapar (services/frontend/nginx.conf).
//
// Frontend kodda hep relative path kullan ("/api/profile" gibi); böylece
// dev/prod ayrımı yapmadan aynı kod çalışır.

import { defineConfig, loadEnv } from "vite"
import react from "@vitejs/plugin-react"

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "")
  const apiTarget = env.VITE_API_URL || "http://localhost:8000"
  // RAG admin servisi farklı portta (Adım 5 — port 8003).
  const ragTarget = env.VITE_RAG_URL || "http://localhost:8003"
  const wsTarget = apiTarget.replace(/^http/, "ws")

  return {
    plugins: [react()],
    server: {
      host: "0.0.0.0",
      port: 5173,
      strictPort: true,
      proxy: {
        "/api":   { target: apiTarget, changeOrigin: true },
        "/auth":  { target: apiTarget, changeOrigin: true },
        "/admin": { target: ragTarget, changeOrigin: true },   // RAG admin
        "/ws":    { target: wsTarget,  ws: true, changeOrigin: true },
      },
    },
    build: {
      outDir: "dist",
      sourcemap: false,
      chunkSizeWarningLimit: 400,
      rollupOptions: {
        output: {
          // node_modules altındaki ağır kütüphaneleri kendi chunk'larına ayır.
          // Hedef: ana index chunk < 250 KB; lazy panellerle de paylaşılabilir.
          manualChunks(id) {
            if (!id.includes("node_modules")) return
            if (id.includes("node_modules/recharts") ||
                id.includes("node_modules/d3"))            return "recharts"
            if (id.includes("node_modules/framer-motion")) return "framer"
            if (id.includes("node_modules/react-router"))  return "router"
            if (id.includes("node_modules/@tanstack"))     return "query"
            if (id.includes("node_modules/react") ||
                id.includes("node_modules/react-dom"))     return "vendor"
          },
        },
      },
    },
  }
})
