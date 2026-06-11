#!/usr/bin/env bash
# RAVEL — Tam uçtan uca test (gerçek LLM ile, production-grade).
#
# Akış:
#   1. Admin login → JWT (LLM_MOCK_MODE=false varsayımı, gerçek key yapılandırılmış)
#   2. RAG'da minimum içerik var mı kontrol — yoksa Excel + DOCX yükle (test fixture)
#   3. Öğrenci kaydet + login
#   4. WS bağlan (öğrenci)
#   5. Konu anlatımı (question_id="intro") → text_explanation/step_by_step
#   6. 3 farklı soru çek (asked-set ile tekrar etmemeli)
#   7. Soruyu yanlış cevapla (is_correct=false) → WS'ten error_explanation
#   8. explicit_video_request=true → WS'ten video URL veya text fallback
#
# Ön koşullar:
#   - docker compose up -d (tüm servisler healthy)
#   - .env içinde LLM_MOCK_MODE=false
#   - Admin paneli üzerinden orchestrator_text + orchestrator_manim için
#     gerçek API key + model konfigüre edilmiş olmalı
#
# Çalıştır: bash scripts/test_e2e_full.sh

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
RAG="http://localhost:${RAG_PORT:-8003}"

echo ""
echo "═══ RAVEL Tam Uçtan Uca Test (Gerçek LLM) ═══"

# Servisler healthy mi
hdr "PRECHECK: Container'lar healthy"
for svc in api_gateway orchestrator bandit rag manim_worker postgres kafka qdrant redis; do
  H=$(docker inspect -f '{{.State.Health.Status}}' "ravel_$svc" 2>/dev/null || echo "missing")
  if [ "$H" = "healthy" ] || [ "$H" = "running" ] || \
     ([ "$svc" = "qdrant" ] && docker ps --format '{{.Names}}' | grep -q "^ravel_qdrant$"); then
    ok "ravel_$svc: $H"
  else
    fail "ravel_$svc: $H"
  fi
done

# ────────────────────────────────────────────────────────────────────
# 1) Admin login (.env LLM_MOCK_MODE'u kontrol et)
# ────────────────────────────────────────────────────────────────────
hdr "1) Admin login + LLM_MOCK_MODE kontrolü"

ADMIN_LOGIN=$(curl -sS -X POST "$API/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"ravel_admin_2025"}')
ADMIN_TOKEN=$(echo "$ADMIN_LOGIN" | python3 -c "import json,sys;print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || echo "")
if [ -n "$ADMIN_TOKEN" ]; then
  ok "Admin login başarılı"
else
  fail "Admin login fail: $ADMIN_LOGIN"
  echo ""
  echo "═════════════════════════════════════"
  printf "  Passed: ${GREEN}%d${NC}    Failed: ${RED}%d${NC}\n" "$PASS" "$FAIL"
  echo "═════════════════════════════════════"
  exit 1
fi

ORCH_MOCK=$(docker compose exec -T orchestrator env 2>/dev/null | grep -E "^LLM_MOCK_MODE=" | cut -d= -f2 || echo "")
echo "    Orchestrator LLM_MOCK_MODE=$ORCH_MOCK"
if [ "$ORCH_MOCK" = "false" ]; then
  ok "LLM_MOCK_MODE=false (gerçek LLM kullanılıyor)"
else
  fail "LLM_MOCK_MODE=$ORCH_MOCK — bu test gerçek LLM ile koşmalı"
  echo "    .env'i düzelt: LLM_MOCK_MODE=false  →  docker compose restart orchestrator"
fi

# Orchestrator için en azından orchestrator_text agent'ı yapılandırılmış mı?
LLM_CFGS=$(curl -sS -H "Authorization: Bearer $ADMIN_TOKEN" "$RAG/admin/llm/configs" 2>/dev/null || echo "")
HAS_TEXT=$(echo "$LLM_CFGS" | python3 -c "
import json,sys
try:
  d = json.load(sys.stdin)
  print(any(c.get('agent_name')=='orchestrator_text' and c.get('api_key_set') and c.get('is_active') for c in d.get('configs',[])))
except: print(False)" 2>/dev/null)
if [ "$HAS_TEXT" = "True" ]; then
  ok "orchestrator_text LLM config aktif (api_key_set=true)"
else
  fail "orchestrator_text LLM config yok/inaktif — admin panelinden yapılandır"
fi

# ────────────────────────────────────────────────────────────────────
# 2) Fixture yükle (test deterministik olsun: e2efull_uslu topic'i altında
#    4 üslü-ifade sorusu garantile)
# ────────────────────────────────────────────────────────────────────
hdr "2) Fixture yükle (e2efull_uslu topic'inde 4 soru)"

TEST_TOPIC="e2efull_uslu"
TEST_GRADE=7

# DOCX dosyasının file path stem'i parser tarafından file_name olarak
# kullanılır (Path.stem). Bu yüzden Excel file_name kolonu DOCX dosya
# adıyla aynı olmalı; aksi halde parser excel_meta.get((file_name, qnum))
# eşleşemez → answer_key + taxonomic_level kaybı + bazı chunk'lar atlanabilir.
# Bu test'te DOCX = "e2efull_set.docx" → stem "e2efull_set"
docker compose exec -T rag python - <<PY >/dev/null 2>&1
import openpyxl
wb = openpyxl.Workbook(); ws = wb.active
ws.append(["file_name","test_no","question_number","taxonomic_level","answer_key"])
for n, ans in [(1,"B"),(2,"C"),(3,"A"),(4,"D")]:
    ws.append(["e2efull_set", 1, n, "B1", ans])
wb.save("/tmp/e2efull_index.xlsx")
from docx import Document
d = Document()
qs = [
    (1, "Üslü ifadelerde 2^3 işleminin sonucu kaçtır? a) 6 b) 8 c) 9 d) 12 e) 16"),
    (2, "3^2 + 4^2 işleminin sonucu kaçtır? a) 12 b) 14 c) 25 d) 49 e) 7"),
    (3, "5^3 işleminin sonucu nedir? a) 125 b) 25 c) 75 d) 15 e) 100"),
    (4, "10^2 - 3^2 kaçtır? a) 91 b) 81 c) 100 d) 109 e) 49"),
]
for n, body in qs:
    p = d.add_paragraph(); r = p.add_run(f"{n}."); r.bold = True
    p.add_run(f" {body}")
d.save("/tmp/e2efull_set.docx")
PY

docker cp ravel_rag:/tmp/e2efull_index.xlsx /tmp/e2efull_index.xlsx >/dev/null 2>&1
docker cp ravel_rag:/tmp/e2efull_set.docx   /tmp/e2efull_set.docx   >/dev/null 2>&1
if [ ! -s /tmp/e2efull_index.xlsx ] || [ ! -s /tmp/e2efull_set.docx ]; then
  fail "fixture dosyaları üretilemedi"
else
  ok "fixture dosyaları üretildi"
fi

EX_RESP=$(curl -sS -X POST "$RAG/admin/upload/excel" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -F "file=@/tmp/e2efull_index.xlsx")
EX_ROWS=$(echo "$EX_RESP" | python3 -c "import json,sys;print(json.load(sys.stdin).get('rows_or_chunks',0))" 2>/dev/null || echo 0)
if [ "$EX_ROWS" -ge 4 ]; then
  ok "Excel index yüklendi ($EX_ROWS satır)"
else
  fail "Excel upload başarısız: $EX_RESP"
fi

Q_RESP=$(curl -sS -X POST "$RAG/admin/upload/questions" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -F "file=@/tmp/e2efull_set.docx" \
  -F "file_type=docx" \
  -F "grade_level=${TEST_GRADE}" \
  -F "subject=${TEST_TOPIC}")
WRITTEN=$(echo "$Q_RESP" | python3 -c "import json,sys;print(json.load(sys.stdin).get('written_chunks',0))" 2>/dev/null || echo 0)
if [ "$WRITTEN" -ge 3 ]; then
  ok "fixture chunk'ları Qdrant'ta: $WRITTEN"
else
  fail "fixture upload başarısız: $Q_RESP"
fi
rm -f /tmp/e2efull_index.xlsx /tmp/e2efull_set.docx

# Asked-set'i temizle ki test deterministik başlasın (önceki çalıştırmaların
# kalıntısı olmasın)
docker compose exec -T redis redis-cli --scan --pattern "asked:*:${TEST_TOPIC}" 2>/dev/null \
  | xargs -r docker compose exec -T redis redis-cli del >/dev/null 2>&1 || true

# ────────────────────────────────────────────────────────────────────
# 3) Öğrenci login (cold-start)
# ────────────────────────────────────────────────────────────────────
hdr "3) Öğrenci login (cold-start)"

STU_LOGIN=$(curl -sS -X POST "$API/auth/login" -H 'Content-Type: application/json' -d "{\"grade_level\":${TEST_GRADE}}")
STU_TOKEN=$(echo "$STU_LOGIN" | python3 -c "import json,sys;print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || echo "")
STUDENT=$(echo "$STU_LOGIN" | python3 -c "import json,sys;print(json.load(sys.stdin).get('student_id',''))" 2>/dev/null || echo "")
if [ -n "$STU_TOKEN" ] && [ -n "$STUDENT" ]; then
  ok "Öğrenci hazır: student_id=$STUDENT"
else
  fail "Öğrenci login fail: $STU_LOGIN"; exit 1
fi

# ────────────────────────────────────────────────────────────────────
# 4) Senaryo A: Konu anlatımı (question_id="intro") → text_explanation
# ────────────────────────────────────────────────────────────────────
hdr "4) Senaryo A — Konu Anlatımı (intro) gerçek LLM yanıtı"

INTRO_OUT=$(docker compose exec -T api_gateway python <<PY
import asyncio, json
import httpx
from websockets import connect

API = "http://localhost:8000"
TOKEN = "$STU_TOKEN"
STUDENT = "$STUDENT"
TOPIC = "$TEST_TOPIC"

async def main():
    uri = f"ws://localhost:8000/ws/{STUDENT}?token={TOKEN}"
    async with connect(uri) as ws:
        print("WS_CONNECTED")
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{API}/api/answer",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "question_id": "intro",
                    "topic": TOPIC,
                    "taxonomic_level": "A1",
                    "student_answer": "",
                    "is_correct": False,
                    "time_spent": 0,
                    "explicit_video_request": False,
                },
            )
            r.raise_for_status()
            sent = r.json()["trace_id"]
            print(f"ANSWER_OK trace={sent}")
        try:
            deadline = asyncio.get_event_loop().time() + 60
            while asyncio.get_event_loop().time() < deadline:
                msg = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - asyncio.get_event_loop().time()))
                payload = json.loads(msg)
                tid = payload.get("trace_id")
                ct = payload.get("content_type")
                body_len = len(payload.get("body_html") or "")
                print(f"FRAME ct={ct} trace={tid} body_len={body_len}")
                if tid == sent and ct in ("text_explanation","step_by_step"):
                    snippet = (payload.get("body_html") or "")[:140].replace("\n"," ")
                    print(f"INTRO_OK body_snippet={snippet}")
                    return
        except asyncio.TimeoutError:
            pass
        print("INTRO_TIMEOUT")

asyncio.run(main())
PY
)
echo "$INTRO_OUT" | sed 's/^/    /'
echo "$INTRO_OUT" | grep -q "WS_CONNECTED"  && ok "WebSocket bağlandı"        || fail "WS bağlantısı"
echo "$INTRO_OUT" | grep -q "ANSWER_OK"     && ok "/api/answer (intro) 200"   || fail "intro answer"
if echo "$INTRO_OUT" | grep -q "INTRO_OK"; then
  ok "Konu anlatımı LLM yanıtı geldi (text_explanation/step_by_step)"
else
  fail "Konu anlatımı yanıtı 60 sn içinde gelmedi"
fi

# ────────────────────────────────────────────────────────────────────
# 5) Senaryo B: 3 ardışık /api/question — farklı question_id'ler
# ────────────────────────────────────────────────────────────────────
hdr "5) Senaryo B — 3 ardışık soru çekimi (tekrar etmemeli)"

QIDS=""
FIRST_QID=""
FIRST_AK=""
FIRST_TEXT=""
FIRST_HAS_TEXT="0"
for i in 1 2 3; do
  Q=$(curl -sS -H "Authorization: Bearer $STU_TOKEN" \
    "$API/api/question?topic=${TEST_TOPIC}&taxonomic_level=A1")
  QID=$(echo "$Q" | python3 -c "import json,sys;print(json.load(sys.stdin).get('question_id',''))" 2>/dev/null || echo "")
  AK=$(echo "$Q"  | python3 -c "import json,sys;print(json.load(sys.stdin).get('answer_key','') or '')" 2>/dev/null || echo "")
  HAS_TEXT=$(echo "$Q" | python3 -c "import json,sys;print(1 if (json.load(sys.stdin).get('question_text') or '').strip() else 0)" 2>/dev/null || echo "0")
  echo "    [#$i] qid=$QID ak=$AK has_text=$HAS_TEXT"
  QIDS="${QIDS}${QID}"$'\n'
  if [ "$i" = "1" ]; then
    FIRST_QID="$QID"; FIRST_AK="$AK"; FIRST_HAS_TEXT="$HAS_TEXT"
    FIRST_TEXT=$(echo "$Q" | python3 -c "import json,sys;print(json.load(sys.stdin).get('question_text','') or '')" 2>/dev/null || echo "")
  fi
done

UNIQ=$(printf "%s" "$QIDS" | sort -u | grep -c . || true)
if [ "$UNIQ" -ge 2 ]; then
  ok "Sorular çeşitlendi (uniq=$UNIQ/3)"
else
  fail "3 ardışık çağrıda farklı question_id gelmedi (uniq=$UNIQ)"
fi

# Geçerli question_text + question_id
if [ -n "$FIRST_QID" ] && [ "$FIRST_HAS_TEXT" = "1" ]; then
  ok "İlk soru question_text + question_id dolu"
else
  fail "İlk soru eksik field (qid='$FIRST_QID' has_text=$FIRST_HAS_TEXT)"
fi

# ────────────────────────────────────────────────────────────────────
# 5b) Senaryo B+: asked-set tüketimi → exhausted=true → DELETE → reset
# ────────────────────────────────────────────────────────────────────
hdr "5b) Senaryo B+ — asked-set tüketimi (exhausted) + DELETE reset"

# RAG retriever rerank_top_n limit'i nedeniyle aslında dönen unique chunk
# sayısı fixture'daki soru sayısından daha az olabilir. Bu yüzden 4. çağrı
# ya yeni soru (RAG limit yetiyorsa) ya exhausted (limit dolduysa) — ikisi
# de geçerli. 5. çağrı asked-set tükendiğinde kesinlikle exhausted olmalı.
Q4=$(curl -sS -H "Authorization: Bearer $STU_TOKEN" \
  "$API/api/question?topic=${TEST_TOPIC}&taxonomic_level=A1")
EX4=$(echo "$Q4" | python3 -c "import json,sys;print(json.load(sys.stdin).get('exhausted', False))" 2>/dev/null || echo False)
QID4=$(echo "$Q4" | python3 -c "import json,sys;print(json.load(sys.stdin).get('question_id',''))" 2>/dev/null || echo "")
if [ "$EX4" = "False" ] && [ -n "$QID4" ]; then
  ok "4. soru: yeni soru geldi (qid=$QID4)"
elif [ "$EX4" = "True" ]; then
  ok "4. soru: RAG retriever limit'ine ulaşıldı, exhausted (Senaryo B'de 3 unique tüketildi)"
else
  fail "4. soru beklenmedik: exhausted=$EX4 qid=$QID4"
fi

# Sonuncu çağrı — asked-set kesinlikle dolu olmalı, exhausted bekleniyor
Q5=$(curl -sS -H "Authorization: Bearer $STU_TOKEN" \
  "$API/api/question?topic=${TEST_TOPIC}&taxonomic_level=A1")
EX5=$(echo "$Q5" | python3 -c "import json,sys;print(json.load(sys.stdin).get('exhausted', False))" 2>/dev/null || echo False)
TOTAL5=$(echo "$Q5" | python3 -c "import json,sys;print(json.load(sys.stdin).get('total_asked', 0))" 2>/dev/null || echo 0)
MSG5=$(echo "$Q5" | python3 -c "import json,sys;print(json.load(sys.stdin).get('message',''))" 2>/dev/null || echo "")
if [ "$EX5" = "True" ]; then
  ok "Sonraki çağrı exhausted=true (total_asked=$TOTAL5, message='$MSG5')"
else
  fail "Sonraki çağrı exhausted=false beklenmedik: $Q5"
fi

# DELETE ile asked-set'i sıfırla
DEL_RESP=$(curl -sS -X DELETE -H "Authorization: Bearer $STU_TOKEN" \
  "$API/api/question/asked?topic=${TEST_TOPIC}")
DEL_STATUS=$(echo "$DEL_RESP" | python3 -c "import json,sys;print(json.load(sys.stdin).get('status',''))" 2>/dev/null || echo "")
if [ "$DEL_STATUS" = "cleared" ]; then
  ok "DELETE /api/question/asked → cleared"
else
  fail "DELETE response beklenmedik: $DEL_RESP"
fi

# Reset sonrası tekrar soru gelmeli
Q6=$(curl -sS -H "Authorization: Bearer $STU_TOKEN" \
  "$API/api/question?topic=${TEST_TOPIC}&taxonomic_level=A1")
EX6=$(echo "$Q6" | python3 -c "import json,sys;print(json.load(sys.stdin).get('exhausted', False))" 2>/dev/null || echo False)
QID6=$(echo "$Q6" | python3 -c "import json,sys;print(json.load(sys.stdin).get('question_id',''))" 2>/dev/null || echo "")
if [ "$EX6" = "False" ] && [ -n "$QID6" ]; then
  ok "Reset sonrası soru geldi (qid=$QID6)"
else
  fail "Reset sonrası exhausted hâlâ true: $Q6"
fi

# ────────────────────────────────────────────────────────────────────
# 6) Senaryo C: Yanlış cevap → WS error_explanation
# ────────────────────────────────────────────────────────────────────
hdr "6) Senaryo C — Yanlış cevap → gerçek LLM açıklaması"

# İlk soruyu yanlış cevapla (answer_key dışı bir şık seç).
# Düzeltme 1: question_text + correct_answer da yolla — LLM hangi soruyla
# uğraştığını bilsin.
TARGET_QID="${FIRST_QID:-q_unknown}"
RIGHT_KEY="${FIRST_AK:-A}"
if [ "$RIGHT_KEY" = "A" ]; then WRONG="B"; else WRONG="A"; fi

WRONG_OUT=$(STU_TOKEN="$STU_TOKEN" STUDENT="$STUDENT" TARGET_QID="$TARGET_QID" \
            TEST_TOPIC="$TEST_TOPIC" WRONG="$WRONG" RIGHT_KEY="$RIGHT_KEY" \
            FIRST_TEXT="$FIRST_TEXT" \
            docker compose exec -T \
              -e STU_TOKEN -e STUDENT -e TARGET_QID -e TEST_TOPIC \
              -e WRONG -e RIGHT_KEY -e FIRST_TEXT \
              api_gateway python <<'PY'
import asyncio, json, os
import httpx
from websockets import connect

API = "http://localhost:8000"
TOKEN = os.environ["STU_TOKEN"]; STUDENT = os.environ["STUDENT"]
QID = os.environ["TARGET_QID"]; TOPIC = os.environ["TEST_TOPIC"]
WRONG = os.environ["WRONG"]
RIGHT = os.environ["RIGHT_KEY"]
QTEXT = os.environ.get("FIRST_TEXT","")

async def main():
    uri = f"ws://localhost:8000/ws/{STUDENT}?token={TOKEN}"
    async with connect(uri) as ws:
        print("WS_CONNECTED")
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{API}/api/answer",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "question_id": QID, "topic": TOPIC,
                    "taxonomic_level": "A1",
                    "student_answer": WRONG,
                    "is_correct": False, "time_spent": 12,
                    "explicit_video_request": False,
                    "question_text": QTEXT,
                    "correct_answer": RIGHT,
                },
            )
            r.raise_for_status()
            sent = r.json()["trace_id"]
            print(f"ANSWER_OK trace={sent}")
        try:
            deadline = asyncio.get_event_loop().time() + 90
            while asyncio.get_event_loop().time() < deadline:
                msg = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - asyncio.get_event_loop().time()))
                payload = json.loads(msg)
                tid = payload.get("trace_id"); ct = payload.get("content_type")
                body = (payload.get("body_html") or "")
                print(f"FRAME ct={ct} trace={tid} len={len(body)}")
                if tid == sent and ct in ("text_explanation","step_by_step"):
                    snippet = body[:160].replace(chr(10),' ')
                    print(f"EXPLAIN_OK snippet={snippet}")
                    # Bağlam doğrulaması: LLM soruyu biliyorsa açıklamada üslü
                    # ifadelerle ilgili anahtar kelimeler geçmeli
                    # LLM bağlam farkındalığı: üslü-ifade konusuyla ilgili
                    # herhangi bir anahtar kelime / sembol açıklamada geçmeli.
                    bl = body.lower()
                    relevant = any(k in bl for k in ["üs","kuvvet","üzeri","üze "]) or \
                               any(k in body for k in ["^", "²", "³"])
                    print(f"CONTEXT_AWARE={'1' if relevant else '0'}")
                    return
        except asyncio.TimeoutError:
            pass
        print("EXPLAIN_TIMEOUT")

asyncio.run(main())
PY
)
echo "$WRONG_OUT" | sed 's/^/    /'
echo "$WRONG_OUT" | grep -q "ANSWER_OK"   && ok "/api/answer (wrong) 200"          || fail "wrong answer POST"
if echo "$WRONG_OUT" | grep -q "EXPLAIN_OK"; then
  ok "Yanlış cevaba gerçek LLM açıklaması geldi"
else
  fail "Açıklama 90 sn içinde gelmedi"
fi
if echo "$WRONG_OUT" | grep -q "CONTEXT_AWARE=1"; then
  ok "LLM açıklaması soru bağlamını kullandı (üslü ifadeler anahtar kelime)"
else
  fail "LLM açıklaması soruyla alakasız (Düzeltme 1 eksik)"
fi

# ────────────────────────────────────────────────────────────────────
# 7) Senaryo D: explicit_video_request → video URL veya text fallback
# ────────────────────────────────────────────────────────────────────
hdr "7) Senaryo D — Video isteği (explicit_video_request=true)"

VIDEO_OUT=$(docker compose exec -T api_gateway python <<PY
import asyncio, json
import httpx
from websockets import connect

API = "http://localhost:8000"
TOKEN = "$STU_TOKEN"; STUDENT = "$STUDENT"; TOPIC = "$TEST_TOPIC"

async def main():
    uri = f"ws://localhost:8000/ws/{STUDENT}?token={TOKEN}"
    async with connect(uri) as ws:
        print("WS_CONNECTED")
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                f"{API}/api/answer",
                headers={"Authorization": f"Bearer {TOKEN}"},
                json={
                    "question_id": "intro", "topic": TOPIC,
                    "taxonomic_level": "A1",
                    "student_answer": "",
                    "is_correct": False, "time_spent": 0,
                    "explicit_video_request": True,
                },
            )
            r.raise_for_status()
            sent = r.json()["trace_id"]
            print(f"ANSWER_OK trace={sent}")
        # Video render+QA loop'u uzun sürer (60-180 sn). Hem video hem
        # text fallback (DLQ sonrası) kabul edilir.
        try:
            deadline = asyncio.get_event_loop().time() + 180
            video_seen = False
            text_seen = False
            while asyncio.get_event_loop().time() < deadline:
                msg = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - asyncio.get_event_loop().time()))
                payload = json.loads(msg)
                tid = payload.get("trace_id"); ct = payload.get("content_type")
                print(f"FRAME ct={ct} trace={tid}")
                if tid != sent:
                    continue
                if ct == "video":
                    print(f"VIDEO_OK url={payload.get('video_url','')[:80]}")
                    return
                if ct in ("text_explanation","step_by_step","system_message"):
                    text_seen = True
                    print(f"TEXT_FALLBACK snippet={(payload.get('body_html') or '')[:80]}")
                    # text + sonradan video da gelebilir; biraz daha bekle
                    await asyncio.sleep(0.1)
        except asyncio.TimeoutError:
            pass
        if text_seen:
            print("VIDEO_TEXT_FALLBACK_OK")
        else:
            print("VIDEO_NONE")

asyncio.run(main())
PY
)
echo "$VIDEO_OUT" | sed 's/^/    /'
if echo "$VIDEO_OUT" | grep -q "VIDEO_OK"; then
  ok "Video URL'si geldi (Manim render başarılı)"
elif echo "$VIDEO_OUT" | grep -q "VIDEO_TEXT_FALLBACK_OK"; then
  ok "Video render fail oldu — text fallback geldi (graceful degradation OK)"
else
  fail "Ne video ne fallback metin — 180 sn timeout"
fi

# ────────────────────────────────────────────────────────────────────
# Cleanup: asked-set + opsiyonel fixture chunk'ları
# ────────────────────────────────────────────────────────────────────
hdr "Cleanup"

docker compose exec -T redis redis-cli --scan --pattern "asked:*:${TEST_TOPIC}" 2>/dev/null \
  | xargs -r docker compose exec -T redis redis-cli del >/dev/null 2>&1 || true
ok "asked-set temizlendi"

# ────────────────────────────────────────────────────────────────────
echo ""
echo "═════════════════════════════════════"
printf "  Passed: ${GREEN}%d${NC}    Failed: ${RED}%d${NC}\n" "$PASS" "$FAIL"
echo "═════════════════════════════════════"
[ "$FAIL" -eq 0 ]
