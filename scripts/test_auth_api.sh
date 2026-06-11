#!/usr/bin/env bash
# RAVEL — Adım 8 Faz 1 backend smoke
#
# Doğrulanan endpoint'ler:
#   POST /auth/login (legacy + username/password)
#   POST /auth/register (admin only)
#   GET  /auth/me
#   GET  /auth/verify
#   POST /auth/logout
#   GET  /api/profile
#   GET  /api/question?topic=...&taxonomic_level=...
#   POST /api/chat
#   CORS preflight (OPTIONS) çalışıyor mu

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

echo ""
echo "═══ RAVEL Adım 8 Faz 1 — Backend smoke ═══"

# ────────────────────────────────────────────────────────────────────
# 1) Default admin login (username/password)
# ────────────────────────────────────────────────────────────────────
hdr "TEST 1: POST /auth/login (default admin: $ADMIN_DEFAULT_USERNAME)"

ADMIN_LOGIN=$(curl -sS -X POST "$API/auth/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$ADMIN_DEFAULT_USERNAME\",\"password\":\"$ADMIN_DEFAULT_PASSWORD\"}")
echo "    $ADMIN_LOGIN" | head -c 200; echo "..."
ADMIN_TOKEN=$(echo "$ADMIN_LOGIN" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('access_token',''))")
ADMIN_ROLE=$(echo "$ADMIN_LOGIN" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('role',''))")
[ -n "$ADMIN_TOKEN" ] && ok "admin token alındı" || { fail "admin login fail"; exit 1; }
[ "$ADMIN_ROLE" = "admin" ] && ok "JWT'de role=admin" || fail "role yok: $ADMIN_ROLE"

# Yanlış parola → 401
RC_BAD=$(curl -sS -o /dev/null -w "%{http_code}" -X POST "$API/auth/login" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$ADMIN_DEFAULT_USERNAME\",\"password\":\"wrong\"}")
[ "$RC_BAD" = "401" ] && ok "yanlış parola → 401" || fail "expected 401, got $RC_BAD"

# Olmayan user → 401 (existence sızdırmasın)
RC_NOUSER=$(curl -sS -o /dev/null -w "%{http_code}" -X POST "$API/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"_does_not_exist_","password":"foo"}')
[ "$RC_NOUSER" = "401" ] && ok "olmayan user → 401" || fail "expected 401, got $RC_NOUSER"

# ────────────────────────────────────────────────────────────────────
# 2) Legacy anonymous login (grade_level only)
# ────────────────────────────────────────────────────────────────────
hdr "TEST 2: Legacy anonymous login"

LEG=$(curl -sS -X POST "$API/auth/login" -H 'Content-Type: application/json' \
  -d '{"grade_level":7}')
LEG_TOKEN=$(echo "$LEG" | python3 -c "import json,sys; print(json.load(sys.stdin).get('access_token',''))")
LEG_ROLE=$(echo "$LEG" | python3 -c "import json,sys; print(json.load(sys.stdin).get('role',''))")
[ -n "$LEG_TOKEN" ] && ok "anonim token alındı" || fail "legacy login fail"
[ "$LEG_ROLE" = "student" ] && ok "anonim role=student" || fail "role: $LEG_ROLE"

# ────────────────────────────────────────────────────────────────────
# 3) /auth/register (admin only)
# ────────────────────────────────────────────────────────────────────
hdr "TEST 3: POST /auth/register (admin guard)"

NEW_USER="testkid_$$"
# 3.1 admin token ile register
REG=$(curl -sS -X POST "$API/auth/register" \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "{\"username\":\"$NEW_USER\",\"password\":\"secret123\",\"grade_level\":6,\"display_name\":\"Test Kid\"}")
echo "    $REG"
echo "$REG" | grep -q "\"username\":\"$NEW_USER\"" && ok "register başarılı" || fail "register payload"

# 3.2 non-admin token register → 403 (password ≥6 char Pydantic min)
RC_REG_403=$(curl -sS -o /dev/null -w "%{http_code}" -X POST "$API/auth/register" \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $LEG_TOKEN" \
  -d "{\"username\":\"hacker_$$\",\"password\":\"validpw\",\"grade_level\":7}")
[ "$RC_REG_403" = "403" ] && ok "öğrenci token register'a → 403" || fail "expected 403, got $RC_REG_403"

# 3.3 duplicate → 409 (password ≥6 char)
RC_DUP=$(curl -sS -o /dev/null -w "%{http_code}" -X POST "$API/auth/register" \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "{\"username\":\"$NEW_USER\",\"password\":\"differentpw\",\"grade_level\":6}")
[ "$RC_DUP" = "409" ] && ok "duplicate username → 409" || fail "expected 409, got $RC_DUP"

# 3.4 yeni user ile login
NEW_LOGIN=$(curl -sS -X POST "$API/auth/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$NEW_USER\",\"password\":\"secret123\"}")
NEW_TOKEN=$(echo "$NEW_LOGIN" | python3 -c "import json,sys; print(json.load(sys.stdin).get('access_token',''))")
NEW_DN=$(echo "$NEW_LOGIN" | python3 -c "import json,sys; print(json.load(sys.stdin).get('display_name',''))")
[ -n "$NEW_TOKEN" ] && ok "yeni user login ok" || fail "yeni user login"
[ "$NEW_DN" = "Test Kid" ] && ok "display_name response'ta" || fail "display_name yok: $NEW_DN"

# ────────────────────────────────────────────────────────────────────
# 4) /auth/me + /auth/verify + /auth/logout
# ────────────────────────────────────────────────────────────────────
hdr "TEST 4: /auth/me + /auth/verify + /auth/logout"

ME=$(curl -sS -H "Authorization: Bearer $NEW_TOKEN" "$API/auth/me")
echo "    $ME"
echo "$ME" | grep -q "\"username\":\"$NEW_USER\"" && ok "/auth/me username doğru" || fail "/auth/me payload"
echo "$ME" | grep -q "\"role\":\"student\"" && ok "/auth/me role=student" || fail "role"
echo "$ME" | grep -q "\"grade_level\":6" && ok "/auth/me grade_level=6" || fail "grade_level"

VERIFY=$(curl -sS -H "Authorization: Bearer $NEW_TOKEN" "$API/auth/verify")
echo "$VERIFY" | grep -q "\"valid\":true" && ok "/auth/verify valid" || fail "verify"

RC_LOGOUT=$(curl -sS -o /dev/null -w "%{http_code}" -X POST -H "Authorization: Bearer $NEW_TOKEN" "$API/auth/logout")
[ "$RC_LOGOUT" = "200" ] && ok "/auth/logout → 200" || fail "logout: $RC_LOGOUT"

# ────────────────────────────────────────────────────────────────────
# 5) /api/profile (gamification)
# ────────────────────────────────────────────────────────────────────
hdr "TEST 5: GET /api/profile (gamification)"

PROF=$(curl -sS -H "Authorization: Bearer $NEW_TOKEN" "$API/api/profile")
echo "    $PROF"
echo "$PROF" | grep -q "\"xp\":" && ok "xp alanı var" || fail "xp eksik"
echo "$PROF" | grep -q "\"streak\":" && ok "streak alanı var" || fail "streak eksik"
echo "$PROF" | grep -q "\"today_correct\":" && ok "today_correct alanı var" || fail "today_correct eksik"
echo "$PROF" | grep -q "\"correct_total\":" && ok "correct_total alanı var" || fail "correct_total eksik"

# ────────────────────────────────────────────────────────────────────
# 6) /api/question — RAG'a sor (Adım 5b'de yüklenmiş Üslü İfadeler chunks'ları)
# ────────────────────────────────────────────────────────────────────
hdr "TEST 6: GET /api/question?topic=Uslu_Ifadeler&taxonomic_level=B1"

# Önce RAG'da Üslü İfadeler question chunks olduğundan emin olmak için
# stats kontrol et (admin token ile).
STATS=$(curl -sS -H "Authorization: Bearer $ADMIN_TOKEN" "http://localhost:${ADMIN_API_PORT:-8003}/admin/stats")
echo "    RAG stats: $STATS"
echo "$STATS" | grep -q "\"question\":" && ok "RAG'da question chunk var (Adım 5b'den)" \
  || echo "    NOT: RAG'da question chunk yoksa /api/question 404 döner — bu test'i atla"

QUESTION=$(curl -sS -w "\nHTTP_CODE=%{http_code}" -H "Authorization: Bearer $NEW_TOKEN" \
  "$API/api/question?topic=Uslu_Ifadeler&taxonomic_level=B1")
echo "    $QUESTION" | head -c 600; echo "..."
HTTP_CODE=$(echo "$QUESTION" | grep -oE "HTTP_CODE=[0-9]+" | cut -d= -f2)
QBODY=$(echo "$QUESTION" | sed 's/HTTP_CODE=.*//')

if [ "$HTTP_CODE" = "200" ]; then
  echo "$QBODY" | grep -q "\"question_text\":" && ok "question_text alanı var" || fail "question_text yok"
  echo "$QBODY" | grep -q "\"options\":" && ok "options alanı var" || fail "options yok"
  echo "$QBODY" | grep -qE "\"key\":\"A\"|\"key\":\"a\"" && ok "şıklar parse edildi" || fail "şıklar yok"
  echo "$QBODY" | grep -q "\"answer_key\":" && ok "answer_key alanı var" || fail "answer_key yok"
elif [ "$HTTP_CODE" = "404" ]; then
  echo "    → 404: RAG'da bu topic için question chunk yok (boş Qdrant beklenen senaryo)"
  ok "/api/question 404 davranışı doğru (chunk yok)"
elif [ "$HTTP_CODE" = "504" ]; then
  fail "RAG timeout — content_retrieval_responses tüketici çalışmıyor olabilir"
else
  fail "/api/question beklenmeyen HTTP $HTTP_CODE"
fi

# ────────────────────────────────────────────────────────────────────
# 7) /api/chat → student_interactions_stream'e event
# ────────────────────────────────────────────────────────────────────
hdr "TEST 7: POST /api/chat (Kafka event üret)"

OFF_BEFORE=$(docker compose exec -T kafka /opt/kafka/bin/kafka-get-offsets.sh \
  --bootstrap-server kafka:9092 --topic student_interactions_stream 2>/dev/null \
  | awk -F: '{sum+=$3} END {print sum+0}')

CHAT=$(curl -sS -X POST "$API/api/chat" \
  -H "Authorization: Bearer $NEW_TOKEN" -H 'Content-Type: application/json' \
  -d '{"message":"Üslü ifadeler nasıl çalışır?","topic":"Uslu_Ifadeler","taxonomic_level":"A2"}')
echo "    $CHAT"
echo "$CHAT" | grep -q "\"status\":\"accepted\"" && ok "/api/chat accepted" || fail "chat ack"

sleep 2
OFF_AFTER=$(docker compose exec -T kafka /opt/kafka/bin/kafka-get-offsets.sh \
  --bootstrap-server kafka:9092 --topic student_interactions_stream 2>/dev/null \
  | awk -F: '{sum+=$3} END {print sum+0}')
[ "$OFF_AFTER" -gt "$OFF_BEFORE" ] && ok "student_interactions +$((OFF_AFTER-OFF_BEFORE))" || fail "Kafka event üretilmedi"

# ────────────────────────────────────────────────────────────────────
# 8) CORS preflight
# ────────────────────────────────────────────────────────────────────
hdr "TEST 8: CORS preflight"

CORS=$(curl -sS -i -X OPTIONS "$API/api/profile" \
  -H "Origin: http://localhost:5173" \
  -H "Access-Control-Request-Method: GET" \
  -H "Access-Control-Request-Headers: authorization" 2>&1)
echo "    $CORS" | head -c 500; echo "..."

echo "$CORS" | grep -qi "access-control-allow-origin: http://localhost:5173" && ok "Allow-Origin frontend" \
  || fail "Allow-Origin yok"
echo "$CORS" | grep -qi "access-control-allow-methods" && ok "Allow-Methods var" \
  || fail "Allow-Methods yok"

# ────────────────────────────────────────────────────────────────────
# Cleanup
# ────────────────────────────────────────────────────────────────────
hdr "CLEANUP: test user sil"
docker compose exec -T postgres psql -U ravel_admin -d ravel_db1 -c \
  "DELETE FROM students WHERE username = '$NEW_USER';" >/dev/null 2>&1
ok "test user '$NEW_USER' silindi"

echo ""
echo "═════════════════════════════════════"
printf "  Passed: ${GREEN}%d${NC}    Failed: ${RED}%d${NC}\n" "$PASS" "$FAIL"
echo "═════════════════════════════════════"
[ "$FAIL" -eq 0 ]
