#!/usr/bin/env bash
set -euo pipefail

export COMPOSE_PROJECT_NAME="workstream-smoke-${GITHUB_RUN_ID:-$$}"
created_env=0

cleanup() {
  docker compose down --volumes --remove-orphans
  if [[ "$created_env" == "1" ]]; then
    rm -f .env
  fi
}
trap cleanup EXIT

if [[ ! -f .env ]]; then
  cp .env.example .env
  created_env=1
fi

docker compose up --detach --build --wait --wait-timeout 120 api worker beat

migrate_id="$(docker compose ps --all --quiet migrate)"
test "$(docker inspect --format '{{.State.ExitCode}}' "$migrate_id")" = "0"
test "$(docker inspect --format '{{.State.Health.Status}}' "$(docker compose ps --quiet api)")" = "healthy"
curl --fail --silent --show-error http://localhost:8000/health/ready | grep -q '"status":"ok"'
test "$(docker inspect --format '{{.State.Running}}' "$(docker compose ps --quiet worker)")" = "true"
test "$(docker inspect --format '{{.State.Running}}' "$(docker compose ps --quiet beat)")" = "true"

for _ in $(seq 1 30); do
  worker_logs="$(docker compose logs worker)"
  beat_logs="$(docker compose logs beat)"
  if grep -Fq "  . workstream.outbox.dispatch" <<<"$worker_logs" && \
    grep -Fq "Scheduler: Sending due task dispatch-outbox (workstream.outbox.dispatch)" \
      <<<"$beat_logs"; then
    test "$(docker inspect --format '{{.State.Running}}' "$(docker compose ps --quiet worker)")" = "true"
    test "$(docker inspect --format '{{.State.Running}}' "$(docker compose ps --quiet beat)")" = "true"
    exit 0
  fi
  sleep 1
done

docker compose logs api worker beat migrate
exit 1
