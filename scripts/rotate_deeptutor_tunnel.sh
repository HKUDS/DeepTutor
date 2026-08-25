#!/bin/zsh
# Rotate the DeepTutor Cloudflare Quick Tunnel and publish its URL to backend-owned storage.

set -u

ROOT="${DEEPTUTOR_ROOT:-/Users/Shared/DeepTutor}"
LOG="${DEEPTUTOR_TUNNEL_LOG:-/tmp/deeptutor_tunnel.log}"
STATE_DIR="$ROOT/data/system/auth"
STATE_FILE="$STATE_DIR/deeptutor_tunnel.json"
TEMP_FILE="${STATE_FILE}.tmp.$$"
USER_ID="$(id -u)"

umask 077
mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"

: > "$LOG"
launchctl kickstart -k "gui/${USER_ID}/com.deeptutor.cloudflared"

URL=""
for _ in $(seq 1 60); do
  sleep 1
  URL=$(grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' "$LOG" 2>/dev/null | grep -v 'Requesting' | head -1)
  if [[ -n "$URL" ]]; then
    break
  fi
done

if [[ -z "$URL" ]]; then
  print -u2 "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: no DeepTutor tunnel URL captured"
  exit 1
fi

printf '{"url":"%s","updated":"%s"}\n' "$URL" "$(date '+%Y-%m-%dT%H:%M:%S%z')" > "$TEMP_FILE"
chmod 600 "$TEMP_FILE"
mv "$TEMP_FILE" "$STATE_FILE"
print "[$(date '+%Y-%m-%d %H:%M:%S')] DeepTutor tunnel rotated -> $URL"
