# RAVEL — Assessment & Analytics Service (Adım 9 — YAZILMADI)

> **DURUM: Bu servis henüz kodlanmadı.** Klasörde şu an yalnızca `requirements.txt`
> (placeholder, pinli sürüm yok) ve `.python-version` var. `app/`, `Dockerfile`,
> ve `docker-compose.yml` girdisi **yok**. Bu belge, repoyu klonlayan geliştiricinin
> servisi sıfırdan, projenin geri kalanıyla birebir aynı pattern'lerle yazabilmesi
> için hazırlanmış **eksiksiz yapım kılavuzudur (blueprint)**.
>
> RAVEL'in 6 mikro servisinden **tek eksik olan budur**. Diğer 5 servis + Frontend hazır.

---

## 0. Bir Bakışta

| Özellik | Değer |
|---|---|
| Servis adı | `analytics` (Assessment & Analytics Service) |
| Rol | Pedagojik başarı metriklerini hesaplayan **read-only analiz katmanı** |
| Öğrenciyle konuşur mu? | **Hayır.** Müdahale üretmez, sadece veri okur ve metrik üretir |
| Teknoloji | Python 3.11 + **Polars** (veya Pandas) + asyncpg + aiokafka + FastAPI |
| Bağlı DB | PostgreSQL **DB-2 (`ravel_db2`) — SADECE OKUMA** (`interaction_logs`) |
| Kafka (tüketici) | `student_interactions_stream` (canlı etkileşim akışı) |
| HTTP portu (öneri) | **8005** (8000–8004 dolu: gateway/orchestrator/bandit/rag/manim) |
| Frontend bağlantısı | Admin panelindeki `StatisticsTab.jsx` (Recharts) bu servisi besleyecek |
| Hesapladığı metrikler | **g** (Öğrenme Kazancı), **MCR** (Yanılgı Düzeltme Oranı), **RI** (Kalıcılık İndeksi) |

---

## 1. Bu Servis Ne İşe Yarar?

RAVEL'in "karne defteri"dir. Bandit anlık karar verir (online, <50ms), öğrenciye
müdahale (metin/örnek/video) sunar. Analytics ise **geriye dönük, toplu (batch)**
çalışır: `interaction_logs` tablosundaki olay geçmişini okuyup **öğrenmenin gerçekten
gerçekleşip gerçekleşmediğini** ölçen pedagojik metrikler üretir.

İki farklı zaman ölçeği:

| | Bandit | Analytics |
|---|---|---|
| Zaman | Gerçek zamanlı (her etkileşimde) | Batch / periyodik / istek üzerine |
| Birim | Tek öğrenci, tek karar | Kohort, konu, taksonomi seviyesi |
| Çıktı | Eylem seçimi (text/step/video) | Rapor & grafik verisi (g, MCR, RI) |
| DB-2 | SELECT + INSERT | **Sadece SELECT** |

**Kullanım amaçları:**
1. Öğretmen/yönetici panelleri (Frontend `StatisticsTab`) — sınıf/konu bazlı başarı grafikleri
2. A/B testi — hangi müdahale formatı (text vs step vs video) daha çok öğrenme kazancı sağlıyor?
3. Sistem sağlığı — hangi konularda öğrenciler tıkanıyor (yüksek `frustration_index`, düşük MCR)?

---

## 2. Hesaplanacak Metrikler (Formüller + SQL Kaynak Alanları)

Tüm metrikler `interaction_logs` tablosundan türetilir. Kullanılabilir kolonlar:

```
log_id, student_id, topic_id, taxonomic_level, action_taken,
is_correct, time_spent_seconds, frustration_index, reward_signal, "timestamp"
```

### 2.1. Öğrenme Kazancı — g (Normalized Learning Gain / Hake's gain)

Bir öğrencinin (veya kohortun) bir konuda **müdahale öncesi** ve **sonrası** başarısının
normalize edilmiş farkı.

```
g = (post_score − pre_score) / (1 − pre_score)
```

- `pre_score`  = müdahale öncesi pencerede o `topic_id` için doğru oranı (0–1)
- `post_score` = müdahale sonrası pencerede aynı `topic_id` için doğru oranı (0–1)
- `pre_score == 1` ise tanımsız → o öğrenci/konu g hesabından dışlanır (zaten ustalaşmış)
- Yorum: **g ≈ 1** maksimum kazanç, **g ≤ 0** öğrenme yok / gerileme

**Pencere tanımı (kohort yaklaşımı, öneri):** her öğrencinin bir `topic_id` altındaki
etkileşimlerini `timestamp`'e göre sırala, ilk N'i `pre`, son N'i `post` kabul et
(N parametrik, varsayılan 3). Tek etkileşim varsa dışla.

### 2.2. Yanılgı Düzeltme Oranı — MCR (Misconception Correction Rate)

Yanlış cevaplanan (yanılgı tespit edilen) durumların, **aynı `topic_id` + `taxonomic_level`
ikilisinde sonradan doğruya dönen** oranı.

```
MCR = düzeltilen_yanılgı_sayısı / toplam_yanılgı_sayısı
```

- "Yanılgı" = bir (`student_id`, `topic_id`, `taxonomic_level`) için `is_correct = false` olan ilk olay
- "Düzeltildi" = aynı üçlü için **daha sonraki** (`timestamp >`) bir olayda `is_correct = true`
- Yorum: **MCR ≈ 1** müdahaleler yanılgıları iyi düzeltiyor; düşük MCR → içerik/pedagoji sorunu

### 2.3. Kalıcılık İndeksi — RI (Retention Index)

Öğrenci bir konuda doğru cevaba ulaştıktan **belirli bir süre sonra** (gecikmeli tekrar)
hâlâ doğru yapabiliyor mu?

```
RI = gecikmeli_tekrarda_doğru / toplam_gecikmeli_tekrar
```

- "Gecikmeli tekrar" = bir (`student_id`, `topic_id`) için ilk doğrudan **en az Δt sonra**
  (varsayılan Δt = 24 saat, parametrik) gelen bir sonraki aynı-konu etkileşimi
- Yorum: **RI ≈ 1** kalıcı öğrenme; düşük RI → bilgi kalıcı değil, tekrar gerekiyor

> **NOT:** Δt, N (pencere), ve diğer eşikler **hardcoded olmamalı** — `.env`'den okunmalı
> (proje kuralı #2). Önerilen env adları §6'da.

---

## 3. Mimari Tasarım (Önerilen)

Diğer servislerle tutarlı olması için **iki paralel asyncio task** (ADR-013 deseni,
RAG'deki gibi):

```
                ┌─────────────────────────────────────────────┐
                │              analytics service               │
                │                                              │
  Kafka  ──────▶│  [Task 1] Kafka Consumer                     │
  student_       │   group_id = analytics                       │
  interactions   │   → canlı etkileşimleri sayaç/cache'e işler  │
  _stream        │     (opsiyonel: Redis'te rolling aggregate) │
                │                                              │
  HTTP   ──────▶│  [Task 2] FastAPI (:8005)                    │──▶ asyncpg (DB-2 read)
  (admin panel)  │   GET /health                                │     SELECT only
                │   GET /metrics/learning-gain?...             │
                │   GET /metrics/mcr?...                        │──▶ Polars: agg + g/MCR/RI
                │   GET /metrics/retention?...                 │
                │   GET /metrics/overview?...                  │
                └─────────────────────────────────────────────┘
```

**İki yaklaşım var; takımla netleştir (§8 Açık Kararlar):**

- **(A) Pull / on-demand (önerilen başlangıç):** Frontend istek attıkça FastAPI endpoint'i
  DB-2'den okur, Polars ile hesaplar, JSON döner. Basit, stateless, cache'lenebilir (Redis).
- **(B) Push / pre-aggregated:** Kafka consumer sürekli rolling aggregate tutar (Redis/DB),
  endpoint hazır sonucu döner. Düşük gecikme ama daha karmaşık. Büyük veri hacminde gerekli olur.

Başlangıç için **(A)** yeterli; Kafka consumer'ı şimdilik hafif tut (örn. canlı sayaçlar
veya sadece "son aktivite" cache'i), ağır metrik hesabı endpoint'te DB-2 SELECT ile yapılsın.

---

## 4. Beklenen Dosya Yapısı

Diğer servisleri (özellikle `services/rag` ve `services/bandit`) **birebir** örnek al:

```
services/analytics/
├── README.md                ← bu dosya
├── .python-version          ← "3.11" (zaten var)
├── requirements.txt         ← §5'teki pinli sürümlerle DOLDUR
├── Dockerfile               ← §7 (bandit/Dockerfile'ın kopyası, port 8005)
└── app/
    ├── __init__.py
    ├── config.py            ← pydantic-settings Settings (bandit/config.py deseni)
    ├── main.py              ← lifespan: startup→tasks→shutdown (bandit/main.py deseni)
    ├── db_io.py             ← DB2ReadClient (asyncpg, statement_cache_size=0)
    ├── kafka_io.py          ← KafkaConsumer wrapper (bandit/kafka_io.py'den KOPYALA)
    ├── redis_io.py          ← (opsiyonel) cache / rolling aggregate
    ├── metrics.py           ← g / MCR / RI hesap fonksiyonları (Polars) — saf, test edilebilir
    ├── schemas.py           ← Pydantic response modelleri
    └── api.py               ← FastAPI router (GET /metrics/*, /health)
```

> **`metrics.py` saf (pure) olmalı:** DataFrame girer, metrik çıkar. DB/Kafka'ya dokunmaz.
> Böylece §9'daki unit testler container'sız, deterministik koşar.

---

## 5. `requirements.txt` (Pinli — bu içerikle değiştir)

Mevcut placeholder'ı sil, şunu yaz (sürümler diğer servislerle hizalı, 2026-05 seti):

```
# RAVEL — Analytics (Assessment & Analytics) pinned dependencies
# Python 3.11

fastapi==0.115.5
uvicorn[standard]==0.32.1
aiokafka==0.12.0
asyncpg==0.30.0
redis[hiredis]==5.2.0
polars==1.17.1
pydantic==2.10.3
pydantic-settings==2.6.1
python-jose[cryptography]==3.3.0   # admin JWT doğrulama (gateway ile aynı JWT_SECRET_KEY)
opentelemetry-api==1.31.0
opentelemetry-sdk==1.31.0
```

> Pandas tercih edilirse `polars` yerine `pandas==2.2.3` + `pyarrow==18.1.0`.
> Proje genelinde Polars öneriliyor (daha hızlı, düşük bellek) — CLAUDE.md "Pandas veya Polars".

---

## 6. Konfigürasyon (`.env` — kök `.env`'e eklenecek bölüm)

**Hiçbir değer hardcoded olmayacak** (proje kuralı #2). `config.py` bunları
`pydantic-settings` ile okur. Kök `.env` ve `.env.example`'a şu bölümü ekle:

```bash
# ─── Analytics (Adım 9) ───
ANALYTICS_PORT=8005
ANALYTICS_GROUP_ID=analytics
# DB-2 read-only. Şimdilik ravel_app DSN'i kullanılır (UPDATE/DELETE zaten yasak).
# Production sertleştirmesi: SELECT-only ravel_analytics rolü (§8).
DB2_DSN=postgresql://ravel_app:ravel_app_dev_password_change_me@pgbouncer:6432/ravel_db2
REDIS_URL=redis://:ravel_redis_dev_change_me@redis:6379/0
KAFKA_BOOTSTRAP_SERVERS=kafka:9092
# Admin endpoint'leri için JWT doğrulama (gateway ile AYNI secret)
JWT_SECRET_KEY=replace_me_with_a_long_random_string_at_least_48_chars_dev_only
JWT_ALGORITHM=HS256
# Metrik parametreleri (hardcoded DEĞİL)
ANALYTICS_GAIN_WINDOW=3              # pre/post pencere büyüklüğü (N etkileşim)
ANALYTICS_RETENTION_DELAY_HOURS=24  # RI için minimum gecikme Δt
ANALYTICS_CACHE_TTL_SECONDS=300     # endpoint sonuç cache süresi (Redis)
```

> `docker-compose.yml`'de `${...}` ile geçilir (aşağıdaki §7.2 compose girdisine bak).
> `config.py`'yi `services/bandit/app/config.py`'den uyarlayarak yaz — `lru_cache`'li
> `get_settings()`, `SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)`.

---

## 7. Docker

### 7.1. `Dockerfile` (bandit/Dockerfile'ın kopyası, port 8005)

Multi-stage, non-root (`ravel` uid 1000), `python:3.11-slim`. Sadece **EXPOSE 8002 → 8005**
değişir. Polars/asyncpg ARM64 (M-serisi Mac) için pre-built wheel taşır; `build-essential`
yine de güvenli kalsın:

```dockerfile
FROM python:3.11-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libffi-dev && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /build
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

FROM python:3.11-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH=/opt/venv/bin:$PATH
RUN groupadd -r ravel && useradd -r -g ravel -u 1000 ravel
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY app/ /app/app/
RUN chown -R ravel:ravel /app
USER ravel
EXPOSE 8005
CMD ["python", "-m", "app.main"]
```

### 7.2. `docker-compose.yml` — eklenecek servis girdisi

`frontend`'den önce/sonra fark etmez; aşağıdaki bloğu `services:` altına ekle. Frontend
admin paneli bu servise ulaşacaksa `frontend` `depends_on`'una `analytics` da eklenmeli
(ve `nginx.conf`'a `/analytics` upstream proxy — §8).

```yaml
  # ─────────── Analytics (Step 9) — read-only metrics over DB-2 ───────────
  analytics:
    build:
      context: ./services/analytics
      dockerfile: Dockerfile
    container_name: ravel_analytics
    restart: unless-stopped
    depends_on:
      kafka:
        condition: service_healthy
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      pgbouncer:
        condition: service_started
    environment:
      LOG_LEVEL: INFO
      ANALYTICS_PORT: "8005"
      DB2_DSN: ${DB2_DSN}
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0
      KAFKA_BOOTSTRAP_SERVERS: kafka:9092
      ANALYTICS_GROUP_ID: ${ANALYTICS_GROUP_ID:-analytics}
      JWT_SECRET_KEY: ${JWT_SECRET_KEY}
      JWT_ALGORITHM: HS256
      ANALYTICS_GAIN_WINDOW: ${ANALYTICS_GAIN_WINDOW:-3}
      ANALYTICS_RETENTION_DELAY_HOURS: ${ANALYTICS_RETENTION_DELAY_HOURS:-24}
      ANALYTICS_CACHE_TTL_SECONDS: ${ANALYTICS_CACHE_TTL_SECONDS:-300}
    ports:
      - "${ANALYTICS_PORT:-8005}:8005"
    healthcheck:
      test: ["CMD-SHELL", "python -c 'import urllib.request as r; r.urlopen(\"http://localhost:8005/health\").read()'"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 20s
    networks:
      - ravel_net
```

---

## 8. Önerilen HTTP API

FastAPI, port 8005. Admin endpoint'leri JWT `role="admin"` ile korunur (RAG admin API'siyle
aynı desen — `services/rag/app/admin_api.py`'ye bak).

| Method | Path | Açıklama | Query parametreleri |
|---|---|---|---|
| GET | `/health` | Liveness (auth yok) | — |
| GET | `/metrics/overview` | Özet panel: toplam öğrenci, etkileşim, ort. g/MCR/RI | `grade_level?`, `from?`, `to?` |
| GET | `/metrics/learning-gain` | Öğrenme Kazancı (g) | `topic_id?`, `grade_level?`, `student_id?` |
| GET | `/metrics/mcr` | Yanılgı Düzeltme Oranı | `topic_id?`, `taxonomic_level?` |
| GET | `/metrics/retention` | Kalıcılık İndeksi (RI) | `topic_id?`, `delay_hours?` |
| GET | `/metrics/action-breakdown` | A/B: text vs step vs video başarı kıyası | `topic_id?` |

Yanıt örneği (`/metrics/overview`):

```json
{
  "generated_at": "2026-06-12T10:00:00Z",
  "filters": { "grade_level": 6 },
  "totals": { "students": 412, "interactions": 18230 },
  "metrics": {
    "avg_learning_gain": 0.61,
    "misconception_correction_rate": 0.74,
    "retention_index": 0.68
  },
  "by_action": {
    "text":          { "success_rate": 0.58, "avg_gain": 0.49 },
    "step_by_step":  { "success_rate": 0.66, "avg_gain": 0.63 },
    "video":         { "success_rate": 0.71, "avg_gain": 0.72 }
  }
}
```

---

## 9. Testler (`scripts/test_analytics_*.sh`)

Diğer servislerin test scriptlerini (örn. `scripts/test_bandit_unit.sh`,
`scripts/test_rag_e2e.sh`) örnek al. Aynı `ok/fail/hdr` bash helper deseni.

**`scripts/test_analytics_unit.sh` (host, container'sız — `metrics.py` saf fonksiyonları):**
1. Bilinen küçük bir DataFrame ile **g** doğru mu? (elle hesaplanmış beklenen değer)
2. **MCR** — yanlış→doğru senaryosu 1.0, hiç düzelmeyen 0.0
3. **RI** — Δt eşiği altında kalan tekrar sayılmamalı, üstündekiler sayılmalı
4. `pre_score == 1` olan öğrenci g'den dışlanıyor mu? (sıfıra bölme yok)
5. Boş veri → metrikler `null`/`0`, çökme yok

**`scripts/test_analytics_e2e.sh` (compose ayakta):**
1. DB-2'ye bilinen sahte `interaction_logs` satırları INSERT et (ravel_admin ile — test fixture)
2. `GET /metrics/overview` çağır → beklenen g/MCR/RI değerleri dönüyor mu?
3. JWT'siz admin endpoint → **401**
4. `/health` → 200
5. Kafka `student_interactions_stream`'e mesaj at → consumer düşmeden işliyor mu? (log/sayaç)

> Sahte veri INSERT'i testte `ravel_admin` (superuser DSN) ile yapılır; `ravel_app`
> append-only olduğundan test fixture'ı için sorun değil ama temizlik için ayrı bir
> `test_student_id` kullan (DB-2'den DELETE yapılamaz — append-only; test verisi kalır,
> bu yüzden sabit bir test UUID'si seç ve metrik sorgularını ona filtrele).

---

## 10. Uyulması ZORUNLU Proje Kuralları (CLAUDE.md'den)

1. **Kendi `venv`'inde çalışır** — scaffold sonrası HEMEN host venv kur (ADR-009):
   ```bash
   cd services/analytics
   python3.11 -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   ```
2. **Tüm config `.env`'den** — kaynak kodda hardcoded değer yok.
3. **DB-2'ye SADECE SELECT** — bu servis zaten yazmaz; asla INSERT/UPDATE/DELETE ekleme.
4. **asyncpg + PgBouncer:** `statement_cache_size=0` ZORUNLU (ADR-011) — yoksa ilk sorgudan
   sonra sessizce patlar. `db_io.py`'yi `services/bandit/app/db_io.py`'den uyarla.
5. **Kafka mesajları JSON şemasına uygun** — `student_interactions_stream` şeması CLAUDE.md'de.
6. **`trace_id` taşı** — her Kafka mesajı + HTTP isteğinde izlenebilirlik için (kural #8).
7. **İki consumer ayrımı (ADR-013):** uzun-süren handler ile response topic'leri ayrı
   consumer'da. (Analytics tek topic dinliyorsa kritik değil ama deseni boz­ma.)
8. **Karar verirsen ADR yaz:** önemli her karar hem memory'ye hem `docs/decisions.md`'ye
   (ADR formatı). Sıradaki numara **ADR-020**.

---

## 11. Açık Kararlar (Takımla Netleştir)

Bunlar bilinçli olarak **karara bağlanmadı** — yazmadan önce ekiple konuş:

1. **Pull mu Push mu?** (§3) — başlangıç için on-demand FastAPI (pull) öneriliyor.
2. **Frontend entegrasyon yolu:** Admin paneli şu an `/admin` üzerinden RAG'e gidiyor.
   Analytics için (a) `frontend/nginx.conf`'a `/analytics` upstream eklenir ve
   `vite.config.js` proxy'sine `/analytics → analytics:8005` yazılır; (b) ya da metrikler
   gateway üzerinden proxy'lenir. `StatisticsTab.jsx` şu an muhtemelen mock veriyle çalışıyor.
3. **Read-only rol:** Şimdilik `ravel_app` (UPDATE/DELETE zaten yok). Production'da
   SELECT-only `ravel_analytics` rolü açmak istenirse `infra/postgres/init_app_role.sh`'a
   grant eklenir + yeni `DB2_RO_DSN`. (Sertleştirme, zorunlu değil.)
4. **Δt ve N varsayılanları** (24h / 3) pedagojik olarak ekiple doğrulanmalı.
5. **Periyodik batch job** gerekecek mi (örn. günlük rollup tablosu)? İlk sürümde gerek yok.

---

## 12. Yapılacaklar Özeti (Checklist)

- [ ] `requirements.txt`'i §5 ile değiştir
- [ ] `app/config.py` (bandit deseni, §6 env'leri)
- [ ] `app/db_io.py` — `DB2ReadClient` (asyncpg, `statement_cache_size=0`, sadece SELECT)
- [ ] `app/kafka_io.py` — bandit'ten kopyala
- [ ] `app/metrics.py` — saf g/MCR/RI fonksiyonları (Polars)
- [ ] `app/schemas.py` — Pydantic response modelleri
- [ ] `app/api.py` — FastAPI router (§8 endpoint'leri, JWT admin guard)
- [ ] `app/main.py` — lifespan: DB+Redis+Kafka consumer+uvicorn (bandit deseni)
- [ ] `Dockerfile` — §7.1 (port 8005)
- [ ] Kök `.env` + `.env.example` — §6 bloğu
- [ ] `docker-compose.yml` — §7.2 servis girdisi
- [ ] `scripts/test_analytics_unit.sh` + `scripts/test_analytics_e2e.sh`
- [ ] `docs/decisions.md` — ADR-020 (Analytics tasarım kararları)
- [ ] Memory güncelle (proje fazı: 6/6 servis tamam)
- [ ] Frontend `StatisticsTab` gerçek veriye bağlandı mı? (§11.2)
```
