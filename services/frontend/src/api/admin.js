// Admin endpoint'leri (Faz 4'te kullanılacak — RAG admin API + Gateway register).
import { api } from "./client"

const RAG_BASE =
  import.meta.env.VITE_RAG_URL ||
  // Aynı host'tan farklı port: dev'de Vite proxy /admin'i Gateway'e yönlendirir,
  // ama RAG admin Gateway'in arkasında değil — direkt 8003. Bu yüzden burada
  // explicit olmamız iyi. nginx prod'da "/admin" rotası RAG'a upstream edilir.
  ""

const ragApi = {
  get: (path, opts) => api.get(`${RAG_BASE}${path}`, opts),
  post: (path, body, opts) => api.post(`${RAG_BASE}${path}`, body, opts),
  put: (path, body, opts) => api.put(`${RAG_BASE}${path}`, body, opts),
  delete: (path, opts) => api.delete(`${RAG_BASE}${path}`, opts),
}

// ─── İçerik (Adım 5) ─────────────────────────────────────────────
export async function uploadExcelIndex(file, onProgress) {
  const fd = new FormData()
  fd.append("file", file)
  return ragApi.post("/admin/upload/excel", fd, {
    headers: { "Content-Type": "multipart/form-data" },
    onUploadProgress: (e) => onProgress && e.total && onProgress(e.loaded / e.total),
  }).then((r) => r.data)
}

export async function uploadQuestionFile(file, fileType, gradeLevel, subject, onProgress) {
  const fd = new FormData()
  fd.append("file", file)
  fd.append("file_type", fileType)
  fd.append("grade_level", String(gradeLevel))
  fd.append("subject", subject)
  return ragApi.post("/admin/upload/questions", fd, {
    headers: { "Content-Type": "multipart/form-data" },
    onUploadProgress: (e) => onProgress && e.total && onProgress(e.loaded / e.total),
  }).then((r) => r.data)
}

export async function uploadTheoryFile(file, fileType, gradeLevel, subject, onProgress) {
  const fd = new FormData()
  fd.append("file", file)
  fd.append("file_type", fileType)
  fd.append("grade_level", String(gradeLevel))
  fd.append("subject", subject)
  return ragApi.post("/admin/upload/theory", fd, {
    headers: { "Content-Type": "multipart/form-data" },
    onUploadProgress: (e) => onProgress && e.total && onProgress(e.loaded / e.total),
  }).then((r) => r.data)
}

export async function fetchStats() {
  const r = await ragApi.get("/admin/stats")
  return r.data
}

// ─── LLM yönetimi (Adım 7e) ─────────────────────────────────────
export async function listProviders() {
  const r = await ragApi.get("/admin/llm/providers")
  return r.data.providers
}

export async function listLLMConfigs() {
  const r = await ragApi.get("/admin/llm/configs")
  return r.data.configs
}

export async function upsertLLMConfig(payload) {
  const r = await ragApi.post("/admin/llm/config", payload)
  return r.data
}

export async function patchLLMConfig(agentName, patch) {
  const r = await ragApi.put(`/admin/llm/config/${encodeURIComponent(agentName)}`, patch)
  return r.data
}

export async function deleteLLMConfig(agentName) {
  const r = await ragApi.delete(`/admin/llm/config/${encodeURIComponent(agentName)}`)
  return r.data
}

export async function testLLMConfig(agentName) {
  const r = await ragApi.post(`/admin/llm/test/${encodeURIComponent(agentName)}`)
  return r.data
}

// ─── Kullanıcı yönetimi ─────────────────────────────────────────
export async function adminRegister({ username, password, gradeLevel, displayName, role }) {
  const r = await api.post("/auth/register", {
    username,
    password,
    grade_level: gradeLevel,
    display_name: displayName,
    role: role || "student",
  })
  return r.data
}
