#!/usr/bin/env bash
# Deploy the whole RMN stack, optionally overriding the public hostname and
# the storage backend.
#
#   scripts/deploy.sh                  # host from deployment/kustomization.yaml
#   scripts/deploy.sh rmn.example.org  # override the host for this deploy
#   scripts/deploy.sh rmn.example.org --dry-run   # print manifests, apply nothing
#   scripts/deploy.sh --dry-run        # same, with the configured host
#   scripts/deploy.sh --storage nfs    # NFS storage (README "Storage")
#
# --storage hostpath (the default) deploys deployment/ as it is: server and
# executors mount the node directory /data/nfs. --storage nfs adds the
# deployment/components/nfs component (in-cluster NFS server + NFS mounts); do
# not combine it with a `components:` entry enabled in kustomization.yaml.
#
# Kustomize has no notion of arguments, so an override is done by building a
# throwaway overlay on top of deployment/ that merges the new host into the
# rmn-config ConfigMap (and re-runs the Ingress host replacement) and/or adds
# the nfs component.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
base="$repo_root/deployment"
host=""
dry_run=""
storage="hostpath"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) dry_run="--dry-run" ;;
    --storage)
      [[ $# -ge 2 ]] || { echo "--storage needs a value: hostpath or nfs" >&2; exit 2; }
      storage="$2"; shift ;;
    --storage=*) storage="${1#--storage=}" ;;
    --*) echo "unknown option: $1" >&2; exit 2 ;;
    *) host="$1" ;;
  esac
  shift
done
case "$storage" in
  hostpath|nfs) ;;
  *) echo "--storage must be hostpath or nfs, not '$storage'" >&2; exit 2 ;;
esac

if [[ -z "$host" && "$storage" == "hostpath" ]]; then
  target="$base"
else
  # kustomize refuses absolute resource paths, so the overlay is created next
  # to deployment/ (inside the repo, gitignored) and points at it relatively.
  overlay="$(mktemp -d "$repo_root/.deploy-overlay.XXXXXX")"
  trap 'rm -rf "$overlay"' EXIT
  cat > "$overlay/kustomization.yaml" <<YAML
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
# the base sets it on its own resources only, not on the component's
namespace: default
resources:
  - ../deployment
YAML
  if [[ "$storage" == "nfs" ]]; then
    cat >> "$overlay/kustomization.yaml" <<YAML
components:
  - ../deployment/components/nfs
YAML
  fi
  if [[ -n "$host" ]]; then
    cp "$base/replacements.yaml" "$overlay/"
    cat >> "$overlay/kustomization.yaml" <<YAML
generatorOptions:
  disableNameSuffixHash: true
configMapGenerator:
  - name: rmn-config
    behavior: merge
    literals:
      - host=$host
replacements:
  - path: replacements.yaml
YAML
  fi
  target="$overlay"
fi

if [[ "$dry_run" == "--dry-run" ]]; then
  kubectl kustomize "$target"
else
  kubectl apply -k "$target"
fi
