// RAVEL frontend — Tailwind config (Adım 8)
// Spec'teki sıkı palet + Poppins (display) / Inter (body) ikilisi.

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        ravel: {
          // Backgrounds — CSS variable üzerinden, .light/.dark ile değişir.
          bg:       "var(--ravel-bg)",
          surface:  "var(--ravel-surface)",
          elevated: "var(--ravel-elevated)",
          // Text — CSS variable.
          text:     "var(--ravel-text)",
          muted:    "var(--ravel-muted)",
          // Accents — sabit; her iki temada da aynı kalır.
          blue:     "#3B82F6",
          purple:   "#8B5CF6",
          gold:     "#F59E0B",
          green:    "#10B981",
          red:      "#EF4444",
        },
      },
      fontFamily: {
        // Poppins for display/headlines (600/700)
        display: ["Poppins", "ui-sans-serif", "system-ui"],
        // Inter for body (400/500)
        sans:    ["Inter", "ui-sans-serif", "system-ui"],
      },
      boxShadow: {
        glow:    "0 0 32px -4px rgba(59,130,246,0.45)",
        "glow-purple": "0 0 32px -4px rgba(139,92,246,0.45)",
        "glow-gold":   "0 0 32px -4px rgba(245,158,11,0.45)",
        elevated:      "0 12px 32px -8px rgba(0,0,0,0.55)",
      },
      backgroundImage: {
        "gradient-aurora":
          "radial-gradient(circle at 20% 30%, #3B82F6 0%, transparent 40%), " +
          "radial-gradient(circle at 80% 60%, #8B5CF6 0%, transparent 45%), " +
          "linear-gradient(180deg, #0A0F1E 0%, #111827 100%)",
        "text-aurora":
          "linear-gradient(135deg, #3B82F6 0%, #8B5CF6 50%, #F59E0B 100%)",
      },
      animation: {
        "float-slow": "float 18s ease-in-out infinite",
        "float-slower": "float 24s ease-in-out infinite",
        "shimmer": "shimmer 2.5s linear infinite",
        "shake":   "shake 0.45s cubic-bezier(.36,.07,.19,.97) both",
        "pulse-soft": "pulseSoft 1.6s ease-in-out infinite",
      },
      keyframes: {
        float: {
          "0%, 100%": { transform: "translateY(0) rotate(0deg)" },
          "50%":      { transform: "translateY(-22px) rotate(8deg)" },
        },
        shimmer: {
          "0%":   { backgroundPosition: "0% 50%" },
          "100%": { backgroundPosition: "200% 50%" },
        },
        shake: {
          "10%, 90%": { transform: "translateX(-2px)" },
          "20%, 80%": { transform: "translateX(4px)" },
          "30%, 50%, 70%": { transform: "translateX(-8px)" },
          "40%, 60%": { transform: "translateX(8px)" },
        },
        pulseSoft: {
          "0%, 100%": { opacity: "0.6" },
          "50%":      { opacity: "1" },
        },
      },
    },
  },
  plugins: [],
}
