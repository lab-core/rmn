#!/usr/bin/env bash
# Deploy the whole RMN stack, optionally overriding the public hostname.
#
#   scripts/deploy.sh                  # host from deployment/kustomization.yaml
#   scripts/deploy.sh rmn.example.org  # override the host for this deploy
#   scripts/deploy.sh rmn.example.org --dry-run   # print manifests, apply nothing
#
# Kustomize has no notion of arguments, so a host override is done by building
# a throwaway overlay on top of deployment/ that merges the new value into the
# rmn-config ConfigMap and re-runs the Ingress host replacement.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
base="$repo_root/deployment"
host="${1:-}"
dry_run="${2:-}"

if [[ -z "$host" ]]; then
  target="$base"
else
  # kustomize refuses absolute resource paths, so the overlay is created next
  # to deployment/ (inside the repo, gitignored) and points at it relatively.
  overlay="$(mktemp -d "$repo_root/.deploy-overlay.XXXXXX")"
  trap 'rm -rf "$overlay"' EXIT
  cp "$base/host-replacements.yaml" "$overlay/"
  cat > "$overlay/kustomization.yaml" <<YAML
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../deployment
generatorOptions:
  disableNameSuffixHash: true
configMapGenerator:
  - name: rmn-config
    behavior: merge
    literals:
      - host=$host
replacements:
  - path: host-replacements.yaml
YAML
  target="$overlay"
fi

if [[ "$dry_run" == "--dry-run" ]]; then
  kubectl kustomize "$target"
else
  kubectl apply -k "$target"
fi
