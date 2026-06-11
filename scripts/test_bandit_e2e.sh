#!/usr/bin/env bash
# RAVEL — Step 4 Aşama 2 end-to-end test
#
# Tam zincir:
#   /api/answer ↓
#   Gateway → Kafka(student_interactions_stream)
#   → Orchestrator
#       → Kafka(bandit_decision_requests)
#       → Bandit Actor
#       → Kafka(bandit_decision_responses)
#   → Orchestrator → Kafka(content_retrieval_requests)  [RAG yok → timeout fallback]
#   → Orchestrator → Kafka(content_delivery_stream)
#   → Gateway → WebSocket → client
#
# İkinci /api/answer atılınca + öncekinin pending kaydı varsa:
#   → Orchestrator → Kafka(reward_logs_stream)
#   → Bandit Learner → DB-2 (interaction_logs INSERT)

set -uo pipefail
cd "$(dirname "$0")/.."

# shellcheck disable=SC1091
set -a; source .env; set +a

GREEN="\033[0;32m"; RED="\033[0;31m"; YELLOW="\033[0;33m"; NC="\033[0m"
PASS=0; FAIL=0
ok()   { printf "  ${GREEN}✓${NC} %s\n" "$1"; PASS=$((PASS+1)); }
fail() { printf "  ${RED}✗${NC} %s\n" "$1"; FAIL=$((FAIL+1)); }
hdr()  { printf "\n${YELLOW}═══ %s ═══${NC}\n" "$1"; }

API="http://localhost:${API_GATEWAY_PORT:-8000}"

# Bu test Bandit reward döngüsünü ölçüyor — gerçek LLM yanıtının kalitesi
# konu değil, sadece WS frame'inin trace_id ile geri dönmesi yeterli. Gerçek
# LLM 15-30 sn sürebiliyor, test 15 sn timeout'la flake oluyor. Mock LLM'e
# alıp test'i deterministik yapıyoruz.
echo "→ Setup: Orchestrator'ı LLM_MOCK_MODE=true ile yeniden başlat"
LLM_MOCK_MODE=true docker compose up -d --no-deps orchestrator >/dev/null 2>&1
PREV_ORCH=$(docker compose logs --no-color orchestrator 2>&1 | grep -c "orchestrator ready" || true)
for i in $(seq 1 30); do
  CUR=$(docker compose logs --no-color orchestrator 2>&1 | grep -c "orchestrator ready" || true)
  if [ "$CUR" -gt "$PREV_ORCH" ]; then break; fi
  sleep 1
done
sleep 2  # consumer rejoin pad
trap 'echo "→ Cleanup: Orchestrator .env LLM_MOCK_MODE değerine geri dönüyor"; docker compose up -d --no-deps orchestrator >/dev/null 2>&1' EXIT

hdr "Step 4 E2E — Gateway → Orchestrator → Bandit → Orchestrator → Gateway → WS"

# Kafka offset'leri başlangıç (delta hesaplamak için)
get_offset() {
  docker compose exec -T kafka /opt/kafka/bin/kafka-get-offsets.sh \
    --bootstrap-server kafka:9092 --topic "$1" 2>/dev/null \
    | awk -F: '{sum+=$3} END {print sum+0}'
}

ORCH_LOG_MARKER=$(docker compose logs --no-color orchestrator 2>&1 | wc -l)

OFF_INTER_BEFORE=$(get_offset student_interactions_stream)
OFF_BREQ_BEFORE=$(get_offset bandit_decision_requests)
OFF_BRES_BEFORE=$(get_offset bandit_decision_responses)
OFF_REW_BEFORE=$(get_offset reward_logs_stream)
OFF_DEL_BEFORE=$(get_offset content_delivery_stream)
# Adım 6 sonrası: Bandit "video" derse delivery yerine video_ready_events
# çıkıyor. İki topic'in toplamı her zaman ≥ event sayısı kadar olmalı.
OFF_VRE_BEFORE=$(get_offset video_ready_events)
echo "→ Başlangıç offset'leri:"
echo "    student_interactions_stream  : $OFF_INTER_BEFORE"
echo "    bandit_decision_requests     : $OFF_BREQ_BEFORE"
echo "    bandit_decision_responses    : $OFF_BRES_BEFORE"
echo "    reward_logs_stream           : $OFF_REW_BEFORE"
echo "    content_delivery_stream      : $OFF_DEL_BEFORE"
echo "    video_ready_events           : $OFF_VRE_BEFORE"

# DB-2 kayıt sayısı
DB2_BEFORE=$(docker compose exec -T postgres psql -U ravel_admin -d ravel_db2 -At \
  -c "SELECT COUNT(*) FROM interaction_logs;" 2>/dev/null | tr -d '[:space:]')
echo "    DB-2 interaction_logs        : $DB2_BEFORE"

# Login
echo ""
echo "→ Login"
LOGIN=$(curl -sS -X POST "$API/auth/login" -H 'Content-Type: application/json' -d '{"grade_level":7}')
TOKEN=$(echo "$LOGIN"   | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
STUDENT=$(echo "$LOGIN" | python3 -c "import json,sys; print(json.load(sys.stdin)['student_id'])")
[ -n "$TOKEN" ] && [ -n "$STUDENT" ] && ok "got token for student=$STUDENT" \
                                    || fail "login failed"

# Tek Python süreciyle: WS bağlan → 2 ardışık /api/answer → her iki WS yanıtını al
echo ""
echo "→ WS bağlan + 2 ardışık /api/answer + her iki yanıtı topla (max 30 sn)"

OUTPUT=$(docker compose exec -T api_gateway python <<PY
import asyncio, json, time, sys, traceback
import httpx
from websockets import connect

API = "http://localhost:8000"
TOKEN = "$TOKEN"
STUDENT = "$STUDENT"

async def main():
    uri = f"ws://localhost:8000/ws/{STUDENT}?token={TOKEN}"
    async with connect(uri) as ws:
        print("WS_CONNECTED")
        async with httpx.AsyncClient(timeout=10) as client:
            # ── Birinci yanıt: yanlış (Bandit'i tetikler, pending kaydı oluşur)
            r1 = await client.post(
                f"{API}/api/answer",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "question_id": "q_e2e_1",
                    "topic": "Uslu_Ifadeler",
                    "taxonomic_level": "B1",
                    "student_answer": "C",
                    "is_correct": False,
                    "time_spent": 42,
                },
            )
            r1.raise_for_status()
            t1 = r1.json()["trace_id"]
            print(f"ANSWER1 trace={t1}")
            try:
                m1 = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                print(f"WS1 trace={m1.get('trace_id')} content_type={m1.get('content_type')}")
            except asyncio.TimeoutError:
                print("WS1_TIMEOUT")
                return

            # ── Aralarda 2 sn bekle (T_actual sıfırdan büyük olsun)
            await asyncio.sleep(2)

            # ── İkinci yanıt: doğru → öncekinin reward'ı +1.0 olur
            r2 = await client.post(
                f"{API}/api/answer",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "question_id": "q_e2e_2",
                    "topic": "Uslu_Ifadeler",
                    "taxonomic_level": "B1",
                    "student_answer": "B",
                    "is_correct": True,
                    "time_spent": 35,
                },
            )
            r2.raise_for_status()
            t2 = r2.json()["trace_id"]
            print(f"ANSWER2 trace={t2}")
            try:
                m2 = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                print(f"WS2 trace={m2.get('trace_id')} content_type={m2.get('content_type')}")
            except asyncio.TimeoutError:
                print("WS2_TIMEOUT")
                return

            print(f"TRACES_OK" if (m1.get("trace_id") == t1 and m2.get("trace_id") == t2) else "TRACES_MISMATCH")

try:
    asyncio.run(main())
except Exception:
    traceback.print_exc()
    sys.exit(1)
PY
)

echo "$OUTPUT" | sed 's/^/    /'
echo ""

# WS doğrulamaları
echo "$OUTPUT" | grep -q "WS_CONNECTED" && ok "WebSocket bağlandı"      || fail "WS bağlanmadı"
echo "$OUTPUT" | grep -q "ANSWER1"      && ok "1. /api/answer gitti"    || fail "1. answer fail"
echo "$OUTPUT" | grep -q "WS1 trace="   && ok "1. WS yanıtı geldi"      || fail "1. WS yanıtı yok"
echo "$OUTPUT" | grep -q "ANSWER2"      && ok "2. /api/answer gitti"    || fail "2. answer fail"
echo "$OUTPUT" | grep -q "WS2 trace="   && ok "2. WS yanıtı geldi"      || fail "2. WS yanıtı yok"
echo "$OUTPUT" | grep -q "TRACES_OK"    && ok "trace_id'ler her iki zincirde de korundu" \
                                        || fail "trace_id mismatch"

# Reward + DB-2 yazımının tamamlanması için ek 5 sn
echo ""
echo "→ Reward propagation için 5 sn bekle (Orchestrator → Kafka → Bandit Learner → DB-2)"
sleep 5

# Kafka offset delta'ları
echo ""
echo "→ Kafka topic delta'ları"
OFF_INTER_AFTER=$(get_offset student_interactions_stream)
OFF_BREQ_AFTER=$(get_offset bandit_decision_requests)
OFF_BRES_AFTER=$(get_offset bandit_decision_responses)
OFF_REW_AFTER=$(get_offset reward_logs_stream)
OFF_DEL_AFTER=$(get_offset content_delivery_stream)
OFF_VRE_AFTER=$(get_offset video_ready_events)

DELTA_INTER=$((OFF_INTER_AFTER - OFF_INTER_BEFORE))
DELTA_BREQ=$((OFF_BREQ_AFTER - OFF_BREQ_BEFORE))
DELTA_BRES=$((OFF_BRES_AFTER - OFF_BRES_BEFORE))
DELTA_REW=$((OFF_REW_AFTER - OFF_REW_BEFORE))
DELTA_DEL=$((OFF_DEL_AFTER - OFF_DEL_BEFORE))
DELTA_VRE=$((OFF_VRE_AFTER - OFF_VRE_BEFORE))
# Adım 6: Bandit "video" derse delivery yerine video_ready_events'e gider
# (Manim render + upload yolu). İkisinin toplamı event sayısına eşit olmalı.
DELTA_OUT=$((DELTA_DEL + DELTA_VRE))

printf "    student_interactions_stream  : +%d  (beklenen: ≥2)\n" "$DELTA_INTER"
printf "    bandit_decision_requests     : +%d  (beklenen: ≥2  — her event Bandit'i tetikler)\n" "$DELTA_BREQ"
printf "    bandit_decision_responses    : +%d  (beklenen: ≥2  — Bandit Actor yanıt verdi)\n" "$DELTA_BRES"
printf "    reward_logs_stream           : +%d  (beklenen: ≥1  — 2. event'te 1. event'in reward'ı emit)\n" "$DELTA_REW"
printf "    content_delivery_stream      : +%d  (text/step_by_step kararları)\n" "$DELTA_DEL"
printf "    video_ready_events           : +%d  (video kararları → Manim render)\n" "$DELTA_VRE"
printf "    Σ (delivery + video_ready)   : +%d  (beklenen: ≥2 — her event bir output)\n" "$DELTA_OUT"

[ "$DELTA_INTER" -ge 2 ] && ok "student_interactions_stream +$DELTA_INTER" || fail "student_interactions delta yetersiz"
[ "$DELTA_BREQ"  -ge 2 ] && ok "bandit_decision_requests +$DELTA_BREQ"     || fail "bandit_decision_requests delta yetersiz"
[ "$DELTA_BRES"  -ge 2 ] && ok "bandit_decision_responses +$DELTA_BRES"    || fail "bandit_decision_responses delta yetersiz"
[ "$DELTA_REW"   -ge 1 ] && ok "reward_logs_stream +$DELTA_REW"            || fail "reward emit görülmedi"
[ "$DELTA_OUT"   -ge 2 ] && ok "content_delivery + video_ready toplam +$DELTA_OUT" || fail "output delta yetersiz (delivery=$DELTA_DEL video_ready=$DELTA_VRE)"

# DB-2 INSERT (Bandit Learner tarafından)
DB2_AFTER=$(docker compose exec -T postgres psql -U ravel_admin -d ravel_db2 -At \
  -c "SELECT COUNT(*) FROM interaction_logs;" 2>/dev/null | tr -d '[:space:]')
DB2_DELTA=$((DB2_AFTER - DB2_BEFORE))

echo ""
echo "→ DB-2 interaction_logs delta: +$DB2_DELTA  (beklenen: ≥1 — Learner reward'ı tüketince INSERT yapar)"
[ "$DB2_DELTA" -ge 1 ] && ok "DB-2'de yeni kayıt oluştu" || fail "DB-2 INSERT yok"

# Bu öğrenci için son kayıt
echo ""
echo "→ Bu öğrenci için DB-2'deki son kayıt"
docker compose exec -T postgres psql -U ravel_admin -d ravel_db2 \
  -c "SELECT student_id, action_taken, is_correct, time_spent_seconds, ROUND(reward_signal::numeric, 3) AS reward_signal
      FROM interaction_logs WHERE student_id = '$STUDENT'
      ORDER BY \"timestamp\" DESC LIMIT 1;" 2>&1 | sed 's/^/    /'

# Orchestrator log'unun Bandit/reward izini doğrula
echo ""
echo "→ Orchestrator log analizi (yalnızca bu test run'ı için)"
# Sadece test başlangıcında bıraktığımız marker'dan sonraki satırlar
ORCH_LOG=$(docker compose logs --no-color orchestrator 2>&1 | tail -n +$((ORCH_LOG_MARKER + 1)))
echo "$ORCH_LOG" | grep -q "delivered text intervention" && ok "delivery yapıldı (bu run'da)" \
                                                         || fail "delivery log yok"
echo "$ORCH_LOG" | grep -q "reward emitted"              && ok "reward log Orchestrator tarafında görüldü" \
                                                         || fail "reward emit log yok"
# Bu run'da Bandit timeout görüldü mü?
TIMEOUT_COUNT=$(echo "$ORCH_LOG" | grep -c "Bandit timeout" || true)
if [ "$TIMEOUT_COUNT" -eq 0 ]; then
  ok "Bandit timeout log'u yok → her iki istekte de gerçek karar geldi"
else
  fail "Bu run'da $TIMEOUT_COUNT Bandit timeout log'u var → Bandit yanıt vermemiş"
fi

# Bandit log'unun inference + DB INSERT izini doğrula
echo ""
echo "→ Bandit log analizi"
BANDIT_LOG=$(docker compose logs --tail=80 bandit 2>&1)
INF_COUNT=$(echo "$BANDIT_LOG" | grep -c "inference_ms=" || true)
DB_COUNT=$(echo "$BANDIT_LOG" | grep -c "inserted interaction_log" || true)
printf "    inference_ms log'u: %d  (beklenen: ≥2)\n" "$INF_COUNT"
printf "    DB INSERT log'u   : %d  (beklenen: ≥1)\n" "$DB_COUNT"
[ "$INF_COUNT" -ge 2 ] && ok "Actor 2+ kez inference yaptı"             || fail "Actor inference log yetersiz"
[ "$DB_COUNT"  -ge 1 ] && ok "Learner 1+ kez DB-2 INSERT'i tamamladı"  || fail "Learner DB INSERT log yok"

echo ""
echo "═════════════════════════════════════"
printf "  Passed: ${GREEN}%d${NC}    Failed: ${RED}%d${NC}\n" "$PASS" "$FAIL"
echo "═════════════════════════════════════"
[ "$FAIL" -eq 0 ]
