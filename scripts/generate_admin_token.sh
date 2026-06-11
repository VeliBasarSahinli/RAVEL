#!/usr/bin/env bash
# RAG admin API'sine gönderilecek JWT token üret.
# API Gateway /auth/login'a role="admin" parametresiyle istek atıyor.
#
# Usage:
#   ./scripts/generate_admin_token.sh
#   ./scripts/generate_admin_token.sh export   # eval $(...) için TOKEN= çıktısı

set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "✗ .env not found." >&2
  exit 1
fi
# shellcheck disable=SC1091
set -a; source .env; set +a

API="http://localhost:${API_GATEWAY_PORT:-8000}"

RESP=$(curl -sS -X POST "$API/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"grade_level":6,"role":"admin"}')

TOKEN=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

if [ -z "$TOKEN" ]; then
  echo "✗ token üretilemedi:"
  echo "$RESP"
  exit 1
fi

if [ "${1:-}" = "export" ]; then
  echo "ADMIN_TOKEN=$TOKEN"
else
  echo "$TOKEN"
fi
