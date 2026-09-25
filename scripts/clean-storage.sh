#!/usr/bin/env bash
#
# Sweep the storage share: report, and optionally delete, the files and
# folders that no longer belong to any row of the database (jobs deleted while
# the share was unreachable, uploads interrupted mid-write, ...), and the jobs
# of the database none of whose files are left on the share.
#
# It calls POST /admin/storage/clean on the server, which owns the layout and
# is the only process with the share mounted. Reports by default; deleting
# takes --delete.
#
# Usage:
#   scripts/clean-storage.sh                     # dry run, 24 h age guard
#   scripts/clean-storage.sh --delete            # delete the orphans
#   scripts/clean-storage.sh --min-age-hours 1   # widen the sweep
#   scripts/clean-storage.sh --usage             # add disk usage by file age
#   scripts/clean-storage.sh --delete --include-strays
#   scripts/clean-storage.sh --delete --include-empty-jobs  # also drop the jobs
#                                                           # without any file
#   RMN_URL=http://localhost scripts/clean-storage.sh
#
# ADMIN_API_KEY must be exported (README "Admin commands"); in the cluster:
#   export ADMIN_API_KEY=$(kubectl get secret rmn-secrets \
#     -o jsonpath="{.data['admin-api-key']}" | base64 -d)
#
set -euo pipefail

url="${RMN_URL:-http://localhost}"
dry_run=true
include_strays=false
include_empty_jobs=false
usage=false
min_age_hours=24

while [ $# -gt 0 ]; do
  case "$1" in
    --delete)          dry_run=false ;;
    --include-strays)  include_strays=true ;;
    --include-empty-jobs) include_empty_jobs=true ;;
    --usage)           usage=true ;;
    --min-age-hours)   min_age_hours="${2:?--min-age-hours needs a value}"; shift ;;
    --url)             url="${2:?--url needs a value}"; shift ;;
    -h|--help)         sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)                 echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

if [ -z "${ADMIN_API_KEY:-}" ]; then
  echo "ADMIN_API_KEY is not set; see README \"Admin commands\"." >&2
  exit 1
fi

if [ "$dry_run" = false ]; then
  echo "==> This DELETES files from the storage share. Run without --delete first."
  if [ "$include_empty_jobs" = true ]; then
    echo "==> It also DELETES from the database every job listed under empty_jobs."
  fi
  read -rp "Type 'delete' to continue: " answer
  [ "$answer" = "delete" ] || { echo "Aborted."; exit 1; }
fi

# the key travels in the header, never in the argv or the query string; the
# status code is appended on a line of its own so an error page is not fed
# to jq
response=$(curl -sS -w '\n%{http_code}' -X POST \
  -H "X-Admin-Key: $ADMIN_API_KEY" \
  -H "Content-Type: multipart/form-data" \
  --form "dry_run=$dry_run" \
  --form "include_strays=$include_strays" \
  --form "include_empty_jobs=$include_empty_jobs" \
  --form "usage=$usage" \
  --form "min_age_hours=$min_age_hours" \
  "$url/api/admin/storage/clean")
code="${response##*$'\n'}"
response="${response%$'\n'*}"

if [ "$code" != "200" ]; then
  echo "Server answered HTTP $code at $url:" >&2
  head -c 300 <<<"$response" >&2
  echo >&2
  if [ "$code" = "502" ] || [ "$code" = "504" ]; then
    echo "A 502/504 comes from the proxy: after a rebuild of the local stack," \
      "restart nginx (docker restart rmn-nginx-1)." >&2
  fi
  if [ "$dry_run" = false ]; then
    echo "The sweep may have started before the error: run a dry run to see" \
      "what is left." >&2
  fi
  exit 1
fi

if command -v jq >/dev/null 2>&1; then
  echo "$response" | jq '
    {response, dry_run, bytes, too_recent, scanned,
     orphans: (.orphans // [] | length), strays: (.strays // [] | length),
     empty_jobs: (.empty_jobs // [] | length),
     deleted: (.deleted // [] | length),
     deleted_jobs: (.deleted_jobs // [] | length), failed: (.failed // []),
     missing: (.missing // []), usage}'
  echo "--- paths ---"
  echo "$response" | jq -r '
    ((.orphans // [])[] | "\(.reason)\t\(.path)"),
    ((.strays // [])[] | "stray (kept unless --include-strays)\t\(.path)")'
  echo "--- jobs without any file ---"
  echo "$response" | jq -r '(.empty_jobs // [])[]
    | "\(.job_id)\t\(.job_status)\t\(.user_id)\t"
      + (if .age_seconds == null then "?" else "\(.age_seconds / 86400 | floor)d" end)
      + "\t\(.job_name)"'
else
  echo "$response"
fi
