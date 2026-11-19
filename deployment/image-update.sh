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
# The Jobs (executor, trainer, idle-sweep) need nothing: each run starts a new
# pod, which pulls the tag.
#
#   deployment/image-update.sh server socketio webapp
#   deployment/image-update.sh --dry-run server     # report, change nothing
#
# Environment: NAMESPACE (default: the current one), SLACK_TOKEN and
# SLACK_CHANNEL to announce each rollout (optional).
# Requires: bash, kubectl, jq, curl.
set -euo pipefail

ANNOTATION="rmn/image-digest"
dry_run=0
deployments=()
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=1 ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    -*) echo "unknown option: $arg" >&2; exit 2 ;;
    *) deployments+=("$arg") ;;
  esac
done
[ "${#deployments[@]}" -gt 0 ] || { echo "usage: $0 [--dry-run] DEPLOYMENT..." >&2; exit 2; }

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

status=0
for name in "${deployments[@]}"; do
  if ! dep="$(kubectl "${ns_args[@]}" get deployment "$name" -o json)"; then
    status=1; continue
  fi
  image="$(jq -r '.spec.template.spec.containers[0].image' <<<"$dep")"
  if [[ "$image" == *@* ]]; then
    echo "$name: $image is pinned by digest, skipped"; continue
  fi
  [[ "${image##*/}" == *:* ]] || image="$image:latest"
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
exit "$status"
