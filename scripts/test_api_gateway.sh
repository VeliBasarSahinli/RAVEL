#!/usr/bin/env bash
# RAVEL — Step 2a end-to-end test for the API Gateway.
# Scenario:
#   1. POST /auth/login → token, student_id
#   2. GET  /auth/verify
#   3. WebSocket /ws/{student_id}?token=... (using gateway container's own python)
#   4. POST /api/answer → 200
#   5. Read student_interactions_stream from Kafka, assert message + trace_id

set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "✗ .env not found. Run:  cp .env.example .env" >&2
  exit 1
fi
# shellcheck disable=SC1091
set -a; source .env; set +a

API="http://localhost:${API_GATEWAY_PORT:-8000}"
GREEN="\033[0;32m"; RED="\033[0;31m"; NC="\033[0m"
PASS=0; FAIL=0

ok()   { printf "  ${GREEN}✓${NC} %s\n" "$1"; PASS=$((PASS+1)); }
fail() { printf "  ${RED}✗${NC} %s\n" "$1"; FAIL=$((FAIL+1)); }

# ── 1. Login ─────────────────────────────────────────────────────────
echo ""
echo "→ Login"
LOGIN_RESP=$(curl -s -X POST "$API/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"grade_level":6}')
TOKEN=$(echo "$LOGIN_RESP"   | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
STUDENT=$(echo "$LOGIN_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['student_id'])")
EXPIRES=$(echo "$LOGIN_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['expires_in'])")
[ -n "$TOKEN" ] && [ -n "$STUDENT" ] && ok "got token (expires_in=$EXPIRES) for student=$STUDENT" \
                                    || fail "login failed: $LOGIN_RESP"

# ── 2. Verify ────────────────────────────────────────────────────────
echo ""
echo "→ Verify"
VERIFY=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/auth/verify")
echo "$VERIFY" | grep -q "\"valid\":true" \
  && ok "token verified ($VERIFY)" \
  || fail "verify failed: $VERIFY"

# ── 3. WebSocket connect (uses the api_gateway container's python) ───
echo ""
echo "→ WebSocket /ws/$STUDENT (5 sn boyunca açık tut)"
WS_OUTPUT=$(docker compose exec -T api_gateway python -c "
import asyncio, json, sys
from websockets import connect

async def main():
    uri = f'ws://localhost:8000/ws/$STUDENT?token=$TOKEN'
    try:
        async with connect(uri) as ws:
            print('CONNECTED')
            await asyncio.sleep(2)
            print('STILL_OPEN')
    except Exception as e:
        print(f'WS_ERROR: {e}', file=sys.stderr)
        sys.exit(1)

asyncio.run(main())
" 2>&1) && WS_RC=0 || WS_RC=$?

if [ "$WS_RC" -eq 0 ] && echo "$WS_OUTPUT" | grep -q "CONNECTED" && echo "$WS_OUTPUT" | grep -q "STILL_OPEN"; then
  ok "websocket connected and stayed open"
else
  fail "websocket: $WS_OUTPUT"
fi

# ── 4. Submit answer ─────────────────────────────────────────────────
echo ""
echo "→ POST /api/answer"
ANSWER_RESP=$(curl -s -X POST "$API/api/answer" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "question_id":"q_6_mat_2_10",
    "topic":"Uslu_Ifadeler",
    "taxonomic_level":"B1",
    "student_answer":"C",
    "is_correct":false,
    "time_spent":42
  }')
TRACE=$(echo "$ANSWER_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('trace_id',''))")
[ -n "$TRACE" ] && ok "answer accepted (trace_id=$TRACE)" || fail "answer failed: $ANSWER_RESP"

# ── 5. Verify Kafka received the message ─────────────────────────────
# Tüm mesajları oku (timeout ile), bizim trace_id'yi içereni bul.
# --from-beginning + --max-messages 1 yaklaşımı en eski mesajı alıyor
# ve testin gönderdiği mesajı bulamıyordu (Kafka topic'i biriktikçe).
echo ""
echo "→ Kafka student_interactions_stream'i oku (bizim trace'i ara)"
ALL_MSGS=$(docker compose exec -T kafka /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server kafka:9092 \
  --topic student_interactions_stream \
  --from-beginning --timeout-ms 8000 2>/dev/null)

KAFKA_MSG=$(echo "$ALL_MSGS" | grep "\"trace_id\": \"$TRACE\"" | head -1)

if [ -n "$KAFKA_MSG" ]; then
  echo "    bulundu: $(echo "$KAFKA_MSG" | head -c 120)…"
  ok "trace_id ($TRACE) Kafka mesajında bulundu"
  # Schema sanity (CLAUDE.md ile uyumlu mu)
  if echo "$KAFKA_MSG" | grep -q '"event_type": "question_answered"'; then
    ok "Kafka mesajı CLAUDE.md schema'sına uygun"
  else
    fail "schema hatalı: event_type yok"
  fi
else
  fail "trace_id ($TRACE) Kafka'da bulunamadı (toplam mesaj sayısı: $(echo "$ALL_MSGS" | wc -l))"
fi

echo ""
echo "═════════════════════════════════════"
printf "  Passed: ${GREEN}%d${NC}    Failed: ${RED}%d${NC}\n" "$PASS" "$FAIL"
echo "═════════════════════════════════════"
[ "$FAIL" -eq 0 ]
