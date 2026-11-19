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
# rolls the Deployment out; the new pod pulls the tag again. The annotation
# keeps a runtime that records another digest than the registry's (a platform
# manifest instead of the index) from restarting the pods at every run.
#
# The Jobs (executor, trainer, idle-sweep) always run the newest image: each
# run starts a new pod, which pulls the tag. But the executor image is large,
# and the first task after a release would wait for that pull. With
# --executor SCALEDJOB, a new image of that KEDA ScaledJob wakes an executor
# right away, as `minikube-helper.sh -r` does (GET /admin/executor queues an
# empty job), so the node holds the image before a task needs it. The digest
# it woke an executor for is kept in the annotation rmn/executor-digest of the
# CronJob named by --state-cronjob (default image-update).
#
#   deployment/image-update.sh server socketio webapp
#   deployment/image-update.sh --dry-run server     # report, change nothing
#   deployment/image-update.sh --executor job-executor server socketio webapp
#
# Environment: NAMESPACE (default: the current one), SLACK_TOKEN and
# SLACK_CHANNEL to announce each rollout (optional); for --executor,
# ADMIN_API_KEY and SERVER_URL (no /api prefix, default http://server:5000).
# Requires: bash, kubectl, jq, curl.
set -euo pipefail

ANNOTATION="rmn/image-digest"
EXECUTOR_ANNOTATION="rmn/executor-digest"
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
    -h|--help) sed -n '2,35p' "$0"; exit 0 ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *) deployments+=("$1") ;;
  esac
  shift
done
if [ "${#deployments[@]}" -eq 0 ] && [ -z "$executor" ]; then
  echo "usage: $0 [--dry-run] [--executor SCALEDJOB] DEPLOYMENT..." >&2; exit 2
fi

ns_args=()
[ -n "${NAMESPACE:-}" ] && ns_args=(-n "$NAMESPACE")

# registry digest of a Docker Hub image reference "repo:tag" (repo without a
# "/" is an official library image)
hub_digest() {
  local repo="${1%:*}" tag="${1##*:}" token
  [[ "$repo" == */* ]] || repo="library/$repo"
  token="$(curl -fsS --max-time 15 \
    "https://auth.docker.io/token?service=registry.docker.io&scope=repository:${repo}:pull" \
    | jq -r .token)"
  curl -fsSI --max-time 15 \
    -H "Authorization: Bearer $token" \
    -H 'Accept: application/vnd.oci.image.index.v1+json' \
    -H 'Accept: application/vnd.docker.distribution.manifest.list.v2+json' \
    -H 'Accept: application/vnd.docker.distribution.manifest.v2+json' \
    -H 'Accept: application/vnd.oci.image.manifest.v1+json' \
    "https://registry-1.docker.io/v2/${repo}/manifests/${tag}" \
    | tr -d '\r' | awk 'tolower($1) == "docker-content-digest:" {print $2}'
}

slack() {
  [ -n "${SLACK_TOKEN:-}" ] && [ -n "${SLACK_CHANNEL:-}" ] || return 0
  jq -n --arg ch "$SLACK_CHANNEL" --arg t "$1" '{channel:$ch,text:$t}' \
    | curl -sS --max-time 15 -X POST https://slack.com/api/chat.postMessage \
        -H "Authorization: Bearer $SLACK_TOKEN" -H 'Content-Type: application/json' -d @- \
    | jq -e .ok > /dev/null || echo "Slack post failed" >&2
}

# "repo:tag" of an image reference, ":latest" added when it has no tag; fails
# on an image pinned by digest
image_tag() {
  local image="$1"
  [[ "$image" == *@* ]] && return 1
  [[ "${image##*/}" == *:* ]] || image="$image:latest"
  echo "$image"
}

status=0
for name in "${deployments[@]+"${deployments[@]}"}"; do
  if ! dep="$(kubectl "${ns_args[@]}" get deployment "$name" -o json)"; then
    status=1; continue
  fi
  image="$(jq -r '.spec.template.spec.containers[0].image' <<<"$dep")"
  if ! image="$(image_tag "$image")"; then
    echo "$name: pinned by digest, skipped"; continue
  fi
  if ! latest="$(hub_digest "$image")" || [ -z "$latest" ]; then
    echo "$name: cannot read the digest of $image on Docker Hub" >&2
    status=1; continue
  fi
  recorded="$(jq -r --arg a "$ANNOTATION" '.spec.template.metadata.annotations[$a] // ""' <<<"$dep")"
  selector="$(jq -r '.spec.selector.matchLabels | to_entries | map("\(.key)=\(.value)") | join(",")' <<<"$dep")"
  running="$(kubectl "${ns_args[@]}" get pods -l "$selector" \
    -o jsonpath='{range .items[*]}{.status.containerStatuses[0].imageID}{"\n"}{end}')"

  if [ "$latest" = "$recorded" ]; then
    echo "$name: $image is $latest, already rolled out"; continue
  fi
  if [ -n "$running" ] && ! grep -qv "@${latest}\$" <<<"$running"; then
    echo "$name: $image is $latest, already running"; continue
  fi
  echo "$name: $image is now $latest (running: $(echo "${running:-none}" | sed 's/.*@//' | sort -u | tr '\n' ' '))"
  if [ "$dry_run" -eq 1 ]; then continue; fi
  patch="$(jq -n --arg a "$ANNOTATION" --arg d "$latest" \
    '{spec:{template:{metadata:{annotations:{($a):$d}}}}}')"
  if kubectl "${ns_args[@]}" patch deployment "$name" -p "$patch" > /dev/null; then
    echo "$name: rolled out"
    slack ":rocket: ${name} redémarré sur ${image} (${latest:7:12})"
  else
    status=1
  fi
done

# --- the executor: wake one when its image changed ---------------------------
wake_executor() {
  local image latest woken code
  if ! image="$(kubectl "${ns_args[@]}" get scaledjob "$executor" \
      -o jsonpath='{.spec.jobTargetRef.template.spec.containers[0].image}')"; then
    return 1
  fi
  if ! image="$(image_tag "$image")"; then
    echo "$executor: pinned by digest, skipped"; return 0
  fi
  if ! latest="$(hub_digest "$image")" || [ -z "$latest" ]; then
    echo "$executor: cannot read the digest of $image on Docker Hub" >&2
    return 1
  fi
  woken="$(kubectl "${ns_args[@]}" get cronjob "$state_cronjob" -o json \
    | jq -r --arg a "$EXECUTOR_ANNOTATION" '.metadata.annotations[$a] // ""')" || return 1
  if [ "$latest" = "$woken" ]; then
    echo "$executor: $image is $latest, an executor already pulled it"; return 0
  fi
  echo "$executor: $image is now $latest, waking an executor to pull it"
  [ "$dry_run" -eq 1 ] && return 0
  if [ -z "${ADMIN_API_KEY:-}" ]; then
    echo "$executor: ADMIN_API_KEY is not set, cannot wake an executor" >&2
    return 1
  fi
  # the key goes through curl's config on stdin, not the argv
  code="$(printf 'header = "X-Admin-Key: %s"\n' "$ADMIN_API_KEY" \
    | curl -sS --max-time 30 --retry 3 --retry-all-errors --config - \
        -o /dev/null -w '%{http_code}' "${SERVER_URL:-http://server:5000}/admin/executor")" \
    || code="unreachable"
  if [ "$code" != 200 ]; then
    echo "$executor: the server answered $code to /admin/executor" >&2
    return 1
  fi
  # recorded only once an executor was asked for: a failure retries next run
  kubectl "${ns_args[@]}" annotate --overwrite cronjob "$state_cronjob" \
    "$EXECUTOR_ANNOTATION=$latest" > /dev/null || return 1
  echo "$executor: executor woken"
}
if [ -n "$executor" ]; then
  wake_executor || status=1
fi

exit "$status"
