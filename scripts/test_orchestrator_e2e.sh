#!/usr/bin/env bash
# RAVEL — Step 3 end-to-end test for the full chain:
#   Gateway → Kafka(student_interactions_stream)
#   → Orchestrator → Kafka(content_delivery_stream)
#   → Gateway → WebSocket → client
#
# RAG isn't running yet, so the orchestrator's request to
# content_retrieval_requests will time out (~3s). That's the
# *expected* path for this step: the breaker fallback feeds the
# (mock) LLM and a canned text reply gets pushed to the WebSocket.

set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "✗ .env not found." >&2
  exit 1
fi
# shellcheck disable=SC1091
set -a; source .env; set +a

GREEN="\033[0;32m"; RED="\033[0;31m"; NC="\033[0m"
PASS=0; FAIL=0
ok()   { printf "  ${GREEN}✓${NC} %s\n" "$1"; PASS=$((PASS+1)); }
fail() { printf "  ${RED}✗${NC} %s\n" "$1"; FAIL=$((FAIL+1)); }

API="http://localhost:${API_GATEWAY_PORT:-8000}"

echo ""
echo "═══ RAVEL Step 3 E2E (Gateway → Orchestrator → Gateway → WS) ═══"

# ── 1. Login ─────────────────────────────────────────────────────────
echo ""
echo "→ 1) Login"
LOGIN=$(curl -sS -X POST "$API/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"grade_level":6}')
TOKEN=$(echo "$LOGIN"   | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
STUDENT=$(echo "$LOGIN" | python3 -c "import json,sys; print(json.load(sys.stdin)['student_id'])")
[ -n "$TOKEN" ] && [ -n "$STUDENT" ] && ok "got token for student=$STUDENT" \
                                    || fail "login failed: $LOGIN"

# ── 2. Tek bir Python süreci: WS bağlan → answer POST → WS recv ───────
# Bunu API Gateway container'ının kendi venv'inden çalıştırıyoruz
# (httpx + websockets kütüphaneleri orada zaten var).
echo ""
echo "→ 2) WS bağlan + /api/answer + WS'ten yanıt bekle (max 15 sn)"

OUTPUT=$(docker compose exec -T api_gateway python <<PY
import asyncio, json, sys, traceback
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
            r = await client.post(
                f"{API}/api/answer",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "question_id": "q_6_mat_2_10",
                    "topic": "Uslu_Ifadeler",
                    "taxonomic_level": "B1",
                    "student_answer": "C",
                    "is_correct": False,
                    "time_spent": 42,
                },
            )
            r.raise_for_status()
            data = r.json()
            print(f"ANSWER_ACCEPTED trace={data['trace_id']}")
            sent_trace = data["trace_id"]
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=15)
            payload = json.loads(msg)
            print(f"WS_RECEIVED trace={payload.get('trace_id')} content_type={payload.get('content_type')}")
            print(f"BODY: {payload.get('body_html','')[:120]}")
            if payload.get("trace_id") == sent_trace:
                print("TRACE_MATCH")
            else:
                print(f"TRACE_MISMATCH expected={sent_trace} got={payload.get('trace_id')}")
            if "MOCK LLM YANITI" in payload.get("body_html", ""):
                print("MOCK_LLM_TAG_FOUND")
        except asyncio.TimeoutError:
            print("WS_TIMEOUT")

try:
    asyncio.run(main())
except Exception:
    traceback.print_exc()
    sys.exit(1)
PY
)

echo "$OUTPUT" | sed 's/^/    /'
echo ""

echo "$OUTPUT" | grep -q "WS_CONNECTED"        && ok "WebSocket bağlandı"               || fail "WS bağlantı"
echo "$OUTPUT" | grep -q "ANSWER_ACCEPTED"     && ok "/api/answer 200 döndü"            || fail "answer POST"
echo "$OUTPUT" | grep -q "WS_RECEIVED"         && ok "WS'ten downstream mesaj geldi"    || fail "WS recv timeout"
echo "$OUTPUT" | grep -q "TRACE_MATCH"         && ok "trace_id Gateway → Orchestrator → Gateway zincirinde korundu" \
                                              || fail "trace_id eşleşmedi"
# Adım 6 sonrası Bandit "video" derse content_type=video gelir (sadece video URL);
# "text"/"step_by_step" derse text_explanation gelir. LLM_MOCK_MODE=true ise
# body_html'de "MOCK LLM YANITI" tag'ı bulunur; false ise gerçek LLM yanıtı
# (gateway başarılı çağrıyı gösterir). Üç davranış da geçerli.
if echo "$OUTPUT" | grep -q "MOCK_LLM_TAG_FOUND"; then
  ok "Mock LLM yanıtı body_html'de bulundu (LLM_MOCK_MODE=true)"
elif echo "$OUTPUT" | grep -qi "content_type=video"; then
  ok "Bandit 'video' kararı verdi → manim akışı"
elif echo "$OUTPUT" | grep -qiE "content_type=(text|step)_explanation"; then
  ok "Gerçek LLM yanıtı (LLM_MOCK_MODE=false) — text/step açıklama geldi"
else
  fail "Ne mock LLM tag ne video ne de text_explanation — beklenmeyen WS payload"
fi

# ── 3. Orchestrator log'unda işlemenin izini doğrula ─────────────────
echo ""
echo "→ 3) Orchestrator log'undan akışı doğrula"
LOGS=$(docker compose logs --tail=80 orchestrator 2>&1)

echo "$LOGS" | grep -qE "\[trace_[0-9a-f]+\] processing"   && ok "Orchestrator event'i tüketti" \
                                                            || fail "consume log yok"
# Step 5 sonrası RAG canlı; iki olası akış kabul:
#   a) RAG returned N chunks  (RAG cevap verdi, gerçek retrieval)
#   b) RAG unavailable        (timeout veya circuit open — eski Step 3 davranışı)
if echo "$LOGS" | grep -qE "RAG returned|RAG unavailable"; then
  ok "RAG akışı işlendi (returned veya unavailable)"
else
  fail "RAG ile ilgili log'u görünmedi"
fi
echo "$LOGS" | grep -q "delivered text intervention"       && ok "Orchestrator content_delivery_stream'e yazdı" \
                                                            || fail "delivery log'u görünmedi"

# ── 4. Kafka'da student_interactions_stream'de mesaj var mı? ────────
echo ""
echo "→ 4) Kafka mesaj denetimi"
COUNT_INT=$(docker compose exec -T kafka /opt/kafka/bin/kafka-get-offsets.sh \
  --bootstrap-server kafka:9092 --topic student_interactions_stream 2>/dev/null \
  | awk -F: '{sum+=$3} END {print sum+0}')
COUNT_DEL=$(docker compose exec -T kafka /opt/kafka/bin/kafka-get-offsets.sh \
  --bootstrap-server kafka:9092 --topic content_delivery_stream 2>/dev/null \
  | awk -F: '{sum+=$3} END {print sum+0}')
COUNT_RR=$(docker compose exec -T kafka /opt/kafka/bin/kafka-get-offsets.sh \
  --bootstrap-server kafka:9092 --topic content_retrieval_requests 2>/dev/null \
  | awk -F: '{sum+=$3} END {print sum+0}')

echo "    student_interactions_stream:  $COUNT_INT mesaj"
echo "    content_retrieval_requests:    $COUNT_RR mesaj  (Orchestrator RAG'a istek attı, RAG yanıt vermedi)"
echo "    content_delivery_stream:       $COUNT_DEL mesaj  (Orchestrator → Gateway)"
[ "$COUNT_INT" -ge 1 ] && ok "student_interactions_stream'de en az 1 mesaj" || fail "interaction stream boş"
[ "$COUNT_RR"  -ge 1 ] && ok "content_retrieval_requests'te en az 1 mesaj" || fail "RAG isteği gönderilmedi"
[ "$COUNT_DEL" -ge 1 ] && ok "content_delivery_stream'de en az 1 mesaj"    || fail "delivery boş"

# ── Özet ─────────────────────────────────────────────────────────────
echo ""
echo "═════════════════════════════════════"
printf "  Passed: ${GREEN}%d${NC}    Failed: ${RED}%d${NC}\n" "$PASS" "$FAIL"
echo "═════════════════════════════════════"
[ "$FAIL" -eq 0 ]
