// Ortak markdown render bileşeni — LLM açıklamalarını **bold**, ###
// başlık, listeler, oklar (→) gibi markdown ile düzgün gösterir.
//
// Kullanım: <Markdown body={msg.body_html} variant="card" />
//   - variant="card"  → öğretmen açıklama kartı (purple aksanlı başlıklar)
//   - variant="chat"  → daha kompakt sohbet baloncuğu
//   - variant="intro" → konu anlatımı sayfası (büyük gövde)

import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

const VARIANTS = {
  card:  { size: "text-sm",   spacing: "leading-relaxed" },
  chat:  { size: "text-sm",   spacing: "leading-relaxed" },
  intro: { size: "text-[15px]", spacing: "leading-relaxed" },
}

export default function Markdown({ body, variant = "card" }) {
  const v = VARIANTS[variant] || VARIANTS.card
  return (
    <div className={`text-ravel-text ${v.size} ${v.spacing}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: (p) => <h3 className="font-display text-base font-semibold text-ravel-text mt-3 mb-1.5" {...p} />,
          h2: (p) => <h3 className="font-display text-base font-semibold text-ravel-text mt-3 mb-1.5" {...p} />,
          h3: (p) => <h4 className="font-display text-sm font-semibold text-ravel-purple uppercase tracking-widest mt-3 mb-1.5" {...p} />,
          h4: (p) => <h5 className="font-display text-sm font-semibold text-ravel-text mt-2 mb-1" {...p} />,
          p:  (p) => <p className="mb-2 last:mb-0" {...p} />,
          ul: (p) => <ul className="my-2 ml-5 list-disc space-y-1" {...p} />,
          ol: (p) => <ol className="my-2 ml-5 list-decimal space-y-1" {...p} />,
          li: (p) => <li className="leading-relaxed" {...p} />,
          strong: (p) => <strong className="font-semibold text-ravel-text" {...p} />,
          em: (p) => <em className="text-ravel-muted" {...p} />,
          code: (p) => <code className="rounded bg-ravel-bg/60 px-1 py-0.5 text-[0.85em] text-ravel-blue" {...p} />,
          a: (p) => <a className="text-ravel-blue hover:underline" target="_blank" rel="noreferrer" {...p} />,
          blockquote: (p) => <blockquote className="my-2 border-l-2 border-ravel-purple/50 pl-3 italic text-ravel-muted" {...p} />,
          hr: () => <hr className="my-3 border-white/10" />,
        }}
      >
        {String(body || "")}
      </ReactMarkdown>
    </div>
  )
}
