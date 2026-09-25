#!/usr/bin/env bash
#
# Monthly storage report: asks the server for a dry run of the storage sweep
# plus a disk usage summary (POST /admin/storage/clean, dry_run=true,
# usage=true) and posts both to Slack: GB used by files older than 0, 30, 90,
# 180 and 365 days, then the orphans, if any. It never deletes: the share
# should hold no orphans, so a finding is a bug to look at, and the operator
# deletes by hand with scripts/clean-storage.sh --delete after reading it.
#
# Runs as the storage-report CronJob (deployment/storage-report.yml), which
# mounts this file from the storage-report-script ConfigMap.
#
# Environment:
#   ADMIN_API_KEY    operator secret of the /admin/* endpoints (required)
#   SERVER_URL       server base URL, no /api prefix (default http://server:5000)
#   MIN_AGE_HOURS    skip paths modified more recently (default 720, 30 days)
#   SLACK_TOKEN, SLACK_CHANNEL   post the findings; without them the report
#                    only goes to the job log
#
# Exit status: 0 the report ran (findings or not), 1 the sweep or the Slack
# post failed, so the Job fails and the health sentinel reports it.
#
# Requires: bash, curl, jq (the CronJob runs it in alpine/k8s).
set -euo pipefail

server_url="${SERVER_URL:-http://server:5000}"
min_age_hours="${MIN_AGE_HOURS:-720}"
max_paths=20

slack() { # text
  if [ -z "${SLACK_TOKEN:-}" ] || [ -z "${SLACK_CHANNEL:-}" ]; then
    echo "SLACK_TOKEN / SLACK_CHANNEL not set; report left in the job log." >&2
    return 0
  fi
  local resp
  resp="$(jq -n --arg ch "$SLACK_CHANNEL" --arg t "$1" '{channel:$ch,text:$t}' \
    | curl -sS --max-time 15 -X POST https://slack.com/api/chat.postMessage \
        -H "Authorization: Bearer $SLACK_TOKEN" -H 'Content-Type: application/json' -d @- \
    || echo '{"ok":false,"error":"curl failed"}')"
  if [ "$(jq -r .ok <<<"$resp")" != "true" ]; then
    echo "Slack post failed: $(jq -r '.error // .' <<<"$resp")" >&2
    return 1
  fi
}

fail() { # message
  echo "$1" >&2
  slack "🚨 RMN storage report failed: $1" || true
  exit 1
}

[ -n "${ADMIN_API_KEY:-}" ] || fail "ADMIN_API_KEY is not set"

# The sweep walks the whole share and sizes every orphan: allow it time (the
# server's gunicorn timeout is 30 min, the Job deadline 20 min).
body="$(mktemp)"
code="$(curl -sS --max-time 900 -o "$body" -w '%{http_code}' -X POST \
  -H "X-Admin-Key: $ADMIN_API_KEY" \
  --form "dry_run=true" \
  --form "usage=true" \
  --form "min_age_hours=$min_age_hours" \
  "$server_url/admin/storage/clean" 2>&1)" || fail "server unreachable: $code"
[ "$code" = "200" ] || fail "server returned HTTP $code: $(head -c 300 "$body")"
report="$(cat "$body")"
jq -e .orphans >/dev/null <<<"$report" || fail "unexpected answer: $(head -c 300 <<<"$report")"

# disk usage: one line per age threshold, then the filesystem itself. Padded
# in jq: busybox (alpine/k8s) has no `column`.
usage="$(jq -r '
  def gb: . / 1e9 * 10 | round / 10 | tostring + " GB";
  def pad($n): tostring | (" " * ([$n - length, 0] | max)) + .;
  (.usage.older_than_days | to_entries | sort_by(.key | tonumber)[]
   | (if .key == "0" then "all files" else "older than \(.key)d" end) as $label
   | "\($label + " " * (15 - ($label | length)))\(.value.bytes | gb | pad(10))"
     + "\(.value.files | pad(10)) files"),
  (.usage.disk // empty
   | "disk           \(.used | gb) used of \(.total | gb), \(.free | gb) free")
  ' <<<"$report")"

orphans="$(jq '.orphans|length' <<<"$report")"
strays="$(jq '.strays|length' <<<"$report")"
missing="$(jq '.missing|length' <<<"$report")"
summary="$(jq -r --argjson h "$min_age_hours" '
  "\(.orphans|length) orphan(s), \(.bytes / 1e9 * 10 | round / 10) GB"
  + " | \(.strays|length) stray(s) | \(.missing|length) template row(s) without image"
  + " (older than \($h)h; scanned \(.scanned.jobs) job and"
  + " \(.scanned.templates) template path(s))"' <<<"$report")"
echo "$usage"
echo "Storage sweep: $summary"

text="📦 RMN storage, monthly report"$'\n''```'$'\n'"$usage"$'\n''```'
if [ "$orphans" -eq 0 ] && [ "$strays" -eq 0 ] && [ "$missing" -eq 0 ]; then
  text+=$'\n'"✅ No orphan files ($summary)."
else
  # every path goes to the log; Slack gets the first $max_paths
  paths="$(jq -r '
    (.orphans[] | "orphan  \(.reason)  \(.path)"),
    (.strays[]  | "stray   \(.path)"),
    (.missing[] | "missing \(.)")' <<<"$report")"
  echo "$paths"
  total="$(wc -l <<<"$paths" | tr -d ' ')"
  shown="$(head -n "$max_paths" <<<"$paths")"
  [ "$total" -gt "$max_paths" ] && shown+=$'\n'"… $((total - max_paths)) more in the job log"
  text+=$'\n'"⚠️ $summary"$'\n''```'$'\n'"$shown"$'\n''```'
  text+=$'\n'"Nothing was deleted. Review with \`scripts/clean-storage.sh --min-age-hours $min_age_hours\`,"
  text+=" then add \`--delete\`."
fi
slack "$text"
