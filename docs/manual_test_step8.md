# RAVEL — Adım 8 Manuel Test Rehberi

**Sürüm:** 0.8 (Frontend tamamlandı) · **Tarih:** 2026-05-06

Bu rehber, RAVEL platformunun frontend (Adım 8) tamamlandıktan sonra
uçtan uca manuel test edilmesi için adım adım senaryoları içerir.
Her senaryo bağımsız olarak veya sıralı koşulabilir; ancak Senaryo 1, 2 ve 3
diğer senaryolar için ön koşuldur (sistem ayağa kalkmadan, admin/öğrenci
hesabı oluşmadan ve LLM yapılandırılmadan tam akış test edilemez).

> **İpucu:** Tüm senaryoları tek seferde koşmak için sırayla 1 → 9.

---

## Senaryo 1: Sistem başlatma

### Ön Koşullar

- Docker Desktop çalışıyor
- `git pull` ile güncel kod
- 8000, 8001, 8002, 8003, 5173, 5432, 6379, 9092, 9000, 6333 portları boş
- `.env` dosyası `.env.example` baz alınarak hazırlandı

### Adımlar

1. Proje kökünde terminal aç:
   ```bash
   cd /path/to/project_ravel
   ```
2. Tüm container'ları kaldır:
   ```bash
   docker compose up -d
   ```
3. ~30 saniye bekle (Postgres + Kafka KRaft + Qdrant + MinIO healthy olana kadar).
4. Container durumlarını kontrol et:
   ```bash
   docker compose ps
   ```
5. Tarayıcıda aç: <http://localhost:5173>

### Beklenen Sonuç

- Tüm servisler **healthy** durumunda
- `ravel_postgres`, `ravel_redis`, `ravel_kafka`, `ravel_qdrant`, `ravel_minio` Up
- `ravel_api_gateway`, `ravel_orchestrator`, `ravel_bandit_actor`, `ravel_bandit_learner`, `ravel_rag`, `ravel_manim_worker`, `ravel_frontend` Up (healthy)
- Tarayıcıda RAVEL landing page görünmeli (RAVEL logo + iki rol kartı: Öğrenciyim / Yöneticiyim + arka planda yüzen matematik sembolleri)

### Olası Sorunlar

| Sorun | Neden | Çözüm |
|---|---|---|
| `ravel_postgres` "starting" → "unhealthy" | Migration dosyaları hatalı | `docker compose logs postgres` → SQL hatasını oku, `infra/postgres/migrations/`'ı düzelt |
| `ravel_kafka` restart döngüsünde | KRaft cluster id farklı | `docker compose down -v` → `up -d` (named volume sıfırlanır) |
| Frontend "Connection refused" | Frontend container daha hazır değil | `docker compose logs frontend` → `nginx: ready`'yi bekle (~6 sn) |
| Port çakışması | Başka servis 5173/8000'i kullanıyor | `lsof -i :5173` → çakışan süreci kapat |

---

## Senaryo 2: Admin girişi ve öğrenci kaydı

### Ön Koşullar

- Senaryo 1 tamamlandı (sistem ayakta)
- Admin seed script'i çalıştırılmış olmalı (otomatik: `infra/postgres/seed_admin.sh` ilk açılışta tetiklenir)

### Adımlar

1. Landing page'de **"Yöneticiyim"** kartına tıkla.
2. Login formunda:
   - Kullanıcı adı: `admin`
   - Şifre: `ravel_admin_2025`
3. **"Giriş Yap"** butonuna tıkla.
4. Yönlendirme sonrası ana sayfada (MainPage) sağ üstte **⚙️ Admin** butonu görünmeli.
5. **⚙️ Admin** butonuna tıkla → sağdan slide-over panel açılır.
6. **"Öğrenci Ekle"** sekmesinde:
   - Kullanıcı adı: `ali_test`
   - Şifre: `Ali2025!` (en az 8 karakter)
   - Görünen ad: `Ali Yılmaz`
   - Şifre tekrar
7. **"Öğrenci Oluştur"** butonuna tıkla.
8. Yeşil banner'da "Öğrenci başarıyla oluşturuldu" mesajını gör.
9. Sağ üstte **"Çıkış"** → landing page'e dön.
10. **"Öğrenciyim"** → kullanıcı adı: `ali_test`, şifre: `Ali2025!` → **"Giriş Yap"**.

### Beklenen Sonuç

- Admin giriş başarılı; sağ üstte ⚙️ Admin butonu görünüyor
- Slide-over panel 4 sekmeyle açılıyor (Öğrenci Ekle / İçerik Yükleme / LLM Yönetimi / İstatistikler)
- Yeni öğrenci başarıyla kaydedildi (DB-1'de student satırı + bcrypt password_hash)
- Öğrenci girişi başarılı; MainPage açılıyor (ama ⚙️ Admin butonu görünmüyor)
- Sol sidebar'da 4 sınıf kartı (5/6/7/8) görünüyor

### Olası Sorunlar

| Sorun | Neden | Çözüm |
|---|---|---|
| "Geçersiz kimlik bilgileri" | Admin seed çalışmadı | `docker compose exec postgres psql -U ravel_app db1 -c "SELECT username FROM students WHERE role='admin'"` — boşsa `infra/postgres/seed_admin.sh`'i manuel çalıştır |
| "8 karakter altı şifre" hatası | Validation çalışıyor | Daha uzun şifre kullan |
| Öğrenci kaydı başarısız "username already exists" | Aynı isim kullanıldı | Farklı username dene |
| ⚙️ Admin butonu görünmüyor | role !== "admin" | JWT'yi decode et: `localStorage.getItem("ravel.auth.v1")` → token → jwt.io'da role'ü kontrol et |

---

## Senaryo 3: LLM konfigürasyonu

### Ön Koşullar

- Senaryo 2 tamamlandı (admin girişi yapıldı)
- Bir adet OpenAI veya OpenRouter API key elinde

### Adımlar

1. Admin paneli aç (**⚙️ Admin**).
2. **"LLM Yönetimi"** sekmesine geç.
3. **`orchestrator_text`** ajan kartını bul.
4. **"Yapılandır"** butonuna tıkla.
5. Açılan formda:
   - Provider: `openrouter` (veya `openai`)
   - Model: `anthropic/claude-sonnet-4-5` (OpenRouter) veya `gpt-4o-mini` (OpenAI)
   - API Key: senin gerçek anahtarın
   - Temperature: `0.3` (varsayılan kalabilir)
   - Max tokens: `1500`
6. **"Test Et"** butonuna tıkla.
7. ~5 saniye bekle → yeşil banner: "Bağlantı başarılı, model X yanıt verdi".
8. **"Kaydet"** butonuna tıkla → API key AES-256-GCM ile şifrelenip DB'ye yazıldı.
9. Diğer ajanlar için de tekrarla (öncelik: `orchestrator_video_code`, `rag_step_by_step`, `orchestrator_chat`).
10. Terminalde `LLM_MOCK_MODE=false` yap:
    ```bash
    # .env dosyasında
    LLM_MOCK_MODE=false
    ```
11. Orchestrator'ı yeniden başlat:
    ```bash
    docker compose restart orchestrator
    ```
12. ~10 saniye bekle, container yeniden ayağa kalkana kadar.

### Beklenen Sonuç

- "Test Et" yanıtı yeşil banner ile dönüyor
- DB'de `llm_configs` tablosunda agent_id'ye karşılık şifrelenmiş `api_key` BYTEA değeri var (`SELECT agent_id, length(api_key) FROM llm_configs;`)
- Mock modu kapatıldıktan sonra gerçek LLM'den yanıt alınıyor
- `docker compose logs orchestrator -f` → `LLM_MOCK_MODE=false` ve provider çağrıları görünüyor

### Olası Sorunlar

| Sorun | Neden | Çözüm |
|---|---|---|
| "Test Et" → 401 / "auth error" | API key hatalı | Doğru key gir; OpenRouter için `sk-or-...` formatında |
| "Test Et" → "model not found" | Model adı yanlış | OpenRouter listesinden tam adı kopyala (`anthropic/claude-sonnet-4-5`) |
| "Test Et" → timeout | Network sorunu | Container'dan curl: `docker compose exec orchestrator curl -I https://openrouter.ai` |
| Kaydet sonrası API key görünüyor | Maskelenmemiş | Sayfayı yenile → maskelenmiş `••••...sk-...XYZ` görünür |
| Restart sonrası hala mock | `.env` okunmadı | `docker compose down && up -d` (compose env'i tam reload) |

---

## Senaryo 4: İçerik yükleme (Soru Havuzu + Konu Anlatımı)

### Ön Koşullar

- Senaryo 2 tamamlandı (admin girişi)
- Test için: `question_level.xlsx` (soru index dosyası), `6_mat_1.pdf` (soru havuzu PDF), bir adet konu anlatımı PDF (örn. `6_carpan_kat_anlatim.pdf`)

### Adımlar — Soru Havuzu

1. Admin paneli → **"İçerik Yükleme"** sekmesi.
2. Sağdaki **"Soru Havuzu Yükle"** kartına git.
3. **Aşama 1**: Excel index dosyasını sürükle-bırak alanına bırak (`question_level.xlsx`).
4. **"Yükle"** → yeşil banner: "X satır okundu" (X = Excel satır sayısı).
5. **Aşama 2** kilidi açılır. PDF/DOCX dosyasını dropzone'a bırak (`6_mat_1.pdf`).
6. **"Yükle"** → progress bar → tamamlanınca yeşil banner: "Y chunk eklendi".

### Adımlar — Konu Anlatımı

1. Soldaki **"Konu Anlatımı Yükle"** kartına git.
2. PDF/DOCX seç (`6_carpan_kat_anlatim.pdf`).
3. **Sınıf**: 6
4. **Konu**: "Çarpanlar ve Katlar"
5. **"Yükle"** → progress bar → yeşil banner: "Z chunk eklendi".

### Doğrulama

1. **"İstatistikler"** sekmesine geç.
2. Toplam chunk büyük rakamla görünmeli (örn. ~120).
3. Pie chart: "Soru" mavi, "Konu Anlatımı" mor.
4. Bar chart: en çok chunk'a sahip dosya isimleri (örn. `6_mat_1`, `6_carpan_kat_anlatim`).

### Beklenen Sonuç

- Excel + PDF birleşince `content_type=question` chunk'ları üretildi (taxonomic_level + answer_key metadata'sı dolu)
- Konu anlatımı PDF'i `content_type=theory` ile vektörleştirildi
- İstatistikler tab'ı toplam, tür dağılımı ve dosya bazlı bar grafiği gösteriyor

### Olası Sorunlar

| Sorun | Neden | Çözüm |
|---|---|---|
| Excel "kolonlar bulunamadı" | Excel template'i farklı | Beklenen kolonlar: `file_name, question_number, taxonomic_level, answer_key` |
| PDF parse "0 soru bulundu" | PDF formatı uyumsuz | PyMuPDF parser regex'i kontrol et |
| Aşama 2 kilidi açılmıyor | Aşama 1 başarısız | Tekrar dene; backend log: `docker compose logs rag -f` |
| Konu yükleme "503" | RAG servisi down | `docker compose restart rag` |
| İstatistikler boş | Cache eskimiş | "↻ Yenile" butonuna tıkla |

---

## Senaryo 5: Öğrenci öğrenme akışı (uçtan uca)

### Ön Koşullar

- Senaryo 1-4 tamamlandı (sistem ayakta, öğrenci hesabı var, LLM yapılandırıldı, soru/konu içeriği yüklü)
- Öğrenci hesabıyla giriş yapılmış olmalı

### Adımlar

1. Öğrenci hesabıyla giriş (`ali_test` / `Ali2025!`).
2. Sol sidebar'dan **6. Sınıf** kartına tıkla.
3. Ana alanda 6. sınıf konuları kart olarak görünmeli (Çarpanlar ve Katlar, Üslü İfadeler, vs.).
4. **"Çarpanlar ve Katlar"** kartına tıkla.
5. Konu anlatımı görüntüsü (TopicIntro) → 1-3 saniye içinde LLM'den (mock veya gerçek) Türkçe konu anlatımı paragrafları gelmeli.
6. **"Hazırım, Başlayalım!"** butonuna tıkla → ModeSelector ekranı.
7. **"Soru Çöz"** modunu seç.
8. İlk soru görünmeli (RAG'den çekilmiş, A/B/C/D şıklı).
9. Yanlış bir şık seç → **"Cevapla"** → kırmızı feedback animasyonu (shake) + LLM açıklaması.
10. **"Yeni Soru"** → ikinci soru gelmeli.
11. Doğru şık seç → **"Cevapla"** → yeşil feedback + confetti animasyonu + sağ üstte XP +10/+20.
12. En az 3 farklı soruda doğru/yanlış kombinasyonu test et.

### Beklenen Sonuç

- Konu anlatımı LLM yanıtı 5 saniye içinde geliyor
- Soru kartı RAG chunk'ından parse edilmiş (soru metni + A/B/C/D + answer_key)
- Yanlış cevapta kırmızı banner + LLM error_explanation
- Doğru cevapta confetti + XP artışı (gamification store güncellendi)
- Sağ üst Pill'lerde streak ve XP rozetleri animasyonla yenileniyor

### Olası Sorunlar

| Sorun | Neden | Çözüm |
|---|---|---|
| TopicIntro spinner sonsuz | Orchestrator yanıt vermiyor | `docker compose logs orchestrator -f` → Kafka topic'lerinde mesaj akışı kontrolü |
| "Soru bulunamadı" | RAG'de o seviyede chunk yok | İçerik yükleme adımını yeniden yap; Bandit cold-start için A1 isteyebilir |
| Confetti gözükmüyor | canvas-confetti yüklenemedi | DevTools console'da hata kontrol et |
| XP artmıyor | Backend reward_logs_stream akmadı | `docker compose logs bandit_actor -f` → reward event'i görmeli |
| Yanlış cevapta yeşil → bug | answer_key parse hatalı | RAG chunk metadata'sını kontrol et |

---

## Senaryo 6: Konu Öğren (Manim videosu)

### Ön Koşullar

- Senaryo 5 başlatıldı (öğrenci girişi + 6. sınıf + Çarpanlar ve Katlar konusu seçili)
- Manim Worker container ayakta
- LLM_MOCK_MODE=false (gerçek video kodu üretmek için Anthropic/OpenRouter API key gerekli)

### Adımlar

1. Soru çözme modundaysan, **"Modu Değiştir"** butonuna tıkla.
2. ModeSelector → **"Konu Öğren (Video)"** seç.
3. **"Videoyu Hazırla"** butonuna tıkla.
4. Spinner görünmeli; ekranda "Video hazırlanıyor..." mesajı.
5. 15-45 saniye bekle (LLM kod üretimi → sandbox testi → Manim render → MinIO upload).
6. Video player ekranda görünmeli (mp4, otomatik oynatma kapalı).
7. **Play** butonuna tıkla → video oynamaya başlar.
8. **Pause** → durur.
9. **İleri/Geri** (10 sn) butonları ile gezin.
10. Ses kontrolü ile sesi kapat/aç.
11. **"İndir"** butonuna tıkla → mp4 dosyası indirilir.
12. **"Devam Et"** → ModeSelector'a dön.

### Beklenen Sonuç

- Video render 45 saniye içinde tamamlandı
- Video player tüm kontrollerle çalışıyor
- İndirme başarılı (mp4, MinIO presigned URL)
- Ses ve kalite makul (Manim default)

### Olası Sorunlar

| Sorun | Neden | Çözüm |
|---|---|---|
| 45 sn timeout → fallback metin | LLM kodu hatalı veya render yavaş | Yeniden dene; `docker compose logs manim_worker -f` |
| "QA döngüsü maks deneme" | LLM kodu sürekli hatalı | Prompt template'leri kontrol et (`services/orchestrator/app/prompts/manim_*.yaml`) |
| Video oynamıyor | MinIO URL erişilemez | `docker compose exec minio mc ls local/ravel-videos` |
| Ses yok | Manim varsayılan sessiz | Beklenen davranış; spec ses içermiyor |
| İndirme 403 | Presigned URL süresi doldu | "Yenile" → tekrar üret |

---

## Senaryo 7: Soru-Cevap (sohbet)

### Ön Koşullar

- Senaryo 5/6 başlatıldı (öğrenci + konu seçili)
- LLM yapılandırılmış

### Adımlar

1. **"Modu Değiştir"** → **"Soru-Cevap"** modu.
2. ChatBox ekranı açılır (boş mesaj listesi + alt input).
3. Input'a yaz: "Çarpan ve kat arasındaki fark nedir?"
4. **Enter** veya gönder butonu → mesaj sağa hizalı baloncukta görünür.
5. Sol tarafta **"yazıyor..."** typing indicator (3 dot animasyonu).
6. ~3-8 saniye sonra LLM yanıtı sol baloncukta görünür.
7. Yeni soru: "Bana bir örnek verir misin?"
8. Yanıt geldikten sonra üçüncü mesaj: "Sayı 24 için tüm çarpanlarını yaz."
9. En az 3 mesaj alışverişi tamamla.

### Beklenen Sonuç

- WebSocket bağlantısı sağlam (Navbar'da yeşil ●)
- Her kullanıcı mesajından sonra typing indicator görünüyor
- LLM yanıtları Türkçe, konuya bağlı ve pedagojik
- Mesaj geçmişi kaybolmuyor (mod değiştirip dönünce hala duruyor — learningStore persist)

### Olası Sorunlar

| Sorun | Neden | Çözüm |
|---|---|---|
| Mesaj gönderilmiyor | API 401 | Tekrar giriş yap; JWT süresi dolmuş olabilir |
| Typing indicator sonsuz | Orchestrator yanıt yok | Logs kontrolü; Kafka `content_delivery_stream` |
| Yanıt İngilizce | Prompt template hatalı | `services/orchestrator/app/prompts/qa_dialog.yaml` → "Türkçe yanıtla" instruction kontrol |
| WS ● kırmızı | WebSocket reconnect başarısız | Sayfa yenile; nginx upstream proxy kontrolü |

---

## Senaryo 8: Tema toggle

### Ön Koşullar

- Senaryo 1 tamamlandı (frontend açık)

### Adımlar

1. Landing page'de sağ üstteki **☀️** ikonuna tıkla.
2. Tüm ekran (arka plan, kart, metin) açık temaya geçer.
3. Sayfayı yenile (Cmd+R / Ctrl+R).
4. Açık tema korunmuş olmalı (localStorage).
5. Giriş yap → MainPage açılır.
6. Navbar'da sağ üstteki **🌙** ikonuna tıkla → koyu temaya dön.
7. Sayfa yenile → koyu tema korunmuş.

### Beklenen Sonuç

- Tema değişimi <100ms (CSS variable transition)
- Tüm bileşenler tek anda dönüşüyor (sidebar, navbar, kartlar, formlar, admin paneli)
- Aksan renkler (mavi, mor, altın, yeşil, kırmızı) iki temada da aynı kalıyor
- localStorage'da `ravel-theme` key'i `{"state":{"theme":"light"}}` görünür
- Sayfa yenilemede flicker yok (hidrasyon öncesi inline script çalışıyor)

### Olası Sorunlar

| Sorun | Neden | Çözüm |
|---|---|---|
| Toggle çalışmıyor | themeStore mount edilmedi | DevTools → Console: `useThemeStore.getState()` kontrolü |
| Yarı dönüşüm (bazı bileşenler dark) | Hardcoded renk var | Bileşenleri tara: `bg-[#0A0F1E]` gibi hardcoded renkleri `bg-ravel-bg`'e çevir |
| Sayfa yenilemede flicker | Hidrasyon scripti çalışmadı | `index.html`'deki inline script localStorage parse hatası verdi mi kontrol et |
| Tercih kaybediliyor | Persist key uyumsuz | localStorage'da `ravel-theme` kontrolü |

---

## Senaryo 9: Admin istatistikleri

### Ön Koşullar

- Senaryo 4 tamamlandı (içerik yüklü)
- Admin girişi yapıldı

### Adımlar

1. Admin paneli → **"İstatistikler"** sekmesine geç.
2. Üstte büyük rakam: **Toplam chunk** (örn. 120).
3. Altında pie chart: "Soru" (mavi) + "Konu Anlatımı" (mor) yüzdeleri.
4. Altında bar chart: dosya isimlerine göre chunk sayısı (en çok 10 dosya).
5. Sağ üstteki **"↻ Yenile"** butonuna tıkla → veri tekrar çekilir, sayılar güncellenir.
6. Yeni içerik yükle (Senaryo 4) → Yenile → toplam chunk artmalı.

### Beklenen Sonuç

- 3 grafik düzgün render oluyor (Recharts ResponsiveContainer)
- Pie chart legend'ı Türkçe ("Soru", "Konu Anlatımı")
- Bar chart YAxis'da dosya adları okunabilir (uzun isimler kısaltılmış: `6_carpan_kat...`)
- Tooltip hover'da chunk sayısı + tam dosya adı
- Yenile butonu spinner göstermeden hızlıca güncelliyor

### Olası Sorunlar

| Sorun | Neden | Çözüm |
|---|---|---|
| "İstatistik yüklenemedi" | RAG /admin/stats erişilemez | Network tab → 401/403/503 kontrol et |
| Pie chart boş | by_content_type tüm değerler 0 | İçerik yüklemeyi tekrar yap |
| Bar chart boş | by_file_name boş | RAG admin endpoint dönüşünü doğrula: `curl http://localhost:8003/admin/stats` |
| Renkler bozuk | Recharts paleti farklı | StatisticsTab.jsx içinde RAVEL palette doğrula |
| Yenile çalışmıyor | useEffect bağımlılık yanlış | `load()` fonksiyonu state değişiminde tekrar çağrılır |

---

## Test Sonu Kontrol Listesi

- [ ] Senaryo 1: Sistem ayakta (tüm container healthy)
- [ ] Senaryo 2: Admin + öğrenci hesabı oluşturuldu
- [ ] Senaryo 3: LLM yapılandırıldı (orchestrator_text testi yeşil)
- [ ] Senaryo 4: Soru havuzu + konu anlatımı yüklendi
- [ ] Senaryo 5: 3+ soru çözüldü (yanlış+doğru kombinasyonu)
- [ ] Senaryo 6: Manim video render başarılı
- [ ] Senaryo 7: 3+ chat mesajı gidip geldi
- [ ] Senaryo 8: Tema toggle çalışıyor + persist
- [ ] Senaryo 9: İstatistikler grafikleri render oluyor

**Tüm senaryolar PASS ise:** RAVEL Adım 8 tam fonksiyonel.

---

## Hızlı sıfırlama (test sonrası)

Tüm container'ları + volume'ları temizleyip baştan başlamak için:

```bash
docker compose down -v
docker compose up -d
```

> **Uyarı:** `down -v` Postgres + Qdrant + MinIO + Kafka volume'larını siler;
> tüm öğrenci hesapları, içerik chunk'ları ve LLM konfigürasyonları kaybolur.
> Sadece tam temiz state istiyorsan kullan.
