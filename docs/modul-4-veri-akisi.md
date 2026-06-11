# RAVEL Eğitim Serisi — Modül 4: Veri Akışı

> Bir mesajın sistem içinde uçtan uca yolculuğu.
>
> **Tarih:** 2026-05-04
> **Bağlam:** RAVEL projesinin Adım 1 (altyapı) tamamlandıktan sonra, Adım 2'ye geçmeden
> önce yürütülen 4 modüllük eğitim serisinin son modülü.

---

Bu modülde Modül 1-2-3'te öğrendiğin tüm parçaları **canlı bir senaryoya** bağlayacağız. Soyut mimariden, "saatte 14:32:01'de Ali hangi mesajı, hangi servise, ne sırayla gönderiyor"a geçiyoruz.

İki büyük senaryo var:
- **Hata senaryosu** (öğrenci yanlış cevap verdi) — sistemin tüm parçaları devreye girer; bu yüzden onu detaylı anlatacağım
- **Mutlu yol** (öğrenci doğru cevap verdi) — kısa anlatacağım

Ek olarak: **hata yönetimi** (bir servis çökerse), **trace_id ile takip**, ve sonunda iki egzersiz.

---

## A. Genel prensipler — önce zihinsel modeli kuralım

### Prensip 1: Asla kimse beklemez

Klasik mimaride Gateway, Orchestrator'dan cevap gelmesini bekler. RAVEL'de **kimse kimseyi beklemez**. Mesajını Kafka'ya yazar, sonraki tüketici hazır olduğunda okur. Bu yüzden tek bir kullanıcı isteği, yan yana 4-5 servisi tetikleyebilir ama hiçbiri kilitli kalmaz.

### Prensip 2: Mesajlar `correlation_id` ile bağlanır

Bir öğrenci tıklar, sistem **3-5 farklı Kafka mesajı** üretir. Hangi yanıtın hangi isteğe ait olduğunu bulmak için her mesaj bir `correlation_id` (veya `trace_id`) taşır. Mesela:
- Gateway `req_8812` ID'li mesaj atar
- Orchestrator yanıtında `req_8812` korur
- Sonunda Gateway o ID'yi görüp doğru WebSocket bağlantısına iter

### Prensip 3: "Default-to-Text" kuralı (kaynak korumacı)

Tek bir soruda yanlış cevap → **Bandit'i bile beklemeden** RAG+LLM ile metin yanıtı üretilir. Çünkü:
- Video render = pahalı (45 sn'ye kadar, GPU)
- Tek hata henüz "sistematik kavram yanılgısı" sayılmaz

Video sadece iki durumda tetiklenir:
1. Öğrenci açıkça "Video Oluştur" butonuna basar
2. Öğrenci yepyeni bir ana konuya başlar (kavramsal giriş animasyonu)

---

## B. Senaryo: Ali, üslü ifadeler sorusunu yanlış yapıyor

**Bağlam:** Ali (6. sınıf, `student_id = std_9912`) `2³ × 2² = ?` sorusunda C şıkkını işaretledi. Doğru cevap B. Şu an 14:32:01.

Aşağıda **her saniyede ne olduğunu** adım adım göreceksin.

### ⏱ T+0 ms — GUI'de tıklama

Ali "C" butonuna basar. React frontend hemen bir WebSocket mesajı atar:

```json
// GUI → Gateway (WebSocket)
{
  "event": "answer_submitted",
  "session_token": "jwt-...",
  "question_id": "q_6_mat_2_10",
  "selected_answer": "C",
  "time_spent": 42
}
```

Aynı anda GUI **"Yanıtın değerlendiriliyor..."** spinner'ı gösterir.

### ⏱ T+5 ms — Gateway: Redis + Kafka

API Gateway 3 işi paralel yapar:

1. **Redis'ten oturum doğrula** (`session:std_9912` anahtarını oku, JWT geçerli mi?)
2. **Cevabı doğru/yanlış olarak işaretle** (`is_correct: false`)
3. **Kafka'ya yaz** (asıl iş bu):

```json
// Topic: student_interactions_stream
{
  "event_id": "e4b3-4f21-88aa",
  "trace_id": "trace_8812",
  "student_id": "std_9912",
  "event_type": "question_answered",
  "payload": {
    "question_id": "q_6_mat_2_10",
    "topic": "Uslu_Ifadeler",
    "taxonomic_level": "B1",
    "is_correct": false,
    "time_spent": 42,
    "explicit_video_request": false
  },
  "timestamp": "2026-05-04T14:32:01Z"
}
```

Gateway artık işini bitirdi; yeni isteklere bakabilir. **Beklemiyor.**

### ⏱ T+10 ms — Aynı mesaj, üç ayrı tüketiciye

`student_interactions_stream` topic'ini **üç farklı consumer group** dinliyor. Üçü de aynı mesajı alır ama farklı şeyler yapar:

```
                    student_interactions_stream
                          │ (e4b3-4f21-88aa)
              ┌───────────┼───────────┐
              ▼           ▼           ▼
        Orchestrator  Bandit Learner  Analytics
        "ne yapayım?" "ödülü ölçeyim"  "loglayayım"
```

**Kafka'nın gücü burada:** üç consumer'ın her biri kendi temposunda okur, biri yavaşsa diğerleri etkilenmez.

### ⏱ T+15 ms — Analytics servisi (en basit yol)

Analytics mesajı alır, **DB-2'ye INSERT** atar. Hepsi bu. Reward henüz bilinmediği için `reward_signal` şimdilik 0.0 yazılır (sonra gerçek değerle yeni satır eklenir, eski satır asla update edilmez):

```sql
-- DB-2 (PgBouncer üzerinden)
INSERT INTO interaction_logs
  (student_id, topic_id, taxonomic_level, action_taken,
   is_correct, time_spent_seconds, frustration_index, reward_signal)
VALUES ('std_9912', 'math_6_uslu', 'B1', 'pending', false, 42, 0.6, 0.0);
```

### ⏱ T+15 ms — Bandit Learner (gecikmeli ödül için hazırlık)

Learner mesajı alır ama **henüz ödülü hesaplayamaz**. Çünkü ödül = "müdahaleden sonraki soruda öğrenci doğru yaptı mı?" — o soru daha sorulmadı bile.

Bu yüzden Learner, bağlamı (öğrencinin 12-D context vector'ı) **Redis'e geçici olarak yazar**:

```
SET pending:trace_8812 '{"context_vector":[6,1,0,0.45,2,0.3,1.2,0.6,0,2,0.7,0.3], "action_taken":null}'
EXPIRE pending:trace_8812 1800   # 30 dk içinde sonraki soru gelmezse unut
```

### ⏱ T+15 ms — Orchestrator (asıl beyin)

Orchestrator mesajı alır, kararı verir:

> Tek soruda yanlış cevap. Default-to-Text kuralı devreye giriyor. Bandit'i bile çağırmıyorum, doğrudan RAG+LLM ile metin yanıtı üreteceğim.

Burada **kritik tasarım kararı**: Orchestrator, Bandit'e gitmeden, RAG'a istek atar. Çünkü tek hata için video pahası göze alınmaz.

```json
// Topic: content_retrieval_requests (Orchestrator → RAG)
{
  "trace_id": "trace_8812",
  "query": {
    "subject": "Uslu_Ifadeler",
    "taxonomic_level": "B1",
    "content_type": "explanation",
    "context": "Öğrenci 2³ × 2² işlemini yanlış yaptı, üslerin toplanması kuralında hata yapmış olabilir"
  },
  "top_k": 5
}
```

### ⏱ T+50 ms — RAG: vektör araması + döndür

RAG servisi mesajı alır, üç adım:

**1. Embedding üret:**
"üslerin toplanması kuralı, 2³ × 2²" cümlesini multilingual MiniLM modeline verir → 384-D vektör.

**2. Qdrant'a hibrit sorgu:**
```python
qdrant.search(
    collection="rag_knowledge_base",
    query_vector=[0.012, -0.045, ...],
    query_filter={
        "must": [
            {"key": "subject", "match": {"value": "Uslu_Ifadeler"}},
            {"key": "taxonomic_level", "match": {"value": "B1"}},
            {"key": "content_type", "match": {"value": "explanation"}}
        ]
    },
    limit=5
)
```

Qdrant 5 en yakın chunk'ı döner (hepsi B1 seviyesinde, üslü ifadeler konusunda, açıklama tipinde).

**3. Kafka'ya yanıt:**
```json
// Topic: content_retrieval_responses (RAG → Orchestrator)
{
  "trace_id": "trace_8812",
  "chunks": [
    {"text": "Aynı tabanlı üsler çarpılırken üsler TOPLANIR: a^m × a^n = a^(m+n)", "score": 0.92},
    {"text": "Örnek: 2³ × 2² = 2^(3+2) = 2⁵ = 32", "score": 0.88},
    ...
  ]
}
```

### ⏱ T+150 ms — Orchestrator: LLM ile pedagojik metin

Orchestrator chunk'ları alır, önce **Redis Semantic Cache**'e bakar:

```
Yeni sorgu embedding'i ile cache'teki embeddingleri karşılaştır
%95+ benzerlik var mı?
   ├─ Evet → cache'ten cevap döndür (≤10 ms, sıfır LLM maliyeti)
   └─ Hayır → LLM'e git
```

Cache miss varsayalım. Orchestrator LLM'e prompt atar:

```
Sen bir 6. sınıf matematik öğretmenisin. Aşağıdaki kaynaklardan
yararlanarak öğrenciye nazik, kavramsal bir açıklama yap.

Soru: 2³ × 2² = ?
Öğrencinin verdiği yanıt: C (yanlış)

Kaynaklar:
- Aynı tabanlı üsler çarpılırken üsler TOPLANIR...
- Örnek: 2³ × 2² = 2^(3+2) = 2⁵ = 32

Çıktı:
1. Hatayı yargılamadan belirt
2. Kuralı sade dille açıkla
3. Adım adım çözümü göster
```

LLM ~800 ms'de yanıt döner. Orchestrator metni paketler:

```json
// Topic: content_delivery_stream (Orchestrator → Gateway)
{
  "trace_id": "trace_8812",
  "student_id": "std_9912",
  "content_type": "text_explanation",
  "body_html": "<p>Çok yakındın aslında! Bu soruda küçük bir kural devreye giriyor...</p>...",
  "next_action": "wait_for_student"
}
```

### ⏱ T+1000 ms — Gateway: WebSocket → GUI

Gateway `content_delivery_stream`'i dinliyor. Mesajı alır, `trace_id`'den hangi öğrenciye gideceğini bulur, **WebSocket üzerinden GUI'ye iter**.

Ali'nin ekranında spinner kapanır, açıklama belirir. **Toplam süre: ~1 saniye** (CLAUDE.md SLA'sı: <1.5 sn metin yanıtı).

### ⏱ T+30 sn — Ali sonraki soruyu cevaplar (gecikmeli ödül)

Ali açıklamayı okur, "Anladım" der, sonraki benzer soruyu çözer. Bu sefer doğru. Yeni mesaj `student_interactions_stream`'e düşer:

```json
{
  "trace_id": "trace_8813",
  "previous_trace_id": "trace_8812",
  "is_correct": true,
  ...
}
```

Bandit Learner bu mesajı görür, **Redis'teki `pending:trace_8812`** kaydını okur, ödülü hesaplar:

```
C_t = +0.5  (sonraki soruyu doğru, ipucuyla)
T_baseline / T_actual = 0.9  (zaman verimli)
S_t = +1.0   ("Anladım" anketi)

r_t = 0.6 × 0.5 + 0.2 × 0.9 + 0.2 × 1.0 = 0.68
```

Bu ödülü `reward_logs_stream` topic'ine yazar. Bandit Learner mini-batch eğitim için biriktirir; her 100 mesajda bir model güncellenir, MinIO'ya yeni ağırlıklar yüklenir, Redis Pub/Sub ile Actor'a "yeni model hazır" sinyali gider, Actor canlı trafiği aksatmadan modeli swap eder.

---

## C. Senaryo 2: Mutlu yol (doğru cevap)

Daha kısa bir akış. Ali doğru cevap verirse:

1. **GUI → Gateway → Kafka** (`student_interactions_stream`, `is_correct: true`)
2. **Orchestrator** mesajı görür → "öğrenci hazır, üst seviyeye taşıyalım"
3. **Bandit Actor**'a sorar: "B1 başardı, B2'ye mi geçeyim?"
4. **Bandit** bağlamı değerlendirir, `decision = "upgrade_to_B2"` döner
5. **RAG**'a istek: "B2 seviyesinde, üslü ifadeler, content_type=question, file_name=6_mat_2 ile uygun bir soru"
6. RAG Qdrant'tan filtreli vektör araması yapar, B2 seviyesinde benzer ama biraz daha zor bir soru bulur
7. **Orchestrator** kısa bir tebrik mesajıyla soruyu birleştirir, Gateway'e iter
8. GUI'de "Harika! Şimdi biraz daha zorlayıcı bir soru:" + yeni soru

Toplam süre: ~700-900 ms. Video motoru asla tetiklenmez.

---

## D. "Video Oluştur" senaryosu (kullanıcı açıkça istedi)

Ali metin açıklamayı yetersiz buldu, sağ üstteki "Video Oluştur" butonuna bastı. Bu senaryo daha karmaşık:

1. **Gateway → Kafka** (`student_interactions_stream`, `explicit_video_request: true`)
2. **Orchestrator**: "Tamam, video onayı geldi"
3. **RAG**'dan **content_type=theory** filtreli kaynaklar çek (üslü ifadelerin görsel anlatımı)
4. **Orchestrator → LLM**: "Bu konseptleri anlatan bir Manim Python kodu yaz, 30 sn'lik video"
5. LLM Manim kodu üretir → `manim_render_tasks` topic'ine atılır
6. **Manim Worker** kodu alır, **sandbox**'ta önce sözdizimi/güvenlik testi yapar
   - **Eğer kod hatalı:** `qa_correction_loop` topic'ine "şu hata var, düzelt" diye geri gönderir → max 3 deneme
   - **Eğer 3 deneme sonra hala hatalı:** mesaj `dead_letter_queue_ravel`'e düşer → Orchestrator fallback metni döner
7. Kod sağlamsa render başlar. **Süre limiti: 45 saniye** (CLAUDE.md SLA)
8. Render başarılı → MP4 MinIO'ya yüklenir → URL `video_ready_events` topic'ine yazılır
9. **Gateway** URL'i alır, WebSocket'le GUI'ye iter, video Ali'nin ekranında oynar

**Süre boyunca Ali ne görür?** "Video hazırlanıyor..." mesajı + ilerleme göstergesi. 45 sn dolmuşsa otomatik olarak metin fallback'e döner.

---

## E. Hata senaryoları — her şey ters giderse?

RAVEL gerçek dünya için tasarlanmış, dolayısıyla 4-5 farklı failure mode'a hazırlık var:

### E.1 — RAG çöktü
**Sorun:** Qdrant cevap vermiyor, RAG `content_retrieval_responses`'a hiçbir mesaj atmıyor.

**Çözüm:** Orchestrator ↔ RAG arasında **Circuit Breaker** (Python `pybreaker` lib'i). 5 ardışık başarısız istekte devre "Açık" duruma geçer; sonraki istekleri RAG'a hiç göndermez, doğrudan **Redis'teki statik fallback metni** döner ("Şu an açıklama yapılamıyor, lütfen birkaç dakika sonra tekrar deneyin").

Sistem kilitlenmez, kullanıcı en azından bir şey görür.

### E.2 — Manim render zaman aşımı
**Sorun:** 45 sn doldu, video hâlâ hazır değil.

**Çözüm:** Mesaj `dead_letter_queue_ravel` topic'ine düşer. Orchestrator DLQ'yu dinliyor, fallback metin senaryosu devreye girer:
> "Video şu an oluşturulamadı, ancak adım adım çözümü şurada..."

### E.3 — Bandit Actor cevap vermedi
**Sorun:** Bandit kararı 50 ms'de gelmesi gerekirken yok.

**Çözüm:** Orchestrator timeout uygular (örn. 200 ms). Süre dolunca **default kararı** uygular: `intervention_type = text`. Sistem yine de yanıt verir, sadece kişiselleştirme bir tık zayıflar.

### E.4 — Bir servis crash oldu
**Sorun:** Orchestrator container'ı OOM kill aldı.

**Çözüm:** Orchestrator **stateless** (durum Redis'te). Docker `restart: unless-stopped` ile saniyeler içinde yeni container kalkar. Kafka'da hangi offset'e kadar okuduğunu hatırlar, kaldığı yerden devam eder. **Kullanıcı sadece o anki isteğin biraz gecikmesini fark eder; veri kaybı yoktur.**

---

## F. Trace_id ile bir mesajı uçtan uca takip etmek

Hata oluştuğunda "hangi servise nereden ulaştı, nerede takıldı?" sorusunu cevaplamak için her mesaj `trace_id` taşır. Production'da OpenTelemetry + Jaeger ile bu zaman çizelgesi otomatik çizilir:

```
trace_id = trace_8812

  ⏱ 0ms     Gateway: receive WebSocket message
  ⏱ 5ms     Gateway: write to student_interactions_stream
  ⏱ 12ms    Orchestrator: consume student_interactions_stream
  ⏱ 14ms    Orchestrator: write to content_retrieval_requests
  ⏱ 22ms    RAG: consume content_retrieval_requests
  ⏱ 48ms    RAG: Qdrant search complete (26 ms)
  ⏱ 52ms    RAG: write to content_retrieval_responses
  ⏱ 55ms    Orchestrator: consume content_retrieval_responses
  ⏱ 58ms    Orchestrator: cache miss, calling LLM
  ⏱ 845ms   Orchestrator: LLM responded (787 ms)
  ⏱ 850ms   Orchestrator: write to content_delivery_stream
  ⏱ 855ms   Gateway: consume + push WebSocket
  ⏱ 870ms   GUI: render
```

Bu modülde Jaeger'ı henüz kurmadık (Adım 3-4'e ertelenmişti). Ama her serviste her log/mesaj `trace_id` taşıyacak şekilde yazılacak — şimdiden alışmak iyi.

---

## G. Egzersizler

### Egzersiz 1 — Kağıt üstünde simülasyon

Ali video butonuna bastı. **Hangi 6 Kafka topic'i** sırayla kullanılır? Hangi mesajda hangi `trace_id`/`correlation_id` taşınır?

İpucu: `student_interactions_stream`, `bandit_decision_requests`, `bandit_decision_responses`, `content_retrieval_requests`, `content_retrieval_responses`, `manim_render_tasks`, `qa_correction_loop` (gerekirse), `video_ready_events` arasından seç ve sırala.

### Egzersiz 2 — Failure analizi

Şu durumda hangi fallback devreye girer, kullanıcı ne görür?

a) Qdrant container'ı çöktü ama Postgres ayakta.
b) Manim Worker render başlattı ama 47. saniyede hâlâ bitmedi.
c) Bandit Actor 200 ms'de cevap vermedi.
d) Kafka cluster'ı tamamen çöktü.

(d) zor: Kafka olmadan **hiçbir şey** çalışmaz. Bu yüzden production'da Kafka 3+ broker'lı, replication factor 3'le kurulur. Bizim dev'de tek broker — kabul edilebilir bir risk.

### Egzersiz 3 — End-to-end manuel deneme

Bir Python servisin yokken bile, **CLI araçlarıyla** Ali'nin akışını canlı yaşayabilirsin:

1. Bir terminal: `student_interactions_stream` topic'ini **producer** olarak aç, yukarıdaki örnek JSON'u yaz.
2. Başka terminal: aynı topic'i **consumer** olarak izle (`--from-beginning`). Mesajın geldiğini gör.
3. Postgres'e bağlan, DB-2'ye manuel bir interaction satırı INSERT et (Analytics'i simüle et).
4. Qdrant'a bir test koleksiyonu aç, içine 5 vektör koy (RAG'i simüle et).

Bunlar Adım 2'de yazacağın gerçek servislerin **manuel hali**.

---

## Modül 4 sonu — kontrol soruları

1. Ali yanlış cevap verince **kaç farklı Kafka topic**'ine mesaj yazılır? Hangileri?
2. Default-to-Text kuralı tetiklenince Bandit servisi devreye **girer mi**?
3. RAG'ın Qdrant sorgusu cevap vermezse, kullanıcı 30 saniye boyunca beyaz ekran mı görür?
4. Bandit'in ödülü neden hemen değil, bir sonraki soruda hesaplanır?
5. Video render başarısız olursa, mesaj nereye düşer ve kim onu yakalar?

---

## Eğitim serisi referansı

| Modül | Konu |
|---|---|
| Modül 1 | Container ve Compose temelleri |
| Modül 2 | Servislerin rolü (Postgres, PgBouncer, Redis, Kafka, Qdrant, MinIO) |
| Modül 3 | Pratik komutlar — her servise nasıl bağlanılır, debug edilir |
| **Modül 4** | **Veri akışı (bu dosya)** |
