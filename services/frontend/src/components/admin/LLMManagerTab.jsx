// LLM Yönetimi — 3 ajan kartı: orchestrator_text / orchestrator_manim /
// orchestrator_correction. Her ajanın provider/model/key durumu + Düzenle
// butonu inline form açar. Kaydet → POST /admin/llm/config (upsert).
// Test Et → POST /admin/llm/test/{agent}.

import { motion, AnimatePresence } from "framer-motion"
import { useEffect, useState } from "react"
import {
  listLLMConfigs,
  listProviders,
  upsertLLMConfig,
  deleteLLMConfig,
  testLLMConfig,
} from "../../api/admin"

// 3 sabit ajan + her birinin kullandığı prompt modları (Adım 7c).
const AGENTS = [
  {
    name: "orchestrator_text",
    label: "Metin Öğretmeni",
    desc: "Soru çözüm yardımı, konu anlatımı, soru-cevap diyalogu.",
    modes: ["error_explanation", "topic_teaching", "step_by_step", "qa_dialog"],
    accent: "blue",
  },
  {
    name: "orchestrator_manim",
    label: "Manim Kod Üreticisi",
    desc: "Konu anlatım videoları için Manim sahne kodu.",
    modes: ["manim_code"],
    accent: "purple",
  },
  {
    name: "orchestrator_correction",
    label: "Manim Düzeltici",
    desc: "Sandbox/render hatası alan Manim kodunu düzeltir.",
    modes: ["manim_correction"],
    accent: "gold",
  },
]

const PROVIDER_HINTS = {
  anthropic:  { needsKey: true,  needsEndpoint: false, modelPlaceholder: "claude-sonnet-4-6" },
  openai:     { needsKey: true,  needsEndpoint: false, modelPlaceholder: "gpt-4o" },
  openrouter: { needsKey: true,  needsEndpoint: false, modelPlaceholder: "anthropic/claude-sonnet-4-5" },
  gemini:     { needsKey: true,  needsEndpoint: false, modelPlaceholder: "gemini-1.5-pro" },
  ollama:     { needsKey: false, needsEndpoint: true,  modelPlaceholder: "llama3.1:8b" },
  custom:     { needsKey: false, needsEndpoint: true,  modelPlaceholder: "modelin-adi" },
}

const ACCENT_CSS = {
  blue:   { ring: "ring-ravel-blue/40",   text: "text-ravel-blue",   tag: "bg-ravel-blue/10 text-ravel-blue" },
  purple: { ring: "ring-ravel-purple/40", text: "text-ravel-purple", tag: "bg-ravel-purple/10 text-ravel-purple" },
  gold:   { ring: "ring-ravel-gold/40",   text: "text-ravel-gold",   tag: "bg-ravel-gold/10 text-ravel-gold" },
}

export default function LLMManagerTab() {
  const [configs, setConfigs] = useState(null)        // null = loading
  const [providers, setProviders] = useState(null)
  const [error, setError] = useState(null)
  const [editing, setEditing] = useState(null)        // agent_name | null

  async function load() {
    setError(null)
    try {
      const [cfg, prv] = await Promise.all([
        listLLMConfigs(),
        listProviders(),
      ])
      setConfigs(cfg)
      setProviders(prv)
    } catch (err) {
      setError(formatError(err))
    }
  }

  useEffect(() => { load() }, [])

  function configFor(name) {
    return (configs || []).find((c) => c.agent_name === name)
  }

  return (
    <div className="space-y-4">
      <div>
        <h3 className="font-display text-base font-semibold text-ravel-text">
          LLM Sağlayıcı Konfigürasyonu
        </h3>
        <p className="mt-1 text-xs text-ravel-muted leading-relaxed">
          Her ajan için ayrı sağlayıcı seçebilirsin. Anahtarlar AES-256-GCM ile
          şifrelenip DB-1'de saklanır; arayüzde yalnızca ilk 4 karakter
          maskelenmiş gösterilir.
        </p>
      </div>

      {error && (
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
      )}

      {!error && configs == null && <Skeleton />}

      {!error && configs != null && (
        <div className="space-y-3">
          {AGENTS.map((agent) => (
            <AgentCard
              key={agent.name}
              agent={agent}
              config={configFor(agent.name)}
              providers={providers}
              isEditing={editing === agent.name}
              onEdit={() => setEditing(agent.name)}
              onCancel={() => setEditing(null)}
              onSaved={async () => { setEditing(null); await load() }}
              onDeleted={async () => { setEditing(null); await load() }}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ─── AgentCard ───────────────────────────────────────────────────

function AgentCard({ agent, config, providers, isEditing, onEdit, onCancel, onSaved, onDeleted }) {
  const a = ACCENT_CSS[agent.accent]
  const configured = Boolean(config)

  return (
    <div className={[
      "rounded-2xl border bg-ravel-elevated/40 p-4 transition-all",
      configured ? `border-white/10 ring-1 ${a.ring}` : "border-white/5 border-dashed",
    ].join(" ")}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h4 className={`font-display text-sm font-semibold ${a.text}`}>
              {agent.label}
            </h4>
            <code className="text-[10px] uppercase tracking-widest text-ravel-muted bg-ravel-elevated rounded px-1.5 py-0.5">
              {agent.name}
            </code>
          </div>
          <p className="mt-1 text-xs text-ravel-muted leading-relaxed">{agent.desc}</p>

          {/* Mod etiketleri */}
          <div className="mt-2 flex flex-wrap gap-1">
            {agent.modes.map((m) => (
              <span key={m} className={`text-[10px] px-1.5 py-0.5 rounded-md ${a.tag}`}>
                {m}
              </span>
            ))}
          </div>

          {/* Mevcut config özeti */}
          {configured ? (
            <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
              <KV k="Sağlayıcı" v={config.provider} />
              <KV k="Model" v={config.model_name} />
              <KV k="API Key" v={config.api_key_set ? config.api_key_masked || "✓ kayıtlı" : "—"} />
              <KV k="Tokens / Temp"
                  v={`${config.max_tokens} · ${config.temperature.toFixed(2)}`} />
            </dl>
          ) : (
            <p className="mt-3 text-xs text-ravel-muted italic">
              Henüz yapılandırılmamış. Düzenle'ye tıkla.
            </p>
          )}
        </div>

        {!isEditing && (
          <button
            type="button"
            onClick={onEdit}
            className={[
              "shrink-0 rounded-lg px-3 py-1.5 text-xs font-medium transition-all",
              configured
                ? "bg-ravel-elevated/80 text-ravel-text hover:bg-ravel-elevated"
                : `bg-ravel-elevated text-ravel-text hover:shadow-glow ring-1 ${a.ring}`,
            ].join(" ")}
          >
            {configured ? "Düzenle" : "Yapılandır"}
          </button>
        )}
      </div>

      <AnimatePresence initial={false}>
        {isEditing && (
          <motion.div
            key="form"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
          >
            <div className="mt-4 border-t border-white/5 pt-4">
              <ConfigForm
                agentName={agent.name}
                accent={agent.accent}
                existing={config}
                providers={providers || []}
                onCancel={onCancel}
                onSaved={onSaved}
                onDeleted={onDeleted}
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function KV({ k, v }) {
  return (
    <>
      <dt className="text-ravel-muted">{k}</dt>
      <dd className="text-ravel-text font-medium tabular-nums truncate">{v}</dd>
    </>
  )
}

// ─── Inline form ─────────────────────────────────────────────────

function ConfigForm({ agentName, accent, existing, providers, onCancel, onSaved, onDeleted }) {
  const [provider, setProvider] = useState(existing?.provider || "openrouter")
  const [modelName, setModelName] = useState(existing?.model_name || "")
  const [apiKey, setApiKey] = useState("")               // her zaman boş başla
  const [endpointUrl, setEndpointUrl] = useState(existing?.endpoint_url || "")
  const [maxTokens, setMaxTokens] = useState(existing?.max_tokens || 1024)
  const [temperature, setTemperature] = useState(existing?.temperature ?? 0.7)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [testResult, setTestResult] = useState(null)

  const hint = PROVIDER_HINTS[provider] || PROVIDER_HINTS.openrouter
  const accentCSS = ACCENT_CSS[accent] || ACCENT_CSS.blue

  // Mevcut key varsa "kayıtlı" placeholder'ı, yoksa direkt
  const apiKeyPlaceholder = existing?.api_key_set
    ? "••••••••  (mevcut key korunur, yeni girersen değişir)"
    : "sk-..."

  async function save() {
    setBusy(true); setError(null); setTestResult(null)
    try {
      const payload = {
        agent_name: agentName,
        provider,
        model_name: modelName.trim() || hint.modelPlaceholder,
        max_tokens: Number(maxTokens),
        temperature: Number(temperature),
      }
      if (apiKey) payload.api_key = apiKey
      if (hint.needsEndpoint) payload.endpoint_url = endpointUrl.trim()
      // Anahtar eskiden vardı + form key boş + sağlayıcı key gerektiriyor: backend
      // upsert mevcut blob'u kaybetmesin diye PUT kullanmalı.
      if (existing && !apiKey) {
        // patchLLMConfig sadece dolu alanları gönderir ve api_key blob'u korur.
        const { patchLLMConfig } = await import("../../api/admin")
        const patch = {
          provider, model_name: payload.model_name,
          max_tokens: payload.max_tokens, temperature: payload.temperature,
        }
        if (hint.needsEndpoint) patch.endpoint_url = payload.endpoint_url
        await patchLLMConfig(agentName, patch)
      } else {
        await upsertLLMConfig(payload)
      }
      onSaved()
    } catch (err) {
      setError(formatError(err))
    } finally {
      setBusy(false)
    }
  }

  async function runTest() {
    if (!existing && !apiKey && hint.needsKey) {
      setError("Test etmeden önce API key gir.")
      return
    }
    setBusy(true); setError(null); setTestResult(null)
    try {
      // Yeni veya değiştirilmiş key varsa önce kaydet, sonra test et.
      // Bu sayede test gerçek DB config'i ile çalışır.
      if (apiKey || !existing) {
        const payload = {
          agent_name: agentName, provider,
          model_name: modelName.trim() || hint.modelPlaceholder,
          max_tokens: Number(maxTokens), temperature: Number(temperature),
        }
        if (apiKey) payload.api_key = apiKey
        if (hint.needsEndpoint) payload.endpoint_url = endpointUrl.trim()
        await upsertLLMConfig(payload)
      }
      const r = await testLLMConfig(agentName)
      setTestResult(r)
    } catch (err) {
      setError(formatError(err))
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    if (!existing) { onCancel(); return }
    if (!confirm(`'${agentName}' konfigürasyonu silinsin mi?`)) return
    setBusy(true); setError(null)
    try {
      await deleteLLMConfig(agentName)
      onDeleted()
    } catch (err) {
      setError(formatError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Sağlayıcı">
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            disabled={busy}
            className="w-full rounded-xl border border-white/10 bg-ravel-elevated/80 px-3.5 py-2.5 text-sm text-ravel-text focus:outline-none focus:ring-2 focus:ring-ravel-blue/50"
          >
            {(providers.length ? providers : Object.keys(PROVIDER_HINTS)).map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </Field>

        <Field label="Model adı">
          <input
            type="text"
            value={modelName}
            placeholder={hint.modelPlaceholder}
            onChange={(e) => setModelName(e.target.value)}
            disabled={busy}
            className="w-full rounded-xl border border-white/10 bg-ravel-elevated/80 px-3.5 py-2.5 text-sm text-ravel-text placeholder:text-ravel-muted/60 focus:outline-none focus:ring-2 focus:ring-ravel-blue/50"
          />
        </Field>
      </div>

      {hint.needsKey && (
        <Field label="API Key">
          <input
            type="password"
            value={apiKey}
            placeholder={apiKeyPlaceholder}
            onChange={(e) => setApiKey(e.target.value)}
            disabled={busy}
            autoComplete="new-password"
            className="w-full rounded-xl border border-white/10 bg-ravel-elevated/80 px-3.5 py-2.5 text-sm text-ravel-text placeholder:text-ravel-muted/60 focus:outline-none focus:ring-2 focus:ring-ravel-purple/50"
          />
        </Field>
      )}

      {hint.needsEndpoint && (
        <Field label="Endpoint URL">
          <input
            type="text"
            value={endpointUrl}
            placeholder="http://host.docker.internal:11434"
            onChange={(e) => setEndpointUrl(e.target.value)}
            disabled={busy}
            className="w-full rounded-xl border border-white/10 bg-ravel-elevated/80 px-3.5 py-2.5 text-sm text-ravel-text placeholder:text-ravel-muted/60 focus:outline-none focus:ring-2 focus:ring-ravel-blue/50"
          />
        </Field>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Slider
          label={`Max tokens · ${maxTokens}`}
          min={256} max={4096} step={128}
          value={maxTokens} onChange={setMaxTokens} disabled={busy}
        />
        <Slider
          label={`Temperature · ${Number(temperature).toFixed(2)}`}
          min={0} max={2} step={0.05}
          value={temperature} onChange={setTemperature} disabled={busy}
        />
      </div>

      {error && (
        <div className="rounded-xl border border-ravel-red/40 bg-ravel-red/10 px-3 py-2 text-sm text-ravel-red">
          {error}
        </div>
      )}

      {testResult && (
        <TestResult result={testResult} />
      )}

      <div className="flex flex-wrap items-center gap-2 pt-1">
        <button
          type="button"
          onClick={save}
          disabled={busy}
          className={[
            "rounded-xl px-4 py-2 text-sm font-medium text-white transition-all disabled:opacity-40 disabled:cursor-not-allowed",
            accent === "purple"
              ? "bg-ravel-purple hover:bg-ravel-purple/90 hover:shadow-glow-purple"
              : accent === "gold"
                ? "bg-ravel-gold hover:bg-ravel-gold/90 hover:shadow-glow-gold"
                : "bg-ravel-blue hover:bg-ravel-blue/90 hover:shadow-glow",
          ].join(" ")}
        >
          {busy ? "İşleniyor…" : "Kaydet"}
        </button>
        <button
          type="button"
          onClick={runTest}
          disabled={busy}
          className="rounded-xl bg-ravel-elevated/80 border border-white/10 px-4 py-2 text-sm font-medium text-ravel-text hover:bg-ravel-elevated transition-all disabled:opacity-40"
        >
          {busy ? "…" : "Test Et"}
        </button>
        {existing && (
          <button
            type="button"
            onClick={remove}
            disabled={busy}
            className="rounded-xl bg-ravel-red/15 border border-ravel-red/30 px-4 py-2 text-sm font-medium text-ravel-red hover:bg-ravel-red/25 transition-all disabled:opacity-40"
          >
            Sil
          </button>
        )}
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="ml-auto text-sm text-ravel-muted hover:text-ravel-text"
        >
          İptal
        </button>
      </div>
    </div>
  )
}

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="text-xs uppercase tracking-widest text-ravel-muted">
        {label}
      </span>
      <div className="mt-1.5">{children}</div>
    </label>
  )
}

function Slider({ label, min, max, step, value, onChange, disabled }) {
  return (
    <Field label={label}>
      <input
        type="range" min={min} max={max} step={step}
        value={value} disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-ravel-purple"
      />
    </Field>
  )
}

function TestResult({ result }) {
  const ok = Boolean(result?.ok)
  return (
    <motion.div
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      className={[
        "rounded-xl border px-3 py-2 text-sm",
        ok
          ? "border-ravel-green/40 bg-ravel-green/10 text-ravel-green"
          : "border-ravel-gold/40 bg-ravel-gold/10 text-ravel-gold",
      ].join(" ")}
    >
      <div className="flex items-center justify-between">
        <span className="font-medium">
          {ok ? "✓ Bağlantı başarılı" : "⚠ Bağlantı başarısız"}
        </span>
        <span className="text-xs tabular-nums opacity-80">
          {result.latency_ms} ms
        </span>
      </div>
      {result.sample_text && (
        <p className="mt-2 text-xs text-ravel-text/80 italic break-words">
          "{result.sample_text}"
        </p>
      )}
      {result.error && (
        <p className="mt-1 text-xs opacity-90 break-words">{result.error}</p>
      )}
    </motion.div>
  )
}

function Skeleton() {
  return (
    <div className="space-y-3">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="rounded-2xl border border-white/5 bg-ravel-elevated/30 p-4"
        >
          <div className="h-4 w-32 rounded bg-ravel-elevated animate-pulse" />
          <div className="mt-2 h-3 w-3/4 rounded bg-ravel-elevated/60 animate-pulse" />
          <div className="mt-3 h-3 w-1/2 rounded bg-ravel-elevated/60 animate-pulse" />
        </div>
      ))}
    </div>
  )
}

function formatError(err) {
  const status = err?.response?.status
  const detail = err?.response?.data?.detail
  if (status === 400) return Array.isArray(detail) ? detail[0]?.msg : detail || "İstek geçersiz."
  if (status === 401) return "Yetkin sona erdi, tekrar giriş yap."
  if (status === 403) return "Bu işlem için yönetici yetkisi gerekli."
  if (status === 404) return "Konfigürasyon bulunamadı."
  if (status === 409) return "Çakışma — başka bir kayıt var."
  if (status === 422) return Array.isArray(detail) ? detail[0]?.msg : detail || "Form verileri geçersiz."
  if (status === 503) return "Servis erişilebilir değil (DB veya ENCRYPTION_KEY)."
  if (err?.code === "ERR_NETWORK") return "Sunucuya ulaşılamıyor."
  return detail || err?.message || "Beklenmeyen bir hata oluştu."
}
