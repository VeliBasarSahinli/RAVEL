#!/usr/bin/env bash
# RAVEL — Step 4 Aşama 1 unit tests for Bandit
#
# 1) LinTS matematiksel doğruluk     — ground-truth eylemi öğrenir mi?
# 2) Actor inference SLA             — 100 ardışık <50ms median?
# 3) Learner reward formula          — bilinen değerlerle r_t doğru mu?
# 4) Hot-swap mekanizması            — Redis sinyal → Actor reload?
# 5) DB-2 append-only INSERT         — reward → Learner → DB-2 (ADR-011 dersi)

set -uo pipefail
cd "$(dirname "$0")/.."

# shellcheck disable=SC1091
set -a; source .env; set +a

GREEN="\033[0;32m"; RED="\033[0;31m"; YELLOW="\033[0;33m"; NC="\033[0m"
PASS=0; FAIL=0
ok()   { printf "  ${GREEN}✓${NC} %s\n" "$1"; PASS=$((PASS+1)); }
fail() { printf "  ${RED}✗${NC} %s\n" "$1"; FAIL=$((FAIL+1)); }
hdr()  { printf "\n${YELLOW}═══ %s ═══${NC}\n" "$1"; }

# ╔══════════════════════════════════════════════════════════════════╗
# ║ TEST 1 — LinTS matematiksel doğruluk                             ║
# ╚══════════════════════════════════════════════════════════════════╝

hdr "TEST 1: LinTS — 100 iterasyon sonra ground-truth eylemi öğrenir mi?"

OUT=$(docker compose exec -T bandit python <<'PY'
import numpy as np
from app.lints import LinTS

np.random.seed(42)

# Senaryo: 3 eylem, 12 boyut, alpha=1.0
# Ground truth: action 0 her context'te yüksek reward (~1), action 1/2 ~0.
# Bandit Thompson Sampling ile 100 iterasyonda action 0'ı tercih etmeyi öğrenmeli.
N_ITERS = 100
DIM = 12
N_ACTIONS = 3

bandit = LinTS(n_actions=N_ACTIONS, context_dim=DIM, alpha=1.0)

# Ground-truth theta vectors
true_theta = [
    np.full(DIM, 0.8),   # action 0 — yüksek reward (her boyut katkı yapar)
    np.zeros(DIM),       # action 1 — sıfır
    np.zeros(DIM),       # action 2 — sıfır
]

selections = []
for t in range(N_ITERS):
    ctx = np.random.uniform(0.3, 0.7, size=DIM)
    action, _ = bandit.select_action(ctx)
    # Ground-truth reward + small noise
    reward = float(ctx @ true_theta[action]) + np.random.normal(0, 0.05)
    bandit.update(ctx, action, reward)
    selections.append(action)

# Son 30 seçimde action 0 oranı (öğrenmenin yakınsamasını ölçer)
last_30 = selections[-30:]
rate_action_0 = sum(1 for a in last_30 if a == 0) / len(last_30)
total_action_0 = sum(1 for a in selections if a == 0) / len(selections)

print(f"action 0 son 30 oranı : {rate_action_0:.2%}")
print(f"action 0 toplam oranı : {total_action_0:.2%}")
print(f"son 30 dağılım        : 0={last_30.count(0)} 1={last_30.count(1)} 2={last_30.count(2)}")

# Threshold: son 30'da action 0 ≥ 60% (Thompson exploration ile %100 değil)
if rate_action_0 >= 0.60:
    print("VERDICT: PASS")
else:
    print("VERDICT: FAIL — convergence too slow")
PY
)

echo "$OUT" | sed 's/^/    /'
if echo "$OUT" | grep -q "VERDICT: PASS"; then
  ok "LinTS ground-truth eylemi öğrendi (son 30 iterasyonda ≥60% action 0)"
else
  fail "LinTS yakınsamadı"
fi

# ╔══════════════════════════════════════════════════════════════════╗
# ║ TEST 2 — Actor inference SLA (<50ms median)                      ║
# ╚══════════════════════════════════════════════════════════════════╝

hdr "TEST 2: Actor inference SLA — 100 ardışık select_action <50ms"

OUT=$(docker compose exec -T bandit python <<'PY'
import time
import numpy as np
from app.lints import LinTS
from app.config import get_settings

s = get_settings()
lt = LinTS(s.bandit_num_actions, s.bandit_context_dim, s.bandit_alpha)

# Ağırlıkları biraz dolu yap (gerçek senaryoya benzer)
np.random.seed(7)
for _ in range(50):
    ctx = np.random.rand(s.bandit_context_dim)
    a = np.random.randint(s.bandit_num_actions)
    lt.update(ctx, a, np.random.rand())

# 100 inference süresini ölç
times_ms = []
for _ in range(100):
    ctx = np.random.rand(s.bandit_context_dim)
    t0 = time.perf_counter()
    lt.select_action(ctx)
    times_ms.append((time.perf_counter() - t0) * 1000.0)

times_ms.sort()
median = times_ms[50]
p95 = times_ms[95]
mx = times_ms[-1]
print(f"median : {median:.3f} ms")
print(f"p95    : {p95:.3f} ms")
print(f"max    : {mx:.3f} ms")
print(f"SLA    : {s.actor_inference_timeout_ms} ms")

if median < s.actor_inference_timeout_ms and p95 < s.actor_inference_timeout_ms:
    print("VERDICT: PASS")
else:
    print("VERDICT: FAIL")
PY
)

echo "$OUT" | sed 's/^/    /'
if echo "$OUT" | grep -q "VERDICT: PASS"; then
  ok "Actor inference SLA korundu (median + p95 < 50ms)"
else
  fail "Actor inference SLA ihlal"
fi

# ╔══════════════════════════════════════════════════════════════════╗
# ║ TEST 3 — Learner reward formula                                  ║
# ╚══════════════════════════════════════════════════════════════════╝

hdr "TEST 3: Learner reward formula r = α·C + β·(T_baseline/T_actual) + γ·S"

OUT=$(docker compose exec -T bandit python <<'PY'
from app.learner import LearnerService
from app.config import get_settings
from app.schemas import RewardLogEntry

settings = get_settings()
ls = LearnerService.__new__(LearnerService)  # bypass __init__ (no clients needed)
ls.settings = settings

def case(label, c_t, t_baseline, t_actual, s_t, expected):
    e = RewardLogEntry(
        correlation_id="x", trace_id="x", student_id="x",
        context_vector=[0.5]*12, action_taken=0,
        c_t=c_t, t_baseline=t_baseline, t_actual=t_actual, s_t=s_t,
        topic_id="t", taxonomic_level="B1", is_correct=(c_t > 0),
        timestamp="2026-05-04T00:00:00Z",
    )
    r = ls.compute_reward(e)
    delta = abs(r - expected)
    status = "✓" if delta < 0.001 else "✗"
    print(f"{status} {label:40s} expected={expected:+.3f} got={r:+.3f}")
    return delta < 0.001

# CLAUDE.md alpha=0.6, beta=0.2, gamma=0.2
# Case 1: ideal — correct, fast, "Anladım"
#   r = 0.6·1 + 0.2·(60/30) + 0.2·1 = 0.6 + 0.4 + 0.2 = 1.20
# Case 2: yanlış cevap, yavaş çözüm, "Anlamadım"
#   r = 0.6·(-1) + 0.2·(60/120) + 0.2·(-1) = -0.6 + 0.1 - 0.2 = -0.70
# Case 3: ipucu yardımıyla, ortalama süre, nötr
#   r = 0.6·0.5 + 0.2·(60/60) + 0.2·0 = 0.30 + 0.20 + 0 = 0.50
# Case 4: T_actual çok küçük → cap (2.0) devreye girer
#   r = 0.6·1 + 0.2·min(60/1, 2.0) + 0.2·0 = 0.60 + 0.40 = 1.00
# Case 5: T_actual = 0 → safe fallback -1.0

results = []
results.append(case("ideal correct/fast/Anladım",       +1.0, 60, 30,  +1.0, +1.20))
results.append(case("wrong/slow/Anlamadım",             -1.0, 60, 120, -1.0, -0.70))
results.append(case("hint-aided/avg/neutral",           +0.5, 60, 60,   0.0, +0.50))
results.append(case("T_actual tiny → cap kicks in",     +1.0, 60, 1,    0.0, +1.00))
results.append(case("T_actual = 0 → fallback",          +1.0, 60, 0,   +1.0, -1.00))

if all(results):
    print("VERDICT: PASS")
else:
    print("VERDICT: FAIL")
PY
)

echo "$OUT" | sed 's/^/    /'
if echo "$OUT" | grep -q "VERDICT: PASS"; then
  ok "Learner reward formula tüm 5 vakada doğru"
else
  fail "Reward formula yanlış"
fi

# ╔══════════════════════════════════════════════════════════════════╗
# ║ TEST 4 — Hot-swap mekanizması                                    ║
# ╚══════════════════════════════════════════════════════════════════╝

hdr "TEST 4: Hot-swap — Redis sinyal → Actor MinIO'dan ağırlık yükler"

# 4.1) MinIO'ya yeni LinTS ağırlıkları yaz (container içinden)
echo "→ 4.1) MinIO'ya tipik bir LinTS dump'ı yaz"
docker compose exec -T bandit python <<'PY' 2>&1 | sed 's/^/    /'
import asyncio
import numpy as np
from app.minio_io import MinIOClient
from app.lints import LinTS
from app.config import get_settings

async def main():
    s = get_settings()
    m = MinIOClient(s.minio_endpoint, s.minio_access_key, s.minio_secret_key, s.minio_bucket_weights)
    await m.start()
    lt = LinTS(s.bandit_num_actions, s.bandit_context_dim, s.bandit_alpha)
    # Action 0'ı belirgin şekilde "öğrenmiş" yap, ki swap görünür olsun
    np.random.seed(123)
    for _ in range(20):
        ctx = np.random.rand(s.bandit_context_dim)
        lt.update(ctx, 0, 1.0)
    await m.save_weights(lt.to_dict())
    await m.stop()
    print("WEIGHTS_SAVED")

asyncio.run(main())
PY

# 4.2) Bandit log'unun şu anki uzunluğunu al (marker)
LOG_MARKER=$(docker compose logs --no-color bandit 2>&1 | wc -l)

# 4.3) Redis'e weight update sinyali yayınla
echo ""
echo "→ 4.2) Redis'e 'bandit:weights:updated' sinyali yayınla"
RESULT=$(docker compose exec -T redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning \
  PUBLISH "bandit:weights:updated" "test_swap_$(date +%s)" 2>&1)
echo "    PUBLISH result: $RESULT (subscriber sayısı)"

# 4.4) Actor'ın reload yaptığını log'da gör
echo ""
echo "→ 4.3) Actor 'weights hot-swapped successfully' log'unu bekle (max 10 sn)"
sleep 1
SUCCESS=false
for i in $(seq 1 10); do
  NEW_LOGS=$(docker compose logs --no-color bandit 2>&1 | tail -n +$((LOG_MARKER + 1)))
  if echo "$NEW_LOGS" | grep -q "received weight update signal" \
     && echo "$NEW_LOGS" | grep -q "weights hot-swapped successfully"; then
    SUCCESS=true
    break
  fi
  sleep 1
done

if $SUCCESS; then
  ok "Actor sinyali aldı + MinIO'dan yeni ağırlıkları yükledi"
else
  fail "Hot-swap log'ları görünmedi"
  docker compose logs --tail=15 bandit 2>&1 | sed 's/^/      /'
fi

# ╔══════════════════════════════════════════════════════════════════╗
# ║ TEST 5 — Learner DB-2 INSERT (ADR-011 dersi: explicit doğrulama) ║
# ╚══════════════════════════════════════════════════════════════════╝

hdr "TEST 5: Learner DB-2 INSERT (append-only)"

# Spesifik bir test student_id ile filtre
TEST_STUDENT=$(python3 -c "import uuid; print(uuid.uuid4())")
TEST_TRACE="trace_unit_test_5_$(date +%s)"
TEST_CORR="corr_unit_test_5_$(date +%s)"

echo "→ 5.1) Test öncesi DB-2'de bu student için kayıt sayısı"
COUNT_BEFORE=$(docker compose exec -T postgres psql -U ravel_admin -d ravel_db2 -At \
  -c "SELECT COUNT(*) FROM interaction_logs WHERE student_id = '$TEST_STUDENT';" 2>/dev/null | tr -d '[:space:]')
echo "    önce: $COUNT_BEFORE"

echo ""
echo "→ 5.2) reward_logs_stream'e geçerli RewardLogEntry mesajı at"
TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
MSG=$(cat <<JSON
{"correlation_id":"$TEST_CORR","trace_id":"$TEST_TRACE","student_id":"$TEST_STUDENT","context_vector":[0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.5],"action_taken":0,"c_t":1.0,"t_baseline":60.0,"t_actual":30.0,"s_t":1.0,"topic_id":"unit_test_topic","taxonomic_level":"B1","is_correct":true,"frustration_index":0.2,"timestamp":"$TS"}
JSON
)
echo "$MSG" | docker compose exec -T kafka /opt/kafka/bin/kafka-console-producer.sh \
  --bootstrap-server kafka:9092 --topic reward_logs_stream >/dev/null 2>&1
echo "    enjekte edildi"

echo ""
echo "→ 5.3) Bandit Learner consume + DB-2 INSERT için 5 sn bekle"
sleep 5

echo ""
echo "→ 5.4) DB-2'de bu student için yeni kayıt sayısı"
COUNT_AFTER=$(docker compose exec -T postgres psql -U ravel_admin -d ravel_db2 -At \
  -c "SELECT COUNT(*) FROM interaction_logs WHERE student_id = '$TEST_STUDENT';" 2>/dev/null | tr -d '[:space:]')
echo "    sonra: $COUNT_AFTER"

[ "$COUNT_AFTER" -gt "$COUNT_BEFORE" ] && ok "Learner DB-2'ye INSERT yaptı (delta=$((COUNT_AFTER - COUNT_BEFORE)))" \
                                       || fail "DB-2'de yeni kayıt görünmedi"

echo ""
echo "→ 5.5) Eklenen kaydın içeriği (reward_signal beklenen 1.20'ye yakın olmalı)"
docker compose exec -T postgres psql -U ravel_admin -d ravel_db2 \
  -c "SELECT student_id, action_taken, is_correct, time_spent_seconds, reward_signal
      FROM interaction_logs WHERE student_id = '$TEST_STUDENT'
      ORDER BY \"timestamp\" DESC LIMIT 1;" 2>&1 | sed 's/^/    /'

# ╔══════════════════════════════════════════════════════════════════╗
# ║ ÖZET                                                             ║
# ╚══════════════════════════════════════════════════════════════════╝

echo ""
echo "═════════════════════════════════════"
printf "  Passed: ${GREEN}%d${NC}    Failed: ${RED}%d${NC}\n" "$PASS" "$FAIL"
echo "═════════════════════════════════════"

[ "$FAIL" -eq 0 ]
