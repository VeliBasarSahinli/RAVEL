// İstatistikler — RAG /admin/stats verisi.
//   - Toplam chunk (büyük rakam)
//   - Pie: question vs theory dağılımı (mavi/mor)
//   - Bar: file_name başına chunk sayısı

import { motion } from "framer-motion"
import { useEffect, useState } from "react"
import {
  PieChart, Pie, Cell, Tooltip,
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  ResponsiveContainer, Legend,
} from "recharts"
import { fetchStats } from "../../api/admin"

const RAVEL = {
  blue:   "#3B82F6",
  purple: "#8B5CF6",
  gold:   "#F59E0B",
  green:  "#10B981",
  red:    "#EF4444",
  text:   "#F9FAFB",
  muted:  "#9CA3AF",
  surf:   "#1F2937",
  bg:     "#111827",
}

const CONTENT_COLORS = {
  question:    RAVEL.blue,
  theory:      RAVEL.purple,
  explanation: RAVEL.gold,
}

export default function StatisticsTab() {
  const [stats, setStats] = useState(null)
  const [error, setError] = useState(null)

  async function load() {
    setError(null)
    try {
      const data = await fetchStats()
      setStats(data)
    } catch (err) {
      setError(formatError(err))
    }
  }

  useEffect(() => { load() }, [])

  if (error) {
    return (
      <div className="rounded-xl border border-ravel-red/40 bg-ravel-red/10 px-3 py-2 text-sm text-ravel-red">
        {error}
        <button
          onClick={load}
          type="button"
          className="ml-3 rounded-lg bg-ravel-red/20 px-3 py-1 text-xs hover:bg-ravel-red/30"
        >
          Tekrar dene
        </button>
      </div>
    )
  }

  if (stats == null) {
    return (
      <div className="space-y-3">
        <Skeleton h="h-24" />
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Skeleton h="h-56" />
          <Skeleton h="h-56" />
        </div>
      </div>
    )
  }

  const total = stats.total_chunks || 0
  const isEmpty = total === 0

  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between gap-3">
        <div>
          <h3 className="font-display text-base font-semibold text-ravel-text">
            Vektör DB İstatistikleri
          </h3>
          <p className="mt-1 text-xs text-ravel-muted">
            Koleksiyon: <code className="text-ravel-text">{stats.collection_name}</code> ·
            <span className="ml-1">vektör boyutu: <strong className="text-ravel-text">{stats.vector_dim}</strong></span>
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          className="rounded-lg bg-ravel-elevated/80 px-3 py-1.5 text-xs text-ravel-muted hover:text-ravel-text transition-colors"
        >
          ↻ Yenile
        </button>
      </div>

      {/* Toplam chunk büyük */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="rounded-2xl border border-white/10 bg-gradient-to-br from-ravel-blue/15 via-ravel-elevated/60 to-ravel-purple/15 px-6 py-7 text-center"
      >
        <p className="text-[10px] uppercase tracking-widest text-ravel-muted">
          Toplam chunk
        </p>
        <p className="mt-1 font-display text-5xl font-bold text-aurora tabular-nums">
          {total.toLocaleString("tr-TR")}
        </p>
      </motion.div>

      {isEmpty ? (
        <EmptyState />
      ) : (
        <>
          <ContentTypePie byType={stats.by_content_type || {}} />
          <FileBarChart byFile={stats.by_file_name || {}} />
        </>
      )}
    </div>
  )
}

// ─── Pie chart ───────────────────────────────────────────────────

function ContentTypePie({ byType }) {
  const data = Object.entries(byType)
    .filter(([, v]) => v > 0)
    .map(([key, value]) => ({
      name: prettyType(key),
      key,
      value,
    }))

  if (data.length === 0) return null

  return (
    <ChartCard title="Tür Dağılımı" desc="question vs theory">
      <ResponsiveContainer width="100%" height={240}>
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="name"
            cx="50%"
            cy="50%"
            innerRadius={50}
            outerRadius={90}
            paddingAngle={3}
            stroke="none"
          >
            {data.map((d) => (
              <Cell
                key={d.key}
                fill={CONTENT_COLORS[d.key] || RAVEL.muted}
              />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{
              backgroundColor: RAVEL.bg,
              border: `1px solid ${RAVEL.surf}`,
              borderRadius: 12,
              color: RAVEL.text,
            }}
            cursor={false}
          />
          <Legend
            wrapperStyle={{ color: RAVEL.muted, fontSize: 12 }}
            iconType="circle"
          />
        </PieChart>
      </ResponsiveContainer>
    </ChartCard>
  )
}

// ─── Bar chart ───────────────────────────────────────────────────

function FileBarChart({ byFile }) {
  // En çok chunk'a sahip ilk 10
  const data = Object.entries(byFile)
    .filter(([k, v]) => k && k !== "null" && v > 0)
    .map(([file_name, chunks]) => ({
      file_name,
      chunks,
      label: shortenFileName(file_name),
    }))
    .sort((a, b) => b.chunks - a.chunks)
    .slice(0, 10)

  if (data.length === 0) {
    return (
      <ChartCard title="Konu Bazlı Chunk" desc="file_name başına chunk sayısı">
        <p className="text-xs text-ravel-muted py-8 text-center">
          Henüz konu bazlı kayıt yok.
        </p>
      </ChartCard>
    )
  }

  return (
    <ChartCard
      title="Konu Bazlı Chunk"
      desc={`En çok chunk'a sahip ${data.length} dosya`}
    >
      <ResponsiveContainer width="100%" height={Math.max(180, data.length * 32)}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 16, left: 8, bottom: 4 }}
        >
          <CartesianGrid stroke={RAVEL.surf} strokeDasharray="3 3" horizontal={false} />
          <XAxis
            type="number"
            stroke={RAVEL.muted}
            fontSize={11}
            allowDecimals={false}
          />
          <YAxis
            type="category"
            dataKey="label"
            stroke={RAVEL.muted}
            fontSize={11}
            width={150}
            interval={0}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: RAVEL.bg,
              border: `1px solid ${RAVEL.surf}`,
              borderRadius: 12,
              color: RAVEL.text,
            }}
            cursor={{ fill: "rgba(139,92,246,0.08)" }}
            formatter={(value) => [value, "chunks"]}
            labelFormatter={(_, payload) =>
              payload?.[0]?.payload?.file_name || ""
            }
          />
          <Bar dataKey="chunks" fill={RAVEL.blue} radius={[0, 6, 6, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  )
}

// ─── Helpers ─────────────────────────────────────────────────────

function ChartCard({ title, desc, children }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-2xl border border-white/10 bg-ravel-elevated/40 p-4"
    >
      <div className="mb-3 flex items-baseline justify-between">
        <h4 className="font-display text-sm font-semibold text-ravel-text">
          {title}
        </h4>
        {desc && <span className="text-[10px] uppercase tracking-widest text-ravel-muted">{desc}</span>}
      </div>
      {children}
    </motion.div>
  )
}

function EmptyState() {
  return (
    <div className="rounded-2xl border border-dashed border-white/10 bg-ravel-elevated/30 px-6 py-12 text-center">
      <div className="text-5xl">📭</div>
      <p className="mt-3 font-display text-base text-ravel-text">
        Henüz içerik yüklenmedi
      </p>
      <p className="mt-1 text-xs text-ravel-muted">
        "İçerik Yükleme" sekmesinden Excel index ve PDF/DOCX dosyalarını ekle.
      </p>
    </div>
  )
}

function Skeleton({ h = "h-24" }) {
  return <div className={`w-full ${h} rounded-2xl bg-ravel-elevated/40 animate-pulse`} />
}

function prettyType(k) {
  return ({
    question:    "Soru",
    theory:      "Konu Anlatımı",
    explanation: "Açıklama",
  })[k] || k
}

function shortenFileName(s) {
  if (!s) return ""
  // "step5_e2e_set" → "step5_e2e_set"; "6_kesirler_pool" → kalır.
  // 22 karakterden uzunsa baş/son kırp.
  if (s.length <= 22) return s
  return s.slice(0, 14) + "…" + s.slice(-6)
}

function formatError(err) {
  const status = err?.response?.status
  const detail = err?.response?.data?.detail
  if (status === 401) return "Yetkin sona erdi, tekrar giriş yap."
  if (status === 403) return "Bu işlem için yönetici yetkisi gerekli."
  if (status === 503) return "RAG servisi şu an erişilebilir değil."
  if (err?.code === "ERR_NETWORK") return "Sunucuya ulaşılamıyor."
  return detail || err?.message || "İstatistik yüklenemedi."
}
