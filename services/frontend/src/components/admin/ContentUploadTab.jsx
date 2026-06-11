// İçerik Yükleme — iki bağımsız kart:
//
// Kart 1 — Konu Anlatımı (POST /admin/upload/theory)
//   PDF/DOCX + Sınıf + Konu (CURRICULUM'dan). Excel gerekmez.
//
// Kart 2 — Soru Havuzu (iki aşama)
//   Aşama 1: Excel index → POST /admin/upload/excel
//   Aşama 2: Sınıf + Konu + PDF/DOCX → POST /admin/upload/questions
//   Excel taxonomic_level/answer_key/test_no'yu eşliyor; subject + grade_level
//   admin tarafından açıkça verilir → chunk metadata'sına işlenir.
//
// Her iki kart kendi state'i içinde — biri diğerini etkilemez.

import { motion, AnimatePresence } from "framer-motion"
import { useState } from "react"
import {
  uploadExcelIndex,
  uploadQuestionFile,
  uploadTheoryFile,
} from "../../api/admin"
import { CURRICULUM, GRADES } from "../../data/curriculum"
import DropZone from "./DropZone"

export default function ContentUploadTab() {
  return (
    <div className="grid grid-cols-1 gap-5">
      <TheoryUploadCard />
      <QuestionPoolCard />
    </div>
  )
}

// ─── Kart 1: Konu Anlatımı ──────────────────────────────────────────

function TheoryUploadCard() {
  const [file, setFile] = useState(null)
  const [gradeLevel, setGradeLevel] = useState(6)
  const [topicId, setTopicId] = useState("")
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  const fileType = file?.name?.toLowerCase().endsWith(".docx") ? "docx" : "pdf"
  const topicsForGrade = CURRICULUM[gradeLevel]?.topics || []
  const canUpload = Boolean(file) && Boolean(topicId) && !busy

  async function submit() {
    if (!canUpload) return
    setBusy(true); setError(null); setResult(null); setProgress(0)
    try {
      const out = await uploadTheoryFile(
        file, fileType, gradeLevel, topicId,
        (p) => setProgress(Math.round(p * 100)),
      )
      setResult(out)
    } catch (err) {
      setError(formatError(err))
    } finally {
      setBusy(false)
      setProgress(100)
    }
  }

  function reset() {
    setFile(null); setResult(null); setError(null); setProgress(0)
  }

  return (
    <CardShell
      icon="🎓"
      title="Konu Anlatımı Yükle"
      desc="PDF veya DOCX seç, sınıfı ve konuyu eşle. Excel gerekmez."
      accent="purple"
    >
      <div className="space-y-3">
        <DropZone
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          disabled={busy}
          hint="pdf veya docx · konu anlatımı dosyası"
          onFile={setFile}
        />

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Select
            label="Sınıf"
            value={String(gradeLevel)}
            onChange={(v) => { setGradeLevel(Number(v)); setTopicId("") }}
            disabled={busy}
            options={GRADES.map((g) => ({ value: String(g), label: `${g}. sınıf` }))}
          />
          <Select
            label="Konu"
            value={topicId}
            onChange={setTopicId}
            disabled={busy}
            placeholder={`${gradeLevel}. sınıftan konu seç…`}
            options={topicsForGrade.map((t) => ({
              value: t.id, label: `${t.icon} ${t.label}`,
            }))}
          />
        </div>

        {busy && <ProgressBar value={progress} accent="purple" />}

        {error && <ErrorBanner>{error}</ErrorBanner>}

        {result && (
          <SuccessBanner>
            "{result.file_name}" işlendi ·{" "}
            <strong>{result.written_chunks ?? result.parsed_chunks ?? 0}</strong>{" "}
            chunk yazıldı (atlanan: {result.skipped_chunks ?? 0}, hatalı:{" "}
            {result.failed_chunks ?? 0}).
          </SuccessBanner>
        )}

        <div className="flex gap-2 pt-1">
          <button
            type="button"
            onClick={submit}
            disabled={!canUpload}
            className="rounded-xl bg-ravel-purple px-5 py-2.5 text-sm font-medium text-white hover:bg-ravel-purple/90 hover:shadow-glow-purple transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {busy ? "Yükleniyor…" : "Yükle"}
          </button>
          {(result || error) && (
            <button
              type="button"
              onClick={reset}
              className="rounded-xl bg-ravel-elevated/80 px-4 py-2.5 text-sm text-ravel-muted hover:text-ravel-text transition-colors"
            >
              Yeni Dosya
            </button>
          )}
        </div>
      </div>
    </CardShell>
  )
}

// ─── Kart 2: Soru Havuzu (iki aşama) ────────────────────────────────

function QuestionPoolCard() {
  // Aşama 1
  const [excelFile, setExcelFile] = useState(null)
  const [excelBusy, setExcelBusy] = useState(false)
  const [excelProgress, setExcelProgress] = useState(0)
  const [excelResult, setExcelResult] = useState(null)
  const [excelError, setExcelError] = useState(null)

  // Aşama 2
  const [qFile, setQFile] = useState(null)
  const [qGradeLevel, setQGradeLevel] = useState(6)
  const [qTopicId, setQTopicId] = useState("")
  const [qBusy, setQBusy] = useState(false)
  const [qProgress, setQProgress] = useState(0)
  const [qResult, setQResult] = useState(null)
  const [qError, setQError] = useState(null)

  const excelLoaded = Boolean(excelResult)
  const fileType = qFile?.name?.toLowerCase().endsWith(".docx") ? "docx" : "pdf"
  const qTopicsForGrade = CURRICULUM[qGradeLevel]?.topics || []

  async function submitExcel() {
    if (!excelFile || excelBusy) return
    setExcelBusy(true); setExcelError(null); setExcelResult(null); setExcelProgress(0)
    try {
      const out = await uploadExcelIndex(
        excelFile, (p) => setExcelProgress(Math.round(p * 100)),
      )
      setExcelResult(out)
    } catch (err) {
      setExcelError(formatError(err))
    } finally {
      setExcelBusy(false)
      setExcelProgress(100)
    }
  }

  async function submitQuestions() {
    if (!qFile || qBusy || !excelLoaded || !qTopicId) return
    setQBusy(true); setQError(null); setQResult(null); setQProgress(0)
    try {
      const out = await uploadQuestionFile(
        qFile, fileType, qGradeLevel, qTopicId,
        (p) => setQProgress(Math.round(p * 100)),
      )
      setQResult(out)
    } catch (err) {
      setQError(formatError(err))
    } finally {
      setQBusy(false)
      setQProgress(100)
    }
  }

  function resetQuestions() {
    setQFile(null); setQResult(null); setQError(null); setQProgress(0)
  }

  const canUploadQuestions = excelLoaded && Boolean(qFile) && Boolean(qTopicId) && !qBusy

  return (
    <CardShell
      icon="📝"
      title="Soru Havuzu Yükle"
      desc="Önce Excel index, sonra sınıf/konu seçip soru dosyasını yükle. Excel taxonomic_level ve answer_key'i eşler; sınıf/konu metadata bu kart üzerinden yazılır."
      accent="blue"
    >
      <div className="space-y-5">
        {/* Aşama 1 */}
        <Stage step="1" title="Excel Index">
          <DropZone
            accept=".xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            disabled={excelBusy}
            hint="xlsx · soru-havuzu eşleştirme tablosu"
            onFile={setExcelFile}
          />

          {excelBusy && <ProgressBar value={excelProgress} accent="blue" />}

          {excelError && <ErrorBanner>{excelError}</ErrorBanner>}

          {excelResult && (
            <SuccessBanner>
              <strong>{excelResult.rows_or_chunks ?? 0}</strong> satır okundu ·
              "{excelResult.file_name}" yüklendi.
            </SuccessBanner>
          )}

          <button
            type="button"
            onClick={submitExcel}
            disabled={!excelFile || excelBusy}
            className="rounded-xl bg-ravel-blue px-5 py-2.5 text-sm font-medium text-white hover:bg-ravel-blue/90 hover:shadow-glow transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {excelBusy
              ? "Yükleniyor…"
              : excelLoaded
                ? "Yeniden Yükle"
                : "Index'i Yükle"}
          </button>
        </Stage>

        {/* Aşama 2 */}
        <Stage
          step="2"
          title="Soru Dosyası"
          locked={!excelLoaded}
        >
          <AnimatePresence initial={false}>
            {!excelLoaded && (
              <motion.div
                key="locked-warn"
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="rounded-xl border border-ravel-gold/30 bg-ravel-gold/5 px-3 py-2 text-xs text-ravel-gold"
              >
                ⓘ Önce 1. aşamada Excel index yükle.
              </motion.div>
            )}
          </AnimatePresence>

          <div className={excelLoaded ? "space-y-3" : "space-y-3 pointer-events-none opacity-50"}>
            <DropZone
              accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              disabled={!excelLoaded || qBusy}
              hint="pdf veya docx · soru havuzu dosyası"
              onFile={setQFile}
            />

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Select
                label="Sınıf"
                value={String(qGradeLevel)}
                onChange={(v) => { setQGradeLevel(Number(v)); setQTopicId("") }}
                disabled={!excelLoaded || qBusy}
                options={GRADES.map((g) => ({ value: String(g), label: `${g}. sınıf` }))}
              />
              <Select
                label="Konu"
                value={qTopicId}
                onChange={setQTopicId}
                disabled={!excelLoaded || qBusy}
                placeholder={`${qGradeLevel}. sınıftan konu seç…`}
                options={qTopicsForGrade.map((t) => ({
                  value: t.id, label: `${t.icon} ${t.label}`,
                }))}
              />
            </div>

            {qBusy && <ProgressBar value={qProgress} accent="blue" />}

            {qError && <ErrorBanner>{qError}</ErrorBanner>}

            {qResult && (
              <SuccessBanner>
                "{qResult.file_name}" işlendi ·{" "}
                <strong>{qResult.written_chunks ?? qResult.parsed_chunks ?? 0}</strong>{" "}
                chunk yazıldı (atlanan: {qResult.skipped_chunks ?? 0}, hatalı:{" "}
                {qResult.failed_chunks ?? 0}).
              </SuccessBanner>
            )}

            <div className="flex gap-2 pt-1">
              <button
                type="button"
                onClick={submitQuestions}
                disabled={!canUploadQuestions}
                className="rounded-xl bg-ravel-blue px-5 py-2.5 text-sm font-medium text-white hover:bg-ravel-blue/90 hover:shadow-glow transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {qBusy ? "Yükleniyor…" : "Yükle"}
              </button>
              {(qResult || qError) && (
                <button
                  type="button"
                  onClick={resetQuestions}
                  className="rounded-xl bg-ravel-elevated/80 px-4 py-2.5 text-sm text-ravel-muted hover:text-ravel-text transition-colors"
                >
                  Yeni Dosya
                </button>
              )}
            </div>
          </div>
        </Stage>
      </div>
    </CardShell>
  )
}

// ─── Shared shells ─────────────────────────────────────────────────

function CardShell({ icon, title, desc, accent, children }) {
  const ringClass =
    accent === "purple" ? "ring-ravel-purple/30" : "ring-ravel-blue/30"
  const iconBg =
    accent === "purple" ? "bg-ravel-purple/15 text-ravel-purple" : "bg-ravel-blue/15 text-ravel-blue"
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={[
        "rounded-2xl border border-white/10 bg-ravel-elevated/40 p-5",
        "ring-1", ringClass,
      ].join(" ")}
    >
      <div className="flex items-start gap-3">
        <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl text-xl ${iconBg}`}>
          {icon}
        </span>
        <div className="min-w-0">
          <h3 className="font-display text-base font-semibold text-ravel-text">
            {title}
          </h3>
          <p className="mt-0.5 text-xs text-ravel-muted leading-relaxed">{desc}</p>
        </div>
      </div>
      <div className="mt-5">{children}</div>
    </motion.section>
  )
}

function Stage({ step, title, locked, children }) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <span className={[
          "grid h-6 w-6 place-items-center rounded-full font-display text-[11px] font-bold",
          locked
            ? "bg-ravel-elevated text-ravel-muted"
            : "bg-ravel-blue/20 text-ravel-blue ring-1 ring-ravel-blue/40",
        ].join(" ")}>
          {step}
        </span>
        <h4 className={[
          "font-display text-sm font-semibold",
          locked ? "text-ravel-muted" : "text-ravel-text",
        ].join(" ")}>
          {title}
        </h4>
      </div>
      <div className="space-y-3">{children}</div>
    </div>
  )
}

function Select({ label, value, onChange, options, disabled, placeholder }) {
  return (
    <label className="block">
      <span className="text-xs uppercase tracking-widest text-ravel-muted">
        {label}
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="mt-1.5 w-full rounded-xl border border-white/10 bg-ravel-elevated/80 px-3.5 py-2.5 text-sm text-ravel-text focus:outline-none focus:ring-2 focus:ring-ravel-purple/50 disabled:opacity-60"
      >
        {placeholder && <option value="">{placeholder}</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </label>
  )
}

function ProgressBar({ value, accent }) {
  const color = accent === "purple" ? "bg-ravel-purple" : "bg-ravel-blue"
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-ravel-elevated">
      <motion.div
        className={`h-full ${color}`}
        initial={false}
        animate={{ width: `${Math.min(value, 100)}%` }}
        transition={{ duration: 0.3 }}
      />
    </div>
  )
}

function SuccessBanner({ children }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl border border-ravel-green/40 bg-ravel-green/10 px-3 py-2 text-sm text-ravel-green"
    >
      ✓ {children}
    </motion.div>
  )
}

function ErrorBanner({ children }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl border border-ravel-red/40 bg-ravel-red/10 px-3 py-2 text-sm text-ravel-red"
    >
      {children}
    </motion.div>
  )
}

function formatError(err) {
  const status = err?.response?.status
  const detail = err?.response?.data?.detail
  if (status === 400) return Array.isArray(detail) ? detail[0]?.msg : detail || "İstek geçersiz."
  if (status === 401) return "Yetkin sona erdi, tekrar giriş yap."
  if (status === 403) return "Bu işlem için yönetici yetkisi gerekli."
  if (status === 413) return "Dosya çok büyük."
  if (status === 422) return Array.isArray(detail) ? detail[0]?.msg : detail || "Form verileri geçersiz."
  if (status === 503) return "RAG servisi şu an erişilebilir değil."
  if (err?.code === "ERR_NETWORK") return "Sunucuya ulaşılamıyor."
  return detail || err?.message || "Beklenmeyen bir hata oluştu."
}
