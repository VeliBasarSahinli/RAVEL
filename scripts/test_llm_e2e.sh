#!/usr/bin/env bash
# RAVEL — Adım 7 Aşama 3: Gerçek LLM uçtan uca testi
#
# KULLANIM:
#   OPENROUTER_API_KEY=sk-or-v1-... \
#   OPENROUTER_MODEL=anthropic/claude-sonnet-4-5 \   # veya openai/gpt-4o
#   ./scripts/test_llm_e2e.sh
#
# Akış:
#   1) BANDIT_FORCE_DECISION=text → orchestrator deterministik text yolu
#   2) LLM_MOCK_MODE=false ile Orchestrator restart
#   3) RAG admin: orchestrator_text için OpenRouter config oluştur
#      (ENCRYPTION_KEY .env'den, api_key encrypt edilir)
#   4) Test endpoint: /admin/llm/test/orchestrator_text → ok=true bekleniyor
#   5) /api/answer → WS recv → gerçek Türkçe pedagojik yanıt geliyor mu?
#      - 100+ kelime
#      - Türkçe karakter içeriyor
#      - <düşünce> bloğu görünmüyor (CoT temizlenmiş)
#   6) BANDIT_FORCE_DECISION=video + manim agent config → gerçek Manim kodu
#      üretilip render ediliyor mu? (SANDBOX'tan geçecek format kontrolü)
#   7) Cleanup: configs sil, BANDIT_FORCE_DECISION boşa, LLM_MOCK_MODE=true

set -uo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
set -a; source .env; set +a

GREEN="\033[0;32m"; RED="\033[0;31m"; YELLOW="\033[0;33m"; NC="\033[0m"
PASS=0; FAIL=0
ok()   { printf "  ${GREEN}✓${NC} %s\n" "$1"; PASS=$((PASS+1)); }
fail() { printf "  ${RED}✗${NC} %s\n" "$1"; FAIL=$((FAIL+1)); }
hdr()  { printf "\n${YELLOW}═══ %s ═══${NC}\n" "$1"; }

# Required: OPENROUTER_API_KEY (env veya .env)
KEY="${OPENROUTER_API_KEY:-}"
MODEL="${OPENROUTER_MODEL:-anthropic/claude-sonnet-4-5}"
if [ -z "$KEY" ]; then
  echo "✗ OPENROUTER_API_KEY env yok. Kullanım:"
  echo "  OPENROUTER_API_KEY=sk-or-v1-... ./scripts/test_llm_e2e.sh"
  exit 1
fi

API="http://localhost:${API_GATEWAY_PORT:-8000}"
RAG="http://localhost:${ADMIN_API_PORT:-8003}"

echo ""
echo "═══ RAVEL Adım 7 Aşama 3 — Gerçek LLM E2E (OpenRouter) ═══"
echo "  Model: $MODEL"
echo ""

ADMIN_LOGIN=$(curl -sS -X POST "$API/auth/login" -H 'Content-Type: application/json' \
  -d '{"grade_level":6,"role":"admin"}')
ADMIN_TOKEN=$(echo "$ADMIN_LOGIN" | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

# ────────────────────────────────────────────────────────────────────
# 1) Orchestrator real-LLM moduna geç (LLM_MOCK_MODE=false + FORCE=text)
# ────────────────────────────────────────────────────────────────────
hdr "SETUP: Orchestrator + Bandit yeniden konfigüre"

LLM_MOCK_MODE=false BANDIT_FORCE_DECISION=text \
  docker compose up -d --no-deps orchestrator bandit >/dev/null 2>&1
echo "    container'lar yeniden başlatıldı"

# Healthy bekle
for i in $(seq 1 60); do
  H1=$(docker inspect -f '{{.State.Health.Status}}' ravel_orchestrator 2>/dev/null)
  H2=$(docker inspect -f '{{.State.Health.Status}}' ravel_bandit 2>/dev/null)
  if [ "$H1" = "healthy" ] && [ "$H2" = "healthy" ]; then
    echo "    ✓ ($i sn) orchestrator + bandit healthy"
    break
  fi
  sleep 1
done
sleep 3
ok "Orchestrator real-LLM modunda + Bandit FORCE=text"

# ────────────────────────────────────────────────────────────────────
# 2) Admin: orchestrator_text config (OpenRouter)
# ────────────────────────────────────────────────────────────────────
hdr "TEST 1: orchestrator_text için OpenRouter config"

CREATE=$(curl -sS -X POST "$RAG/admin/llm/config" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d "{\"agent_name\":\"orchestrator_text\",\"provider\":\"openrouter\",\"model_name\":\"$MODEL\",\"api_key\":\"$KEY\",\"max_tokens\":800,\"temperature\":0.5}")
echo "$CREATE" | grep -q "\"api_key_set\":true" && ok "config oluştu (api_key_set=true)" || { fail "create"; echo "$CREATE"; }
if echo "$CREATE" | grep -q "$KEY"; then fail "GÜVENLİK: api_key plaintext sızdı"; else ok "api_key plaintext sızmadı"; fi

# ────────────────────────────────────────────────────────────────────
# 3) Test endpoint
# ────────────────────────────────────────────────────────────────────
hdr "TEST 2: /admin/llm/test — gerçek 'Merhaba' isteği"

TEST_R=$(curl -sS -X POST "$RAG/admin/llm/test/orchestrator_text" \
  -H "Authorization: Bearer $ADMIN_TOKEN")
echo "    $TEST_R"
if echo "$TEST_R" | grep -q "\"ok\":true"; then
  ok "OpenRouter test isteği başarılı"
  LATENCY=$(echo "$TEST_R" | python3 -c "import json,sys; print(json.load(sys.stdin).get('latency_ms','?'))")
  echo "    latency: ${LATENCY}ms"
else
  fail "test endpoint ok=false"
fi

# ────────────────────────────────────────────────────────────────────
# 4) /api/answer → WS recv → gerçek pedagojik yanıt
# ────────────────────────────────────────────────────────────────────
hdr "TEST 3: /api/answer → WS → Türkçe pedagojik yanıt"

LOGIN=$(curl -sS -X POST "$API/auth/login" -H 'Content-Type: application/json' \
  -d '{"grade_level":7}')
TOKEN=$(echo "$LOGIN"   | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
STUDENT=$(echo "$LOGIN" | python3 -c "import json,sys; print(json.load(sys.stdin)['student_id'])")

OUT=$(docker compose exec -T api_gateway python <<PY
import asyncio, json, sys
import httpx
from websockets import connect

API="http://localhost:8000"; TOKEN="$TOKEN"; STUDENT="$STUDENT"

async def main():
    uri = f"ws://localhost:8000/ws/{STUDENT}?token={TOKEN}"
    async with connect(uri) as ws:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{API}/api/answer",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"question_id":"q_llm_e2e","topic":"Uslu_Ifadeler","taxonomic_level":"B1",
                      "student_answer":"6","is_correct":False,"time_spent":40})
            print(f"ANSWER trace={r.json()['trace_id']}")
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=60)
            data = json.loads(msg)
            print(f"WS_OK content_type={data.get('content_type')}")
            print(f"BODY_LEN={len(data.get('body_html',''))}")
            print(f"BODY_FIRST_300:{data.get('body_html','')[:300]}")
            print(f"BODY_LAST_200:{data.get('body_html','')[-200:]}")
        except asyncio.TimeoutError:
            print("WS_TIMEOUT")

asyncio.run(main())
PY
)
echo "$OUT" | sed 's/^/    /'

echo "$OUT" | grep -q "WS_OK content_type=text_explanation" && ok "WS text_explanation geldi" || fail "WS recv"
BODY_LEN=$(echo "$OUT" | grep "^BODY_LEN=" | sed 's/.*BODY_LEN=//' | head -1)
[ "${BODY_LEN:-0}" -ge 300 ] && ok "yanıt yeterince uzun ($BODY_LEN B)" || fail "yanıt kısa: $BODY_LEN B"

# Türkçe karakter kontrolü
echo "$OUT" | grep -qE "ş|ğ|ü|ö|ç|ı|İ" && ok "Türkçe karakter içeriyor" || fail "Türkçe karakter yok"

# CoT bloğu sızıntısı
if echo "$OUT" | grep -qE "<düşünce>|</düşünce>|<thinking>|</thinking>"; then
  fail "CoT bloğu öğrenciye sızdı"
else
  ok "CoT bloğu temizlenmiş (öğrenciye sızmadı)"
fi

# ────────────────────────────────────────────────────────────────────
# 5) Manim akışı — orchestrator_manim config + FORCE=video
# ────────────────────────────────────────────────────────────────────
hdr "TEST 4: orchestrator_manim → gerçek Manim kodu üretimi"

curl -sS -X POST "$RAG/admin/llm/config" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d "{\"agent_name\":\"orchestrator_manim\",\"provider\":\"openrouter\",\"model_name\":\"$MODEL\",\"api_key\":\"$KEY\",\"max_tokens\":1024,\"temperature\":0.3}" \
  >/dev/null

# Bandit'i video moduna geçir
LLM_MOCK_MODE=false BANDIT_FORCE_DECISION=video \
  docker compose up -d --no-deps bandit >/dev/null 2>&1
for i in $(seq 1 30); do
  H=$(docker inspect -f '{{.State.Health.Status}}' ravel_bandit 2>/dev/null)
  [ "$H" = "healthy" ] && break
  sleep 1
done
sleep 3
ok "Bandit FORCE=video aktif"

# Baseline offsets
MR_BEFORE=$(docker compose exec -T kafka /opt/kafka/bin/kafka-get-offsets.sh \
  --bootstrap-server kafka:9092 --topic manim_render_tasks 2>/dev/null \
  | awk -F: '{sum+=$3} END {print sum+0}')
VR_BEFORE=$(docker compose exec -T kafka /opt/kafka/bin/kafka-get-offsets.sh \
  --bootstrap-server kafka:9092 --topic video_ready_events 2>/dev/null \
  | awk -F: '{sum+=$3} END {print sum+0}')

OUT=$(docker compose exec -T api_gateway python <<PY
import asyncio, json, sys
import httpx
from websockets import connect

API="http://localhost:8000"; TOKEN="$TOKEN"; STUDENT="$STUDENT"

async def main():
    uri = f"ws://localhost:8000/ws/{STUDENT}?token={TOKEN}"
    async with connect(uri) as ws:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{API}/api/answer",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={"question_id":"q_video_real","topic":"Uslu_Ifadeler","taxonomic_level":"B1",
                      "student_answer":"X","is_correct":False,"time_spent":35,"explicit_video_request":True})
            print(f"ANSWER trace={r.json()['trace_id']}")
        try:
            deadline = asyncio.get_event_loop().time() + 180
            while asyncio.get_event_loop().time() < deadline:
                msg = await asyncio.wait_for(
                    ws.recv(),
                    timeout=max(0.1, deadline - asyncio.get_event_loop().time()),
                )
                data = json.loads(msg)
                if data.get("content_type") == "video":
                    print(f"VIDEO_OK url=...{data.get('video_url','')[-40:]}")
                    print(f"DURATION={data.get('duration_seconds')}")
                    return
            print("WS_TIMEOUT_NO_VIDEO")
        except asyncio.TimeoutError:
            print("WS_TIMEOUT")

asyncio.run(main())
PY
)
echo "$OUT" | sed 's/^/    /'

MR_AFTER=$(docker compose exec -T kafka /opt/kafka/bin/kafka-get-offsets.sh \
  --bootstrap-server kafka:9092 --topic manim_render_tasks 2>/dev/null \
  | awk -F: '{sum+=$3} END {print sum+0}')
VR_AFTER=$(docker compose exec -T kafka /opt/kafka/bin/kafka-get-offsets.sh \
  --bootstrap-server kafka:9092 --topic video_ready_events 2>/dev/null \
  | awk -F: '{sum+=$3} END {print sum+0}')

[ "$MR_AFTER" -gt "$MR_BEFORE" ] && ok "manim_render_tasks +$((MR_AFTER-MR_BEFORE))" || fail "manim_render_tasks artmadı"
echo "$OUT" | grep -q "VIDEO_OK" && ok "video_ready WS'ten ulaştı" || fail "VIDEO_OK yok (gerçek LLM kodu sandbox/render geçmedi)"

# ────────────────────────────────────────────────────────────────────
# Cleanup
# ────────────────────────────────────────────────────────────────────
hdr "CLEANUP: configs sil + ortam restore"

curl -sS -X DELETE "$RAG/admin/llm/config/orchestrator_text" \
  -H "Authorization: Bearer $ADMIN_TOKEN" >/dev/null
curl -sS -X DELETE "$RAG/admin/llm/config/orchestrator_manim" \
  -H "Authorization: Bearer $ADMIN_TOKEN" >/dev/null
ok "config'ler silindi"

LLM_MOCK_MODE=true BANDIT_FORCE_DECISION="" \
  docker compose up -d --no-deps orchestrator bandit >/dev/null 2>&1
for i in $(seq 1 30); do
  H1=$(docker inspect -f '{{.State.Health.Status}}' ravel_orchestrator 2>/dev/null)
  H2=$(docker inspect -f '{{.State.Health.Status}}' ravel_bandit 2>/dev/null)
  [ "$H1" = "healthy" ] && [ "$H2" = "healthy" ] && break
  sleep 1
done
ok "ortam mock-mode + LinTS'e döndü"

echo ""
echo "═════════════════════════════════════"
printf "  Passed: ${GREEN}%d${NC}    Failed: ${RED}%d${NC}\n" "$PASS" "$FAIL"
echo "═════════════════════════════════════"
[ "$FAIL" -eq 0 ]
