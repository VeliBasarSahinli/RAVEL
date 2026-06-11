#!/usr/bin/env bash
# RAVEL — Step 3 robustness tests
#
# 1) Hata izolasyonu  : Bozuk JSON enjekte edildiğinde orchestrator
#                       crash etmemeli; sadece o event kaybolmalı, loop
#                       devam etmeli.
# 2) Circuit Breaker  : 5 ardışık RAG timeout'undan sonra breaker OPEN
#                       state'e geçmeli; sonraki istekler RAG'a hiç
#                       gitmeden fallback ile yanıtlanmalı.

set -uo pipefail
cd "$(dirname "$0")/.."

# shellcheck disable=SC1091
set -a; source .env; set +a

API="http://localhost:${API_GATEWAY_PORT:-8000}"
GREEN="\033[0;32m"; RED="\033[0;31m"; YELLOW="\033[0;33m"; NC="\033[0m"
PASS=0; FAIL=0

ok()   { printf "  ${GREEN}✓${NC} %s\n" "$1"; PASS=$((PASS+1)); }
fail() { printf "  ${RED}✗${NC} %s\n" "$1"; FAIL=$((FAIL+1)); }
hdr()  { printf "\n${YELLOW}═══ %s ═══${NC}\n" "$1"; }

# Bu test orchestrator'ın hata izolasyonu + circuit breaker davranışını
# saniye-skala'da ölçüyor. Gerçek LLM çağrısı 20-30 sn süreyse delivery
# event'i wait_for_log timeout'una takılır → false negative. Test
# süresince LLM_MOCK_MODE=true ile orchestrator'ı yeniden başlat, test
# sonunda compose'u .env varsayılanına geri al.
echo "→ Setup: Orchestrator'ı LLM_MOCK_MODE=true ile yeniden başlat"
LLM_MOCK_MODE=true docker compose up -d --no-deps orchestrator >/dev/null 2>&1
PREV_ORCH=$(docker compose logs --no-color orchestrator 2>&1 | grep -c "orchestrator ready" || true)
for i in $(seq 1 30); do
  CUR=$(docker compose logs --no-color orchestrator 2>&1 | grep -c "orchestrator ready" || true)
  if [ "$CUR" -gt "$PREV_ORCH" ]; then break; fi
  sleep 1
done
sleep 2  # consumer rejoin pad

# Test bitince orchestrator'ı .env varsayılanına döndür
trap 'echo "→ Cleanup: Orchestrator .env LLM_MOCK_MODE değerine geri dönüyor"; docker compose up -d --no-deps orchestrator >/dev/null 2>&1' EXIT

# Marker'dan beri olan log satırları (tail değil — birikmiş log Adım 4
# çalıştırmaları sonrası 1000+ satıra ulaşıyor; tail-300 hata mesajını
# kaçırıyordu, tüm log ise wait_for_log'u yavaşlatıyordu).
LOG_BASELINE=$(docker compose logs --no-color orchestrator 2>&1 | wc -l)
all_logs() {
  docker compose logs --no-color orchestrator 2>&1 | tail -n +$((LOG_BASELINE + 1))
}

wait_for_log() {
  # wait_for_log "<grep pattern>" <max_seconds>
  local pattern="$1"
  local max="${2:-30}"
  for i in $(seq 1 "$max"); do
    if all_logs | grep -q "$pattern"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

# ╔══════════════════════════════════════════════════════════════════╗
# ║ TEST 1 — Bozuk JSON enjeksiyonu                                  ║
# ╚══════════════════════════════════════════════════════════════════╝

hdr "TEST 1: Hata izolasyonu (bozuk JSON enjeksiyonu)"

BAD_MSG='{"event_id":"bad","this_event_is_malformed":true,"missing_required_fields":"yes"}'

echo ""
echo "→ 1.1) student_interactions_stream'e BOZUK mesaj enjekte et"
echo "$BAD_MSG" | docker compose exec -T kafka /opt/kafka/bin/kafka-console-producer.sh \
  --bootstrap-server kafka:9092 --topic student_interactions_stream >/dev/null 2>&1
echo "    enjekte: $BAD_MSG"

echo ""
echo "→ 1.2) Producer warm-up için 3 sn bekle, sonra log poll (max 30 sn)"
sleep 3
if wait_for_log "handler failed: topic=student_interactions_stream" 30; then
  ok "handler failed log'a düştü (exception izole edildi, loop hayatta)"
else
  fail "handler failed log'u bekleme süresinde görünmedi"
fi

echo ""
echo "→ 1.3) ValidationError tip olarak doğrulandı mı?"
if all_logs | grep -qE "ValidationError|pydantic"; then
  ok "Pydantic ValidationError tip olarak doğrulandı"
else
  fail "ValidationError tip ifadesi yok"
fi

echo ""
echo "→ 1.4) Container hâlâ healthy mi?"
HEALTH=$(docker inspect -f '{{.State.Health.Status}}' ravel_orchestrator 2>/dev/null || echo missing)
if [ "$HEALTH" = "healthy" ]; then
  ok "container healthy (crash etmedi)"
else
  fail "container health=$HEALTH"
fi

echo ""
echo "→ 1.5) Loop hayatta mı? Geçerli bir event işle"
LOGIN=$(curl -sS -X POST "$API/auth/login" -H 'Content-Type: application/json' -d '{"grade_level":7}')
TOKEN=$(echo "$LOGIN"   | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
ANSWER=$(curl -sS -X POST "$API/api/answer" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"question_id":"q_robust","topic":"Uslu_Ifadeler","taxonomic_level":"B1","student_answer":"D","is_correct":false,"time_spent":30}')
TRACE=$(echo "$ANSWER" | python3 -c "import json,sys; print(json.load(sys.stdin)['trace_id'])")
echo "    yeni trace gönderildi: $TRACE"

if wait_for_log "$TRACE.*delivered text intervention" 10; then
  ok "yeni event normal şekilde işlendi ve delivery yaptı (loop sağlam)"
else
  fail "yeni event delivery'i log'da görünmedi — loop kırılmış olabilir"
fi

# ╔══════════════════════════════════════════════════════════════════╗
# ║ TEST 2 — Circuit Breaker OPEN geçişi                             ║
# ╚══════════════════════════════════════════════════════════════════╝

hdr "TEST 2: Circuit Breaker (5 ardışık fail → OPEN → fallback short-circuit)"

echo ""
echo "→ 2.0) Step 5 sonrası RAG aktif — Circuit Breaker testi için RAG'ı geçici durdur"
# RAG ayakta iken timeout olmuyor; Circuit Breaker testinin amacı 5 ardışık
# RAG fail. RAG container'ı stop ederek garantili timeout simüle ediyoruz.
docker compose stop rag >/dev/null 2>&1
echo "    rag durduruldu (testin sonunda tekrar başlatılacak)"

echo ""
echo "→ 2.1) Orchestrator'ı restart (FSM ve consumer offset'i clean state'e)"
docker compose restart orchestrator >/dev/null 2>&1

echo "    'orchestrator ready' log'unu bekleniyor (max 30 sn)…"
START_TS=$(date +%s)
PREV_READY=$(docker compose logs --no-color orchestrator 2>&1 | grep -c "orchestrator ready" || true)
for i in $(seq 1 30); do
  CUR=$(docker compose logs --no-color orchestrator 2>&1 | grep -c "orchestrator ready" || true)
  if [ "$CUR" -gt "$PREV_READY" ]; then
    echo "    ✓ yeni 'ready' log'u görüldü ($((($(date +%s) - START_TS))) sn)"
    break
  fi
  sleep 1
done

echo "    BOTH consumer'ların 'Successfully synced' log'unu bekleniyor (interactions + responses)…"
# orchestrator ve orchestrator-responses iki ayrı consumer group; rejoin
# tamamlanmadan istek atmak yarış kaybına yol açıyor.
SYNC_TS=$(date +%s)
for i in $(seq 1 20); do
  SYNC_COUNT=$(docker compose logs --no-color --tail=80 orchestrator 2>&1 \
    | grep -c "Successfully synced group" || true)
  if [ "$SYNC_COUNT" -ge 2 ]; then
    echo "    ✓ iki consumer da synced ($((($(date +%s) - SYNC_TS))) sn)"
    break
  fi
  sleep 1
done
echo "    ek 2 sn safety pad…"
sleep 2

echo ""
echo "→ 2.2) Log offset marker bırak (yalnızca yeni log'ları analiz edeceğiz)"
LOG_MARKER=$(all_logs | wc -l)
echo "    marker satırı: $LOG_MARKER"

echo ""
echo "→ 2.3) 6 ardışık /api/answer at (her biri arasında 4 sn bekle, deterministik)"
LOGIN=$(curl -sS -X POST "$API/auth/login" -H 'Content-Type: application/json' -d '{"grade_level":6}')
TOKEN=$(echo "$LOGIN"   | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

declare -a TRACES=()
for i in 1 2 3 4 5 6; do
  R=$(curl -sS -X POST "$API/api/answer" \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $TOKEN" \
    -d "{\"question_id\":\"q_brk_$i\",\"topic\":\"Uslu_Ifadeler\",\"taxonomic_level\":\"B1\",\"student_answer\":\"X\",\"is_correct\":false,\"time_spent\":40}")
  T=$(echo "$R" | python3 -c "import json,sys; print(json.load(sys.stdin)['trace_id'])")
  TRACES+=("$T")
  echo "    [$i] trace=$T"
  # 4 sn = 3 sn RAG timeout + 1 sn buffer; sıralı RAG çağrılarının deterministik olmasını sağlar
  sleep 4
done

echo ""
echo "→ 2.4) Son tetiklenen olayların tamamlanmasını bekle (ek 3 sn)"
sleep 3

echo ""
echo "→ 2.5) Sadece marker'dan sonraki log'ları analiz et"
NEW_LOGS=$(all_logs | tail -n +$((LOG_MARKER + 1)))

OPEN_COUNT=$(echo "$NEW_LOGS" | grep -c "circuit OPEN" || true)
CIRCUIT_OPEN_ERR=$(echo "$NEW_LOGS" | grep -c "RAG unavailable (CircuitOpenError)" || true)
RAG_TIMEOUT_COUNT=$(echo "$NEW_LOGS" | grep -c "RAG unavailable (TimeoutError)" || true)
DELIVERED_COUNT=$(echo "$NEW_LOGS" | grep -c "delivered text intervention" || true)
# Adım 6: Bandit "video" derse delivery yerine "manim render dispatched"
# log'u atılır; ikisinin toplamı output sayısını verir.
MANIM_DISPATCH_COUNT=$(echo "$NEW_LOGS" | grep -c "manim render dispatched" || true)
TOTAL_OUT=$((DELIVERED_COUNT + MANIM_DISPATCH_COUNT))

echo "    log özeti (sadece test 2 dönemi):"
echo "      'circuit OPEN'                       : $OPEN_COUNT  (≥1 olmalı)"
echo "      'RAG unavailable (TimeoutError)'     : $RAG_TIMEOUT_COUNT  (~5 olmalı — 5 ardışık timeout)"
echo "      'RAG unavailable (CircuitOpenError)' : $CIRCUIT_OPEN_ERR  (≥1 olmalı — short-circuit kanıtı)"
echo "      'delivered text intervention'        : $DELIVERED_COUNT  (text/step_by_step kararları)"
echo "      'manim render dispatched'            : $MANIM_DISPATCH_COUNT  (video kararları)"
echo "      Σ toplam output                      : $TOTAL_OUT  (=6 olmalı — her isteğe bir output)"

[ "$OPEN_COUNT" -ge 1 ]        && ok "circuit OPEN'a geçti"                                  || fail "circuit OPEN log'u yok"
[ "$RAG_TIMEOUT_COUNT" -ge 4 ] && ok "≥4 ardışık RAG TimeoutError (5'inci OPEN yapacak)"      || fail "yeterli timeout sayısı yok ($RAG_TIMEOUT_COUNT)"
[ "$CIRCUIT_OPEN_ERR" -ge 1 ]  && ok "CircuitOpenError ile short-circuit gerçekleşti"        || fail "short-circuit yok — 6. istek de timeout'a girdi"
[ "$TOTAL_OUT" -ge 6 ]         && ok "6 isteğin hepsi işlendi (delivery=$DELIVERED_COUNT manim=$MANIM_DISPATCH_COUNT)" \
                              || fail "output sayısı eksik: $TOTAL_OUT/6"

echo ""
echo "→ 2.6) Trace bazında doğrulama"
ALL_TRACED=true
for t in "${TRACES[@]}"; do
  # delivery VEYA manim dispatched — Bandit kararına göre ikisinden biri olmalı
  if ! echo "$NEW_LOGS" | grep -qE "$t.*delivered|$t.*manim render dispatched"; then
    echo "    ✗ trace $t için ne delivery ne manim dispatched log'u yok"
    ALL_TRACED=false
  fi
done
$ALL_TRACED && ok "6 trace_id'nin hepsi delivery veya manim dispatched log'unda görüldü" \
            || fail "bazı trace'ler için output yok"

# ╔══════════════════════════════════════════════════════════════════╗
# ║ ÖZET                                                             ║
# ╚══════════════════════════════════════════════════════════════════╝

echo ""
echo "→ 2.7) RAG container'ını tekrar başlat (cleanup)"
docker compose start rag >/dev/null 2>&1
for i in $(seq 1 30); do
  h=$(docker inspect -f '{{.State.Health.Status}}' ravel_rag 2>/dev/null || echo missing)
  if [ "$h" = "healthy" ]; then echo "    ✓ rag healthy ($i sn)"; break; fi
  sleep 1
done

echo ""
echo "═════════════════════════════════════"
printf "  Passed: ${GREEN}%d${NC}    Failed: ${RED}%d${NC}\n" "$PASS" "$FAIL"
echo "═════════════════════════════════════"

[ "$FAIL" -eq 0 ]
