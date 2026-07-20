#!/usr/bin/env bash
# Lightspeed harness — on-prem installer ([4.4], issue #26).
#
# Brings up the harness profile (MAS + PostgreSQL) with Podman or Docker
# Compose, generates a SECRET_KEY on first run, waits for health, and runs
# the headless smoke test. Idempotent: re-running reuses the .env.
#
# Usage:  ./deploy/harness/install.sh [up|down|smoke]

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
COMPOSE_FILE="$HERE/compose.yaml"
ENV_FILE="$HERE/.env"

# Prefer podman compose, fall back to docker compose.
if command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
  COMPOSE=(podman compose)
elif command -v docker >/dev/null 2>&1; then
  COMPOSE=(docker compose)
else
  echo "error: need 'podman compose' or 'docker compose'" >&2
  exit 1
fi

ensure_env() {
  if [ ! -f "$ENV_FILE" ]; then
    cp "$HERE/.env.example" "$ENV_FILE"
    echo "created $ENV_FILE from template"
  fi
  if ! grep -qE '^SECRET_KEY=.+' "$ENV_FILE"; then
    local key
    key="$(openssl rand -hex 32)"
    # portable in-place edit (BSD + GNU sed)
    sed -i.bak "s|^SECRET_KEY=.*|SECRET_KEY=${key}|" "$ENV_FILE" && rm -f "${ENV_FILE}.bak"
    echo "generated SECRET_KEY"
  fi
}

cmd_up() {
  ensure_env
  echo "starting harness profile (MAS + PostgreSQL)…"
  "${COMPOSE[@]}" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --build
  echo "waiting for the API to become healthy…"
  for _ in $(seq 1 60); do
    if curl -fsS http://localhost:8002/api/health/ >/dev/null 2>&1; then
      echo "harness is up at http://localhost:8002"
      return 0
    fi
    sleep 2
  done
  echo "error: API did not become healthy in time" >&2
  "${COMPOSE[@]}" -f "$COMPOSE_FILE" logs mas-api | tail -40
  exit 1
}

cmd_down() {
  "${COMPOSE[@]}" -f "$COMPOSE_FILE" down
}

cmd_smoke() {
  # shellcheck disable=SC1090
  set -a; source "$ENV_FILE"; set +a
  python "$REPO_ROOT/multi-agent/tests/e2e/harness_smoke.py" \
    --url http://localhost:8002
}

case "${1:-up}" in
  up)    cmd_up ;;
  down)  cmd_down ;;
  smoke) cmd_smoke ;;
  *) echo "usage: $0 [up|down|smoke]" >&2; exit 2 ;;
esac
