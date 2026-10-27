#!/bin/sh
# Boots the image the way Maritime does and checks the agent server answers on
# $PORT, in both modes the OpenHands integrations use:
#   1. Agent Canvas: a session API key at boot.
#   2. OpenHands Enterprise: deferred init, claimed with POST /api/init.
# Usage: tests/smoke.sh <image>
set -eu

IMAGE="${1:?usage: tests/smoke.sh <image>}"
PORT=18789
HOST_PORT="${HOST_PORT:-28789}"
NAME="maritime-oh-smoke-$$"

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

wait_for() {
    url="$1"
    i=0
    until curl -fsS -o /dev/null "$url"; do
        i=$((i + 1))
        if [ "$i" -ge 180 ]; then
            echo "FAIL: $url did not answer within 180s" >&2
            docker logs "$NAME" >&2 || true
            exit 1
        fi
        sleep 1
    done
}

echo "== session API key mode"
docker run -d ${DOCKER_PLATFORM:+--platform "$DOCKER_PLATFORM"} --name "$NAME" -p "$HOST_PORT:$PORT" \
    -e PORT="$PORT" -e HOME=/tmp/data -e OH_SESSION_API_KEYS_0=smoke-key \
    "$IMAGE" >/dev/null
wait_for "http://127.0.0.1:$HOST_PORT/health"
status=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$HOST_PORT/api/conversations/search")
[ "$status" = 401 ] || { echo "FAIL: expected 401 without a key, got $status" >&2; exit 1; }
status=$(curl -s -o /dev/null -w '%{http_code}' -H 'X-Session-API-Key: smoke-key' \
    "http://127.0.0.1:$HOST_PORT/api/conversations/search")
[ "$status" = 200 ] || { echo "FAIL: expected 200 with the key, got $status" >&2; exit 1; }
cleanup

echo "== deferred init mode"
docker run -d ${DOCKER_PLATFORM:+--platform "$DOCKER_PLATFORM"} --name "$NAME" -p "$HOST_PORT:$PORT" \
    -e PORT="$PORT" -e OH_DEFERRED_INIT=1 -e OH_SECRET_KEY=smoke-init-key \
    "$IMAGE" >/dev/null
wait_for "http://127.0.0.1:$HOST_PORT/alive"
state=$(curl -fsS "http://127.0.0.1:$HOST_PORT/api/init")
echo "$state" | grep -q '"dormant"' || { echo "FAIL: expected dormant, got $state" >&2; exit 1; }

echo "PASS: $IMAGE serves the agent server on \$PORT"
