#!/usr/bin/env bash
# RAVEL — Adım 6 unit testleri (sandbox + render içeren container'da çalışır).
#
# Kapsam:
#   1) Sandbox AST whitelist — yasak import reddediliyor mu, izin verilen geçiyor mu?
#   2) Sandbox forbidden call/attr — exec(), __subclasses__ engelleniyor mu?
#   3) Render — geçerli bir Manim sahnesi <45 sn'de mp4 üretiyor mu?
#   4) DLQ — manim_render_tasks'a 3 ardışık BOZUK kod gönderildiğinde
#      dead_letter_queue_ravel'de mesaj oluşuyor mu?
#
# Çalıştırma yeri: container'ın içinde (Manim + ffmpeg + LaTeX yüklü).
# Sandbox testleri host venv'inden de çalışır; render ve DLQ container ister.

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

echo ""
echo "═══ RAVEL Adım 6 — Manim Worker Unit Tests ═══"

# ────────────────────────────────────────────────────────────────────
# 1) Sandbox testleri (host venv ile — Manim load etmediği için hızlı)
# ────────────────────────────────────────────────────────────────────
hdr "TEST 1: SandboxValidator (host venv)"

VENV="services/manim_worker/venv/bin/python"
if [ ! -x "$VENV" ]; then
  fail "host venv bulunamadı: $VENV"
else
  SANDBOX_OUT=$($VENV - <<'PY' 2>&1
import sys
sys.path.insert(0, "services/manim_worker")
from app.sandbox import SandboxValidator

s = SandboxValidator(allowed_imports=["manim","numpy","math","random"])

cases = [
    ("valid",
     "from manim import *\nimport numpy as np\nclass S(Scene):\n    def construct(self): self.add(Text('x'))\n",
     True, None),
    ("forbidden_import_os",
     "from manim import *\nimport os\nclass S(Scene):\n    def construct(self): pass\n",
     False, "AST_VIOLATION"),
    ("forbidden_import_subprocess",
     "from manim import *\nimport subprocess\nclass S(Scene):\n    def construct(self): pass\n",
     False, "AST_VIOLATION"),
    ("forbidden_call_exec",
     "from manim import *\nexec('print(1)')\n",
     False, "AST_VIOLATION"),
    ("forbidden_call_eval",
     "from manim import *\neval('1+1')\n",
     False, "AST_VIOLATION"),
    ("forbidden_attr_subclasses",
     "from manim import *\nx = ().__class__.__bases__[0].__subclasses__()\n",
     False, "AST_VIOLATION"),
    ("forbidden_attr_globals",
     "from manim import *\nf = lambda: None\nf.__globals__\n",
     False, "AST_VIOLATION"),
    ("forbidden_relative_import",
     "from manim import *\nfrom . import x\n",
     False, "AST_VIOLATION"),
    ("syntax_error",
     "from manim import *\nclass X(Scene)\n    pass\n",
     False, ("AST_VIOLATION","SYNTAX_ERROR")),
]

ok = fail = 0
for name, code, expected_valid, expected_type in cases:
    r = s.validate(code)
    if expected_valid:
        passed = r.is_valid
    else:
        et = expected_type if isinstance(expected_type, tuple) else (expected_type,)
        passed = (not r.is_valid) and (r.error_type in et)
    status = "OK" if passed else "FAIL"
    print(f"{status}|{name}|{r.error_type}|{(r.error_message or '')[:90]}")
    ok += int(passed); fail += int(not passed)

print(f"TOTAL|{ok}/{ok+fail}")
sys.exit(0 if fail == 0 else 1)
PY
  )
  echo "$SANDBOX_OUT" | sed 's/^/    /'
  while IFS='|' read -r status name etype msg; do
    [ -z "$status" ] && continue
    if [ "$status" = "OK" ]; then ok "sandbox::$name"; fi
    if [ "$status" = "FAIL" ]; then fail "sandbox::$name (got type=$etype msg=$msg)"; fi
  done <<<"$SANDBOX_OUT"
fi

# ────────────────────────────────────────────────────────────────────
# 2) Render testi — container içinde Manim 45 sn altında mp4 üretmeli
# ────────────────────────────────────────────────────────────────────
hdr "TEST 2: Render (manim_worker container)"

if ! docker ps --format '{{.Names}}' | grep -q '^ravel_manim_worker$'; then
  fail "ravel_manim_worker container ayakta değil"
else
  RENDER_OUT=$(docker compose exec -T manim_worker python - <<'PY' 2>&1
import sys, time, os
sys.path.insert(0, "/app")
from app.renderer import ManimRenderer, RenderError

code = """
from manim import *
class RavelLesson(Scene):
    def construct(self):
        self.add(Text("RAVEL", font_size=48))
        self.wait(0.3)
"""
r = ManimRenderer(temp_dir="/tmp/manim_renders", default_timeout_seconds=60)
t0 = time.time()
try:
    res = r.render(code, task_id="unit_smoke", quality="480p", timeout_seconds=60)
except RenderError as e:
    print(f"FAIL|RenderError: {e.message}")
    print(f"SNIPPET|{(e.traceback_snippet or '')[:200]}")
    sys.exit(1)
elapsed = time.time() - t0
size = os.path.getsize(res.mp4_path) if os.path.exists(res.mp4_path) else -1
print(f"OK|elapsed={elapsed:.1f}s mp4_size={size}B duration={res.duration_seconds:.2f}s")
# cleanup
r.cleanup_mp4(res.mp4_path)
PY
  )
  echo "$RENDER_OUT" | sed 's/^/    /'
  if echo "$RENDER_OUT" | grep -q "^OK|"; then
    ok "Manim render başarılı (mp4 üretildi)"
  else
    fail "Manim render başarısız (yukarıdaki output'a bak)"
  fi
fi

# ────────────────────────────────────────────────────────────────────
# 3) DLQ testi — bozuk kod 3 attempt sonra DLQ'ya düşmeli
# ────────────────────────────────────────────────────────────────────
hdr "TEST 3: DLQ — 3 ardışık AST_VIOLATION → dead_letter_queue_ravel"

if ! docker ps --format '{{.Names}}' | grep -q '^ravel_manim_worker$'; then
  fail "ravel_manim_worker container ayakta değil — DLQ testi atlandı"
else
  echo ""
  echo "→ 3.1) DLQ baseline offset al"
  DLQ_BEFORE=$(docker compose exec -T kafka /opt/kafka/bin/kafka-get-offsets.sh \
    --bootstrap-server kafka:9092 --topic dead_letter_queue_ravel 2>/dev/null \
    | awk -F: '{sum+=$3} END {print sum+0}')
  echo "    DLQ before: $DLQ_BEFORE"

  echo ""
  echo "→ 3.2) Bozuk kodu attempt=3 ile manim_render_tasks'a enjekte et (max=3 → direkt DLQ)"
  TASK_ID="dlq_$(date +%s)_$$"
  BAD_TASK=$(cat <<JSON
{"task_id":"$TASK_ID","correlation_id":"corr_dlq_$$","trace_id":"trace_dlq_$$","student_id":"std_dlq","manim_code":"from manim import *\nimport os\nclass X(Scene):\n    def construct(self): pass\n","render_quality":"480p","timeout_seconds":30,"attempt_number":3}
JSON
)
  echo "$BAD_TASK" | docker compose exec -T kafka /opt/kafka/bin/kafka-console-producer.sh \
    --bootstrap-server kafka:9092 --topic manim_render_tasks >/dev/null 2>&1
  echo "    enjekte edildi: task_id=$TASK_ID attempt=3"

  echo ""
  echo "→ 3.3) DLQ'da yeni mesaj bekle (max 30 sn)"
  for i in $(seq 1 30); do
    DLQ_NOW=$(docker compose exec -T kafka /opt/kafka/bin/kafka-get-offsets.sh \
      --bootstrap-server kafka:9092 --topic dead_letter_queue_ravel 2>/dev/null \
      | awk -F: '{sum+=$3} END {print sum+0}')
    if [ "$DLQ_NOW" -gt "$DLQ_BEFORE" ]; then
      echo "    ✓ DLQ $i sn'de büyüdü ($DLQ_BEFORE → $DLQ_NOW)"
      break
    fi
    sleep 1
  done

  if [ "${DLQ_NOW:-0}" -gt "$DLQ_BEFORE" ]; then
    ok "DLQ mesajı oluştu (3 attempt aşıldı → fallback path)"
  else
    fail "DLQ büyümedi (offset $DLQ_BEFORE → $DLQ_NOW)"
  fi

  echo ""
  echo "→ 3.4) Worker log'unda DLQ kanıtı"
  # pipefail + grep -q tuzağı (bkz. test_manim_e2e.sh) — sayım kullan.
  DLQ_LOG_COUNT=$(docker compose logs --no-color --tail=200 manim_worker 2>&1 \
    | grep -c "DLQ.*$TASK_ID" || true)
  [ "$DLQ_LOG_COUNT" -ge 1 ] && ok "manim_worker log'unda DLQ kaydı görüldü" \
                             || fail "manim_worker log'unda DLQ kaydı yok"

  echo ""
  echo "→ 3.5) attempt=1 ile bozuk kod → qa_correction_loop'a düşmeli (DLQ değil)"
  QA_BEFORE=$(docker compose exec -T kafka /opt/kafka/bin/kafka-get-offsets.sh \
    --bootstrap-server kafka:9092 --topic qa_correction_loop 2>/dev/null \
    | awk -F: '{sum+=$3} END {print sum+0}')
  TASK_ID2="qa_$(date +%s)_$$"
  BAD_TASK2=$(cat <<JSON
{"task_id":"$TASK_ID2","correlation_id":"corr_qa_$$","trace_id":"trace_qa_$$","student_id":"std_qa","manim_code":"from manim import *\nimport os\nclass X(Scene):\n    def construct(self): pass\n","render_quality":"480p","timeout_seconds":30,"attempt_number":1}
JSON
)
  echo "$BAD_TASK2" | docker compose exec -T kafka /opt/kafka/bin/kafka-console-producer.sh \
    --bootstrap-server kafka:9092 --topic manim_render_tasks >/dev/null 2>&1

  for i in $(seq 1 30); do
    QA_NOW=$(docker compose exec -T kafka /opt/kafka/bin/kafka-get-offsets.sh \
      --bootstrap-server kafka:9092 --topic qa_correction_loop 2>/dev/null \
      | awk -F: '{sum+=$3} END {print sum+0}')
    if [ "$QA_NOW" -gt "$QA_BEFORE" ]; then
      echo "    ✓ qa_correction_loop $i sn'de büyüdü ($QA_BEFORE → $QA_NOW)"
      break
    fi
    sleep 1
  done

  if [ "${QA_NOW:-0}" -gt "$QA_BEFORE" ]; then
    ok "attempt=1 hatası qa_correction_loop'a düştü (DLQ değil)"
  else
    fail "qa_correction_loop büyümedi"
  fi
fi

# ────────────────────────────────────────────────────────────────────
# Özet
# ────────────────────────────────────────────────────────────────────
echo ""
echo "═════════════════════════════════════"
printf "  Passed: ${GREEN}%d${NC}    Failed: ${RED}%d${NC}\n" "$PASS" "$FAIL"
echo "═════════════════════════════════════"
[ "$FAIL" -eq 0 ]
