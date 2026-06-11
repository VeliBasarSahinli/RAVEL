// Gamification: XP / streak / today_correct / kazanılan rozetler.
// Backend kaynağı: GET /api/profile (Adım 8a Faz 1).
// Faz 4'te BadgeEngine eklenecek; şimdilik ham XP/streak alanları.

import { create } from "zustand"

export const useGamificationStore = create((set) => ({
  xp: 0,
  streak: 0,
  todayCorrect: 0,
  correctTotal: 0,
  totalAttempts: 0,
  successRate: 0,
  badges: [],

  setFromProfile: (p) =>
    set({
      xp: p.xp ?? 0,
      streak: p.streak ?? 0,
      todayCorrect: p.today_correct ?? 0,
      correctTotal: p.correct_total ?? 0,
      totalAttempts: p.total_attempts ?? 0,
      successRate: p.success_rate ?? 0,
    }),

  addXP: (n) => set((s) => ({ xp: s.xp + (n || 0) })),
  bumpCorrect: () => set((s) => ({
    todayCorrect: s.todayCorrect + 1,
    correctTotal: s.correctTotal + 1,
  })),
  unlockBadge: (badge) => set((s) => ({
    badges: s.badges.includes(badge) ? s.badges : [...s.badges, badge],
  })),
  reset: () => set({
    xp: 0, streak: 0, todayCorrect: 0,
    correctTotal: 0, totalAttempts: 0, successRate: 0, badges: [],
  }),
}))
