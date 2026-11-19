#!/usr/bin/env bash
# Roll out a Deployment when its image tag points at a new image on Docker Hub.
#
# The Deployments run moving tags (rmni/server:main) with imagePullPolicy
# Always, so a restart is all it takes to run a newly published image, but
# nothing restarted them. For each Deployment named on the command line, this
# script reads the digest the tag points at now (a HEAD on the registry, which
# does not count against Docker Hub's pull limit) and compares it with:
#   - the image the running pods were started from (their imageID), and
#   - the digest this script last rolled the Deployment out for (the pod
#     template annotation rmn/image-digest).
# When it matches neither, the annotation is set to the new digest, which
# rolls the Deployment out; the new pod pulls the tag again. A runtime may
# record the digest of the platform's manifest rather than the registry's
# index: before a first rollout, the pods are then compared with the index's
# manifests too, and afterwards the annotation keeps them from being restarted
# at every run.
#
# The Jobs (executor, trainer, idle-sweep) always run the newest image: each
# run starts a new pod, which pulls the tag. But the executor image is large,
# and the first task after a release would wait for that pull. With
# --executor SCALEDJOB, a new image of that KEDA ScaledJob wakes an executor
# right away, as `minikube-helper.sh -r` does (GET /admin/executor queues an
# empty job), so the node holds the image before a task needs it. The digest
# it woke an executor for is kept in the annotation rmn/executor-digest of the
# CronJob named by --state-cronjob (default image-update). Without an admin
# key (the /admin endpoints are then off), the executor is left alone.
#
#   deployment/image-update.sh server socketio webapp
#   deployment/image-update.sh --dry-run server     # report, change nothing
#   deployment/image-update.sh --executor job-executor server socketio webapp
#
# Exit status: 1 when the cluster refused something (a missing Deployment, a
# denied patch), which needs a person. Docker Hub or the server out of reach
# is only reported: the next run tries again, and a failed Job every 5
# minutes would keep the health sentinel alerting for a day.
#
# Environment: NAMESPACE (default: the current one), SLACK_TOKEN and
# SLACK_CHANNEL to announce each rollout (optional); for --executor,
# ADMIN_API_KEY and SERVER_URL (no /api prefix, default http://server:5000).
# Requires: bash (3.2 is enough), kubectl, jq, curl.
set -euo pipefail

ANNOTATION="rmn/image-digest"
EXECUTOR_ANNOTATION="rmn/executor-digest"

usage() {
  # the header comment above, without its "# "
  awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
}

dry_run=0
executor=""
state_cronjob="image-update"
deployments=()
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry_run=1 ;;
    --executor|--state-cronjob)
      [ $# -ge 2 ] || { echo "$1 needs a value" >&2; exit 2; }
      if [ "$1" = --executor ]; then executor="$2"; else state_cronjob="$2"; fi
      shift ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *) deployments+=("$1") ;;
  esac
  shift
done
if [ "${#deployments[@]}" -eq 0 ] && [ -z "$executor" ]; then
  echo "usage: $0 [--dry-run] [--executor SCALEDJOB] DEPLOYMENT..." >&2; exit 2
fi

# never an empty array: bash before 4.4 calls "${a[@]}" of one unbound
kc=(kubectl)
[ -n "${NAMESPACE:-}" ] && kc+=(-n "$NAMESPACE")

# "repo:tag" of an image reference, ":latest" added when it has no tag; fails
# on an image pinned by digest
image_tag() {
  local image="$1"
  [[ "$image" == *@* ]] && return 1
  [[ "${image##*/}" == *:* ]] || image="$image:latest"
  echo "$image"
}

# Docker Hub repository of "repo:tag" (an official image is library/<name>)
hub_repo() {
  local repo="${1%:*}"
  [[ "$repo" == */* ]] || repo="library/$repo"
  echo "$repo"
}

# one anonymous pull token for every repository of the run (set by hub_login)
token=""
hub_login() {
  local scopes="" image
  for image in "$@"; do
    scopes="$scopes&scope=repository:$(hub_repo "$image"):pull"
  done
  token="$(curl -fsS --max-time 15 \
    "https://auth.docker.io/token?service=registry.docker.io$scopes" | jq -r .token)" \
    && [ -n "$token" ] && [ "$token" != null ]
}

ACCEPT=(
  -H 'Accept: application/vnd.oci.image.index.v1+json'
  -H 'Accept: application/vnd.docker.distribution.manifest.list.v2+json'
  -H 'Accept: application/vnd.docker.distribution.manifest.v2+json'
  -H 'Accept: application/vnd.oci.image.manifest.v1+json'
)

# digest the tag of "repo:tag" points at (a HEAD: outside the pull limit)
hub_digest() {
  curl -fsSI --max-time 15 -H "Authorization: Bearer $token" "${ACCEPT[@]}" \
    "https://registry-1.docker.io/v2/$(hub_repo "$1")/manifests/${1##*:}" \
    | tr -d '\r' | awk 'tolower($1) == "docker-content-digest:" {print $2}'
}

# the platforms' manifests of an index (a GET, so only when needed)
hub_children() {
  curl -fsS --max-time 15 -H "Authorization: Bearer $token" "${ACCEPT[@]}" \
    "https://registry-1.docker.io/v2/$(hub_repo "$1")/manifests/$2" \
    | jq -r '.manifests[]?.digest'
}

slack() {
  [ -n "${SLACK_TOKEN:-}" ] && [ -n "${SLACK_CHANNEL:-}" ] || return 0
  local resp
  resp="$(jq -n --arg ch "$SLACK_CHANNEL" --arg t "$1" '{channel:$ch,text:$t}' \
    | curl -sS --max-time 15 -X POST https://slack.com/api/chat.postMessage \
        -H "Authorization: Bearer $SLACK_TOKEN" -H 'Content-Type: application/json' -d @- \
    || echo '{"ok":false,"error":"curl failed"}')"
  if [ "$(jq -r .ok <<<"$resp" 2>/dev/null)" != true ]; then
    echo "Slack post failed: $(jq -r '.error // .' <<<"$resp" 2>/dev/null || echo "$resp")" >&2
  fi
}

status=0

# --- read the cluster first: the images to ask Docker Hub about -------------
names=()
specs=()
images=()
for name in "${deployments[@]+"${deployments[@]}"}"; do
  if ! dep="$("${kc[@]}" get deployment "$name" -o json)"; then
    status=1; continue
  fi
  image="$(jq -r '.spec.template.spec.containers[0].image' <<<"$dep")"
  if ! image="$(image_tag "$image")"; then
    echo "$name: pinned by digest, skipped"; continue
  fi
  names+=("$name"); specs+=("$dep"); images+=("$image")
done
executor_image=""
if [ -n "$executor" ]; then
  if executor_image="$("${kc[@]}" get scaledjob "$executor" \
      -o jsonpath='{.spec.jobTargetRef.template.spec.containers[0].image}')"; then
    if ! executor_image="$(image_tag "$executor_image")"; then
      echo "$executor: pinned by digest, skipped"; executor_image=""
    fi
  else
    status=1; executor_image=""
  fi
fi

all_images=("${images[@]+"${images[@]}"}")
[ -n "$executor_image" ] && all_images+=("$executor_image")
if [ "${#all_images[@]}" -eq 0 ]; then exit "$status"; fi
if ! hub_login "${all_images[@]}"; then
  echo "Docker Hub unreachable (token), next run tries again" >&2
  exit "$status"
fi

# --- the Deployments ----------------------------------------------------------
i=0
while [ "$i" -lt "${#names[@]}" ]; do
  name="${names[$i]}"; dep="${specs[$i]}"; image="${images[$i]}"
  i=$((i + 1))
  if ! latest="$(hub_digest "$image")" || [ -z "$latest" ]; then
    echo "$name: cannot read the digest of $image on Docker Hub, next run tries again" >&2
    continue
  fi
  recorded="$(jq -r --arg a "$ANNOTATION" '.spec.template.metadata.annotations[$a] // ""' <<<"$dep")"
  if [ "$latest" = "$recorded" ]; then
    echo "$name: $image is $latest, already rolled out"; continue
  fi
  selector="$(jq -r '.spec.selector.matchLabels | to_entries | map("\(.key)=\(.value)") | join(",")' <<<"$dep")"
  if ! running="$("${kc[@]}" get pods -l "$selector" \
      -o jsonpath='{range .items[*]}{.status.containerStatuses[0].imageID}{"\n"}{end}')"; then
    status=1; continue
  fi
  running="$(sed -n 's/.*@//p' <<<"$running" | sort -u)"
  # the pods run it when each one has its index or, before any rollout of
  # ours, one of its platforms' manifests
  current="$latest"
  if [ -z "$recorded" ] && [ -n "$running" ] && grep -qvxF "$latest" <<<"$running"; then
    current="$(printf '%s\n' "$latest"; hub_children "$image" "$latest" || true)"
  fi
  if [ -n "$running" ] && ! grep -qvxF -f <(printf '%s\n' "$current") <<<"$running"; then
    echo "$name: $image is $latest, already running"; continue
  fi
  echo "$name: $image is now $latest (running: $(tr '\n' ' ' <<<"${running:-none}"))"
  [ "$dry_run" -eq 1 ] && continue
  patch="$(jq -n --arg a "$ANNOTATION" --arg d "$latest" \
    '{spec:{template:{metadata:{annotations:{($a):$d}}}}}')"
  if "${kc[@]}" patch deployment "$name" -p "$patch" > /dev/null; then
    echo "$name: rolled out"
    slack ":rocket: ${name} redémarré sur ${image} (${latest:7:12})"
  else
    status=1
  fi
done

# --- the executor: wake one when its image changed ---------------------------
wake_executor() {
  local latest woken code
  if ! latest="$(hub_digest "$executor_image")" || [ -z "$latest" ]; then
    echo "$executor: cannot read the digest of $executor_image on Docker Hub, next run tries again" >&2
    return 0
  fi
  woken="$("${kc[@]}" get cronjob "$state_cronjob" -o json \
    | jq -r --arg a "$EXECUTOR_ANNOTATION" '.metadata.annotations[$a] // ""')" || return 1
  if [ "$latest" = "$woken" ]; then
    echo "$executor: $executor_image is $latest, an executor already pulled it"; return 0
  fi
  if [ -z "${ADMIN_API_KEY:-}" ]; then
    echo "$executor: $executor_image is now $latest; no admin key, the /admin endpoints are off: not woken"
    return 0
  fi
  echo "$executor: $executor_image is now $latest, waking an executor to pull it"
  [ "$dry_run" -eq 1 ] && return 0
  # the key goes through curl's config on stdin, not the argv
  code="$(printf 'header = "X-Admin-Key: %s"\n' "$ADMIN_API_KEY" \
    | curl -sS --max-time 30 --retry 3 --retry-all-errors --config - \
        -o /dev/null -w '%{http_code}' "${SERVER_URL:-http://server:5000}/admin/executor")" \
    || code="unreachable"
  if [ "$code" != 200 ]; then
    # recorded only once an executor was asked for: the next run tries again
    echo "$executor: the server answered $code to /admin/executor, next run tries again" >&2
    return 0
  fi
  "${kc[@]}" annotate --overwrite cronjob "$state_cronjob" \
    "$EXECUTOR_ANNOTATION=$latest" > /dev/null || return 1
  echo "$executor: executor woken"
}
if [ -n "$executor_image" ]; then
  wake_executor || status=1
fi

exit "$status"
