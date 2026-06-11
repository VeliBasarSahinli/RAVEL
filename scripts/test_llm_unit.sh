#!/usr/bin/env bash
# RAVEL — Adım 7 Aşama 1: LLM Gateway + crypto + prompt engine unit
#
# Tamamı host venv'inde çalışır (orchestrator imajı gerekmez):
#   1) crypto.py: AES-256-GCM roundtrip + bad key + auth fail
#   2) llm_gateway: CoT temizleme (5 vaka), mock response, hata yolu
#   3) prompt_engine: 6 mod yükleniyor, render, eksik placeholder warn
#   4) llm_configs_repo: live DB-1 üzerinde upsert/list/update/delete
#   5) llm_gateway: redis cache hit/miss/invalidate

set -uo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1091
set -a; source .env; set +a

GREEN="\033[0;32m"; RED="\033[0;31m"; YELLOW="\033[0;33m"; NC="\033[0m"
PASS=0; FAIL=0
ok()   { printf "  ${GREEN}✓${NC} %s\n" "$1"; PASS=$((PASS+1)); }
fail() { printf "  ${RED}✗${NC} %s\n" "$1"; FAIL=$((FAIL+1)); }
hdr()  { printf "\n${YELLOW}═══ %s ═══${NC}\n" "$1"; }

VENV="services/orchestrator/venv/bin/python"
[ -x "$VENV" ] || { echo "✗ orchestrator venv yok: $VENV" >&2; exit 1; }

DB1_LOCAL="postgresql://ravel_app:${POSTGRES_APP_PASSWORD}@localhost:${PGBOUNCER_PORT:-6432}/ravel_db1"
REDIS_LOCAL="redis://:${REDIS_PASSWORD}@localhost:${REDIS_PORT:-6379}/0"
KEY_HEX="${ENCRYPTION_KEY}"

[ -n "$KEY_HEX" ] || { echo "✗ ENCRYPTION_KEY .env'de boş" >&2; exit 1; }

echo ""
echo "═══ RAVEL Adım 7 Aşama 1 — LLM unit ═══"

# ────────────────────────────────────────────────────────────────────
# 1) crypto + 2) CoT strip — saf Python
# ────────────────────────────────────────────────────────────────────
hdr "TEST 1+2: crypto AES-256-GCM + CoT temizleme"

OUT=$($VENV - <<PY 2>&1
import sys, os
sys.path.insert(0, "services/orchestrator")
from app.crypto import ApiKeyCipher, CryptoError
from app.llm_gateway import _strip_chain_of_thought

KEY = os.environ.get("ENCRYPTION_KEY") or "${KEY_HEX}".strip()
KEY = KEY if KEY else "${KEY_HEX}"
c = ApiKeyCipher(KEY)

# Crypto
ct = c.encrypt("sk-or-v1-test-secret")
assert c.decrypt(ct) == "sk-or-v1-test-secret"
print("OK|crypto::roundtrip")

c2 = ApiKeyCipher("00"*32)
try:
    c2.decrypt(ct); print("FAIL|crypto::wrong_key_should_raise")
except CryptoError:
    print("OK|crypto::wrong_key_raises")

try:
    ApiKeyCipher("not-hex"); print("FAIL|crypto::bad_hex_should_raise")
except CryptoError:
    print("OK|crypto::bad_hex_raises")

try:
    ApiKeyCipher("00"*16); print("FAIL|crypto::short_key_should_raise")
except CryptoError:
    print("OK|crypto::short_key_raises")

assert ApiKeyCipher.mask("sk-some-very-long-key", 4) == "sk-s****"
print("OK|crypto::mask")

# CoT
cases = [
    ("<düşünce>aha</düşünce>Cevap.", "Cevap."),
    ("<thinking>x</thinking>Cevap.", "Cevap."),
    ("Pre <düşünce>X\nY</düşünce> Post", "Pre  Post"),
    ("Hiç tag yok", "Hiç tag yok"),
    ("<DÜŞÜNCE>upper</DÜŞÜNCE>Cevap.", "Cevap."),  # case-insensitive
]
for raw, exp in cases:
    got = _strip_chain_of_thought(raw)
    if got.strip() == exp.strip():
        print(f"OK|cot::{raw[:25]!r}")
    else:
        print(f"FAIL|cot::{raw[:25]!r} got={got!r}")
PY
)
echo "$OUT" | sed 's/^/    /'
while IFS='|' read -r status name _; do
    [ -z "$status" ] && continue
    if [ "$status" = "OK" ];   then ok "$name"; fi
    if [ "$status" = "FAIL" ]; then fail "$name"; fi
done <<<"$OUT"

# ────────────────────────────────────────────────────────────────────
# 3) PromptEngine
# ────────────────────────────────────────────────────────────────────
hdr "TEST 3: PromptEngine yaml load + Jinja2 render"

OUT=$($VENV - <<'PY' 2>&1
import sys, logging
sys.path.insert(0, "services/orchestrator")
from app.prompt_engine import PromptEngine, SUPPORTED_MODES

eng = PromptEngine()
print(f"OK|engine::loaded::{len(SUPPORTED_MODES)}_modes")

# 6 modu render et — minimum gerekli alanlarla
contexts = {
    "error_explanation": dict(grade_level=7, subject="Uslu_Ifadeler", taxonomic_level="B1",
        consecutive_errors=2, learning_style="görsel", success_rate=0.4, frustration_index=0.3,
        question_text="2^3=?", student_answer="6", answer_key="8", rag_content="Üslü ifade..."),
    "topic_teaching": dict(grade_level=6, subject="Kareköklü_İfadeler", taxonomic_level="A2",
        learning_style="sözel", frustration_index=0.1, rag_content="Karekök tanımı..."),
    "step_by_step": dict(grade_level=8, subject="Cebir", taxonomic_level="B1",
        student_answer="x=2", answer_key="x=3", frustration_index=0.5,
        question_text="2x+1=7", rag_content="Denklem çözümü..."),
    "qa_dialog": dict(grade_level=7, subject="Geometri", taxonomic_level="A2",
        frustration_index=0.2, conversation_history="öğrenci: pisagor nedir?",
        student_message="anladım", rag_content="Pisagor teoremi..."),
    "manim_code": dict(grade_level=6, subject="Uslu_Ifadeler", taxonomic_level="A2",
        video_purpose="explanation", learning_style="görsel", rag_content="Üslü ifade..."),
    "manim_correction": dict(error_type="AST_VIOLATION",
        error_message="import 'os' not in whitelist",
        manim_code="from manim import *\nimport os"),
}
for mode, ctx in contexts.items():
    pair = eng.render(mode, ctx)
    assert pair.system_prompt and pair.user_prompt, f"{mode}: empty prompt pair"
    # Pedagojik 4 mod'da Dijital Öğretmen persona'sı bekle
    if mode in ("error_explanation", "topic_teaching", "step_by_step", "qa_dialog"):
        assert "Dijital Öğretmen" in pair.system_prompt, f"{mode}: persona missing"
    print(f"OK|render::{mode}::sys={len(pair.system_prompt)}B::user={len(pair.user_prompt)}B")

# Eksik placeholder uyarısı
import io
buf = io.StringIO()
h = logging.StreamHandler(buf); h.setLevel(logging.WARNING)
logging.getLogger("app.prompt_engine").addHandler(h)
eng.render("step_by_step", {"grade_level": 8})  # rest empty
assert "missing context keys" in buf.getvalue()
print("OK|render::missing_placeholder_warning")
PY
)
echo "$OUT" | sed 's/^/    /'
while IFS='|' read -r status name _; do
    [ -z "$status" ] && continue
    if [ "$status" = "OK" ];   then ok "prompt::$name"; fi
    if [ "$status" = "FAIL" ]; then fail "prompt::$name"; fi
done <<<"$OUT"

# ────────────────────────────────────────────────────────────────────
# 4) LLMConfigsRepo (live DB-1)
# ────────────────────────────────────────────────────────────────────
hdr "TEST 4: LLMConfigsRepo CRUD (canlı DB-1 ravel_app role)"

OUT=$($VENV - <<PY 2>&1
import asyncio, sys
sys.path.insert(0, "services/orchestrator")
import asyncpg
from app.llm_configs_repo import LLMConfigsRepo

async def main():
    pool = await asyncpg.create_pool(
        dsn="${DB1_LOCAL}",
        statement_cache_size=0, min_size=1, max_size=2,
    )
    try:
        repo = LLMConfigsRepo(pool)
        await repo.delete("_test_unit_")

        cfg = await repo.upsert(
            agent_name="_test_unit_", provider="openrouter",
            model_name="anthropic/claude-sonnet-4-5",
            api_key_blob=b"\\x00\\x01blob", endpoint_url=None,
            max_tokens=2048, temperature=0.5,
        )
        assert cfg.provider == "openrouter" and cfg.max_tokens == 2048
        print("OK|repo::upsert")

        cfg2 = await repo.update_partial("_test_unit_", max_tokens=4096)
        assert cfg2.max_tokens == 4096
        assert cfg2.api_key_blob == b"\\x00\\x01blob"
        print("OK|repo::update_partial_tokens_only")

        cfg3 = await repo.update_partial("_test_unit_", clear_api_key=True)
        assert cfg3.api_key_blob is None
        print("OK|repo::clear_api_key")

        all_cfgs = await repo.list_all()
        assert any(c.agent_name == "_test_unit_" for c in all_cfgs)
        print("OK|repo::list_all")

        d = await repo.delete("_test_unit_")
        assert d is True
        d2 = await repo.delete("_test_unit_")
        assert d2 is False
        print("OK|repo::delete_returns_bool")
    finally:
        await pool.close()

asyncio.run(main())
PY
)
echo "$OUT" | sed 's/^/    /'
while IFS='|' read -r status name _; do
    [ -z "$status" ] && continue
    if [ "$status" = "OK" ];   then ok "$name"; fi
    if [ "$status" = "FAIL" ]; then fail "$name"; fi
done <<<"$OUT"

# ────────────────────────────────────────────────────────────────────
# 5) LLMGateway: cache hit/miss/invalidate + mock + LLMError
# ────────────────────────────────────────────────────────────────────
hdr "TEST 5: LLMGateway cache + mock + missing-config error"

OUT=$($VENV - <<PY 2>&1
import asyncio, sys
sys.path.insert(0, "services/orchestrator")
import asyncpg
from app.crypto import ApiKeyCipher
from app.llm_configs_repo import LLMConfigsRepo
from app.llm_gateway import LLMGateway, LLMError, MOCK_RESPONSE, MOCK_MANIM_CODE
from app.redis_io import RedisIO

KEY = "${KEY_HEX}"

async def main():
    pool = await asyncpg.create_pool(
        dsn="${DB1_LOCAL}",
        statement_cache_size=0, min_size=1, max_size=2,
    )
    redis_io = RedisIO("${REDIS_LOCAL}")
    await redis_io.start()
    repo = LLMConfigsRepo(pool)
    cipher = ApiKeyCipher(KEY)
    try:
        # Mock mode
        gw_m = LLMGateway(repo, cipher, redis_io, mock_mode=True)
        await gw_m.start()
        assert (await gw_m.generate("orchestrator_text","s","u")) == MOCK_RESPONSE
        assert (await gw_m.generate("orchestrator_manim","s","u")) == MOCK_MANIM_CODE
        assert (await gw_m.generate("orchestrator_correction","s","u")) == MOCK_MANIM_CODE
        await gw_m.stop()
        print("OK|gateway::mock_3_agents")

        # Real mode w/o config → LLMError
        await repo.delete("_test_gw_")
        await redis_io.client.delete("llm_config:_test_gw_")
        gw = LLMGateway(repo, cipher, redis_io, mock_mode=False)
        await gw.start()
        try:
            await gw.generate("_test_gw_","s","u")
            print("FAIL|gateway::missing_config_should_raise")
        except LLMError as e:
            assert "no active llm_config" in str(e)
            print("OK|gateway::missing_config_raises_LLMError")

        # Cache hit/miss/invalidate
        ct = cipher.encrypt("sk-test-cache")
        await repo.upsert("_test_gw_","openrouter","anthropic/claude-sonnet-4-5",
                          ct, None, 1024, 0.7)
        cfg1 = await gw._get_config_cached("_test_gw_")
        assert cfg1.max_tokens == 1024
        await repo.update_partial("_test_gw_", max_tokens=8192)
        cfg2 = await gw._get_config_cached("_test_gw_")
        assert cfg2.max_tokens == 1024  # stale cache
        await gw.invalidate_cache("_test_gw_")
        cfg3 = await gw._get_config_cached("_test_gw_")
        assert cfg3.max_tokens == 8192
        print("OK|gateway::cache_hit_miss_invalidate")

        # decrypt path
        assert gw._decrypt_key(cfg3) == "sk-test-cache"
        print("OK|gateway::decrypt_path")

        await gw.stop()
        await repo.delete("_test_gw_")
        await redis_io.client.delete("llm_config:_test_gw_")
    finally:
        await redis_io.stop()
        await pool.close()

asyncio.run(main())
PY
)
echo "$OUT" | sed 's/^/    /'
while IFS='|' read -r status name _; do
    [ -z "$status" ] && continue
    if [ "$status" = "OK" ];   then ok "$name"; fi
    if [ "$status" = "FAIL" ]; then fail "$name"; fi
done <<<"$OUT"

# ────────────────────────────────────────────────────────────────────
# Özet
# ────────────────────────────────────────────────────────────────────
echo ""
echo "═════════════════════════════════════"
printf "  Passed: ${GREEN}%d${NC}    Failed: ${RED}%d${NC}\n" "$PASS" "$FAIL"
echo "═════════════════════════════════════"
[ "$FAIL" -eq 0 ]
