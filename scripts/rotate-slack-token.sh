#!/usr/bin/env bash
#
# Rotate the Slack bot token used by the server health check.
#
# The old token was committed to git history, so it MUST be revoked/regenerated
# in Slack (this script cannot do that part). Then run this script with the new
# token to update the cluster Secret and roll the server.
#
# Usage:
#   scripts/rotate-slack-token.sh <new-xoxb-token>
#   scripts/rotate-slack-token.sh           # prompts for the token (not echoed)
#
set -euo pipefail

SECRET_NAME="rmn-secrets"
SECRET_KEY="slack-token"

new_token="${1:-}"
if [ -z "$new_token" ]; then
  read -rsp "New Slack bot token (input hidden): " new_token
  echo
fi
if [ -z "$new_token" ]; then
  echo "No token provided; aborting." >&2
  exit 1
fi

echo "==> Reminders before you continue:"
echo "    1. Revoke/regenerate the OLD token in the Slack app settings."
echo "    2. The old token is in git history — revoking in Slack is the real fix."
echo

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl not found; skipping cluster update." >&2
else
  echo "==> Updating the '$SECRET_KEY' key in Secret '$SECRET_NAME' ..."
  # patch the single key without touching the others (stringData is auto-encoded)
  kubectl patch secret "$SECRET_NAME" \
    --type merge \
    -p "{\"stringData\":{\"$SECRET_KEY\":\"$new_token\"}}"

  echo "==> Rolling the server deployment to pick up the new token ..."
  kubectl rollout restart deployment/server
  kubectl rollout status deployment/server --timeout=120s || true
fi

# keep local docker-compose in sync if a .env is present
if [ -f .env ]; then
  echo "==> Updating SLACK_TOKEN in ./.env ..."
  if grep -q '^SLACK_TOKEN=' .env; then
    tmp="$(mktemp)"
    # replace the line without printing the token
    awk -v t="$new_token" '/^SLACK_TOKEN=/{print "SLACK_TOKEN=" t; next} {print}' .env > "$tmp"
    mv "$tmp" .env
  else
    printf 'SLACK_TOKEN=%s\n' "$new_token" >> .env
  fi
  echo "    (run 'docker compose up -d server' to apply locally)"
fi

echo "==> Done. New token stored in the cluster Secret${SLACK_LOCAL:+ and ./.env}."
