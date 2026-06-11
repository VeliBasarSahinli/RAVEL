// Auth endpoints — Faz 1'de eklenen Gateway sözleşmesi.

import { api } from "./client"

/**
 * Kullanıcı adı + şifre VEYA grade_level (anonim) ile giriş.
 * @returns {Promise<{access_token, expires_in, student_id, role, display_name}>}
 */
export async function login({ username, password, gradeLevel, role }) {
  const body = {}
  if (username && password) {
    body.username = username
    body.password = password
  } else if (gradeLevel != null) {
    body.grade_level = gradeLevel
    if (role) body.role = role
  } else {
    throw new Error("login: username/password veya gradeLevel gerekli")
  }
  const r = await api.post("/auth/login", body)
  return r.data
}

export async function register({ username, password, gradeLevel, displayName, role = "student" }) {
  const r = await api.post("/auth/register", {
    username,
    password,
    grade_level: gradeLevel,
    display_name: displayName,
    role,
  })
  return r.data
}

export async function fetchMe() {
  const r = await api.get("/auth/me")
  return r.data
}

export async function fetchProfile() {
  const r = await api.get("/api/profile")
  return r.data
}

export async function logout() {
  try {
    await api.post("/auth/logout")
  } catch {
    /* yoksa stateless JWT — sessizce yut */
  }
}
