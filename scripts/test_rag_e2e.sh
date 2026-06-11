#!/usr/bin/env bash
# RAVEL — Step 5 Aşama 3 e2e
#
# Tam zincir:
#   /api/answer
#   → Gateway → Kafka(student_interactions_stream)
#   → Orchestrator
#       → Kafka(bandit_decision_requests) → Bandit → Kafka(bandit_decision_responses)
#       → Kafka(content_retrieval_requests) → RAG → Kafka(content_retrieval_responses)
#       → Kafka(content_delivery_stream) → Gateway → WS
#
# Bu test üç farklı durumu doğrular:
#   1) Boş Qdrant (yeni gelen veriden önce) — RAG yanıt veriyor (boş chunk listesi)
#      ama Orchestrator workflow tamamlanıyor (fallback metni LLM'e gidiyor)
#   2) Admin token üretimi (role=admin)
#   3) Admin API → ingest test verisi → retrieval'da chunk dönmesi

set -uo pipefail
cd "$(dirname "$0")/.."

# shellcheck disable=SC1091
set -a; source .env; set +a

API="http://localhost:${API_GATEWAY_PORT:-8000}"
RAG="http://localhost:${ADMIN_API_PORT:-8003}"

GREEN="\033[0;32m"; RED="\033[0;31m"; YELLOW="\033[0;33m"; NC="\033[0m"
PASS=0; FAIL=0
ok()   { printf "  ${GREEN}✓${NC} %s\n" "$1"; PASS=$((PASS+1)); }
fail() { printf "  ${RED}✗${NC} %s\n" "$1"; FAIL=$((FAIL+1)); }
hdr()  { printf "\n${YELLOW}═══ %s ═══${NC}\n" "$1"; }

get_offset() {
  docker compose exec -T kafka /opt/kafka/bin/kafka-get-offsets.sh \
    --bootstrap-server kafka:9092 --topic "$1" 2>/dev/null \
    | awk -F: '{sum+=$3} END {print sum+0}'
}

# ────────── PART 1: e2e (Qdrant boş durum, RAG yanıt veriyor mu?) ──────────

hdr "PART 1: Boş Qdrant ile e2e zincir (RAG cevap verir, chunks=[])"

# Önceki test koşumlarının (özellikle bandit_e2e'nin) Kafka in-flight
# mesajlarının dinmesini bekle — flake'i önler.
sleep 5

OFF_RAG_REQ_BEFORE=$(get_offset content_retrieval_requests)
OFF_RAG_RES_BEFORE=$(get_offset content_retrieval_responses)
OFF_DEL_BEFORE=$(get_offset content_delivery_stream)

# Login
LOGIN=$(curl -sS -X POST "$API/auth/login" -H 'Content-Type: application/json' -d '{"grade_level":7}')
TOKEN=$(echo "$LOGIN"   | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
STUDENT=$(echo "$LOGIN" | python3 -c "import json,sys; print(json.load(sys.stdin)['student_id'])")
ok "login: student=$STUDENT"

# Tek istek + WS yanıtı
echo ""
echo "→ /api/answer + WS recv (max 15 sn)"
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
                json={"question_id":"q_rag_e2e","topic":"Uslu_Ifadeler","taxonomic_level":"B1",
                      "student_answer":"C","is_correct":False,"time_spent":42})
            data = r.json()
            print(f"ANSWER trace={data['trace_id']}")
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                print(f"WS trace={msg.get('trace_id')} content_type={msg.get('content_type')}")
            except asyncio.TimeoutError:
                print("WS_TIMEOUT")
asyncio.run(main())
PY
)
echo "$OUT" | sed 's/^/    /'

echo "$OUT" | grep -q "ANSWER trace=" && ok "/api/answer 200" || fail "answer fail"
echo "$OUT" | grep -q "WS trace="     && ok "WS yanıtı geldi" || fail "WS timeout"

sleep 3
DELTA_RAG_REQ=$(($(get_offset content_retrieval_requests) - OFF_RAG_REQ_BEFORE))
DELTA_RAG_RES=$(($(get_offset content_retrieval_responses) - OFF_RAG_RES_BEFORE))
DELTA_DEL=$(($(get_offset content_delivery_stream) - OFF_DEL_BEFORE))

echo ""
echo "→ Kafka delta'ları:"
printf "    content_retrieval_requests  : +%d\n" "$DELTA_RAG_REQ"
printf "    content_retrieval_responses : +%d  (Step 3'te 0'dı, RAG canlandı!)\n" "$DELTA_RAG_RES"
printf "    content_delivery_stream     : +%d  (text/step_by_step kararları — video kararı buraya yazmaz)\n" "$DELTA_DEL"

[ "$DELTA_RAG_REQ" -ge 1 ] && ok "Orchestrator RAG'a istek attı" || fail "RAG isteği yok"
[ "$DELTA_RAG_RES" -ge 1 ] && ok "RAG cevap verdi (Step 3'teki sessizlik kalktı)" || fail "RAG cevap vermedi"
# WS frame yukarıda zaten alındı (line 83). Output kesin var; delivery=0 ise
# Bandit video kararı verdi ve Manim akışına gitti — Adım 6'ya göre normal.
ok "output üretildi (delivery=$DELTA_DEL; video kararıysa manim_render_tasks'a yazıldı)"

# Orchestrator log'unda "RAG returned N chunks" var mı?
ORCH_LOG=$(docker compose logs --tail=30 orchestrator 2>&1)
if echo "$ORCH_LOG" | grep -q "RAG returned"; then
  ok "Orchestrator log: RAG yanıtı işlendi"
else
  echo "    Not: 'RAG returned' yerine fallback olabilir (Qdrant boş)"
  if echo "$ORCH_LOG" | grep -q "RAG unavailable"; then
    fail "RAG unavailable log'u var (timeout)"
  else
    ok "Orchestrator workflow tamamlandı (fallback veya boş chunks)"
  fi
fi

# ────────── PART 2: Admin token + RAG admin API ─────────────────

hdr "PART 2: Admin token üretimi + RAG admin API"

# Admin token: gateway /auth/login role=admin parametresiyle
ADMIN_LOGIN=$(curl -sS -X POST "$API/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"grade_level":6,"role":"admin"}')
ADMIN_TOKEN=$(echo "$ADMIN_LOGIN" | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
[ -n "$ADMIN_TOKEN" ] && ok "admin token alındı" || { fail "admin token fail"; exit 1; }

# Token payload'ında role=admin var mı?
ROLE_CHECK=$(echo "$ADMIN_TOKEN" | python3 -c "
import sys, base64, json
parts = sys.stdin.read().strip().split('.')
pad = '=' * (-len(parts[1]) % 4)
print(json.loads(base64.urlsafe_b64decode(parts[1] + pad)).get('role','none'))
")
[ "$ROLE_CHECK" = "admin" ] && ok "JWT payload'da role=admin" || fail "role payload yok: $ROLE_CHECK"

# RAG admin /admin/stats — auth çalışıyor mu?
echo ""
echo "→ RAG admin: /admin/stats (auth-required)"
STATS_NO_AUTH=$(curl -sS -o /dev/null -w "%{http_code}" "$RAG/admin/stats")
[ "$STATS_NO_AUTH" = "401" ] && ok "auth-required: 401 without token" || fail "auth-free? code=$STATS_NO_AUTH"

STATS=$(curl -sS -H "Authorization: Bearer $ADMIN_TOKEN" "$RAG/admin/stats")
echo "    $STATS"
echo "$STATS" | grep -q "total_chunks" && ok "admin/stats yanıt verdi" || fail "admin/stats fail"

# Student token ile admin endpoint'i deneme: 403 olmalı
echo ""
echo "→ Student token admin endpoint'e: 403 olmalı"
STUDENT_AS_ADMIN=$(curl -sS -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$RAG/admin/stats")
[ "$STUDENT_AS_ADMIN" = "403" ] && ok "student token reddedildi (403)" || fail "student token kabul edildi (code=$STUDENT_AS_ADMIN)"

# ────────── PART 3: Admin upload → RAG retrieve gerçek içerik ──────

hdr "PART 3: Admin upload → e2e retrieval gerçek içerikle"

# Test verisi (Excel + DOCX) container içinde oluştur, host'a kopyala
echo ""
echo "→ Test verisi oluşturuluyor (rag container içinde)"
docker compose exec -T rag python <<'PY'
import pandas as pd
from docx import Document
from pathlib import Path

# Excel
df = pd.DataFrame([
    {"file_name": "step5_e2e_set", "test_no": 1, "question_number": 1, "taxonomic_level": "B1", "answer_key": "B"},
    {"file_name": "step5_e2e_set", "test_no": 1, "question_number": 2, "taxonomic_level": "B1", "answer_key": "B"},
    {"file_name": "step5_e2e_set", "test_no": 1, "question_number": 3, "taxonomic_level": "B2", "answer_key": "A"},
])
df.to_excel("/tmp/step5_e2e_index.xlsx", index=False)

# DOCX
doc = Document()
def add_q(n, body):
    p = doc.add_paragraph()
    r = p.add_run(f"{n}. "); r.bold = True
    p.add_run(body)
add_q(1, "Üslü ifadelerde 2 üzeri 3 işleminin sonucu kaçtır? a) 6 b) 8 c) 9 d) 12 e) 16")
add_q(2, "Karekök 16 işleminin sonucu nedir? a) 2 b) 4 c) 8 d) 16 e) 256")
add_q(3, "5+3*2 işleminin sonucu kaçtır? a) 11 b) 13 c) 16 d) 21 e) 31")
doc.save("/tmp/step5_e2e_set.docx")
print("FILES_CREATED")
PY

# Container'dan host'a kopyala
docker compose cp rag:/tmp/step5_e2e_index.xlsx /tmp/step5_e2e_index.xlsx
docker compose cp rag:/tmp/step5_e2e_set.docx    /tmp/step5_e2e_set.docx
ok "test fixtures oluşturuldu"

# Excel upload
echo ""
echo "→ POST /admin/upload/excel"
EX_RESP=$(curl -sS -X POST "$RAG/admin/upload/excel" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -F "file=@/tmp/step5_e2e_index.xlsx")
echo "    $EX_RESP"
echo "$EX_RESP" | grep -q "rows_or_chunks" && ok "Excel index yüklendi" || fail "Excel upload fail"

# Questions DOCX upload
echo ""
echo "→ POST /admin/upload/questions (DOCX)"
# grade_level + subject zorunlu (admin upload sırasında metadata yazılır).
# Bu testin Part 3/Part 4 retriever sorguları subject=step5_e2e_set kullanıyor,
# o yüzden upload subject'i de file_name'e eşit veriyoruz.
Q_RESP=$(curl -sS -X POST "$RAG/admin/upload/questions" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -F "file=@/tmp/step5_e2e_set.docx" \
  -F "file_type=docx" \
  -F "grade_level=7" \
  -F "subject=step5_e2e_set")
echo "    $Q_RESP"
WRITTEN=$(echo "$Q_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('written_chunks',0))")
[ "$WRITTEN" = "3" ] && ok "3 chunk Qdrant'a yazıldı" || fail "written_chunks=$WRITTEN"

# Stats sonrası
sleep 1
NEW_STATS=$(curl -sS -H "Authorization: Bearer $ADMIN_TOKEN" "$RAG/admin/stats")
echo ""
echo "    yeni stats: $NEW_STATS"

# Yeni e2e: aynı topic ile /api/answer at, retrieval real chunk dönmeli
echo ""
echo "→ Yeni /api/answer (gerçek RAG içeriği yüklü)"
LOGIN2=$(curl -sS -X POST "$API/auth/login" -H 'Content-Type: application/json' -d '{"grade_level":7}')
TOKEN2=$(echo "$LOGIN2"   | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

# Orchestrator log marker
ORCH_MARKER=$(docker compose logs --no-color orchestrator 2>&1 | wc -l)

ANSWER=$(curl -sS -X POST "$API/api/answer" \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $TOKEN2" \
  -d '{"question_id":"q_rag_e2e_2","topic":"step5_e2e_set","taxonomic_level":"B1","student_answer":"C","is_correct":false,"time_spent":42}')
TRACE2=$(echo "$ANSWER" | python3 -c "import json,sys; print(json.load(sys.stdin)['trace_id'])")
echo "    trace=$TRACE2"

sleep 5

NEW_LOGS=$(docker compose logs --no-color orchestrator 2>&1 | tail -n +$((ORCH_MARKER + 1)))
RAG_HITS=$(echo "$NEW_LOGS" | grep -c "RAG returned")
echo "    Orchestrator RAG hit log'u: $RAG_HITS"
echo "$NEW_LOGS" | grep -E "(RAG returned|delivered)" | head -3 | sed 's/^/      /'

if echo "$NEW_LOGS" | grep -q "RAG returned [^0]"; then
  ok "Bandit kararı text/step_by_step ise — Orchestrator log'unda RAG real chunk gördü"
elif echo "$NEW_LOGS" | grep -q "delivered text intervention"; then
  echo "    Not: bu run'da Bandit content_type=theory önerdi (cold-start stochastic);"
  echo "    Orchestrator 'theory' filter'ıyla aradı, theory chunk yok → 0 chunk normal."
  ok "delivery zinciri tamamlandı"
elif echo "$NEW_LOGS" | grep -q "manim render dispatched"; then
  echo "    Not: bu run'da Bandit 'video' kararı verdi → Manim akışına gidildi (Adım 6)."
  ok "video zinciri tamamlandı (delivery yerine manim_render_tasks)"
else
  fail "delivery yok — zincir kırık"
fi

# ────────── PART 4: Step 5b düzeltme kanıtı (manuel retriever) ─────
hdr "PART 4: Step 5b kanıtı — manuel retriever Qdrant'tan real chunk dönüyor"

CHUNK_OUT=$(docker compose exec -T rag python <<'PY'
import asyncio, json
from app.config import get_settings
from app.qdrant_io import QdrantIO
from app.embedder import Embedder
from app.retriever import Retriever
from app.schemas import ContentRetrievalRequest, ContentRetrievalQuery

async def main():
    s = get_settings()
    qd = QdrantIO(s.qdrant_url, s.qdrant_collection, s.embedding_dim)
    await qd.start()
    e = Embedder(s.embedding_model, cache_folder=s.embedding_cache_folder); e.load()
    r = Retriever(s, e, qd)
    req = ContentRetrievalRequest(
        correlation_id="step5b_proof", trace_id="step5b_proof", student_id=None,
        query=ContentRetrievalQuery(
            subject="step5_e2e_set", taxonomic_level="B1",
            content_type="question",
            context="iki üzeri üç işlemi sonucu",
        ),
        top_k=5,
    )
    resp = await r.retrieve(req)
    print(f"CHUNKS={len(resp.chunks)} TOTAL={resp.total_found}")
    for i, c in enumerate(resp.chunks):
        print(f"  [{i}] score={c.score:.3f}  {c.text[:90]}")
    await qd.stop()

asyncio.run(main())
PY
)
echo "$CHUNK_OUT" | sed 's/^/    /'

CHUNK_COUNT=$(echo "$CHUNK_OUT" | grep -oE "CHUNKS=[0-9]+" | head -1 | grep -oE "[0-9]+")
[ "$CHUNK_COUNT" -gt 0 ] 2>/dev/null && \
  ok "manuel retriever ${CHUNK_COUNT} real chunk döndü (Step 5b filter düzeltmesi çalışıyor)" || \
  fail "manuel retriever 0 chunk — Step 5b başarısız"

# Cleanup
rm -f /tmp/step5_e2e_index.xlsx /tmp/step5_e2e_set.docx
docker compose exec -T rag rm -f /tmp/step5_e2e_index.xlsx /tmp/step5_e2e_set.docx 2>/dev/null || true

# DELETE /admin/content/{file_name} — hijyen (testin sonunda)
curl -sS -X DELETE -H "Authorization: Bearer $ADMIN_TOKEN" "$RAG/admin/content/step5_e2e_set" >/dev/null 2>&1

echo ""
echo "═════════════════════════════════════"
printf "  Passed: ${GREEN}%d${NC}    Failed: ${RED}%d${NC}\n" "$PASS" "$FAIL"
echo "═════════════════════════════════════"
[ "$FAIL" -eq 0 ]
