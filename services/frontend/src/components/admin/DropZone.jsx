// Sürükle-bırak alanı: native HTML5 drag events + dosya seç fallback'i.

import { useRef, useState } from "react"

export default function DropZone({
  accept,
  onFile,
  disabled,
  hint,
  label = "Dosyayı buraya sürükle veya tıkla",
}) {
  const inputRef = useRef(null)
  const [isOver, setOver] = useState(false)
  const [picked, setPicked] = useState(null)

  function reset() {
    setPicked(null)
    if (inputRef.current) inputRef.current.value = ""
  }

  function handleFile(file) {
    if (!file) return
    setPicked(file)
    onFile?.(file)
  }

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); if (!disabled) setOver(true) }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setOver(false)
        if (disabled) return
        const f = e.dataTransfer?.files?.[0]
        if (f) handleFile(f)
      }}
      onClick={() => !disabled && inputRef.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if ((e.key === "Enter" || e.key === " ") && !disabled) {
          e.preventDefault()
          inputRef.current?.click()
        }
      }}
      className={[
        "relative cursor-pointer rounded-2xl border-2 border-dashed",
        "px-5 py-7 text-center transition-all",
        disabled
          ? "border-white/5 bg-ravel-elevated/30 cursor-not-allowed opacity-60"
          : isOver
            ? "border-ravel-purple/60 bg-ravel-purple/10"
            : "border-white/15 bg-ravel-elevated/40 hover:border-ravel-purple/40 hover:bg-ravel-elevated/60",
      ].join(" ")}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        disabled={disabled}
        onChange={(e) => handleFile(e.target.files?.[0])}
        className="hidden"
      />

      {picked ? (
        <div>
          <p className="font-display text-sm font-medium text-ravel-text break-all">
            📄 {picked.name}
          </p>
          <p className="mt-1 text-xs text-ravel-muted">
            {(picked.size / 1024).toFixed(1)} KB · değiştirmek için tıkla
          </p>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); reset() }}
            className="mt-3 text-xs text-ravel-muted underline hover:text-ravel-text"
          >
            Kaldır
          </button>
        </div>
      ) : (
        <div>
          <p className="text-3xl">📂</p>
          <p className="mt-2 text-sm text-ravel-text">{label}</p>
          {hint && <p className="mt-1 text-xs text-ravel-muted">{hint}</p>}
        </div>
      )}
    </div>
  )
}
