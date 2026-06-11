#!/usr/bin/env bash
# RAVEL — Adım 7 Aşama 2: Admin /admin/llm/* endpoint testleri
#
# Akış:
#   1) Admin token al + auth-required davranış
#   2) GET /admin/llm/providers
#   3) POST /admin/llm/config (ollama; api_key gerekmez)
#   4) GET /admin/llm/configs (api_key_set=True, masked)
#   5) PUT /admin/llm/config/{name} (max_tokens patch)
#   6) Cache invalidation: Redis'te llm_config:* DEL oldu mu?
#   7) DELETE /admin/llm/config/{name}
#   8) POST /admin/llm/test/{name} — ollama mock URL → ok=False (network unreachable beklenen)
#
# Bu test gerçek LLM API'sine gitmez; sadece RAG admin API katmanını
# (DB CRUD + Redis cache + provider helper akışı) doğrular.

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
RAG="http://localhost:${ADMIN_API_PORT:-8003}"
AGENT="_test_admin_$$"

echo ""
echo "═══ RAVEL Adım 7 Aşama 2 — Admin /admin/llm/* ═══"

# ────────────────────────────────────────────────────────────────────
# 1) Admin token al
# ────────────────────────────────────────────────────────────────────
hdr "TEST 1: Admin token + auth-required davranış"

ADMIN_LOGIN=$(curl -sS -X POST "$API/auth/login" -H 'Content-Type: application/json' \
  -d '{"grade_level":6,"role":"admin"}')
ADMIN_TOKEN=$(echo "$ADMIN_LOGIN" | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
[ -n "$ADMIN_TOKEN" ] && ok "admin token alındı" || { fail "admin token fail"; exit 1; }

# auth-required: 401 without token
RC_NOAUTH=$(curl -sS -o /dev/null -w "%{http_code}" "$RAG/admin/llm/configs")
[ "$RC_NOAUTH" = "401" ] && ok "401 without token" || fail "expected 401, got $RC_NOAUTH"

# Student (non-admin) token: 403
STU_LOGIN=$(curl -sS -X POST "$API/auth/login" -H 'Content-Type: application/json' \
  -d '{"grade_level":6}')
STU_TOKEN=$(echo "$STU_LOGIN" | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
RC_STU=$(curl -sS -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $STU_TOKEN" \
  "$RAG/admin/llm/configs")
[ "$RC_STU" = "403" ] && ok "student token reddedildi (403)" || fail "expected 403, got $RC_STU"

# ────────────────────────────────────────────────────────────────────
# 2) GET /admin/llm/providers
# ────────────────────────────────────────────────────────────────────
hdr "TEST 2: GET /admin/llm/providers"

PROVIDERS=$(curl -sS -H "Authorization: Bearer $ADMIN_TOKEN" "$RAG/admin/llm/providers")
echo "    $PROVIDERS"
echo "$PROVIDERS" | grep -q "anthropic" && \
echo "$PROVIDERS" | grep -q "openai"    && \
echo "$PROVIDERS" | grep -q "openrouter" && \
echo "$PROVIDERS" | grep -q "ollama"    && \
echo "$PROVIDERS" | grep -q "gemini"    && \
echo "$PROVIDERS" | grep -q "custom"    && \
  ok "6 provider listelendi" || fail "provider listesi eksik"

# ────────────────────────────────────────────────────────────────────
# 3) POST /admin/llm/config (ollama — endpoint zorunlu, api_key gerekmez)
# ────────────────────────────────────────────────────────────────────
hdr "TEST 3: POST /admin/llm/config (ollama)"

# 3.1 ollama endpoint olmadan → 400
RC_NOEP=$(curl -sS -o /dev/null -w "%{http_code}" -X POST "$RAG/admin/llm/config" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d "{\"agent_name\":\"$AGENT\",\"provider\":\"ollama\",\"model_name\":\"llama3:8b\",\"max_tokens\":1024,\"temperature\":0.5}")
[ "$RC_NOEP" = "400" ] && ok "ollama endpoint zorunlu (400)" || fail "expected 400, got $RC_NOEP"

# 3.2 anthropic api_key olmadan → 400
RC_NOKEY=$(curl -sS -o /dev/null -w "%{http_code}" -X POST "$RAG/admin/llm/config" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d "{\"agent_name\":\"$AGENT\",\"provider\":\"anthropic\",\"model_name\":\"claude-sonnet-4-6\",\"max_tokens\":1024,\"temperature\":0.5}")
[ "$RC_NOKEY" = "400" ] && ok "anthropic api_key zorunlu (400)" || fail "expected 400, got $RC_NOKEY"

# 3.3 valid ollama config
CREATE=$(curl -sS -X POST "$RAG/admin/llm/config" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d "{\"agent_name\":\"$AGENT\",\"provider\":\"ollama\",\"model_name\":\"llama3:8b\",\"endpoint_url\":\"http://localhost:11434\",\"max_tokens\":2048,\"temperature\":0.4}")
echo "    $CREATE"
echo "$CREATE" | grep -q "\"agent_name\":\"$AGENT\"" && ok "config oluştu" || fail "create payload"
echo "$CREATE" | grep -q "\"api_key_set\":false" && ok "ollama api_key_set=false" || fail "api_key_set"

# 3.4 anthropic config (api_key encrypt edilecek)
ANT=$(curl -sS -X POST "$RAG/admin/llm/config" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d "{\"agent_name\":\"${AGENT}_ant\",\"provider\":\"anthropic\",\"model_name\":\"claude-sonnet-4-6\",\"api_key\":\"sk-ant-api03-test-fake\",\"max_tokens\":1024,\"temperature\":0.7}")
echo "    $ANT"
echo "$ANT" | grep -q "\"api_key_set\":true" && ok "anthropic api_key_set=true" || fail "anthropic create"
# api_key plaintext sızdırma kontrolü
if echo "$ANT" | grep -q "sk-ant-api03-test-fake"; then
  fail "BÜYÜK GÜVENLİK SORUNU: api_key plaintext response'ta"
else
  ok "api_key plaintext sızmadı"
fi
echo "$ANT" | grep -q "sk-a\\*\\*\\*\\*" && ok "api_key prefix maskeli (sk-a****)" || fail "mask format"

# ────────────────────────────────────────────────────────────────────
# 4) GET /admin/llm/configs
# ────────────────────────────────────────────────────────────────────
hdr "TEST 4: GET /admin/llm/configs (listede maskeli)"

LIST=$(curl -sS -H "Authorization: Bearer $ADMIN_TOKEN" "$RAG/admin/llm/configs")
echo "    $LIST" | head -c 400
echo "..."
echo "$LIST" | grep -q "\"agent_name\":\"$AGENT\"" && ok "$AGENT listede" || fail "ollama config listede yok"
echo "$LIST" | grep -q "\"agent_name\":\"${AGENT}_ant\"" && ok "anthropic config listede" || fail "anthropic config listede yok"
# api_key plaintext sızdırma — list endpoint'inde de
if echo "$LIST" | grep -q "sk-ant-api03-test-fake"; then
  fail "list'te plaintext key sızıntısı"
else
  ok "list'te plaintext key yok"
fi

# ────────────────────────────────────────────────────────────────────
# 5) PUT /admin/llm/config/{name}
# ────────────────────────────────────────────────────────────────────
hdr "TEST 5: PUT /admin/llm/config (partial update + cache invalidation)"

# Cache'i seed et: önce gateway'den oku (mock_mode olsa da cache key'i set etsin)
docker compose exec -T redis redis-cli -a "${REDIS_PASSWORD}" --no-auth-warning \
  set "llm_config:$AGENT" '{"sentinel":"old"}' ex 300 >/dev/null 2>&1 || true

UPDATE=$(curl -sS -X PUT "$RAG/admin/llm/config/$AGENT" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"max_tokens": 4096, "temperature": 0.3}')
echo "    $UPDATE"
echo "$UPDATE" | grep -q "\"max_tokens\":4096" && ok "max_tokens 4096'a güncellendi" || fail "update body"
echo "$UPDATE" | grep -q "\"temperature\":0.3" && ok "temperature 0.3'e güncellendi" || fail "temperature update"

# Cache invalidation kontrolü — Redis'te llm_config:$AGENT silinmiş olmalı
CACHED=$(docker compose exec -T redis redis-cli -a "${REDIS_PASSWORD}" --no-auth-warning \
  get "llm_config:$AGENT" 2>/dev/null | tr -d '[:space:]')
[ -z "$CACHED" ] || [ "$CACHED" = "" ] && ok "cache invalidate: redis key silindi" \
  || fail "cache hâlâ var: $CACHED"

# 404: olmayan agent
RC_404=$(curl -sS -o /dev/null -w "%{http_code}" -X PUT "$RAG/admin/llm/config/_doesnt_exist_" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"max_tokens": 1024}')
[ "$RC_404" = "404" ] && ok "olmayan agent → 404" || fail "expected 404, got $RC_404"

# ────────────────────────────────────────────────────────────────────
# 6) POST /admin/llm/test/{name} (ollama mock URL — network unreachable beklenen)
# ────────────────────────────────────────────────────────────────────
hdr "TEST 6: POST /admin/llm/test (ollama unreachable → ok=false)"

TEST_OUT=$(curl -sS -X POST "$RAG/admin/llm/test/$AGENT" \
  -H "Authorization: Bearer $ADMIN_TOKEN")
echo "    $TEST_OUT"
echo "$TEST_OUT" | grep -q "\"ok\":false" && ok "unreachable URL → ok=false" || fail "test endpoint"
echo "$TEST_OUT" | grep -q "\"provider\":\"ollama\"" && ok "test response provider=ollama" || fail "provider field"
echo "$TEST_OUT" | grep -q "\"agent_name\":\"$AGENT\"" && ok "test response agent_name doğru" || fail "agent field"

# ────────────────────────────────────────────────────────────────────
# 7) DELETE /admin/llm/config/{name}
# ────────────────────────────────────────────────────────────────────
hdr "TEST 7: DELETE /admin/llm/config (+ cache invalidation)"

# Cache'i tekrar seed et
docker compose exec -T redis redis-cli -a "${REDIS_PASSWORD}" --no-auth-warning \
  set "llm_config:$AGENT" '{"sentinel":"x"}' ex 300 >/dev/null 2>&1 || true

DEL=$(curl -sS -X DELETE "$RAG/admin/llm/config/$AGENT" \
  -H "Authorization: Bearer $ADMIN_TOKEN")
echo "    $DEL"
echo "$DEL" | grep -q "\"deleted\":true" && ok "delete=true" || fail "delete payload"

CACHED2=$(docker compose exec -T redis redis-cli -a "${REDIS_PASSWORD}" --no-auth-warning \
  get "llm_config:$AGENT" 2>/dev/null | tr -d '[:space:]')
[ -z "$CACHED2" ] && ok "delete sonrası cache invalidate" \
  || fail "delete sonrası cache hala var: $CACHED2"

# 404 silmeden tekrar dene
RC_DEL_404=$(curl -sS -o /dev/null -w "%{http_code}" -X DELETE "$RAG/admin/llm/config/$AGENT" \
  -H "Authorization: Bearer $ADMIN_TOKEN")
[ "$RC_DEL_404" = "404" ] && ok "olmayan delete → 404" || fail "expected 404, got $RC_DEL_404"

# Cleanup ant
curl -sS -X DELETE "$RAG/admin/llm/config/${AGENT}_ant" \
  -H "Authorization: Bearer $ADMIN_TOKEN" >/dev/null

# ────────────────────────────────────────────────────────────────────
# Özet
# ────────────────────────────────────────────────────────────────────
echo ""
echo "═════════════════════════════════════"
printf "  Passed: ${GREEN}%d${NC}    Failed: ${RED}%d${NC}\n" "$PASS" "$FAIL"
echo "═════════════════════════════════════"
[ "$FAIL" -eq 0 ]
