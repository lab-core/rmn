#!/usr/bin/env bash
# Put the published images inside the minikube node over the local link,
# instead of letting the kubelet pull them from Docker Hub.
#
#   scripts/preload-images.sh                  # all four services, :main
#   scripts/preload-images.sh socketio server  # only these
#   scripts/preload-images.sh --tag 1.6.7      # another tag
#
# Run it ON the cluster host, before rolling out (`minikube-helper.sh -p -r`
# does both).
#
# Why this exists: a pull from inside the node runs at about 10 KB/s, so a
# 99 MB image takes six and a half minutes and a three-service rollout takes
# thirteen, because the kubelet pulls one image at a time. The same pull on
# the host runs at ~77 MB/s and the host-to-node link at ~1.2 GB/s.
#
# The cause is outside this repository: inbound packets for any container on
# this host are dropped while being forwarded (the kernel counts them in
# Ip.FragFails, having needed to fragment a forwarded packet whose DF bit is
# set). The segments arrive coalesced in pairs, too big for the 1500-byte
# bridge, because Hyper-V's vSwitch does receive segment coalescing before
# the packets reach the VM -- `rx-gro-hw` reads `off [fixed]` on hv_netvsc,
# so nothing inside the guest can turn it off. The fix is on the hypervisor
# (`Set-VMSwitch -EnableSoftwareRsc $false`); until then, this script keeps
# deploys fast. Delete it once that is done.
#
# The deployments keep `imagePullPolicy: Always`: with the image already in
# the node, the kubelet only fetches the manifest, which is small enough to
# cross the broken path in well under a second.
set -euo pipefail

SERVICES=(server webapp socketio executor)
TAG=main
REGISTRY=rmni

usage() {
  cat <<'USAGE'
Put the published images inside the minikube node over the local link.

  scripts/preload-images.sh                  all four services, :main
  scripts/preload-images.sh socketio server  only these
  scripts/preload-images.sh --tag 1.6.7      another tag

Run it on the cluster host, before rolling out; minikube-helper.sh -p -r
does both. The header of this file says why it is needed.
USAGE
  exit "${1:-0}"
}

wanted=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage 0 ;;
    -t|--tag) TAG="${2:?--tag needs a value}"; shift 2 ;;
    -*) echo "unknown option: $1" >&2; usage 2 >&2 ;;
    *) wanted+=("$1"); shift ;;
  esac
done
[[ ${#wanted[@]} -gt 0 ]] && SERVICES=("${wanted[@]}")

for cmd in docker minikube; do
  command -v "$cmd" >/dev/null || {
    echo "$cmd not found: run this on the cluster host, not from a laptop" >&2
    exit 1
  }
done

# The node's image ids, read once: `minikube ssh` consumes stdin, which eats
# the rest of a piped script, so it is always given /dev/null.
node_image_id() {
  minikube ssh -- docker images -q "$1" </dev/null 2>/dev/null | tr -d '\r' | head -1
}

failed=0
for service in "${SERVICES[@]}"; do
  image="${REGISTRY}/${service}:${TAG}"
  printf '%-28s ' "$image"

  if ! docker pull -q "$image" >/dev/null 2>&1; then
    echo "pull FAILED"
    failed=1
    continue
  fi
  host_id=$(docker images -q "$image" | head -1)

  if [[ -n "$host_id" && "$host_id" == "$(node_image_id "$image")" ]]; then
    echo "already in the node (${host_id})"
    continue
  fi

  start=$SECONDS
  if minikube image load "$image" </dev/null >/dev/null 2>&1; then
    echo "loaded in $((SECONDS - start))s (${host_id})"
  else
    echo "load FAILED"
    failed=1
  fi
done

exit "$failed"
