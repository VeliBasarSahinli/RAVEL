#!/usr/bin/env bash
# RAVEL — Adım 6 uçtan uca testi.
#
# Akış:
#   Browser → /api/answer → Gateway → student_interactions_stream
#   → Orchestrator → Bandit (FORCED video) → Orchestrator
#   → manim_render_tasks → Manim Worker → MinIO upload
#   → video_ready_events → Gateway → WebSocket → client
#
# Çalıştırmadan önce: docker compose up -d (manim_worker dahil hepsi healthy).
# Bu test BANDIT_FORCE_DECISION=video ortamını gerektirir; yoksa kararı
# stochastic olur ve test flaky olur. Test başında compose'a env'i set edip
# bandit container'ını yeniden başlatıyoruz; bittiğinde resetliyoruz.

set -uo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then echo "✗ .env yok" >&2; exit 1; fi
# shellcheck disable=SC1091
set -a; source .env; set +a

GREEN="\033[0;32m"; RED="\033[0;31m"; YELLOW="\033[0;33m"; NC="\033[0m"
PASS=0; FAIL=0
ok()   { printf "  ${GREEN}✓${NC} %s\n" "$1"; PASS=$((PASS+1)); }
fail() { printf "  ${RED}✗${NC} %s\n" "$1"; FAIL=$((FAIL+1)); }
hdr()  { printf "\n${YELLOW}═══ %s ═══${NC}\n" "$1"; }

API="http://localhost:${API_GATEWAY_PORT:-8000}"

echo ""
echo "═══ RAVEL Adım 6 — Manim Worker E2E ═══"

# ────────────────────────────────────────────────────────────────────
# Setup: Bandit'i FORCE=video ile yeniden başlat
# ────────────────────────────────────────────────────────────────────
hdr "SETUP: Bandit Actor → BANDIT_FORCE_DECISION=video"

if ! docker ps --format '{{.Names}}' | grep -q '^ravel_bandit$'; then
  fail "ravel_bandit container ayakta değil"
  exit 1
fi
if ! docker ps --format '{{.Names}}' | grep -q '^ravel_manim_worker$'; then
  fail "ravel_manim_worker container ayakta değil"
  exit 1
fi

echo ""
echo "→ Bandit'i video kararı verecek şekilde restart et"
BANDIT_FORCE_DECISION=video docker compose up -d --no-deps bandit >/dev/null 2>&1

# Bu test Manim Worker boru hattını izoleli test ediyor (sandbox → render →
# MinIO → WS). LLM kalitesi test kapsamında değil; LLM_MOCK_MODE=true ile
# orchestrator'ı bilinen-iyi mock Manim koduna sabitliyoruz. Aksi halde
# LLM rastgele Manim API yanlışlıkları üretir ve render rc=1 verir.
echo "→ Orchestrator'ı LLM_MOCK_MODE=true ile restart (test deterministic olsun)"
LLM_MOCK_MODE=true docker compose up -d --no-deps orchestrator >/dev/null 2>&1
echo "    'orchestrator ready' log'unu bekleniyor (max 30 sn)…"
PREV_ORCH=$(docker compose logs --no-color orchestrator 2>&1 | grep -c "orchestrator ready" || true)
for i in $(seq 1 30); do
  CUR_ORCH=$(docker compose logs --no-color orchestrator 2>&1 | grep -c "orchestrator ready" || true)
  if [ "$CUR_ORCH" -gt "$PREV_ORCH" ]; then break; fi
  sleep 1
done

echo "    'bandit ready' log'unu bekleniyor (max 30 sn)…"
PREV_READY=$(docker compose logs --no-color bandit 2>&1 | grep -c "bandit ready" || true)
for i in $(seq 1 30); do
  CUR=$(docker compose logs --no-color bandit 2>&1 | grep -c "bandit ready" || true)
  if [ "$CUR" -gt "$PREV_READY" ]; then
    echo "    ✓ ($i sn) bandit ready"
    break
  fi
  sleep 1
done
# Healthy + consumer rejoin pad
for i in $(seq 1 30); do
  HEALTH=$(docker inspect -f '{{.State.Health.Status}}' ravel_bandit 2>/dev/null || echo missing)
  if [ "$HEALTH" = "healthy" ]; then break; fi
  sleep 1
done
sleep 3
ok "Bandit FORCE=video modunda hazır"

# ────────────────────────────────────────────────────────────────────
# 1) Login
# ────────────────────────────────────────────────────────────────────
hdr "TEST 1: Login + token al"

LOGIN=$(curl -sS -X POST "$API/auth/login" -H 'Content-Type: application/json' -d '{"grade_level":7}')
TOKEN=$(echo "$LOGIN"   | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
STUDENT=$(echo "$LOGIN" | python3 -c "import json,sys; print(json.load(sys.stdin)['student_id'])")
[ -n "$TOKEN" ] && [ -n "$STUDENT" ] && ok "token alındı (student=$STUDENT)" \
                                    || fail "login başarısız: $LOGIN"

# ────────────────────────────────────────────────────────────────────
# 2) WS bağlan + /api/answer + WS recv (video_ready bekle)
# ────────────────────────────────────────────────────────────────────
hdr "TEST 2: /api/answer → manim_render_tasks → video_ready_events → WS"

# Baseline offset'leri al — yalnızca yeni mesajları sayacağız.
MR_BEFORE=$(docker compose exec -T kafka /opt/kafka/bin/kafka-get-offsets.sh \
  --bootstrap-server kafka:9092 --topic manim_render_tasks 2>/dev/null \
  | awk -F: '{sum+=$3} END {print sum+0}')
VR_BEFORE=$(docker compose exec -T kafka /opt/kafka/bin/kafka-get-offsets.sh \
  --bootstrap-server kafka:9092 --topic video_ready_events 2>/dev/null \
  | awk -F: '{sum+=$3} END {print sum+0}')
echo "    baselines: manim_render_tasks=$MR_BEFORE  video_ready_events=$VR_BEFORE"

# WS dinleyici + answer POST tek bir Python süreciyle (Gateway venv'i kullanılır):
OUTPUT=$(docker compose exec -T api_gateway python <<PY
import asyncio, json, sys, traceback
import httpx
from websockets import connect

API = "http://localhost:8000"
TOKEN = "$TOKEN"
STUDENT = "$STUDENT"
WS_TIMEOUT = 120        # render <=45 sn + sandbox + upload + Kafka jitter

async def main():
    uri = f"ws://localhost:8000/ws/{STUDENT}?token={TOKEN}"
    async with connect(uri) as ws:
        print("WS_CONNECTED")
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{API}/api/answer",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "question_id": "q_video_e2e",
                    "topic": "Uslu_Ifadeler",
                    "taxonomic_level": "B1",
                    "student_answer": "C",
                    "is_correct": False,
                    "time_spent": 30,
                    "explicit_video_request": True,
                },
            )
            r.raise_for_status()
            sent = r.json()["trace_id"]
            print(f"ANSWER_ACCEPTED trace={sent}")
        # Birden çok WS frame gelebilir (text fallback + video, ya da yalnız video).
        # video tipini bekleyelim, max WS_TIMEOUT.
        try:
            deadline = asyncio.get_event_loop().time() + WS_TIMEOUT
            video_seen = False
            while asyncio.get_event_loop().time() < deadline:
                msg = await asyncio.wait_for(
                    ws.recv(),
                    timeout=max(0.1, deadline - asyncio.get_event_loop().time()),
                )
                payload = json.loads(msg)
                ct = payload.get("content_type")
                tid = payload.get("trace_id")
                print(f"WS_FRAME content_type={ct} trace={tid}")
                if ct == "video" and tid == sent:
                    print(f"VIDEO_RECEIVED trace={tid} url={payload.get('video_url','')[:80]}")
                    print(f"DURATION={payload.get('duration_seconds',0)} SIZE={payload.get('file_size_bytes',0)}")
                    video_seen = True
                    break
            if not video_seen:
                print("WS_TIMEOUT: hiç video tipi mesaj gelmedi")
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

echo "$OUTPUT" | grep -q "WS_CONNECTED"      && ok "WebSocket bağlandı"        || fail "WS bağlantı"
echo "$OUTPUT" | grep -q "ANSWER_ACCEPTED"   && ok "/api/answer 200"           || fail "answer POST"
echo "$OUTPUT" | grep -q "VIDEO_RECEIVED"    && ok "WS'ten video URL geldi"    || fail "VIDEO_RECEIVED yok"

# ────────────────────────────────────────────────────────────────────
# 3) Kafka offset doğrulama
# ────────────────────────────────────────────────────────────────────
hdr "TEST 3: Kafka mesaj sayıları"

MR_AFTER=$(docker compose exec -T kafka /opt/kafka/bin/kafka-get-offsets.sh \
  --bootstrap-server kafka:9092 --topic manim_render_tasks 2>/dev/null \
  | awk -F: '{sum+=$3} END {print sum+0}')
VR_AFTER=$(docker compose exec -T kafka /opt/kafka/bin/kafka-get-offsets.sh \
  --bootstrap-server kafka:9092 --topic video_ready_events 2>/dev/null \
  | awk -F: '{sum+=$3} END {print sum+0}')
echo "    manim_render_tasks: $MR_BEFORE → $MR_AFTER"
echo "    video_ready_events: $VR_BEFORE → $VR_AFTER"

[ "$MR_AFTER" -gt "$MR_BEFORE" ] && ok "manim_render_tasks'a yeni task yazıldı" \
                                || fail "manim_render_tasks büyümedi"
[ "$VR_AFTER" -gt "$VR_BEFORE" ] && ok "video_ready_events'e mesaj yazıldı"     \
                                || fail "video_ready_events büyümedi"

# ────────────────────────────────────────────────────────────────────
# 4) Log doğrulama
# ────────────────────────────────────────────────────────────────────
hdr "TEST 4: Servis log'larında akış izi"

# Not: `set -uo pipefail` + `cmd | grep -q` tuzağı: grep ilk eşleşmede çıkar,
# docker compose logs SIGPIPE alır → exit≠0 → pipefail if'i fail dalına atar.
# Çözüm: grep -c ile sayıma çevir.
DISP_COUNT=$(docker compose logs --no-color --since=10m orchestrator 2>&1 \
  | grep -c "manim render dispatched" || true)
[ "$DISP_COUNT" -ge 1 ] && ok "Orchestrator: 'manim render dispatched' log'u var ($DISP_COUNT)" \
                        || fail "Orchestrator dispatched log'u yok"

VR_LOG_COUNT=$(docker compose logs --no-color --since=10m manim_worker 2>&1 \
  | grep -c "video_ready: task=" || true)
[ "$VR_LOG_COUNT" -ge 1 ] && ok "Manim Worker: 'video_ready' log'u var ($VR_LOG_COUNT)" \
                          || fail "Manim Worker video_ready log'u yok"

BANDIT_VID_COUNT=$(docker compose logs --no-color --since=10m bandit 2>&1 \
  | grep -cE "FORCED decision=video|action=video" || true)
[ "$BANDIT_VID_COUNT" -ge 1 ] && ok "Bandit Actor: video decision verildi ($BANDIT_VID_COUNT)" \
                              || fail "Bandit video decision log'u yok"

# ────────────────────────────────────────────────────────────────────
# Cleanup: Bandit force=boş, Orchestrator LLM_MOCK_MODE'u .env'den al
# ────────────────────────────────────────────────────────────────────
hdr "CLEANUP: Bandit'i FORCE=boş'a, Orchestrator'ı .env LLM_MOCK_MODE değerine geri al"

BANDIT_FORCE_DECISION="" docker compose up -d --no-deps bandit >/dev/null 2>&1
# Orchestrator'ı .env'deki LLM_MOCK_MODE ile yeniden başlat (compose tekrar
# .env'i okuyacak; explicit env biz koymadık).
docker compose up -d --no-deps orchestrator >/dev/null 2>&1

# Sonraki testlerin (rag_e2e vb.) Bandit hazır halde başlamasını garanti et.
echo "    bandit healthy bekleniyor (max 30 sn)…"
for i in $(seq 1 30); do
  HEALTH=$(docker inspect -f '{{.State.Health.Status}}' ravel_bandit 2>/dev/null || echo missing)
  if [ "$HEALTH" = "healthy" ]; then
    # Consumer rejoin için ek 2 sn pad
    sleep 2
    echo "    ✓ ($i sn) bandit healthy"
    break
  fi
  sleep 1
done
ok "Bandit FORCE override kaldırıldı"

# ────────────────────────────────────────────────────────────────────
# Özet
# ────────────────────────────────────────────────────────────────────
echo ""
echo "═════════════════════════════════════"
printf "  Passed: ${GREEN}%d${NC}    Failed: ${RED}%d${NC}\n" "$PASS" "$FAIL"
echo "═════════════════════════════════════"
[ "$FAIL" -eq 0 ]
