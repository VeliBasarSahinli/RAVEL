# RAVEL — Karar Günlüğü (Decision Log)

> Mimari ve proje kararlarının tarihli kaydı, gerekçeleriyle birlikte.
>
> **Format:** ADR (Architecture Decision Record) — her karar atomic, geri dönülebilir bir birim.
> **Çift güvence:** Bu dosya proje deposunda; Claude Code memory'de de paralel notlar var (sohbetler arası hatırlama için). İkisi senkron tutulmalı.
> **Yeni karar nasıl eklenir:** En sondaki "Yeni karar eklemek için" bölümüne bak.

---

## ADR-001 — Vektör DB: Qdrant
*2026-05-04 · Adım 1*

**Bağlam:** CLAUDE.md "Milvus veya Qdrant" diyordu, kesin seçim yapılmamıştı.

**Karar:** Qdrant.

**Gerekçe:**
- Tek binary, ~100 MB RAM (M4 Pro 16GB için bol marj)
- Single-node hibrit arama destekli (metadata filter + vektör mesafesi)
- Milvus 3+ ek konteyner gerektiriyor (etcd, MinIO, standalone)

**Sonuçları:** RAG abstraction katmanı LlamaIndex; üretimde gerekirse Milvus'a geçiş mümkün, kod minimal değişir.

---

## ADR-002 — Kafka koordinasyonu: KRaft (Zookeeper değil)
*2026-05-04 · Adım 1*

**Bağlam:** Klasik Kafka cluster için ayrı bir Zookeeper cluster gerekirdi. Kafka 3.5+ ile KRaft (Kafka kendi kendini koordine eder) standart geldi.

**Karar:** KRaft tek-node modu.

**Gerekçe:**
- Daha az hareketli parça (1 konteyner yerine 2)
- Zookeeper deprecated; yeni proje Zookeeper başlatmamalı
- Dev için yeterli; production'da multi-broker'a kolay geçer

**Sonuçları:** `docker-compose.yml` Kafka servisi `KAFKA_PROCESS_ROLES: broker,controller` ile çalışıyor. Tek broker, RF=1.

---

## ADR-003 — PostgreSQL: tek konteyner + iki database
*2026-05-04 · Adım 1*

**Bağlam:** CLAUDE.md DB-1 (öğrenci profilleri) ve DB-2 (etkileşim logları) için "ayrı şema" diyordu — bu mantıksal ayrım, fiziksel zorunluluk değil.

**Karar:** Tek `postgres` konteyneri içinde `ravel_db1` ve `ravel_db2` adında iki ayrı database.

**Gerekçe:**
- Dev kaynak tasarrufu (tek konteyner ~30 MB RAM)
- Connection string seviyesinde tam izolasyon
- Üretimde fiziksel ayrım gerekirse compose'da iki servis tanımlamak yeterli

**Sonuçları:** `infra/postgres/init.sql` her iki DB'yi de aynı script'te oluşturuyor.

---

## ADR-004 — Observability stack ertelendi
*2026-05-04 · Adım 1*

**Bağlam:** CLAUDE.md Prometheus, Grafana, Jaeger, ELK stack'ini öneriyordu.

**Karar:** Adım 1'den çıkarıldı, sonraki adımlara (büyük olasılıkla 3-4) ertelendi.

**Gerekçe:**
- İzlenecek Python servisi henüz yoktu (boş Prometheus paneli anlamsız)
- 6-7 ekstra konteyner ~4-6 GB RAM yer
- Dev'de hızlı iterasyon için bu yük şu an gereksiz

**Sonuçları:** `trace_id` altyapısı (her HTTP isteği + Kafka mesajında) **şimdiden hazır** (ADR-008d), Jaeger eklendiğinde kod değişmez.

---

## ADR-005 — Python sürümü: 3.11
*2026-05-04 · Adım 1*

**Bağlam:** Tüm Python servisleri için tek bir sürüm seçilmesi gerekiyordu.

**Karar:** Python 3.11.

**Gerekçe:**
- Manim ve PyTorch gibi ağır kütüphaneler 3.13'te hâlâ yeterince oturmadı
- 3.11 stabil, async iyileştirilmiş, type system olgun
- Homebrew'da `python@3.11` mevcut (host: 3.11.13)

**Sonuçları:** Her servisin `.python-version` dosyası `3.11`; Dockerfile'lar `python:3.11-slim` base.

---

## ADR-006 — Apache Kafka image (Bitnami yerine)
*2026-05-04 · Adım 1 · Incident-driven*

**Bağlam:** İlk `docker compose up` denemesinde `bitnami/kafka:3.8` çekilemedi. Bitnami 2025 ortasında ücretsiz public Docker tag'larını kaldırdı; "Bitnami Secure Images" ücretli abonelik modeline geçti.

**Karar:** `apache/kafka:3.8.0` resmi imajına geçildi.

**Gerekçe:**
- Apache imajı kalıcı (resmi proje deposu)
- Multi-arch (M4 Pro ARM64 uyumlu)
- KRaft destekli

**Sonuçları:** Birkaç compose ayarı değişti — env adları (`KAFKA_CFG_*` → `KAFKA_*`), volume yolu (`/bitnami/kafka` → `/var/lib/kafka/data`), binary yolu (`/opt/bitnami/kafka/bin/` → `/opt/kafka/bin/`), `user: root` eklendi (chown için).

**Genel kural:** Yeni servisler için `bitnami/*` imajları kullanılmaz. Resmi upstream (apache, redis, postgres) veya `confluentinc/cp-*` tercih edilir.

---

## ADR-007 — PostgreSQL `ravel_app` kısıtlı rolü
*2026-05-04 · Adım 2b*

**Bağlam:** CLAUDE.md "DB-2'ye asla UPDATE/DELETE yapılmaz" kuralı sadece bir convention'dı. Yanlışlıkla bir UPDATE yazılırsa engelleyecek hiçbir şey yoktu.

**Karar:** İki Postgres rolü:
- `ravel_admin` (superuser; sadece migration ve operasyonel görevler)
- `ravel_app` (kısıtlı; tüm Python servisleri bunu kullanır)

**Yetki matrisi:**

| Database | Tablo | SELECT | INSERT | UPDATE | DELETE |
|---|---|---|---|---|---|
| ravel_db1 | students | ✓ | ✓ | ✓ (Bandit `learning_style_vector` günceller) | ✗ |
| ravel_db2 | interaction_logs | ✓ | ✓ | ✗ | ✗ |

**Gerekçe:**
- Append-only kural artık DB-seviye zorlaması; uygulama hatası veriyi bozamaz
- Defense-in-depth (kod yanlış yapsa bile veri korunur)

**Sonuçları:** `init_app_role.sh` her yeni Postgres init'inde rolü oluşturuyor. PgBouncer userlist'i runtime'da hem `ravel_admin` hem `ravel_app`'i içeriyor.

**Yeni servis için kural:** Her Python servisin connection string'i `POSTGRES_APP_USER` / `POSTGRES_APP_PASSWORD` kullanır. `ravel_admin` ile **asla** bağlanmaz.

---

## ADR-008 — API Gateway tasarım kararları
*2026-05-04 · Adım 2a*

İlk Python servisi yazıldı; sonraki tüm servisler için kalıp olacaktı. Dört önemli ayrıntı netleştirildi.

### 008a — Login passwordless
`/auth/login` parola almıyor; sadece `student_id + grade_level`. DB doğrulaması Adım 2c'de (Orchestrator) yapılacak.

**Gerekçe:** Adım 2a kapsamında Gateway'in DB driver bağımlılığı yoktu. Gerçek auth modeli (parola, SSO veya token-with-OTP) Adım 4-5'te kullanım vakası netleşince eklenir.

### 008b — WebSocket auth: query parametresi
`/ws/{student_id}?token=<jwt>` — header değil, query string.

**Gerekçe:** Browser'lar WebSocket handshake'inde custom header gönderemez. Yaygın çözüm query parametresi.

**Risk:** Query string sunucu loglarına düşebilir. Dev için OK; production'da access log'da `token` parametresi maskelenmeli.

### 008c — Kafka topic auto-creation (servis lifespan'da)
Gateway lifespan'da kullandığı 4 topic'i (`student_interactions_stream`, `session_lifecycle_events`, `content_delivery_stream`, `video_ready_events`) idempotent oluşturuyor.

**Gerekçe:** `auto.create.topics.enable=false` (ADR-002 ile birlikte gelen güvenli default). Her servis kendi tükettiği/ürettiği topic'i ensure eder — microservice ownership pattern'i.

**Sonuçları:** 12 topic'in merkezi yönetimi yok; sahiplik dağılmış.

### 008d — trace_id middleware
Her HTTP isteğine `X-Trace-Id` üretiliyor (gelmemişse), `request.state`'e konuyor, Kafka mesajında taşınıyor.

**Gerekçe:** Distributed tracing temeli; Jaeger eklendiğinde (ADR-004) kod değişmeden çalışacak.

---

## ADR-009 — Her servis için host-side venv
*2026-05-04 · Adım 2a sonrası*

**Bağlam:** Servisler Docker container'larında çalışıyor (multi-stage build, venv container içinde). Ama yerel geliştirme (IDE, LSP, type check, ad-hoc debug) için host'ta da venv gerekli.

**Karar:** Her servis için `services/<name>/venv/` klasörü. Komut:
```bash
cd services/<name>
python3.11 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
```

**Gerekçe:**
- VS Code / PyCharm `.python-version` + `venv/` ile otomatik tespit eder
- Container build etmeden hızlı `python -c "..."` debug
- LSP autocomplete + "go to definition" çalışır

**Sonuçları:** `venv/` `.gitignore`'da. Bekleyen servisler: `orchestrator`, `bandit/actor`, `bandit/learner`, `rag`, `manim_worker`, `analytics` — her biri yazılır yazılmaz aynı venv adımı uygulanır.

---

## ADR-010 — Orchestrator tasarım kararları
*2026-05-04 · Adım 3*

İkinci Python servisi yazıldı; sistemin "beyni" olduğu için API Gateway'den daha karmaşık. Beş alt karar netleştirildi.

### 010a — RAG request-response Kafka pattern'i
İstek-yanıt aslen senkron bir model; Kafka asenkron. Orchestrator her RAG isteğine `correlation_id` üretip `content_retrieval_requests`'e yazıyor, lokal `RAGRequestRegistry`'de bir `asyncio.Future` bekliyor. Tek `KafkaConsumer` iki topic'i (`student_interactions_stream` + `content_retrieval_responses`) dinliyor; response handler `correlation_id`'ye göre `Future.set_result()` çağırıyor.

**Gerekçe:** Distributed request-response pattern; tek instance'da işliyor. Multi-instance ölçek için partition-based routing veya bir reply queue per-instance gerekir (TODO).

### 010b — Bandit yok, Default-to-Text override aktif
Workflow her zaman `BanditDecision(intervention_type="text", difficulty_adjustment=event.payload.taxonomic_level)` üretiyor (sabit). Karar log'a yazılıyor; `bandit_decision_requests`'e mesaj atılmıyor. Topic ensure ediliyor (gelecekteki Bandit servisi için).

**Gerekçe:** Spec'in açık talebi. CLAUDE.md "Default-to-Text" kuralı tek hatada zaten Bandit'i bypass ediyor; Step 4'te Bandit yazıldığında bu override kalkar.

### 010c — Kendi async circuit breaker FSM'i (pybreaker yerine)
`pybreaker` async API'si versiyonlar arasında oturmamış; bizim request-response pattern'imiz `Future.wait_for(timeout)` ile zaten karmaşık. `app/circuit_breaker.py` dahili 3-durumlu FSM (closed → open → half_open) implement ediyor. `pybreaker` `requirements.txt`'te konsept dependency olarak duruyor — gelecekte sync HTTP plugin webhook'larında kullanılabilir.

**Gerekçe:** Test edilebilirlik + öngörülebilir async semantics. Spec "pybreaker ile" dese de async-clean olmadığı için pragmatik sapma.

### 010d — Saf async Python, FastAPI yok
Orchestrator HTTP endpoint sunmuyor (Kafka over the wire). `main.py` `asyncio.run(main())` ile çalışıyor; SIGTERM/SIGINT için `loop.add_signal_handler`. Healthcheck için minimal TCP listener (port 8001); compose `socket.connect(8001)` ile pingliyor.

**Gerekçe:** FastAPI/uvicorn ek bir HTTP layer; orchestrator'da ihtiyaç yok. TCP listener 10 satır, sıfır extra dependency.

### 010e — Gateway event şeması extension: `grade_level`
`StudentInteractionEvent`'in top-level'ına `grade_level` field'ı eklendi (Gateway JWT'den okuyup yazıyor). CLAUDE.md'deki şemaya göre bir extension.

**Gerekçe:** Orchestrator cold-start'ta `upsert_student(student_id, grade_level)` için bu bilgiye ihtiyaç duyuyor; yoksa default değer riski. JWT zaten taşıyor, en doğru kaynak orası.

**Sonuçları:** API Gateway `app/main.py`'da `submit_answer` event dict'ine `"grade_level": payload["grade_level"]` ekledi. Orchestrator schema bunu doğrudan modeliyor.

---

## ADR-011 — asyncpg + PgBouncer transaction mode: prepared statement cache devre dışı
*2026-05-04 · Adım 3 · Incident-driven*

**Bağlam:** Adım 3 robustness testleri sırasında orchestrator'ın `student_interactions_stream` consume eden döngüsünde sessizce başarısız upsert'ler tespit edildi. Stack trace:

```
asyncpg.exceptions.DuplicatePreparedStatementError:
  prepared statement "__asyncpg_stmt_6__" already exists
HINT: pgbouncer with pool_mode set to "transaction" or "statement"
      does not support prepared statements properly.
```

İlk e2e test (Adım 3'ün başında) tesadüfen geçti çünkü asyncpg pool taze, statement cache henüz boştu. İkinci ve sonraki sorgular `DuplicatePreparedStatementError` fırlattı; hata `kafka_io._loop`'un dış `try/except`'i tarafından yakalandı, "handler failed" log'una düştü, döngü devam etti — ama upsert ve select işlemleri hiç çalışmadı.

**Sebep:** asyncpg her bağlantı için client-side prepared statement cache tutuyor (hız için). PgBouncer `transaction` pool mode'da (ADR-002b'de seçildi) her transaction farklı backend'e gidebilir; asyncpg'in cache referansı geçersiz olur, çakışma yaşanır.

**Karar:** asyncpg `create_pool()` çağrısında `statement_cache_size=0` set edildi.

**Gerekçe:** Üç seçenek vardı:
1. PgBouncer'ı atla, doğrudan Postgres'e bağlan (asyncpg kendi pool'u). **Reddedildi** — CLAUDE.md SLA: 200 bağlantı limiti, PgBouncer şart.
2. PgBouncer pool mode'unu `session`'a çevir. **Reddedildi** — async Python servisleri için connection-per-client demek, ölçek çöker.
3. asyncpg statement cache'i devre dışı bırak. **Seçildi** — küçük bir hız kaybı (~%5), ama deterministik davranış. asyncpg dokümanı bu çözümü explicit olarak öneriyor.

**Sonuçları:**
- `services/orchestrator/app/db_io.py` `DB1Client.start()` içinde `statement_cache_size=0`.
- **Yeni servis için kural:** asyncpg + PgBouncer kullanan **her servis** bu ayarı set etmek zorunda. Adım 4+'da Bandit, Analytics gibi servisler asyncpg ile yazılırken aynı ayar gerek.
- Hata sessiz şekilde yutuluyordu çünkü `kafka_io._loop` exception'ı yakalayıp "handler failed" log'una basıyor, loop devam ediyor. Bu davranış doğru (hata izolasyonu) ama bug'ı geç fark etmemize yol açtı. **Gözlem:** integration test setlerine her serviste explicit DB-write doğrulaması koyulmalı (sadece "no crash" yetmiyor).

---

## ADR-012 — Bandit servisi tasarım kararları
*2026-05-04 · Adım 4*

LinTS algoritması + Actor + Learner aynı container'da iki ayrı asyncio task. Six alt-karar netleşti.

### 012a — Tek container içinde Actor + Learner, ayrı asyncio task
İki servis aynı process'te ama mantıksal izolasyon: ayrı LinTS instance, ayrı consumer group_id (`bandit-actor`, `bandit-learner`), ayrı KafkaConsumer. Paylaşımsız tek köprü: MinIO (weight dosyası) + Redis Pub/Sub (hot-swap sinyali).

**Gerekçe:** CLAUDE.md spec'i tek bir "Contextual Bandit Service" olarak tanımlıyor. Production'da ölçek gerekirse Learner ayrı bir konteyner olarak ayrılabilir — kod yapısı buna hazır (sadece `main.py` farklı entry point'lerle bölünür).

### 012b — pybreaker yerine kendi async circuit breaker (devamı, ADR-010c)
Bandit'te de aynı tutum: pybreaker requirements'ta var ama kullanılmıyor. Bandit'te zaten circuit breaker yok (RAG yok), bu mevzu Step 5'te (Bandit ↔ RAG arası ile değil, başka bir yerde).

### 012c — RewardLogEntry şema extension'ı
Spec'teki 8 alana ek olarak `topic_id`, `taxonomic_level`, `is_correct`, `frustration_index` eklendi. Sebep: Learner DB-2'ye `interaction_logs` INSERT yaparken CLAUDE.md şemasındaki bu alanları doldurması gerek; Orchestrator zaten event'te bu bilgilere sahip, sadece reward_logs_stream üzerinden taşıyacak.

### 012d — MinIO async wrapping ThreadPoolExecutor ile
boto3 senkron; `loop.run_in_executor(ThreadPoolExecutor(2), …)` ile async wrap edildi. Aiobotocore eklenmedi (extra dependency). Weight dosyası ~10-50 KB, dakikada 1 yazılır — küçük thread pool yeterli.

### 012e — Hot-swap atomicity
`asyncio.Lock`'lı `_swap_lock` ile LinTS instance reference'ı korunuyor. Yeni weights MinIO'dan yüklenirken eski instance isteklere cevap vermeye devam eder; lock altında atomic referans değişimi yapılır.

### 012f — Reward formula default'ları
- `C_t` = +1.0 / -1.0 (correct/incorrect; ipucu kavramı UI'de henüz yok)
- `T_baseline` = 60 sn sabit (env override)
- `S_t` = 0.0 (Anladım/Kısmen anketi UI'de henüz yok; nötr)
- `time_efficiency_cap` = 2.0 (`T_baseline/T_actual` çok küçük T_actual'da uçuşmasın)

**Sonuçları:** Adım 5+'da bu default'lar gerçek değerlerle değiştirilecek (ipucu sayısı DB'den, S_t GUI'den, T_baseline soru bazında).

---

## ADR-013 — Orchestrator: iki ayrı Kafka consumer (deadlock prevention)
*2026-05-04 · Adım 4 · Incident-driven*

**Bağlam:** Adım 4 e2e testinde "her ikinci event Bandit timeout'una düşüyor" gözlemlendi. Sebep: tek bir KafkaConsumer hem `student_interactions_stream`'i hem `bandit_decision_responses`'i tüketmeye çalışıyordu. Workflow `process_interaction` 3+ saniye sürdüğü için (RAG timeout dahil), aynı consumer Bandit yanıtını alamıyordu — handler bloke olmuş, response ısrarla bekliyordu, kendi kendini deadlock'a benzer bir durumda tutuyordu.

**Karar:** Orchestrator'da iki ayrı KafkaConsumer:
- `interactions_consumer` (group_id=`orchestrator`) — sadece `student_interactions_stream`; workflow'u tetikler
- `responses_consumer` (group_id=`orchestrator-responses`) — `content_retrieval_responses` + `bandit_decision_responses`; registry'ye deliver eder

**Gerekçe:** Aiokafka consumer single-task; tek consumer içinde uzun-süreli handler bloklayıcı. İki consumer iki ayrı asyncio task'ında paralel çalışır; biri workflow yürütürken öbürü registry'lere besleme yapar.

**Sonuçları:**
- `services/orchestrator/app/main.py` iki consumer instance ile yeniden düzenlendi
- Group lag'leri ayrı izlenir (Kafka monitoring için iyi)
- Aynı pattern: Bandit servisi zaten Actor + Learner ayrı consumer'lara sahip (ADR-012a) — tutarlılık

**Yeni servis için kural:** Servis hem uzun-süreli mesaj işleyici hem de düşük-latency response gerektiren bir mesaj tipini aynı consumer üzerinde dinlememeli. İkincisi ayrı bir consumer/group'a alınır.

---

## ADR-014 — `topic_reward_logs` config field'ı (bug fix)
*2026-05-04 · Adım 4 · Bug fix*

**Bağlam:** Step 4 ilk e2e run'ında `_maybe_emit_reward` `AttributeError: 'Settings' object has no attribute 'topic_reward_logs'` ile patladı. workflow.py'de `self.settings.topic_reward_logs` kullanılıyordu ama `config.py`'a field eklemeyi atlamıştım; `main.py`'da `"reward_logs_stream"` hardcoded geçmişti.

**Karar:** `Settings.topic_reward_logs: str = "reward_logs_stream"` field'ı eklendi; tüm hardcoded referanslar `settings.topic_reward_logs`'a çevrildi.

**Gerekçe:** CLAUDE.md kuralı (no hardcoded values); ayrıca farklı ortamlarda topic adı override edilebilmeli.

**Ders:** Workflow kodunu yazdığımda config field'ları paralel güncellenmedi — yeni `Settings` field'ı eklerken aynı commit'te kullanım yerlerini de güncellemek için checklist gerek (commit hook ya da review). Bu ADR-011 ile aynı kategoride: hata sessizce kafka_io._loop'un dış try/except'ine düşüp yutuldu, "handler failed" olarak loglandı, bug geç fark edildi.

---

## ADR-015 — RAG servisi tasarım kararları
*2026-05-05 · Adım 5*

İçeriğin vektörleştirilip Qdrant'a yazılması ve Orchestrator'ın içerik isteklerinin karşılanması. Yedi alt-karar netleşti.

### 015a — Embedding modeli build sırasında image'a kuruluyor
`paraphrase-multilingual-MiniLM-L12-v2` (~471 MB) Dockerfile RUN aşamasında `/opt/models`'a indirilir; runtime download yok. Restart süresi <15 sn.

**Gerekçe:** Spec'in `model_cache` volume mount alternatifi yerine bunu seçtik — image immutable, ortam farklılığı yok, dev-prod aynı. Trade-off: image boyutu ~2 GB (PyTorch + model).

### 015b — MPS otomatik algılanır (host venv) / CPU (container)
Embedder.py `torch.backends.mps.is_available()` kontrolü yapar. macOS host venv'de MPS, Linux container'da CPU. Production'da GPU eklenirse CUDA da algılanır.

### 015c — LaTeX/Unicode normalizasyonu sadece embedding girdisinde
Orijinal `text_content` saklanır (gösterim için); `text_for_embedding` Türkçe okunuşa çevrilir (`x²` → "x kare", `\frac{a}{b}` → "a bölü b"). Embedding kalitesi için kritik — model paraphrase'lara duyarlı.

### 015d — İki aşamalı retrieval: hybrid filter + Qdrant search → rerank
Aşama 1: filter (`content_type` zorunlu + opsiyonel `taxonomic_level`/`grade_level`/`subject`) + cosine similarity ≥ 0.45, top_k=8.
Aşama 2: reranking (sıralama + top_n=3). Eğer 0 sonuç → eşik 0.30'a düşer.

**Gerekçe:** CLAUDE.md'nin hibrit arama tanımı. Reranking tek bir cross-encoder yerine basit skor sıralaması — yeterli, ek model yükü yok.

### 015e — paraphrase model Türkçe profili — eşik 0.45
Model Türkçe paraphrase'lerini 0.55-0.75 aralığında verir; alakasız 0.03-0.10. SIMILARITY_THRESHOLD=0.45 makul: ilişkili-ilişkisiz arasındaki uçurum büyük (yaklaşık 6-19x), 0.45 keskin bir kesim sağlıyor.

### 015f — Admin auth: aynı JWT secret + role="admin" claim
Gateway `/auth/login`'a opsiyonel `role` parametresi eklendi; `role="admin"` geçildiğinde token payload'ında yer alır. RAG `/admin/*` endpoint'leri bu claim'i kontrol eder. Token üretmek için `scripts/generate_admin_token.sh`.

### 015g — DOCX bold detection: "ilk run bold" yeterli
Olimpiyat formatında soru numarası bold + gövde normal yaygın — paragrafın çoğunluğu bold olmuyor. `_is_bold_paragraph` ilk metin run'u bold ise kabul ediyor. İlk denemede `>= 60% bold` kuralı 3/3 soruyu kaçırdı; düzeltme sonrası 3/3 yakalandı.

**Sonuçları:** `services/rag/app/parsers/docx_parser.py` `_is_bold_paragraph` ilk run kontrolü.

### Bilinen sınırlama (Adım 5b iyileştirmesi)
Excel index'te `grade_level` ve `subject` opsiyonel kolonları yok; question chunks'larda bu metadata `null` kalıyor. Orchestrator `grade_level` filter'ı gönderdiğinde Qdrant null kayıtları dışlıyor → real chunk return olmuyor. Çözüm Adım 5b'de: Excel'e iki opsiyonel kolon, parser bunu chunk metadata'sına yazsın. Şimdilik retrieval boş chunk listesi dönerse Orchestrator fallback metni kullanıyor (akış kırılmıyor).

---

## ADR-016 — RAG retriever filter stratejisi: grade_level kaldırıldı
*2026-05-05 · Adım 5b · Bug fix / Tasarım iyileştirmesi*

**Bağlam:** Adım 5'in sonunda gözlemlendi: Orchestrator `grade_level=N` filter'ı gönderiyordu, ancak Excel index zorunlu kılmadığı için question chunks'ları Qdrant'a `grade_level=null` ile yazılıyordu. Filter null kayıtları dışlıyordu → her zaman 0 chunk dönüyordu. Manuel retriever sorgusu kanıtladı: kayıtlar var, similarity yüksek (0.7+), sorun sadece filter.

**Karar:** Filter mantığı sadeleştirildi:
- **Zorunlu:** `content_type` (her zaman uygulanır)
- **Güçlü opsiyonel:** `taxonomic_level` (sadece değer gelirse)
- **Opsiyonel:** `subject` (sadece değer gelirse)
- **Kaldırıldı:** `grade_level` — ne `Retriever`'da ne `ContentRetrievalRequest` şemasında.

**Etkilenen dosyalar:**
- `services/rag/app/retriever.py` — filter dict'ten grade_level çıktı
- `services/orchestrator/app/schemas.py` — `ContentRetrievalRequest.grade_level` alanı kaldırıldı
- `services/orchestrator/app/workflow.py` — `_retrieve_or_fallback` artık `grade_level` set etmiyor

**Gerekçe:** Sınıf seviyesi filtresi mimari seviyede gerekli görünüyor ama veri katmanında zorunlu metadata değil. Doğru çözüm — Excel index'e opsiyonel `grade_level` kolonu eklemek + parser'ların metadata'ya yazması — Adım 5c iyileştirmesi olarak ertelendi. Şimdiki haliyle `subject` (file_name) zaten içerik özgüllüğü için yeterli (her dosya tek bir sınıf seviyesine ait).

**Kanıt:** Manuel retriever sorgu sonrası — `chunks=2 total_found=2`, score 0.759 ve 0.701, alakalı sorular doğru sıralandı. E2E test PART 4'e bu kanıt sertifikası eklendi.

---

## ADR-017 — Manim Worker tasarım kararları
*2026-05-05 · Adım 6*

**Bağlam:** Bandit "video" kararı verdiğinde orkestrasyon LLM'ten Manim sahne kodu üretmek ve onu sandbox'tan geçirip render etmek zorunda. LLM ürettiği kod güvenli olmayabilir; render zaman alır (45 sn SLA); başarısız olursa kullanıcıyı boşta bırakmamak gerek. Birkaç tasarım kararı verildi.

**Kararlar:**

1. **Sandbox: whitelist > blacklist.**
   AST analizi yalnızca `{manim, numpy, math, random}` import'larına izin verir. Blacklist (os/sys/subprocess yasakla) deliklidir; LLM'in bilmediğimiz bir tehlikeli paketi import etmesi her zaman mümkün. Whitelist sıkı ama deterministik. Yasak çağrılar (`exec`, `eval`, `compile`, `__import__`, `open`), yasak öznitelikler (`__class__`, `__subclasses__`, `__globals__`, `__builtins__`) ek olarak engellenir.

2. **Syntax kontrol: `py_compile` + `ast.parse`, Manim'i import etmeden.**
   Manim 0.18.x'te `--dry-run` flag'i yok; gerçek `manim render` 5+ sn alıyor (Manim'i import + Scene parse). Subprocess'te `python -c "ast.parse(...); py_compile.compile(...)"` ile <100 ms'de syntax doğrulanır, Manim load edilmez. `subprocess` izolasyonu defansif (compile() bile teorik olarak yan etki yapabilir). `sys.executable` kullanılır → host venv ve container'da aynı çalışır.

3. **Three-strikes-then-DLQ (CLAUDE.md SLA).**
   Bir task `attempt_number >= MANIM_MAX_RETRIES` (varsayılan 3) ile geldiğinde düzeltme döngüsüne yeniden gönderilmez; doğrudan `dead_letter_queue_ravel`'e yazılır. Orchestrator DLQ tüketicisi fallback metin yanıt üretir.

4. **`BANDIT_FORCE_DECISION` env var — testte deterministik karar.**
   LinTS stokastik; `explicit_video_request=true` x9'u 1 yapsa bile video çıkma garantisi yok. E2E testin flake olmaması için `BANDIT_FORCE_DECISION=video` (veya `manim_video` alias'ı) Actor'da sampling'i bypass eder ve sabit aksiyon döner. Production'da boş bırakılır. Adım 5b'deki "manuel kanıt" pattern'inin bir benzeri: stokastik sistemi testte deterministik hale getir, prodda bırak.

5. **Manim kodu LLM'in dışında değil, içinde üretilir.**
   `LLMClient.generate_manim_code()` ve `LLMClient.correct_manim_code()` metodları eklendi. Adım 6'da mock — sabit bir `RavelLesson(Scene)` döner. Adım 7'de gerçek LLM gelince bu iki metod tek değişimle gerçek olur; çağıran tarafta (Orchestrator workflow) hiçbir şey değişmez.

6. **qa_correction_loop ve dead_letter_queue_ravel mevcut responses_consumer'a eklendi.**
   ADR-013'e göre uzun-handler topic'leri ayrı consumer ister. Burada handler kısa (sadece producer.send) → mevcut responses_consumer içinde işlenebilir. Ek bir consumer açmak fazlalık olurdu.

**Etkilenen dosyalar:**
- `services/manim_worker/` — yeni servis (Dockerfile, requirements.txt, app/{config, schemas, sandbox, renderer, minio_io, kafka_io, main}.py)
- `services/orchestrator/app/llm_client.py` — `generate_manim_code` + `correct_manim_code` mock metodları
- `services/orchestrator/app/workflow.py` — `_dispatch_manim_render`, `handle_qa_correction`, `handle_dlq` eklendi; `process_interaction` video branch'ı kazandı
- `services/orchestrator/app/main.py` — yeni topic'ler ensure_topics'e eklendi; responses_consumer qa_correction_loop + dlq dinliyor
- `services/orchestrator/app/config.py` — `topic_manim_render_tasks`, `topic_qa_correction_loop`, `topic_video_ready_events`, `topic_dlq`, `manim_*` ayarları
- `services/orchestrator/app/schemas.py` — `ManimRenderTask`, `QACorrectionRequest` eklendi
- `services/bandit/app/config.py` — `bandit_force_decision`
- `services/bandit/app/actor.py` — FORCE override; LinTS sampling'i bypass
- `docker-compose.yml` — `manim_worker` servisi + Bandit env var
- `.env` / `.env.example` — Adım 6 ve test override env var'ları
- `scripts/test_manim_unit.sh`, `scripts/test_manim_e2e.sh` — yeni test scriptleri

**Gerekçe:** Spec'te blacklist sandbox önerilmişti ama whitelist daha sıkı ve test edilebilir. py_compile yaklaşımı Manim'in `--dry-run` flag'i olmadığını yakaladı (kullanıcı doğruladı). FORCE_DECISION = test pragmatizmi: gerçek davranışı değiştirmiyor, prod'da boş.

**Sonuçları:** Adım 7'de gerçek LLM geldiğinde:
- `generate_manim_code` + `correct_manim_code` gerçek model çağrılarına dönüşür
- Sandbox aynı kalır (LLM'in ürettiği koda **daha çok** güvenmemek lazım)
- `BANDIT_FORCE_DECISION` test scriptinden çıkarılmaz; üretim ortamında zaten boş

---

## ADR-018 — LLM Gateway, prompt template engine, admin yönetim paneli
*2026-05-06 · Adım 7*

**Bağlam:** Adım 3-6 boyunca `LLMClient` sabit Türkçe mock yanıt veren bir placeholder'dı. Adım 7'de altı sağlayıcı (anthropic, openai, gemini, openrouter, ollama, custom) destekleyen, ajan-bazında konfigüre edilebilen, admin paneli üzerinden yönetilen ve API key'leri AES-256-GCM ile şifreleyen bir LLM Gateway gerekti. Promptlar (system + user) artık mod-bazlı YAML şablonları (Jinja2) — kod içine gömülmüyor.

**Kararlar:**

1. **Tek tablo, ajan-bazlı config: `llm_configs` (DB-1).**
   `(agent_name UNIQUE)` üzerinden upsert; `provider`/`model_name`/`api_key` (BYTEA, AES-256-GCM) /`endpoint_url`/`max_tokens`/`temperature`/`is_active`. Migration script idempotent (`CREATE TABLE IF NOT EXISTS` + grants). `updated_at` trigger ile otomatik. `ravel_app` rolüne SELECT/INSERT/UPDATE/**DELETE** açık (admin paneli silme akışı için — DB-2'nin append-only kuralından farklı; bu tablo bir runtime config objesi).

2. **AES-256-GCM, Fernet değil.** `cryptography.hazmat.primitives.ciphers.aead.AESGCM`. Format: `[12B nonce][ciphertext][16B tag]` BYTEA olarak saklanır. `ENCRYPTION_KEY` 64 hex char (32 byte). Bad-key/short-key/auth-fail testleri ile sertifiyeli. **Anahtar kaybedilirse hiçbir api_key kurtarılamaz** — `.env` backup zorunlu.

3. **Provider router 6 sağlayıcı, gateway tek arayüz.** `LLMGateway.generate(agent_name, system_prompt, user_prompt) → str`:
   - anthropic → `anthropic.Anthropic` SDK (sync, `asyncio.to_thread`)
   - openai / openrouter → `openai.AsyncOpenAI` (base_url override openrouter için `https://openrouter.ai/api/v1`)
   - gemini → `google-generativeai` (sync, `asyncio.to_thread`)
   - ollama / custom → `httpx` POST `/api/chat` (SDK gerekmez; api_key opsiyonel)
   Hata = `LLMError`. Mock fallback YOK — caller (workflow) kendi mock metnini koyar; bu sayede gateway ayrı çağrılarda farklı sağlayıcılarla test edilebilir.

4. **Redis cache, 5 dk TTL, admin DEL ile invalidate.** `llm_config:{agent_name}` JSON; `_get_config_cached` önce Redis, sonra DB. Admin POST/PUT/DELETE Redis DEL eder (RAG'da cache invalidate, Orchestrator aynı Redis'i okuyor). Pub/Sub yerine direkt DEL — 5 dk window kabul edilebilir gecikme.

5. **`<düşünce>` chain-of-thought, prompt'a yazılır ama yanıttan temizlenir.** YAML template'lerde `<düşünce>...</düşünce>` blokları LLM'e gönderilir (CoT'yi devreye sokar). Yanıttan regex ile `<düşünce>...</düşünce>` ve `<thinking>...</thinking>` (case-insensitive, multiline) temizlenir. Defansif: kapanmamış tag varsa ilk close-tag sonrasını al; hiçbiri yoksa metni olduğu gibi döndür. **CoT'nin öğrenciye sızması büyük güvenlik/UX hatası** — test'te explicit kontrol var.

6. **Prompt template engine: 6 mod, paylaşımlı persona.** YAML dosyaları: `error_explanation`, `topic_teaching`, `step_by_step`, `qa_dialog` (4 pedagojik mod, ortak "Dijital Öğretmen" system_prompt'u), `manim_code`, `manim_correction` (2 kod-üretim modu, kendi system_prompt'ları). Jinja2 + `meta.find_undeclared_variables` ile required_vars audit; eksik placeholder warning + boş string default.

7. **agent_name ↔ mode mapping workflow'da, gateway'de değil.** Gateway `agent_name`'i config key olarak kullanır; mode (hangi YAML) workflow'un `_pick_text_mode` mantığında belirlenir (Bandit decision'a + `is_correct`'e göre). Bu ayrım önemli: sysadmin `orchestrator_text` ajanına farklı bir model verince 4 modun hepsi otomatik o modeli kullanır.

8. **Admin paneli RAG service'inde.** Spec gereği. RAG'a minimal DB-1 client (`db1_io.py`), AES cipher, Redis client eklendi. Provider test endpoint'i (`/admin/llm/test/{agent_name}`) — anthropic/openai/openrouter/gemini SDK'larını RAG image'ına yüklemek yerine `httpx` ile direkt REST çağrı yapan minimal `llm_test_helper.py`. RAG image küçük kalır, orchestrator tam-özellikli SDK'lara sahip olur.

9. **DB-2 read-only Orchestrator'dan; consecutive_errors + success_rate.** Yeni `db2_io.DB2ReadClient` — son 20 etkileşim üzerinden topic-bazlı `consecutive_errors` (en güncelden geriye, ilk doğruda kır) ve `success_rate`. DB-2 down ise `(0, 0.0)` default — workflow yine de prompt context üretir.

10. **Frustration heuristik (Adım 8'e kadar geçici).** `consecutive_errors` + `time_spent / t_baseline` doğrusal kombinasyonu → 0.0–1.0. Prompt'taki "duygusal zeka kuralları" bunu okur.

11. **`LLM_MOCK_MODE` toggle korundu.** True ise gateway DB'ye gitmez, sabit Türkçe mock döner. Test'te ve yeni kurulumlarda (config DB'de yokken) işe yarar. Production'da false.

**Etkilenen dosyalar:**
- `infra/postgres/init.sql` + `infra/postgres/init_app_role.sh` — `llm_configs` tablosu + GRANT
- `infra/postgres/migrations/001_llm_configs.sql` — idempotent migration (mevcut volume'a apply)
- `services/orchestrator/app/crypto.py` — AES-256-GCM cipher
- `services/orchestrator/app/llm_configs_repo.py` — CRUD
- `services/orchestrator/app/llm_gateway.py` — 6-provider router + cache + CoT strip + LLMError
- `services/orchestrator/app/prompt_engine.py` — Jinja2 yaml engine
- `services/orchestrator/app/prompts/{6 mod}.yaml` — system_prompt + user_prompt_template
- `services/orchestrator/app/db2_io.py` — read-only stats client
- `services/orchestrator/app/redis_io.py` — `push_conversation` / `get_conversation` (qa_dialog için)
- `services/orchestrator/app/workflow.py` — `_generate_text_intervention`, `_generate_manim_code`, `_correct_manim_code` (gateway + prompt_engine integration); `_pick_text_mode`, `_compute_frustration`, `_student_topic_stats`, `_build_pedagogy_context`
- `services/orchestrator/app/main.py` — gateway/cipher/db2/prompt_engine lifespan
- `services/orchestrator/app/config.py` — `encryption_key`, `llm_request_timeout_seconds`, `db2_dsn`
- `services/orchestrator/requirements.txt` — anthropic, openai, google-generativeai, jinja2, pyyaml, cryptography, httpx
- `services/rag/app/{crypto.py, llm_configs_repo.py, db1_io.py, llm_test_helper.py}` — admin paneli için
- `services/rag/app/admin_api.py` — 6 yeni `/admin/llm/*` endpoint
- `services/rag/app/main.py` — DB-1 + cipher + Redis client lifespan
- `services/rag/app/config.py` — `db1_dsn`, `encryption_key`
- `services/rag/requirements.txt` — asyncpg, cryptography, httpx
- `docker-compose.yml` — Orchestrator + RAG'a `ENCRYPTION_KEY`/`DB1_DSN`/`DB2_DSN` env; RAG'a postgres/pgbouncer depends_on
- `.env`/`.env.example` — `ENCRYPTION_KEY`
- `scripts/test_llm_unit.sh` — Aşama 1: crypto + CoT + prompt + repo + gateway cache (host venv, 27 test)
- `scripts/test_llm_admin.sh` — Aşama 2: RAG admin endpoint'leri (24 test)
- `scripts/test_llm_e2e.sh` — Aşama 3: gerçek OpenRouter API key ile e2e (kullanıcı manuel)

**Gerekçe:** Spec çoğunlukla birebir uygulandı; 5 onay alınmış sapma — (a) DB volume sıfırlama yerine migration; (b) AES-256-GCM (Fernet 128 değil); (c) `claude-sonnet-4-6` default (spec'teki 4-5 olmayan model); (d) `LLM_MOCK_MODE` korundu; (e) E2E test OpenRouter ile (Anthropic key direct değil).

**Sonuçları:** Adım 8 (Analytics) DB-2 read-only client'ı genişletebilir; Adım 9 (Frontend) admin paneli için React UI'da `/admin/llm/*` endpoint'lerini tüketecek. Cache invalidation Pub/Sub'a evrilebilir (multi-orchestrator deployment'ta önemli olur).

---

## ADR-019 — Frontend tasarım kararları (Adım 8)
*2026-05-06 · Adım 8*

**Bağlam:** RAVEL'in 6 mikro servisi backend'de hazır; öğrenciye ve admine yönelik
GUI lazım. Spec açık: dijital özel öğretmen hissi, koyu uzay temalı landing,
admin paneli, gamification (XP/streak), 3 öğrenme modu (soru / video / chat).
Onlarca framework + state library var; doğru kombinasyonu seçmek gerekiyor.

**Karar:** React 18 + Vite 5 + Tailwind 3 + Zustand + Framer Motion + React Query
+ React Router v6 + Recharts. CSS variable tabanlı tema sistemi. State machine
(IDLE → TOPIC_LIST → TOPIC_INTRO → MODE_SELECT → QUESTION/VIDEO/CHAT).
WebSocket + REST hibrit. Always-mounted admin paneli. Bandit bypass for
explicit user intent. Cold-start tax level sabit A1.

### Karar 1 — React + Vite (Next.js değil)

**Bağlam:** SPA mı SSR mi? Next.js modern standart sayılıyor.

**Alternatifler:** (a) Next.js 14 (SSR/RSC); (b) Create React App (deprecated); (c) Vite + React.

**Gerekçe:**
- RAVEL bir SPA — SEO gereksiz (giriş arkasında)
- SSR Anthropic LLM gibi backend-heavy bir akışta gereksiz overhead
- Vite dev server <500ms HMR; CRA artık desteklenmiyor
- Build artifact statik (nginx multi-stage'de servis edilir)

**Sonuçları:** `services/frontend/vite.config.js` proxy ile `/api`,`/auth`,`/admin`,`/ws`
backend servislerine yönlenir. Prod'da nginx aynı path'leri upstream proxy yapar.
Bundle: ~145 KB index + lazy chunk'lar (router, query, framer, recharts ayrı).

### Karar 2 — Tailwind CSS + koyu tema (Material UI değil)

**Bağlam:** Tasarım sistemi seçimi. Hızlı prototipleme + RAVEL palette uyumu lazım.

**Alternatifler:** (a) Material UI v5; (b) Chakra UI; (c) Tailwind CSS + custom config.

**Gerekçe:**
- Material UI ravel-bg/surface/elevated paletini özelleştirmek için tema override şart, bundle ~150 KB
- Tailwind utility-first → palette `tailwind.config.js`'te tek seferde tanımlanır (#0A0F1E, #111827, #1F2937, mavi/mor/altın aksanlar)
- JIT compiler ile prod bundle ~30 KB (kullanılmayan utility'ler purge)
- Glassmorphism efektleri için `card-glass` custom component @layer ile yazıldı

**Sonuçları:** Tüm bileşenler `bg-ravel-*` class'ları kullanır. Aksan renkler
(blue/purple/gold/green/red) sabit tutuldu. Display font: Poppins (600/700);
body font: Inter (400/500). Custom keyframes: shake, shimmer, float, pulseSoft.

### Karar 3 — Zustand (Redux değil)

**Bağlam:** Global state lazım: auth, learning FSM, gamification, theme.

**Alternatifler:** (a) Redux Toolkit; (b) Jotai; (c) Zustand.

**Gerekçe:**
- Redux Toolkit boilerplate ağır (slice, selector, middleware setup) — RAVEL'in
  state'i basit (auth + FSM + XP)
- Zustand bundle ~3 KB (Redux ~12 KB)
- `persist` middleware localStorage entegrasyonunu otomatik yapar
- Selector pattern: `useStore((s) => s.field)` ile re-render kontrolü
- 4 ayrı store: authStore, learningStore, gamificationStore, themeStore (her
  biri kendi sorumluluğunda — single store değil)

**Sonuçları:** `services/frontend/src/store/` 4 dosya. authStore + themeStore
persist'li, learning + gamification ephemeral. Her store ayrı `partialize` ile
hangi alanların persist olacağını kontrol eder.

### Karar 4 — State machine: IDLE → TOPIC_LIST → TOPIC_INTRO → MODE_SELECT → QUESTION/VIDEO/CHAT

**Bağlam:** Öğrenci akışı: sınıf seç → konu seç → mod seç → soru/video/chat.
Bu akışı React component conditional rendering ile mi, yoksa explicit FSM ile mi yöneteyim?

**Alternatifler:** (a) Component conditional (`if (state === ...)` her component'ta);
(b) XState; (c) Zustand store'da string enum + switch.

**Gerekçe:**
- XState overkill (8 state, 12 transition) — learning curve maliyeti var
- String enum + switch en sade pattern
- Her state net bir ekrana karşılık geliyor: TOPIC_LIST = TopicGrid, TOPIC_INTRO = TopicIntro, vs.
- MainPage tek noktada `switch (fsmState)` ile render seçer
- setGrade → TOPIC_LIST, setTopic → TOPIC_INTRO action'ları transition'ı atomik yapar

**Sonuçları:** `learningStore.js` STATES sabitleri export eder. Geçişler tek
yerde tanımlı. Yeni mod eklemek istersen sadece STATES + setMode + render switch
güncellersin. AnimatePresence ile state geçişlerinde 250ms fade animasyonu.

### Karar 5 — Bandit bypass: `question_id="intro"` pattern

**Bağlam:** Öğrenci yeni konuya girdiğinde TOPIC_INTRO'da konu anlatımı
göstermek istiyoruz. Ama Bandit servisi her ipucu kararını stochastic LinTS
ile veriyor; "intro" çağrısında "manim_video" çıkabilir → konu anlatımı
yerine 45 saniyelik render başlar (UX yıkıcı).

**Alternatifler:** (a) Bandit'e "context_type=intro" parametresi ekle ve
manuel filtrele; (b) Frontend "intro" çağrısı yerine doğrudan `topic_teaching`
mod istesin; (c) Orchestrator workflow'unda `question_id == "intro"` ise
Bandit'i atla, doğrudan `topic_teaching` üret.

**Gerekçe:**
- Bandit mimarisi "soru bağlamı" üzerine kurulu — intro context'i yapıya
  uymuyor
- Pedagojik olarak konu girişi her zaman `topic_teaching` olmalı (LLM ile
  ayrıntılı anlatım, soru ipucu değil)
- Reward signal hesaplanmaz (henüz soru yok), Bandit boş feedback alır
- Orchestrator workflow'da tek if ile bypass — Bandit kodunda değişiklik gerekmez

**Sonuçları:** `services/orchestrator/app/workflow.py::_handle_topic_intro`
fonksiyonu eklendi. Frontend `TopicIntro.jsx`'te `question_id: "intro"` payload'ı.
Bandit kararı gelmiyor, doğrudan `prompt_engine.render("topic_teaching", ...)`.

### Karar 6 — WebSocket + REST hibrit

**Bağlam:** Chat akışı için tam-duplex WebSocket mü, yoksa REST + WS hibrit mi?

**Alternatifler:** (a) Pure WebSocket (her mesaj WS üzerinden);
(b) REST gönderim + WebSocket dinleme; (c) HTTP/SSE.

**Gerekçe:**
- Mevcut Kafka altyapısı zaten request/response pattern'inde — Gateway WS
  sadece push notification için
- REST gönderim → Kafka'ya yaz → Orchestrator işle → Kafka response → Gateway
  WS push: bu pipeline test/debug edilebilir
- Pure WS olsaydı her mesaj için ayrı bir Kafka producer akışı gerekirdi
- HTTP/SSE çift yönlü değil; chat'te kullanıcı da yazıyor

**Sonuçları:** `POST /api/chat` (REST) → mesaj gönderimi; WS (`/ws`) → typing
indicator + LLM yanıt push. ChatBox.jsx iki kanalı senkron tutar.

### Karar 7 — Always-mounted admin paneli (AnimatePresence değil)

**Bağlam:** Admin paneli sağdan slide-over. Kapatıp açınca form state'i
kayboluyor mu, korunuyor mu?

**Alternatifler:** (a) AnimatePresence + `mode="wait"` (panel kapalıyken DOM'dan
silinir); (b) `display: none` (state korunur ama animasyon kaybolur);
(c) Always-mounted + transform/visibility ile gizle (hem state korunur hem
animasyon).

**Gerekçe:**
- AnimatePresence: Admin "İçerik Yükleme" formunda PDF seçti, "LLM Yönetimi"
  sekmesine geçti, geri döndüğünde dosya seçimi sıfırlanmış → frustrasyon
- `display: none` → motion animation çalışmaz (DOM'da olsa bile)
- Always-mounted + `x: 100%` + `visibility: hidden` → state korunur, animasyon
  smooth, klavye odağı `aria-hidden` ile dışlanır

**Sonuçları:** `AdminPanel.jsx` 4 sekmeyi `PaneWrap` içinde always-mount
ediyor. Sekme değişiminde sadece opacity + transform. Form state'leri ve
fetch sonuçları korunur. Yarım kalan iş kaybı önlenir.

### Karar 8 — `COLD_START_TAX_LEVEL = "A1"`

**Bağlam:** Yeni öğrenci için ilk soruda Bandit kararı yok (history boş).
Tax level (Bloom seviyesi: A1/A2/B1/B2/C1/C2) frontend'de mi seçilsin, yoksa
sabit mi?

**Alternatifler:** (a) Öğrenciye seviye seçtir (UI chip selector);
(b) Sabit A1; (c) Grade-level'dan otomatik türetme (5. sınıf = A1, 8. sınıf = B1).

**Gerekçe:**
- Bandit'in temel görevi tax level seçmek; UI'da chip selector koyarsak
  Bandit'in anlamı kalmaz
- Pedagojik olarak cold-start için en basit seviyeden başlamak doğru —
  öğrencinin gerçek seviyesini Bandit interaction'lardan öğrenir
- Grade-level eşlemesi yanlış olabilir (8. sınıf öğrencisi konuyu yeni
  görüyor olabilir)

**Sonuçları:** Frontend `QuestionCard.jsx`'te tax level UI yok. Frontend her
soru talebinde `taxonomic_level: "A1"` gönderir. Bandit ilk birkaç
interaction'dan sonra reward'a göre upgrade/downgrade yapar.

### Karar 9 — `grade_level` kayıt formundan kaldırıldı

**Bağlam:** Öğrenci kayıt formunda sınıf alanı zorunlu mu? Spec başlangıçta
zorunluydu.

**Alternatifler:** (a) Zorunlu (sınıfa kilitli hesap);
(b) Opsiyonel (sidebar'da runtime override);
(c) Hiç sorma (her sefer sidebar'dan seç).

**Gerekçe:**
- Bir öğrenci 5. sınıftaysa bile 6. sınıf konularına bakmak isteyebilir
  (öğretmen önerisi, ileri seviye merak)
- Sidebar'da 4 sınıf kartı var → seçim runtime'da olmalı
- Backend `RegisterRequest.grade_level: Optional` → varsayılan 6 placeholder
- Per-request `grade_level` override pattern: AnswerRequest + ChatRequest
  payload'ında grade_level gönderilir

**Sonuçları:** `StudentRegisterForm.jsx` sadece username + password + display_name.
Backend `db1.create_user` grade_level=6 default. Sidebar'dan seçilen sınıf
her API çağrısında payload'a eklenir.

### Karar 10 — CSS variable tabanlı tema sistemi

**Bağlam:** Açık/koyu tema toggle. 20+ bileşene `dark:bg-*` prefix eklemek
yerine merkezi yönetim isteniyor.

**Alternatifler:** (a) Tailwind `dark:` class prefix (her bileşende `bg-white dark:bg-ravel-bg`);
(b) Iki ayrı theme dosyası + dynamic import; (c) CSS variable + `:root` / `.light` switch.

**Gerekçe:**
- `dark:` prefix yaklaşımı 20+ bileşeni tek tek gözden geçirmek demek (~200+ class değişimi)
- CSS variable: `bg-ravel-bg` class'ı `var(--ravel-bg)`'e bağlı; `:root` (dark)
  ve `.light` blokları variable değerlerini değiştirir
- Tüm bileşenler hiç değişmeden tema toggle çalışır
- Aksan renkler (blue/purple/gold/green/red) sabit kalır — sadece arka plan
  + metin değişir
- `index.html`'e inline script ekleyerek hidrasyon öncesi tercih uygulanır →
  ilk render'da flicker yok

**Sonuçları:** `src/index.css` `:root` + `.light` blokları. `tailwind.config.js`
ravel-bg/surface/elevated/text/muted CSS variable'a bind. `themeStore.js`
persist'li. App.jsx useEffect ile `<html>` element'ine `.light` class'ı ekle/kaldır.
Navbar + LandingPage'de toggle butonu (☀️/🌙).

---

**Etkilenen dosyalar:**

- `services/frontend/package.json` — pin'lenmiş bağımlılıklar
- `services/frontend/vite.config.js` — proxy + manualChunks
- `services/frontend/tailwind.config.js` — ravel palette + CSS variable bind
- `services/frontend/nginx.conf` — SPA fallback + 4 upstream proxy + WS Upgrade
- `services/frontend/Dockerfile` — multi-stage node:20 → nginx:1.27
- `services/frontend/src/index.css` — :root + .light theme variables
- `services/frontend/src/App.jsx` — ProtectedRoute + theme effect
- `services/frontend/src/store/{authStore, learningStore, gamificationStore, themeStore}.js`
- `services/frontend/src/hooks/{useAuth, useWebSocket}.js`
- `services/frontend/src/api/{auth, admin, chat}.js`
- `services/frontend/src/data/curriculum.js` — MEB 5-8 hardcoded
- `services/frontend/src/pages/{LandingPage, LoginPage, MainPage, NotFound}.jsx`
- `services/frontend/src/components/layout/{Navbar, Sidebar}.jsx`
- `services/frontend/src/components/learning/{IdleHero, TopicGrid, TopicIntro, ModeSelector, QuestionCard, VideoCard, ChatBox}.jsx`
- `services/frontend/src/components/admin/{AdminPanel, StudentRegisterForm, ContentUploadTab, LLMManagerTab, StatisticsTab, DropZone}.jsx`
- `services/api_gateway/app/auth.py` — bcrypt direct (passlib bypass)
- `services/api_gateway/app/db1_io.py` — auth queries
- `services/api_gateway/app/db2_io.py` — gamification stats
- `services/api_gateway/app/question_parser.py` — RAG chunk → Q+options+answer_key
- `services/api_gateway/app/main.py` — CORS + 7 yeni endpoint
- `infra/postgres/migrations/002_auth.sql` — students.username/password_hash/role
- `infra/postgres/seed_admin.sh` — pgcrypto bcrypt admin seed
- `services/orchestrator/app/workflow.py` — `_handle_topic_intro` (Bandit bypass)
- `docs/manual_test_step8.md` — 9 senaryolu manuel test rehberi

**Gerekçe (özet):** Spec'in dayattığı palet + pedagojik akış birebir korundu.
10 karar bir bütün halinde alındı; her biri spec'teki bir gereksinimi sağlıyor
(tema, FSM, mode select, admin paneli, vs.). Sapma yok.

**Sonuçları:** Adım 9 (Analytics) için frontend hazır — `StatisticsTab`'a
yeni metrikler (öğrenme kazancı g, MCR, RI) Recharts ile eklenecek.
A/B testi UI'sı admin paneline 5. sekme olarak eklenebilir (aynı PaneWrap pattern).
Mobile responsive (md:/lg: breakpoint) zaten yerleşik; native app gerekirse
React Native paylaşımlı olabilir (Zustand + axios + same API'lar).

---

## Yeni karar eklemek için

Bir şey değişiyor, yeni teknoloji seçiliyor, bir kuralı kaldırıyoruz — aşağı doğru en sondan sonra şu şablonla yeni başlık aç:

```markdown
## ADR-NNN — Başlık
*YYYY-MM-DD · Adım X*

**Bağlam:** Sorun nedir, ne karar gerektirdi?
**Karar:** Net cümle.
**Gerekçe:** Maddeli liste.
**Sonuçları:** Hangi dosyalar etkilendi, gelecek davranışı nasıl şekillendiriyor.
```

**İptal edilen / geri alınan kararlar silinmez** — başlığa `(Superseded by ADR-XXX, YYYY-MM-DD)` etiketi eklenir. Bu pattern (immutable history) decision log'un güvenirliğini sağlar.

Karar verirken Claude Code'a haber ver — Claude memory'i de senkron tutabilsin.
