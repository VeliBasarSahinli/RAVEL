#!/usr/bin/env bash
# RAVEL — Step 1 acceptance test
# Verifies the data plane is up, healthy, and reachable from the bridge network.
#
# Usage:  ./scripts/health_check.sh

set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "✗ .env not found. Run:  cp .env.example .env" >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a; source .env; set +a

GREEN="\033[0;32m"; RED="\033[0;31m"; YELLOW="\033[0;33m"; NC="\033[0m"
PASS=0; FAIL=0

dc() { docker compose "$@"; }

check() {
  local name="$1"; shift
  if "$@" > /dev/null 2>&1; then
    printf "  ${GREEN}✓${NC} %s\n" "$name"
    PASS=$((PASS+1))
  else
    printf "  ${RED}✗${NC} %s\n" "$name"
    FAIL=$((FAIL+1))
  fi
}

echo ""
echo "═══ RAVEL Step 1 Acceptance Test ═══"
echo ""

# ------------------------------------------------------------------
echo "→ Container state"
for svc in postgres pgbouncer redis kafka qdrant minio; do
  cid="$(dc ps -q "$svc" 2>/dev/null || true)"
  if [ -z "$cid" ]; then
    printf "  ${RED}✗${NC} %s missing (not started)\n" "$svc"
    FAIL=$((FAIL+1))
    continue
  fi
  status="$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null || echo unknown)"
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}n/a{{end}}' "$cid" 2>/dev/null || echo n/a)"
  if [ "$status" = "running" ] && { [ "$health" = "healthy" ] || [ "$health" = "n/a" ]; }; then
    printf "  ${GREEN}✓${NC} %-10s  state=%s  health=%s\n" "$svc" "$status" "$health"
    PASS=$((PASS+1))
  else
    printf "  ${YELLOW}!${NC} %-10s  state=%s  health=%s\n" "$svc" "$status" "$health"
    FAIL=$((FAIL+1))
  fi
done

# ------------------------------------------------------------------
echo ""
echo "→ Service reachability (from bridge network)"

check "Postgres direct (DB-1)" \
  dc exec -T postgres psql -U "$POSTGRES_USER" -d ravel_db1 -c "SELECT 1"

check "Postgres direct (DB-2)" \
  dc exec -T postgres psql -U "$POSTGRES_USER" -d ravel_db2 -c "SELECT 1"

check "DB-1: students table exists" \
  dc exec -T postgres psql -U "$POSTGRES_USER" -d ravel_db1 -c "SELECT COUNT(*) FROM students"

check "DB-2: interaction_logs table exists" \
  dc exec -T postgres psql -U "$POSTGRES_USER" -d ravel_db2 -c "SELECT COUNT(*) FROM interaction_logs"

check "PgBouncer → ravel_db1" \
  dc exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
    psql -h pgbouncer -p 6432 -U "$POSTGRES_USER" -d ravel_db1 -c "SELECT 1"

check "PgBouncer → ravel_db2" \
  dc exec -T -e PGPASSWORD="$POSTGRES_PASSWORD" postgres \
    psql -h pgbouncer -p 6432 -U "$POSTGRES_USER" -d ravel_db2 -c "SELECT 1"

check "Redis PING" \
  dc exec -T redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ping

check "Kafka broker API" \
  dc exec -T kafka /opt/kafka/bin/kafka-broker-api-versions.sh \
    --bootstrap-server kafka:9092

check "Qdrant /readyz (host)" \
  curl -fsS "http://localhost:${QDRANT_HTTP_PORT}/readyz"

check "MinIO /minio/health/live (host)" \
  curl -fsS "http://localhost:${MINIO_API_PORT}/minio/health/live"

# ------------------------------------------------------------------
echo ""
echo "═════════════════════════════════════"
printf "  Passed: ${GREEN}%d${NC}    Failed: ${RED}%d${NC}\n" "$PASS" "$FAIL"
echo "═════════════════════════════════════"

[ "$FAIL" -eq 0 ]
