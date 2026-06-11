<div align="center">

# 🎓 RAVEL

### Retrieve · Adapt · Video-Enhanced Learning

**Türkiye'deki 5–8. sınıf öğrencileri için AI destekli adaptif matematik eğitim platformu**

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![Kafka](https://img.shields.io/badge/Apache_Kafka-KRaft-231F20?logo=apachekafka)](https://kafka.apache.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![Status](https://img.shields.io/badge/status-pre--production-orange)]()

</div>

---

## 📑 İçindekiler

1. [RAVEL Nedir?](#-ravel-nedir)
2. [Öne Çıkan Özellikler](#-öne-çıkan-özellikler)
3. [Sistem Mimarisi](#-sistem-mimarisi)
4. [Teknoloji Yığını](#-teknoloji-yığını)
5. [Repo Yapısı](#-repo-yapısı)
6. [Hızlı Başlangıç (Quickstart)](#-hızlı-başlangıç-quickstart)
7. [Servisler ve Portlar](#-servisler-ve-portlar)
8. [Bağlamsal Bandit (RL Beyni)](#-bağlamsal-bandit-rl-beyni)
9. [Veri Tabanı Şemaları](#-veri-tabanı-şemaları)
10. [Kafka Topic'leri ve Veri Akışı](#-kafka-topicleri-ve-veri-akışı)
11. [LLM Gateway](#-llm-gateway)
12. [Konfigürasyon (.env Referansı)](#-konfigürasyon-env-referansı)
13. [Test Etme](#-test-etme)
14. [Frontend](#-frontend)
15. [Geliştirme Durumu (Roadmap)](#-geliştirme-durumu-roadmap)
16. [Sorun Giderme (Troubleshooting)](#-sorun-giderme-troubleshooting)
17. [Production Notları](#-production-notları)
18. [Mimari Karar Kayıtları (ADR)](#-mimari-karar-kayıtları-adr)
19. [Katkı ve Geliştirme Kuralları](#-katkı-ve-geliştirme-kuralları)

---

## 🎯 RAVEL Nedir?

RAVEL (**R**etrieve-**A**dapt-**V**ideo-**E**nhanced **L**earning), geleneksel
"herkese tek tip" eğitim yaklaşımının aksine, **her öğrencinin anlık bilişsel durumunu**
analiz ederek kavramsal yanılgıları gerçek zamanlı tespit eden ve en uygun müdahale
formatını **otonom olarak** belirleyen bir **"Dijital Özel Öğretmen"**dir.

Öğrenci bir soruda zorlandığında sistem, bir **Bağlamsal Bandit (Contextual Bandit / RL)**
modeliyle üç müdahaleden birini seçer:

| Eylem | Format | Üreten |
|:---:|---|---|
| **a1** | 📝 Metin ipucu | RAG |
| **a2** | 🪜 Aşamalı çözümlü örnek | RAG + LLM |
| **a3** | 🎬 Dinamik Manim videosu | LLM (kod) → Manim render |

> **Neden bu yaş grubu?** 5–8. sınıf, somuttan soyut düşünceye geçiş dönemidir. Bu dönemde
> oluşan kavram yanılgıları lise ve üniversite başarısını doğrudan etkiler. RAVEL bu yanılgıları
> erken yakalayıp kişiselleştirilmiş müdahaleyle düzeltmeyi hedefler.

**Konu kapsamı:** Matematik — çarpanlar/katlar, üslü/kareköklü ifadeler, geometri, cebirsel ifadeler.

---

## ✨ Öne Çıkan Özellikler

- 🧠 **Adaptif müdahale seçimi** — Linear Thompson Sampling (LinTS) tabanlı bağlamsal bandit, 12 boyutlu bağlam vektöründen <50ms'de karar üretir.
- 🎬 **Otonom video üretimi** — LLM, öğrenciye özel Manim animasyon kodu yazar; izole sandbox'ta güvenlik testinden geçirilip render edilir.
- 📚 **Halüsinasyonsuz içerik (RAG)** — Tüm pedagojik içerik gerçek soru havuzu ve konu anlatımlarından vektör arama ile çekilir.
- ⚡ **Gerçek zamanlı, olay güdümlü mimari** — Apache Kafka üzerinden 6 mikro servis asenkron haberleşir.
- 🔁 **Sıfır kesintili model güncelleme** — Bandit Learner yeni ağırlıkları MinIO'ya yazar, Redis Pub/Sub ile Actor'a hot-swap sinyali gider.
- 🔌 **Model-agnostik LLM Gateway** — Anthropic / OpenAI / Gemini / OpenRouter / Ollama / custom; ajan bazında DB'den yönetilir, API key'ler AES-256-GCM ile şifrelenir.
- 🎮 **Gamification'lı modern arayüz** — React + koyu uzay teması, XP/streak, 3 öğrenme modu (soru / video / sohbet).
- 🛡️ **Append-only event sourcing** — Etkileşim logları asla güncellenmez/silinmez; tam denetlenebilirlik.

---

## 🏗 Sistem Mimarisi

RAVEL **6 mikro servis** + altyapı katmanından oluşur. Tüm servisler Kafka üzerinden
asenkron haberleşir; sadece API Gateway (ve Frontend) dışarıya açıktır.

```
                                   ┌──────────────┐
                                   │   FRONTEND   │  React + Vite + nginx  (:5173)
                                   │ (admin+öğr.) │
                                   └──────┬───────┘
                                  HTTP/REST │ WebSocket
                                   ┌──────▼───────┐
                                   │ API GATEWAY  │  FastAPI · JWT · WS  (:8000)
                                   │  + Session   │◀────────── Redis (session/cache)
                                   └──────┬───────┘
                                          │ Kafka
        ┌─────────────────────────────────┼──────────────────────────────────┐
        │                                  │                                   │
 ┌──────▼───────┐   bandit_decision  ┌─────▼────────┐  content_retrieval ┌─────▼──────┐
 │ ORCHESTRATOR │◀──────────────────▶│    BANDIT    │   ┌───────────────▶│    RAG     │
 │  (sistem     │   _requests/_resp  │ Actor+Learner│   │  _requests/    │  (LlamaIdx │
 │   beyni)     │                    │   (LinTS)    │   │  _responses    │  + Qdrant) │
 │  LangGraph   │                    └──────┬───────┘   │                └─────┬──────┘
 └──┬────────┬──┘                           │           │                      │
    │        │ manim_render_tasks       DB-2│MinIO      │                 Qdrant│ MinIO
    │        │                          (logs)(weights) │                (vektör)(içerik)
    │        ▼                                           │
    │  ┌───────────────┐                                 │
    │  │ MANIM WORKER  │  AST sandbox → render → MinIO   │
    │  │ (izole, CPU)  │  video_ready_events             │
    │  └───────────────┘                                 │
    │                                                    │
    │  ┌───────────────┐         DB-2 (read-only)        │
    └─▶│  ANALYTICS *  │◀────────────────────────────────┘
       │ (g, MCR, RI)  │   * Adım 9 — HENÜZ YAZILMADI
       └───────────────┘     (services/analytics/README.md)
```

**Altyapı katmanı:** PostgreSQL (DB-1 + DB-2) + PgBouncer · Redis · Apache Kafka (KRaft) ·
Qdrant (vektör DB) · MinIO (S3 uyumlu obje deposu).

> ⚠️ **Not:** Analytics servisi (6/6) henüz kodlanmadı — yapım kılavuzu:
> [`services/analytics/README.md`](services/analytics/README.md).

---

## 🧰 Teknoloji Yığını

| Katman | Teknoloji |
|---|---|
| API Gateway | Python · FastAPI (async, WebSocket) · JWT |
| Orchestrator | Python · async (LangGraph deseni) · pybreaker (circuit breaker) |
| Bandit (ML) | Python · NumPy · SciPy (LinTS sıfırdan) |
| RAG | Python · LlamaIndex · sentence-transformers |
| Video Worker | Python · Manim · FFmpeg · LaTeX (izole container) |
| Analytics | Python · Polars · FastAPI *(planlandı)* |
| Frontend | React 18 · Vite 5 · Tailwind 3 · Zustand · Framer Motion · React Query · Recharts |
| Message Broker | Apache Kafka 3.8 (KRaft — Zookeeper yok) |
| Cache / Session | Redis 7.4 |
| İlişkisel DB | PostgreSQL 16 + PgBouncer (transaction pooling) |
| Vektör DB | Qdrant 1.11 |
| Obje Deposu | MinIO (S3 uyumlu) |
| Container | Docker + Docker Compose |
| Gözlemlenebilirlik | OpenTelemetry (trace_id hazır) · Jaeger/Prometheus/Grafana/ELK *(ertelendi)* |

---

## 📁 Repo Yapısı

```
project_ravel/
├── README.md                    ← bu dosya
├── CLAUDE.md                    ← detaylı proje referans belgesi (spec)
├── docker-compose.yml           ← tüm stack (altyapı + 6 servis + frontend)
├── .env.example                 ← ortam değişkeni şablonu (kopyala → .env)
├── docs/
│   ├── decisions.md             ← ADR — mimari karar günlüğü (ADR-001..019)
│   ├── modul-4-veri-akisi.md    ← veri akışı dokümantasyonu
│   └── manual_test_step8.md     ← frontend manuel test senaryoları
├── services/
│   ├── api_gateway/             ← FastAPI · JWT · WS · Kafka (:8000)
│   ├── orchestrator/            ← sistem beyni · workflow · circuit breaker (:8001)
│   ├── bandit/                  ← Actor + Learner · LinTS (:8002)
│   │   └── app/{actor,learner,lints}.py
│   ├── rag/                     ← retrieval + admin API · Qdrant (:8003)
│   │   └── app/parsers/{pdf,docx,excel}_parser.py
│   ├── manim_worker/            ← sandbox + render · MinIO (:8004)
│   ├── analytics/               ← ⚠️ YAZILMADI — blueprint: services/analytics/README.md
│   └── frontend/                ← React + Vite + nginx (:5173)
├── infra/
│   ├── postgres/                ← init.sql, init_app_role.sh, seed_admin.sh, migrations/
│   ├── pgbouncer/               ← pgbouncer.ini
│   ├── redis/ · kafka/ · milvus/
├── shared/
│   ├── kafka_schemas/           ← Kafka JSON şemaları
│   └── models/
└── scripts/                     ← test_*.sh, health_check.sh, generate_admin_token.sh
```

---

## 🚀 Hızlı Başlangıç (Quickstart)

### Ön Koşullar

- **Docker** + **Docker Compose v2** (tek zorunluluk — tüm stack container'da koşar)
- ~8 GB boş RAM (Manim Worker image ~1.6–1.9 GB; ilk build 10–15 dk sürer)
- (Opsiyonel, host-side geliştirme için) **Python 3.11** + her servis için `venv`
- macOS (Apple Silicon dahil — tüm imajlar ARM64 multi-arch) / Linux / WSL2

### 1. Repoyu klonla

```bash
git clone <repo-url> project_ravel
cd project_ravel
```

### 2. Ortam değişkenlerini hazırla

```bash
cp .env.example .env
```

`.env` dosyasını aç ve **en azından** şu sırları üret (dev için varsayılanlar çalışır
ama production'da MUTLAKA değiştir):

```bash
# JWT imzalama anahtarı
python -c 'import secrets; print(secrets.token_urlsafe(48))'

# LLM Gateway şifreleme anahtarı (64 hex char) — KAYBEDERSEN tüm api_key'ler okunamaz!
python -c 'import secrets; print(secrets.token_hex(32))'

# Kafka KRaft cluster id (gerekirse yenile)
docker run --rm apache/kafka:3.8.0 /opt/kafka/bin/kafka-storage.sh random-uuid
```

### 3. Tüm stack'i ayağa kaldır

```bash
docker compose up -d --build
```

İlk build'de Manim Worker uzun sürer (LaTeX + FFmpeg). Sıra: altyapı (Postgres, Kafka,
Redis, Qdrant, MinIO) `healthy` olur → servisler başlar → Kafka topic'leri otomatik oluşur
(her servis kendi topic'lerini `ensure_topics` ile yaratır, **min. 10 partition**).

### 4. Sağlık kontrolü

```bash
./scripts/health_check.sh
# veya tek tek:
curl http://localhost:8000/health     # API Gateway
curl http://localhost:8003/health     # RAG admin
docker compose ps                      # tüm container'lar "healthy" mi?
```

### 5. Arayüze gir

| Arayüz | URL | Giriş |
|---|---|---|
| **Frontend** | http://localhost:5173 | — |
| **Admin paneli** | http://localhost:5173 → admin | `.env`'deki `ADMIN_DEFAULT_USERNAME` / `ADMIN_DEFAULT_PASSWORD` |
| **MinIO konsolu** | http://localhost:9001 | `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` |
| **Qdrant** | http://localhost:6333/dashboard | — |

### Durdurma / sıfırlama

```bash
docker compose down            # container'ları durdur (veri kalır — named volumes)
docker compose down -v         # ⚠️ TÜM veriyi sil (Postgres/Kafka/Qdrant/MinIO volume'leri)
```

> **Not:** Postgres init script'leri (`init.sql`, `seed_admin.sh`, migration'lar) **yalnızca
> boş volume'de, ilk açılışta** çalışır. Şema değişikliği için ya migration ekle ya da
> `docker compose down -v` ile volume'ü sıfırla.

---

## 🔌 Servisler ve Portlar

| Servis | Port | Tip | Sorumluluk | Bağlı altyapı |
|---|:---:|---|---|---|
| **api_gateway** | 8000 | HTTP+WS | JWT auth, oturum, WS↔Kafka köprüsü | Redis, Kafka, DB-1, DB-2 |
| **orchestrator** | 8001 | health TCP | Sistem beyni: bandit→RAG/Manim→LLM akışı, circuit breaker | DB-1, DB-2, Redis, Kafka |
| **bandit** | 8002 | health TCP | Actor (inference <50ms) + Learner (policy update) | DB-2, Redis, MinIO, Kafka |
| **rag** | 8003 | HTTP | Vektör arama + içerik admin API + LLM admin | Qdrant, MinIO, Redis, DB-1, Kafka |
| **manim_worker** | 8004 | health TCP | LLM kod sandbox + render + MinIO upload | MinIO, Kafka |
| **analytics** ⚠️ | 8005 | HTTP | *(planlandı)* g/MCR/RI metrikleri | DB-2 (RO), Redis, Kafka |
| frontend | 5173 | HTTP | React SPA + nginx reverse proxy | api_gateway, rag |
| postgres | 5432 | — | DB-1 (`ravel_db1`) + DB-2 (`ravel_db2`) | — |
| pgbouncer | 6432 | — | Connection pooler (transaction mode) | postgres |
| redis | 6379 | — | Session, semantic cache, pub/sub | — |
| kafka | 9094 | — | Message broker (KRaft, dışa 9094 / iç 9092) | — |
| qdrant | 6333/6334 | — | Vektör DB (REST/gRPC) | — |
| minio | 9000/9001 | — | Obje deposu (S3 API / konsol) | — |

> **Production'da sadece Frontend (ve gerekiyorsa API Gateway) portu dışarı açılır;**
> geri kalan her şey `ravel_net` bridge ağında izole kalır.

---

## 🎰 Bağlamsal Bandit (RL Beyni)

### Bağlam Vektörü `x_t ∈ R^12`

| # | Özellik | Kaynak |
|:---:|---|---|
| x1 | Sınıf seviyesi (5–8) | DB-1 |
| x2,x3 | Öğrenme stili (görsel/sözel, one-hot) | DB-1 |
| x4 | Konu başarı oranı | DB-2 |
| x5 | Üst üste hata sayısı | DB-2 |
| x6 | Video tamamlama oranı | DB-2 |
| x7 | Soruda harcanan süre (z-score) | Redis |
| x8 | Odak/stres indeksi | Redis |
| x9 | "Video Oluştur" tıklaması | GUI |
| x10 | Önceki eylem geçmişi | Sistem |
| x11 | Konunun küresel zorluğu | Sistem |
| x12 | Bilişsel yorgunluk | Sistem |

### Ödül Fonksiyonu

```
r_t = α·C_t  +  β·(T_baseline / T_actual)  +  γ·S_t
        │             │                          │
   doğruluk      zaman verimliliği         öğrenci anketi
   (α=0.6)          (β=0.2)                   (γ=0.2)
```

- **C_t:** ilk denemede doğru `+1` · ipucuyla `+0.5` · yanlış `−1`
- **S_t:** "Anladım / Kısmen / Anlamadım" → normalize `[−1, +1]`

### Actor / Learner Ayrımı

- **Actor (Inference):** RAM'deki güncel politikayla <50ms'de karar üretir.
- **Learner:** Arka planda reward hesaplar, mini-batch (varsayılan 100) ile policy günceller.
- **Hot-Swap:** Learner yeni ağırlıkları MinIO'ya yazar → Redis Pub/Sub sinyali → Actor sıfır kesintiyle yeni ağırlıkları yükler.

### Bloom Taksonomisi (zorluk seviyeleri)

`A1` Hatırlama → `A2` Anlama → `B1` Uygulama → `B2` Analiz → `C1` Değerlendirme → `C2` Yaratma

---

## 🗄 Veri Tabanı Şemaları

Tek Postgres konteyneri, iki ayrı database (ADR-003). Tüm Python servisleri kısıtlı
**`ravel_app`** rolüyle, **PgBouncer üzerinden** bağlanır.

### DB-1 — `ravel_db1`

**`students`** (statik profil):
```sql
student_id            UUID PRIMARY KEY DEFAULT gen_random_uuid()
grade_level           INTEGER CHECK (5..8)
learning_style_vector REAL[2] DEFAULT [0.5, 0.5]   -- [görsel, sözel]
created_at            TIMESTAMPTZ
```

**`llm_configs`** (ajan bazında LLM konfigürasyonu — Adım 7):
```sql
agent_name   TEXT UNIQUE          -- "orchestrator_text" | "orchestrator_manim" | ...
provider     TEXT                 -- anthropic|openai|gemini|openrouter|ollama|custom
model_name   TEXT
api_key      BYTEA                -- AES-256-GCM: 12B nonce || ciphertext || 16B tag
max_tokens   INTEGER · temperature REAL · is_active BOOLEAN
```
> Auth tablosu `002_auth.sql` migration ile gelir; admin kullanıcı `seed_admin.sh` ile seed'lenir.

### DB-2 — `ravel_db2`  (append-only, event sourcing)

**`interaction_logs`**:
```sql
log_id              UUID PRIMARY KEY
student_id          UUID
topic_id            TEXT             -- "math_6_uslu_ifadeler"
taxonomic_level     TEXT             -- "A1".."C2"
action_taken        TEXT CHECK (text | step_by_step | video)
is_correct          BOOLEAN
time_spent_seconds  INTEGER
frustration_index   REAL CHECK (0.0..1.0)
reward_signal       REAL
"timestamp"         TIMESTAMPTZ
```

> 🚨 **KRİTİK:** Bu tabloya **asla UPDATE/DELETE yapılmaz.** `ravel_app` rolünün
> `interaction_logs` üzerindeki grant'ları sadece **SELECT + INSERT** (ADR-007). Yanlışlıkla
> UPDATE/DELETE denenirse Postgres izin katmanında reddeder. Her etkileşim **yeni satır**.

### Qdrant — `rag_knowledge_base` koleksiyonu

```json
{
  "chunk_id": "string (PK)",
  "embedding": "FloatVector (boyut .env'den — dev 384, prod 3072)",
  "text_content": "string",
  "metadata": {
    "content_type": "question | theory | explanation",
    "grade_level": 6, "subject": "Uslu_Ifadeler",
    "file_name": "6_mat_2", "test_no": 5, "question_number": 10,
    "taxonomic_level": "B1", "answer_key": "C"
  }
}
```

---

## 📨 Kafka Topic'leri ve Veri Akışı

Tüm topic'ler **min. 10 partition** (proje kuralı), RF=1 (dev). Topic'ler servisler
açıldığında otomatik oluşturulur (`ensure_topics`). Auto-create kapalı (`KAFKA_AUTO_CREATE_TOPICS_ENABLE=false`).

| Topic | Güzergah | Açıklama |
|---|---|---|
| `student_interactions_stream` | Gateway → Orchestrator, Bandit, Analytics | Her öğrenci etkileşimi |
| `session_lifecycle_events` | Gateway → Orchestrator, Bandit | Giriş/çıkış/boşta |
| `bandit_decision_requests` | Orchestrator → Bandit (Actor) | Müdahale kararı isteği |
| `bandit_decision_responses` | Bandit (Actor) → Orchestrator | Karar yanıtı (<50ms) |
| `reward_logs_stream` | Bandit (Actor) → Bandit (Learner) | ML eğitim verisi |
| `content_retrieval_requests` | Orchestrator → RAG | Pedagojik içerik talebi |
| `content_retrieval_responses` | RAG → Orchestrator | Vektör arama sonuçları |
| `manim_render_tasks` | Orchestrator → Manim Worker | LLM üretimi Manim kodu |
| `qa_correction_loop` | Manim Worker → Orchestrator | Hata düzeltme döngüsü |
| `video_ready_events` | Manim Worker → Gateway, Analytics | Video URL bildirimi |
| `content_delivery_stream` | Orchestrator → Gateway | Metin/tebrik içerikleri |
| `dead_letter_queue_ravel` | Hatalı servis → Orchestrator | Fallback yönetimi |

### Örnek akış: öğrenci soruyu yanlış yanıtlar

```
1. Öğrenci yanıtlar          → Gateway → student_interactions_stream
2. Orchestrator profili okur  (DB-1) → bandit_decision_requests
3. Bandit Actor karar verir   → bandit_decision_responses  (örn. "video")
4a. METİN ise:  Orchestrator → content_retrieval_requests → RAG → content_retrieval_responses
                → LLM ile pedagojik yanıt → content_delivery_stream → Gateway → WS → öğrenci
4b. VİDEO ise:  Orchestrator (LLM Manim kodu üretir) → manim_render_tasks
                → Manim Worker: AST sandbox → render → MinIO → video_ready_events → öğrenci
                → hata olursa qa_correction_loop (maks. 3 deneme) → aşılırsa DLQ → fallback metin
5. Reward:      Bandit Actor → reward_logs_stream → Learner → policy update → hot-swap
```

> **Varsayılan Metin Kuralı:** Tek bir soruda yanlış → Bandit beklenmeden direkt RAG+LLM
> **metin** yanıtı üretilir (kaynak tasarrufu). Video yalnızca (1) öğrenci "Video Oluştur"a
> bastığında veya (2) yeni ana konuya başlandığında tetiklenir.

JSON şemaları: [`shared/kafka_schemas/`](shared/kafka_schemas/) ve CLAUDE.md.

---

## 🤖 LLM Gateway

Tüm ajanlar (Orchestrator, RAG, Manim) **model-agnostik** soyutlama üzerinden LLM çağırır.
Hiçbir model import'ta sabitlenmez — config DB'den (`llm_configs`) yüklenir.

- **6 sağlayıcı:** `anthropic` · `openai` · `gemini` · `openrouter` · `ollama` · `custom`
- **Ajan bazında config:** `orchestrator_text` (4 mod: error_explanation / topic_teaching / step_by_step / qa_dialog), `orchestrator_manim` (manim_code), `orchestrator_correction` (manim_correction)
- **Prompt şablonları:** `services/orchestrator/app/prompts/*.yaml` (Jinja2 — hardcoded değil)
- **Güvenlik:** API key'ler **AES-256-GCM** ile şifreli saklanır (`ENCRYPTION_KEY`); chain-of-thought (`<düşünce>...</düşünce>`) blokları LLM'e gider ama **yanıttan temizlenir** (öğrenciye sızmaz).
- **Semantic cache:** Redis tabanlı (5dk TTL), maliyet düşürür.
- **Mock modu:** `LLM_MOCK_MODE=true` iken sabit Türkçe mock döner (test/dev). **Production'da `false`.**

> ⚠️ **`ENCRYPTION_KEY` kaybolursa** `llm_configs.api_key` sütunundaki tüm key'ler kalıcı
> olarak okunamaz hale gelir. `.env` yedeği zorunludur.

Admin paneli (`/admin/llm/*`) üzerinden CRUD + test + provider listesi yapılır.

---

## ⚙️ Konfigürasyon (.env Referansı)

**Tüm konfigürasyon `.env`'den okunur; kaynak kodda hardcoded değer yoktur** (proje kuralı #2).
Her servis `pydantic-settings` ile bu değişkenleri yükler. Tam liste için
[`.env.example`](.env.example) — başlıca bloklar:

| Blok | Önemli değişkenler |
|---|---|
| PostgreSQL | `POSTGRES_USER/PASSWORD`, `POSTGRES_APP_USER/PASSWORD`, `DB1_DSN`, `DB2_DSN` |
| Redis | `REDIS_PASSWORD`, `REDIS_URL` |
| Kafka | `KAFKA_CLUSTER_ID`, `KAFKA_EXTERNAL_PORT` |
| Qdrant | `QDRANT_URL`, `QDRANT_COLLECTION` |
| MinIO | `MINIO_ROOT_USER/PASSWORD`, `MINIO_BUCKET_{WEIGHTS,CONTENT,VIDEOS}` |
| Embedding | `EMBEDDING_MODEL` (dev: MiniLM-384 / prod: text-embedding-3-large-3072), `EMBEDDING_DIM` |
| Auth | `JWT_SECRET_KEY`, `JWT_ALGORITHM=HS256`, `JWT_EXPIRATION_SECONDS=7200` |
| Bandit | `BANDIT_CONTEXT_DIM=12`, `BANDIT_NUM_ACTIONS=3`, `REWARD_ALPHA/BETA/GAMMA` |
| RAG | `TOP_K=8`, `RERANK_TOP_N=3`, `SIMILARITY_THRESHOLD=0.45` |
| Manim | `MANIM_MAX_RETRIES=3`, `MANIM_RENDER_TIMEOUT_SECONDS=45`, `SANDBOX_ALLOWED_IMPORTS` |
| LLM Gateway | `ENCRYPTION_KEY` (64 hex), `LLM_MOCK_MODE`, `LLM_REQUEST_TIMEOUT_SECONDS` |
| Frontend/Auth | `ADMIN_DEFAULT_USERNAME/PASSWORD`, `FRONTEND_ORIGIN`, `FRONTEND_PORT=5173` |

> ⚠️ `.env`'deki tüm değerler **dev varsayılanı**dır. Production'a çıkmadan önce **hepsini
> döndürün** (özellikle `*_PASSWORD`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY`).

---

## 🧪 Test Etme

Her servis için `scripts/` altında bash test scriptleri var. Genel desen: renkli
`ok/fail/hdr` çıktısı, sonunda `PASS/FAIL` sayacı. **Adım 7 sonrası tam regresyon: 179/179 PASS.**

```bash
# Tümü ayağa kalkmışken sağlık
./scripts/health_check.sh

# Servis bazında (örnekler)
./scripts/test_api_gateway.sh
./scripts/test_auth_api.sh
./scripts/test_bandit_unit.sh          # LinTS doğruluk, <50ms SLA, hot-swap, append-only
./scripts/test_bandit_e2e.sh
./scripts/test_rag_unit.sh
./scripts/test_rag_e2e.sh
./scripts/test_orchestrator_e2e.sh
./scripts/test_orchestrator_robustness.sh
./scripts/test_manim_unit.sh
./scripts/test_manim_e2e.sh
./scripts/test_llm_unit.sh             # host unit
./scripts/test_llm_admin.sh            # admin API
./scripts/test_e2e_full.sh             # uçtan uca tam akış

# LLM gerçek API key ile e2e (manuel):
OPENROUTER_API_KEY=sk-... ./scripts/test_llm_e2e.sh
```

**Deterministik test için:** `BANDIT_FORCE_DECISION` env'i (örn. `"video"`) Bandit'in
stokastik LinTS örneklemesini bypass eder (ADR-017). **Production'da boş bırakılır.**

---

## 💻 Frontend

`services/frontend` — React 18 + Vite 5 + Tailwind 3 + Zustand + Framer Motion +
React Query + React Router v6 + Recharts (ADR-019).

- **Tema:** koyu uzay teması (CSS variable tabanlı), glassmorphism, Poppins/Inter font.
- **State machine:** `IDLE → TOPIC_LIST → TOPIC_INTRO → MODE_SELECT → QUESTION / VIDEO / CHAT`
- **4 ayrı Zustand store:** auth, learning (FSM), gamification (XP/streak), theme
- **Hibrit iletişim:** WebSocket (canlı müdahale) + REST (auth, içerik, admin)
- **Admin paneli (always-mounted):** LLM yönetimi, içerik yükleme, istatistikler, öğrenci kaydı
- **Build:** Vite → statik `dist/` → nginx multi-stage. Proxy: `/api`,`/auth`,`/ws` → gateway; `/admin` → rag.

Geliştirme modu (host'ta):
```bash
cd services/frontend
npm install
npm run dev          # Vite dev server (proxy backend'e yönlenir)
```

---

## 🛣 Geliştirme Durumu (Roadmap)

| Adım | İçerik | Durum |
|:---:|---|:---:|
| 1 | Altyapı (Kafka KRaft, Postgres+PgBouncer, Redis, Qdrant, MinIO) | ✅ |
| 2 | API Gateway (FastAPI, JWT, WS) + `ravel_app` kısıtlı rol | ✅ |
| 3 | Orchestrator (async, circuit breaker, iki consumer) | ✅ |
| 4 | Bandit (Actor + Learner, LinTS, hot-swap) | ✅ |
| 5 | RAG (Qdrant, ingestion, hybrid search, admin API) | ✅ |
| 6 | Manim Worker (AST sandbox, render, MinIO) | ✅ |
| 7 | LLM Gateway (6 provider, AES-256-GCM, prompt engine, admin) | ✅ |
| 8 | Frontend (React SPA + admin panel + gamification) | ✅ |
| **9** | **Analytics & Assessment (g / MCR / RI)** | ⚠️ **YAZILMADI** |
| — | Observability stack (Jaeger/Prometheus/Grafana/ELK) | ⏳ ertelendi |

➡️ **Sıradaki iş:** Analytics servisi. Eksiksiz yapım kılavuzu:
[`services/analytics/README.md`](services/analytics/README.md)

---

## 🔧 Sorun Giderme (Troubleshooting)

| Belirti | Olası sebep / çözüm |
|---|---|
| `bitnami/kafka` pull hatası | Kullanılmıyor; `apache/kafka:3.8.0` resmi imajı kullanılıyor (ADR-006). |
| asyncpg ilk sorgudan sonra sessizce patlıyor | PgBouncer transaction mode + prepared statement cache çakışması. `statement_cache_size=0` zorunlu (ADR-011). |
| Kafka topic'leri oluşmuyor | Auto-create kapalı; servisler `ensure_topics` ile yaratır. Servis loglarına bak. |
| Manim Worker build çok uzun / image büyük | Normal — LaTeX + FFmpeg + dvisvgm. İlk build 10–15 dk, ~1.6–1.9 GB. |
| Postgres şema değişikliği yansımıyor | Init script'leri sadece boş volume'de çalışır → migration ekle veya `docker compose down -v`. |
| LLM yanıtları hep aynı/Türkçe mock | `LLM_MOCK_MODE=true`. Gerçek LLM için `false` yap + `llm_configs`'a aktif config ekle. |
| `api_key`'ler okunamıyor | `ENCRYPTION_KEY` değişti/kayboldu — eski key olmadan kurtarılamaz. `.env` yedeği şart. |
| Frontend healthcheck fail | nginx IPv4-only; healthcheck `127.0.0.1` kullanır (BusyBox wget default'u `[::1]`). |
| Video kararı 45sn'yi aşıyor | Timeout → DLQ devreye girer, fallback metin sunulur (tasarım gereği). |

---

## 🏭 Production Notları

Bu repo **canlıya alınmak üzere** geliştirilmektedir. Dev → prod geçişinde:

- 🔐 **Tüm sırları döndür** — `*_PASSWORD`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY`, MinIO/Redis kimlikleri.
- 🔒 **PgBouncer auth** — dev `auth_type=plain`; prod'da `scram-sha-256` + hashed userlist / auth_query.
- 🌐 **Sadece Frontend/Gateway dışa açık** — geri kalan her şey bridge ağında.
- 📈 **Embedding** — prod'da `text-embedding-3-large` (3072 dim); `EMBEDDING_DIM` ve Qdrant koleksiyonu buna göre.
- 🧠 **`LLM_MOCK_MODE=false`** + `llm_configs`'a gerçek provider/key.
- 🎚 **`BANDIT_FORCE_DECISION` boş** olmalı (yalnızca test override).
- 📊 **Observability'i devreye al** — `trace_id` altyapısı hazır (ADR-004); Jaeger/Prometheus/Grafana/ELK eklenince kod değişmez.
- 📦 **Kafka** — multi-broker + RF≥3; partition sayısı SLA'ya göre (kritik topic'ler min. 10).
- 🗃 **Postgres** — DB-1/DB-2 fiziksel ayrım gerekirse compose'da iki servis; aktif bağlantı limiti 200 (PgBouncer).
- ⚖️ **Auto-scaling** — yük artışında öncelikle Manim Worker replica sayısı artırılır.

### SLA Hedefleri

| Metrik | Hedef |
|---|---|
| Eşzamanlı kullanıcı | 5.000 aktif öğrenci |
| Kafka throughput | 2.000 EPS |
| Bandit inference | < 50 ms |
| RAG + LLM metin yanıtı | < 1.5 sn |
| Manim render timeout | ≤ 45 sn |
| PostgreSQL aktif bağlantı | 200 (PgBouncer) |

---

## 📐 Mimari Karar Kayıtları (ADR)

Önemli her mimari karar **iki yerde** kayıt altında: [`docs/decisions.md`](docs/decisions.md)
(ADR formatı) ve proje hafızası. Mevcut: **ADR-001 … ADR-019**.

Öne çıkanlar: Qdrant (001) · Kafka KRaft (002) · tek-Postgres-iki-DB (003) · observability
ertelendi (004) · Python 3.11 (005) · Apache Kafka imajı (006) · `ravel_app` kısıtlı rol (007) ·
asyncpg+PgBouncer cache tuzağı (011) · iki consumer ayrımı (013) · Manim sandbox (017) ·
LLM Gateway (018) · Frontend (019).

> Yeni karar eklerken sıradaki numara **ADR-020**. Format: bağlam → karar → gerekçe → sonuçlar.

---

## 🤝 Katkı ve Geliştirme Kuralları

Aşağıdaki kurallar **bağlayıcıdır** Dikkat:

1. Her servis kendi `venv`'inde çalışır; bağımlılıklar `requirements.txt`'te **pinli**.
2. Tüm konfigürasyon `.env`'den okunur — **hardcoded değer yok**.
3. **DB-2'ye asla UPDATE/DELETE yapılmaz** — yalnızca INSERT (append-only).
4. Kafka mesajları her zaman tanımlı JSON şemasına uygun olmalı.
5. Her Kafka topic'i **min. 10 partition** ile oluşturulur.
6. Manim Worker kodu **önce sandbox'ta test eder**, direkt render etmez.
7. LLM modeli asla import'ta belirtilmez — **factory/config** üzerinden yüklenir.
8. **`trace_id` her Kafka mesajında taşınır** (servisler arası izlenebilirlik).

Yeni servis yazarken referans desenler: multi-stage Dockerfile (non-root uid 1000, venv) ·
`pydantic-settings` config (`lru_cache`'li `get_settings`) · lifespan-driven startup/shutdown ·
`aiokafka` wrapper'ları · asyncpg `statement_cache_size=0`. En temiz örnek:
`services/bandit` ve `services/rag`.

---

<div align="center">

**RAVEL** — *Her öğrenciye kendi öğretmeni.*

Karar günlüğü → [`docs/decisions.md`](docs/decisions.md)

</div>
