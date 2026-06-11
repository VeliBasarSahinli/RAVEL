# RAVEL — Proje Referans Belgesi (CLAUDE.md)

## Projenin Özeti

RAVEL (Retrieve-Adapt-Video-Enhanced Learning), Türkiye'deki 5-8. sınıf öğrencilerine yönelik
AI destekli adaptif bir matematik eğitim platformudur. Geleneksel "herkese tek tip" yaklaşımının
aksine, öğrencinin anlık bilişsel durumunu analiz ederek kavramsal yanılgıları gerçek zamanlı
tespit eder ve en uygun müdahale formatını (metin, aşamalı örnek veya Manim videosu) otonom
olarak belirler. Sistem bir "Dijital Özel Öğretmen" olarak tasarlanmıştır.

---

## Hedef Kitle ve Kapsam

- **Yaş grubu:** 5, 6, 7, 8. sınıf ortaokul öğrencileri
- **Konu:** Matematik (çarpanlar/katlar, üslü/kareköklü ifadeler, geometri, cebirsel ifadeler)
- **Neden bu kitle?** Somuttan soyut düşünceye geçiş döneminde oluşan kavram yanılgıları
  lise ve üniversite başarısını doğrudan etkiler.

---

## Teknoloji Yığını (Tech Stack)

| Katman | Teknoloji |
|---|---|
| API Gateway | Python / FastAPI (async, WebSocket) |
| Orchestrator | Python / LangGraph veya LlamaIndex Workflow |
| Bandit (ML) | Python / PyTorch veya Scikit-learn |
| RAG Servisi | Python / LlamaIndex, Embedding Modelleri |
| Video Worker | Python / Manim, FFmpeg, LaTeX |
| Analytics | Python / Pandas veya Polars |
| Frontend (GUI) | React.js, Socket.io/WebSocket, Redux |
| Message Broker | Apache Kafka |
| Cache / Session | Redis |
| İlişkisel DB | PostgreSQL + PgBouncer (connection pooling) |
| Vektör DB | Milvus veya Qdrant |
| Dosya Deposu | MinIO (S3 uyumlu) |
| Container | Docker + Docker Compose |
| Gözlemlenebilirlik | OpenTelemetry, Jaeger, Prometheus, Grafana, ELK Stack |

---

## Mimari: 6 Mikro Servis

### 1. API Gateway & Session Management
- **Teknoloji:** FastAPI + Redis
- **Görevler:**
  - JWT kimlik doğrulama ve oturum yönetimi
  - Öğrencinin anlık durumunu Redis'te tutar
  - GUI'den gelen HTTP/WebSocket isteklerini Kafka'ya yazar
  - İç servislerden gelen yanıtları WebSocket ile GUI'ye iter

### 2. RAVEL Orchestrator Agent Service (Sistem Beyni)
- **Teknoloji:** LangGraph / LlamaIndex Workflow + Kafka
- **Bağlı DB:** PostgreSQL DB-1
- **Görevler:**
  - Öğrenci profilini DB-1'den okur
  - Bandit servisine karar isteği atar
  - Metin kararında → RAG servisini tetikler, LLM ile pedagojik yanıt üretir
  - Video kararında → RAG verisini alır, Manim kodu ürettirip kuyruğa atar
  - Circuit Breaker ile hata izolasyonu sağlar

### 3. Contextual Bandit (RL) Service
- **Teknoloji:** PyTorch / Scikit-learn + Kafka
- **Bağlı DB:** PostgreSQL DB-2 + Redis
- **Algoritma:** Linear Thompson Sampling (LinTS) — Bayesyen yaklaşım
- **Alt süreçler:**
  - **Aktör (Inference):** RAM'deki güncel politikayla <50ms'de karar üretir
  - **Öğrenici (Learner):** Arka planda reward hesaplar, mini-batch ile policy günceller
- **Hot-Swapping:** Öğrenici yeni ağırlıkları MinIO'ya yazar → Redis Pub/Sub ile Aktör'e sinyal → sıfır kesintili model güncellemesi

### 4. RAG & Content Retrieval Service
- **Teknoloji:** LlamaIndex + Embedding Modelleri + Kafka
- **Bağlı DB:** Milvus/Qdrant + MinIO
- **Görevler:**
  - PDF/DOCX soru havuzu ve konu anlatımlarını vektörleştirir
  - Hybrid search ile content_type, taxonomic_level, grade_level filtreli sorgular çalıştırır
  - Orkestratör'e halüsinasyonsuz pedagojik içerik döner

### 5. Manim QA & Video Worker Service
- **Teknoloji:** Python Manim + Subprocess/AST güvenlik modülleri
- **Bağlı DB:** MinIO
- **Görevler:**
  - LLM'nin ürettiği Manim Python kodunu sandbox'ta test eder
  - Hata varsa → `qa_correction_loop` ile Orkestratör'e geri gönderir (maks. deneme sayısı var)
  - Başarılıysa GPU/CPU'da render eder (.mp4), MinIO'ya yükler
  - `video_ready_events` ile URL'yi sisteme bildirir
  - Timeout: **45 saniye** — aşılırsa DLQ devreye girer, fallback metin sunulur

### 6. Assessment & Analytics Service
- **Teknoloji:** Pandas / Polars
- **Bağlı DB:** PostgreSQL DB-2 (read-only)
- **Görevler:**
  - Öğrenme Kazancı (g), Yanılgı Düzeltme Oranı (MCR), Kalıcılık İndeksi (RI) hesaplar
  - A/B testi ve öğretmen/yönetici panelleri için analitik veri hazırlar

---

## Bağlamsal Bandit Detayları

### Bağlam Vektörü: x_t ∈ R^12

| # | Özellik | Kaynak | Tip |
|---|---|---|---|
| x1 | Sınıf seviyesi (5-8) | DB-1 | Sürekli |
| x2, x3 | Öğrenme stili (görsel/sözel, one-hot) | DB-1 | [1,0] / [0,1] / [0.5,0.5] |
| x4 | Mevcut konu başarı oranı (0-1) | DB-2 | Sürekli |
| x5 | Üst üste hata sayısı | DB-2 | Sürekli |
| x6 | Geçmiş video tamamlama oranı | DB-2 | Sürekli |
| x7 | Mevcut soruda harcanan süre (z-score) | Redis | Sürekli |
| x8 | Odak/stres indeksi | Redis | Sürekli |
| x9 | "Video Oluştur" butonuna tıklama | GUI | Binary (0/1) |
| x10 | Önceki eylem geçmişi (1/2/3) | Sistem | Kategorik |
| x11 | Konunun küresel zorluk katsayısı | Sistem | Sürekli (0-1) |
| x12 | Bilişsel yorgunluk katsayısı | Sistem | Sürekli |

### Eylem Uzayı: A = {a1, a2, a3}
- **a1:** Metin ipucu (RAG)
- **a2:** Aşamalı örnek (RAG + LLM)
- **a3:** Dinamik Manim videosu

### Ödül Fonksiyonu
```
r_t = α·C_t + β·(T_baseline / T_actual) + γ·S_t
```
- **C_t:** İlk denemede doğru → +1, ipucuyla → +0.5, yanlış → -1
- **T_baseline/T_actual:** Zaman verimliliği (video işe yaramazsa ağır ceza)
- **S_t:** Öğrencinin "Anladım/Kısmen/Anlamadım" anketi → normalize [-1, +1]
- **Ağırlıklar (hiperparametre):** α=0.6, β=0.2, γ=0.2

### Bloom Taksonomisi (Zorluk Seviyeleri)
A1 (Hatırlama) → A2 (Anlama) → B1 (Uygulama) → B2 (Analiz) → C1 (Değerlendirme) → C2 (Yaratma)

---

## Veri Tabanı Şemaları

### PostgreSQL DB-1 — students tablosu (Statik Profil)
```sql
student_id         UUID PRIMARY KEY
grade_level        INTEGER (5-8)
learning_style_vector  FLOAT[2] DEFAULT [0.5, 0.5]
created_at         TIMESTAMP
```

### PostgreSQL DB-2 — interaction_logs tablosu (Append-Only, Event Sourcing)
```sql
log_id             UUID PRIMARY KEY
student_id         UUID FOREIGN KEY
topic_id           STRING  -- örn: "math_6_uslu_ifadeler"
taxonomic_level    STRING  -- örn: "B1", "B2"
action_taken       STRING  -- 'text' | 'step_by_step' | 'video'
is_correct         BOOLEAN
time_spent_seconds INTEGER
frustration_index  FLOAT (0.0-1.0)
reward_signal      FLOAT
timestamp          TIMESTAMP
```
> **KRİTİK:** Bu tabloya asla UPDATE veya DELETE yapılmaz. Her etkileşim yeni satır olarak INSERT edilir.

### Vektör DB (Milvus/Qdrant) — rag_knowledge_base koleksiyonu
```json
{
  "chunk_id": "string (PK)",
  "embedding": "FloatVector (boyut .env'den)",
  "text_content": "string",
  "metadata": {
    "content_type": "question | theory | explanation",
    "grade_level": 6,
    "subject": "Uslu_Ifadeler",
    "file_name": "6_mat_2",
    "test_no": 5,
    "question_number": 10,
    "taxonomic_level": "B1",
    "answer_key": "C"
  }
}
```
> content_type "theory" ise test_no, question_number, answer_key alanları null bırakılır.

---

## Kafka Topic'leri

### Gateway Çıkışlı
| Topic | Güzergah | Açıklama |
|---|---|---|
| `student_interactions_stream` | Gateway → Orchestrator, Bandit(Learner), Analytics | Her öğrenci etkileşimi |
| `session_lifecycle_events` | Gateway → Orchestrator, Bandit | Giriş/çıkış/boşta olayları |

### Bandit İletişimi
| Topic | Güzergah | Açıklama |
|---|---|---|
| `bandit_decision_requests` | Orchestrator → Bandit(Actor) | Müdahale kararı isteği |
| `bandit_decision_responses` | Bandit(Actor) → Orchestrator | Karar yanıtı (<50ms) |
| `reward_logs_stream` | Bandit(Actor) → Bandit(Learner) | ML eğitim verisi |

### RAG İletişimi
| Topic | Güzergah | Açıklama |
|---|---|---|
| `content_retrieval_requests` | Orchestrator → RAG | Pedagojik içerik talebi |
| `content_retrieval_responses` | RAG → Orchestrator | Vektör arama sonuçları |

### Manim İletişimi
| Topic | Güzergah | Açıklama |
|---|---|---|
| `manim_render_tasks` | Orchestrator → Manim Worker | LLM üretimi Manim kodu |
| `qa_correction_loop` | Manim Worker → Orchestrator | Hata düzeltme döngüsü |
| `video_ready_events` | Manim Worker → Gateway, Analytics | Video URL bildirimi |

### Teslimat ve Güvenlik
| Topic | Güzergah | Açıklama |
|---|---|---|
| `content_delivery_stream` | Orchestrator → Gateway | Metin/tebrik içerikleri |
| `dead_letter_queue_ravel` | Hatalı servis → Orchestrator | Fallback yönetimi |

---

## Kafka JSON Şemaları (Örnek Payload'lar)

### student_interactions_stream
```json
{
  "event_id": "e4b3-4f21-88aa",
  "student_id": "std_9912",
  "event_type": "question_answered",
  "payload": {
    "question_id": "q_6_mat_2_10",
    "topic": "Uslu_Ifadeler",
    "taxonomic_level": "B1",
    "student_answer": "C",
    "is_correct": false,
    "time_spent": 42,
    "explicit_video_request": false
  },
  "timestamp": "2026-05-02T14:32:01Z"
}
```

### bandit_decision_responses
```json
{
  "correlation_id": "req_8812",
  "student_id": "std_9912",
  "decision": {
    "intervention_type": "manim_video",
    "difficulty_adjustment": "downgrade_to_A2",
    "confidence_score": 0.87
  },
  "timestamp": "2026-05-02T14:32:01.050Z"
}
```

---

## SLA ve Performans Hedefleri

| Metrik | Hedef |
|---|---|
| Eşzamanlı kullanıcı | 5.000 aktif öğrenci |
| Kafka throughput | 2.000 EPS (events/second) |
| Bandit inference latency | < 50ms |
| RAG + LLM metin yanıt süresi | < 1.5 saniye |
| Manim video render timeout | Maks. 45 saniye |
| PostgreSQL aktif bağlantı limiti | 200 (PgBouncer ile) |
| Kafka partition sayısı (kritik topic'ler) | Min. 10 partition |

---

## LLM Mimarisi (Model-Agnostik)

- Tüm ajanlar (Orchestrator, RAG, Manim Worker) LangChain/LlamaIndex soyutlama katmanı üzerinden çalışır
- Hangi modelin kullanılacağı `.env` dosyasından veya config DB'den yönetilir (kaynak kodda hardcoded değil)
- **Geliştirme:** Açık kaynak lokal modeller (Llama-3 vb.)
- **Üretim:** Bütçeye göre ticari API (OpenAI, Anthropic vb.)
- Sistem Prompt'ları `.yaml` veya `.json` şablon dosyalarında tutulur (hardcoded değil)
- Prompt Injection koruması Middleware katmanında; açılıp kapanabilir (toggleable guardrails)

### Embedding Modeli Yapılandırması (.env'den)
- **Geliştirme:** `paraphrase-multilingual-MiniLM-L12-v2` (384 boyut)
- **Üretim:** `OpenAI text-embedding-3-large` (3072 boyut) veya eşdeğeri

### Semantic Cache
- Redis tabanlı, %95+ anlamsal benzerlikte cache'ten döner
- Maliyet sıfıra indirir, isteğe bağlı devre dışı bırakılabilir

### Configurable RAG Parametreleri
- **Top-K:** Bütçe kısıtlıysa 3, yüksek doğruluk isteniyorsa 10+
- **max_tokens ve temperature:** Her ajan için ayrı ayrı yapılandırılabilir

---

## Video Motor Kuralları (Resource Optimization)

**Varsayılan Metin (Default-to-Text) Kuralı:**
Tek bir soruda yanlış yanıt → Bandit kararını beklemeden sadece RAG + LLM metin yanıtı üretilir.

**Video yalnızca şu iki durumda tetiklenir:**
1. Öğrenci "Video Oluştur" butonuna tıkladığında (explicit feedback)
2. Öğrenci yeni bir ana konuya başladığında (pedagojik giriş animasyonu)

---

## RAG Veri Besleme Hattı (Dual-Stream Ingestion)

### 1. Damar — Soru Havuzu (.pdf, .docx, Excel)
- PDF → PyMuPDF ile parse → soru numarasına göre chunk
- Excel/CSV → Pandas ile oku → taxonomy, answer_key metadata'sı
- İki kaynak `file_name + question_number` üzerinden JOIN edilir
- `content_type: "question"` olarak vektörleştirilir

### 2. Damar — Konu Anlatım Materyalleri
- Konu başlıklarına ve anlamsal bütünlüğe göre semantic chunking
- `content_type: "theory"` veya `"explanation"` olarak etiketlenir

### Hybrid Search Sorgu Örnekleri
```
# Soru çekerken:
WHERE content_type == "question" AND taxonomic_level == "B1" AND test_no == 5

# Konu anlatımı/video için:
WHERE content_type == "theory" AND subject == "Uslu_Ifadeler"
```

---

## DevOps Stratejisi

- Her mikro servis ayrı Docker imajı (multi-stage build)
- Manim Worker izole konteyner (GPU/CPU yoğun, diğer servisleri etkilememesi için)
- Docker Compose ile bridge network: sadece API Gateway'in portu (80/443) dışarıya açık
- Kafka, Redis, PostgreSQL, Milvus/Qdrant altyapı konteynerleri ayrı ayağa kalkar
- **Auto-scaling:** Yük artışında sadece Manim Worker replica sayısı artırılır
- **Stateless servisler:** Orchestrator ve RAG stateless — crash sonrası veri kaybı yok

### Observability Stack
- **Distributed tracing:** OpenTelemetry + Jaeger (her isteğe trace_id atanır)
- **Metrics:** Prometheus + Grafana
- **Logs:** ELK Stack (Elasticsearch, Logstash, Kibana)

### Circuit Breaker (pybreaker)
- Orchestrator ↔ RAG arasında devre kesici
- 5 ardışık başarısız istekte devre "Açık" duruma geçer
- Fallback: Redis'teki statik yedek metin anında döner

---

## Klasör Yapısı (Önerilen)

```
project_ravel/
├── CLAUDE.md                        ← Bu dosya
├── docker-compose.yml
├── .env.example
├── services/
│   ├── api_gateway/
│   ├── orchestrator/
│   ├── bandit/
│   │   ├── actor/
│   │   └── learner/
│   ├── rag/
│   ├── manim_worker/
│   └── analytics/
├── shared/
│   ├── kafka_schemas/
│   └── models/
├── infra/
│   ├── kafka/
│   ├── postgres/
│   ├── redis/
│   └── milvus/
├── frontend/
│   └── (React.js uygulaması)
└── scripts/
    └── (ingestion pipeline, setup vb.)
```

---

## Geliştirme Kuralları (Claude Code için)

1. **Her servis kendi `venv`'inde çalışır**, bağımlılıklar `requirements.txt`'te tanımlıdır.
2. **Tüm konfigürasyon `.env`'den okunur**, kaynak kodda hardcoded değer bulunmaz.
3. **DB-2'ye asla UPDATE/DELETE yapılmaz**, yalnızca INSERT (append-only).
4. **Kafka mesajları her zaman JSON şemasına uygun olmalıdır** (şemalar yukarıda tanımlı).
5. **Her Kafka topic'i min. 10 partition ile oluşturulur**.
6. **Manim Worker her zaman sandbox ortamında** kodu önce test eder, direkt render etmez.
7. **LLM modeli asla import'ta belirtilmez**, her zaman factory/config üzerinden yüklenir.
8. **trace_id her Kafka mesajında taşınır**, servisler arası izlenebilirlik için zorunludur.
