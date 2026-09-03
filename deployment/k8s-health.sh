#!/usr/bin/env bash
#
# RMN cluster sentinel: inspect the Kubernetes cluster with kubectl and report
# anything unhealthy. Runs locally (scripts/k8s-health.sh) or in-cluster as
# the health-sentinel CronJob (deployment/health-sentinel.yml), which mounts
# this file from the k8s-health-script ConfigMap.
#
# Usage:
#   k8s-health.sh [options]
#     -n, --namespace NS         namespace to inspect          (default: default)
#     --host HOST                probe https://HOST/, /api/ and /socket.io/
#     --restart-threshold N      warn when a container restarted >= N times (5)
#     --pending-minutes N        pods Pending / not ready longer than N min (10)
#     --events-minutes N         report Warning events newer than N min (30)
#     --failed-jobs-hours N      report jobs that failed in the last N hours (24)
#     --slack                    post the report to Slack when there are issues
#     --slack-always             post even when everything is healthy
#     --state-configmap NAME     dedupe Slack alerts: only post when the set of
#                                issues changed since the last run, and post a
#                                recovery message when they clear
#     -q, --quiet                print nothing when healthy
#   Environment fallbacks: NAMESPACE, RMN_HOST, SLACK_TOKEN, SLACK_CHANNEL,
#   STATE_CONFIGMAP. Slack needs SLACK_TOKEN (bot token) and SLACK_CHANNEL.
#
# Exit status: 0 healthy, 1 warnings only, 2 at least one critical issue,
#              3 the cluster API itself is unreachable.
#
# Checks: API server readiness; aggregated APIServices; node Ready/pressure conditions; pods (Failed,
# Unknown, Pending too long, CrashLoopBackOff / image pull errors, containers
# not ready, restart count, OOMKilled); Deployments and ReplicationControllers
# with missing replicas; failed Jobs (KEDA executor runs); CronJobs without a
# recent success; PVC/PV not Bound; KEDA ScaledJob not Ready; recent Warning
# events; HTTP probes of the public host.
#
# Requires: bash, kubectl, jq, curl (for --host / --slack); busybox coreutils
# are enough (the CronJob runs it in alpine/k8s).
set -euo pipefail

namespace="${NAMESPACE:-default}"
host="${RMN_HOST:-}"
restart_threshold=5
pending_minutes=10
events_minutes=30
failed_jobs_hours=24
slack=0
slack_always=0
state_configmap="${STATE_CONFIGMAP:-}"
quiet=0

usage() { sed -n '3,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    -n|--namespace) namespace="${2:?}"; shift 2 ;;
    --host) host="${2:?}"; shift 2 ;;
    --restart-threshold) restart_threshold="${2:?}"; shift 2 ;;
    --pending-minutes) pending_minutes="${2:?}"; shift 2 ;;
    --events-minutes) events_minutes="${2:?}"; shift 2 ;;
    --failed-jobs-hours) failed_jobs_hours="${2:?}"; shift 2 ;;
    --slack) slack=1; shift ;;
    --slack-always) slack=1; slack_always=1; shift ;;
    --state-configmap) state_configmap="${2:?}"; shift 2 ;;
    -q|--quiet) quiet=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 1 ;;
  esac
done

for tool in kubectl jq; do
  command -v "$tool" >/dev/null || { echo "$tool is required" >&2; exit 1; }
done

# --- collectors --------------------------------------------------------------

critical=()   # things that are down / broken now
warning=()    # degraded, flapping, or worth a look
ok=()         # one-line summaries of healthy checks
events_summary=""

crit() { critical+=("$1"); }
warn() { warning+=("$1"); }
fine() { ok+=("$1"); }

# jq rows are joined with the ASCII unit separator instead of tabs: tabs are IFS
# whitespace for `read`, so consecutive empty fields would collapse and shift
# columns. `jqr` prepends the `row` helper to every query.
jqr() { local prog="${*: -1}"; jq -r "${@:1:$#-1}" '
def row: map(tostring)|join("\u001f"); '"$prog"; }

# kubectl wrapper: fails the whole run if the API cannot be reached, but treats
# a missing resource kind (e.g. KEDA not installed) as an empty list. stderr is
# kept apart from the JSON: kubectl prints warnings there (e.g. a broken
# aggregated API such as external.metrics.k8s.io) on otherwise successful calls.
kget() {
  local out err errf
  errf="$(mktemp)"
  if ! out="$(kubectl get "$@" -o json 2>"$errf")"; then
    err="$(cat "$errf")"; rm -f "$errf"
    if grep -qi "the server doesn't have a resource type\|no matches for kind" <<<"$err"; then
      echo '{"items":[]}'
      return 0
    fi
    echo "kubectl get $*: $err" >&2
    return 1
  fi
  rm -f "$errf"
  printf '%s' "$out"
}

# --- 0. API server ------------------------------------------------------------

if ! kubectl get --raw /readyz --request-timeout=15s >/dev/null 2>&1; then
  echo "CRITICAL: Kubernetes API server unreachable or not ready ($(kubectl config current-context 2>/dev/null || echo 'no context'))"
  exit 3
fi

# Aggregated APIs (metrics-server, KEDA external metrics, ...) that are not
# Available make every kubectl call print warnings and can break autoscaling.
apiservices="$(kget apiservices)"
while IFS=$'\x1f' read -r name msg; do
  [ -n "$name" ] && warn "apiservice $name unavailable: ${msg:-no details}"
done < <(jqr '.items[]|select(any((.status.conditions // [])[]; .type=="Available" and .status!="True"))
              |[.metadata.name, ((.status.conditions[]|select(.type=="Available")).message // "")]|row' <<<"$apiservices")

# --- 1. nodes -----------------------------------------------------------------

nodes="$(kget nodes)"
node_total="$(jq '.items|length' <<<"$nodes")"
node_ready="$(jq '[.items[]|select(any(.status.conditions[]; .type=="Ready" and .status=="True"))]|length' <<<"$nodes")"
while IFS=$'\x1f' read -r name reason; do
  [ -n "$name" ] && crit "node $name is not Ready (${reason:-unknown})"
done < <(jqr '.items[]|select(any(.status.conditions[]; .type=="Ready" and .status!="True"))
                 |[.metadata.name, ((.status.conditions[]|select(.type=="Ready")).reason // "")]|row' <<<"$nodes")
while IFS=$'\x1f' read -r name cond; do
  [ -n "$name" ] && warn "node $name reports $cond"
done < <(jqr '
.items[]|.metadata.name as $n|.status.conditions[]
                 |select((.type|test("Pressure$")) and .status=="True")|[$n,.type]|row' <<<"$nodes")
while IFS=$'\x1f' read -r name; do
  [ -n "$name" ] && warn "node $name is cordoned (unschedulable)"
done < <(jqr '
.items[]|select(.spec.unschedulable==true)|.metadata.name' <<<"$nodes")
fine "nodes $node_ready/$node_total Ready"

# --- 2. pods ------------------------------------------------------------------

pods="$(kget pods -n "$namespace")"
now_epoch="$(date -u +%s)"
pending_secs=$((pending_minutes * 60))

# Failed / Unknown / long-Pending pods (job pods are expected to Succeed, so a
# Failed job pod is a real signal too)
while IFS=$'\x1f' read -r name phase age_s owner reason; do
  [ -z "$name" ] && continue
  case "$phase" in
    Failed)  warn "pod $name Failed (${reason:-no reason}${owner:+, owner $owner})" ;;
    Unknown) crit "pod $name in Unknown state" ;;
    Pending)
      if [ "$age_s" -ge "$pending_secs" ]; then
        crit "pod $name Pending for $((age_s / 60)) min (${reason:-unscheduled})"
      fi ;;
  esac
done < <(jqr --argjson now "$now_epoch" '
  .items[]|select(.status.phase=="Failed" or .status.phase=="Unknown" or .status.phase=="Pending")
  |[.metadata.name, .status.phase,
    ($now - (.metadata.creationTimestamp|fromdateiso8601)),
    ((.metadata.ownerReferences // [])[0]|if . then "\(.kind)/\(.name)" else "" end),
    ((.status.reason // (.status.conditions // [] | map(select(.status=="False")) | .[0].reason)) // "")]
  |row' <<<"$pods")

# Running pods: container-level problems
while IFS=$'\x1f' read -r pod cname state restarts last_reason ready age_s deleting; do
  [ -z "$pod" ] && continue
  case "$state" in
    CrashLoopBackOff|ImagePullBackOff|ErrImagePull|CreateContainerConfigError|CreateContainerError|InvalidImageName)
      crit "pod $pod container $cname: $state" ;;
    *)
      if [ "$ready" = "false" ] && [ "$deleting" = "false" ] && [ "$age_s" -ge "$pending_secs" ]; then
        warn "pod $pod container $cname not ready for $((age_s / 60)) min (${state:-running})"
      fi ;;
  esac
  if [ "$restarts" -ge "$restart_threshold" ]; then
    warn "pod $pod container $cname restarted $restarts times${last_reason:+ (last: $last_reason)}"
  elif [ "$last_reason" = "OOMKilled" ]; then
    warn "pod $pod container $cname was OOMKilled"
  fi
done < <(jqr --argjson now "$now_epoch" '
  .items[]|select(.status.phase=="Running")
  |.metadata.name as $p
  |($now - (.metadata.creationTimestamp|fromdateiso8601)) as $age
  |(.metadata.deletionTimestamp != null) as $deleting
  |(.status.containerStatuses // [])[]
  |[$p, .name,
    (.state.waiting.reason // .state.terminated.reason // ""),
    .restartCount,
    (.lastState.terminated.reason // ""),
    (.ready|tostring), $age, ($deleting|tostring)]
  |row' <<<"$pods")

pod_running="$(jq '[.items[]|select(.status.phase=="Running")]|length' <<<"$pods")"
pod_total="$(jq '.items|length' <<<"$pods")"
fine "pods $pod_running Running / $pod_total total"

# --- 3. workloads -------------------------------------------------------------

deps="$(kget deployments -n "$namespace")"
while IFS=$'\x1f' read -r name want avail; do
  [ -z "$name" ] && continue
  if [ "$avail" -eq 0 ]; then crit "deployment $name has 0/$want available replicas"
  else warn "deployment $name has $avail/$want available replicas"; fi
done < <(jqr '
.items[]|select((.status.availableReplicas // 0) < (.spec.replicas // 1))
                 |[.metadata.name, (.spec.replicas // 1), (.status.availableReplicas // 0)]|row' <<<"$deps")
fine "deployments $(jq '[.items[]|select((.status.availableReplicas // 0) >= (.spec.replicas // 1))]|length' <<<"$deps")/$(jq '.items|length' <<<"$deps") fully available"

rcs="$(kget replicationcontrollers -n "$namespace")"
while IFS=$'\x1f' read -r name want ready; do
  [ -z "$name" ] && continue
  if [ "$ready" -eq 0 ]; then crit "replicationcontroller $name has 0/$want ready replicas"
  else warn "replicationcontroller $name has $ready/$want ready replicas"; fi
done < <(jqr '
.items[]|select((.status.readyReplicas // 0) < (.spec.replicas // 1))
                 |[.metadata.name, (.spec.replicas // 1), (.status.readyReplicas // 0)]|row' <<<"$rcs")
fine "replicationcontrollers $(jq '[.items[]|select((.status.readyReplicas // 0) >= (.spec.replicas // 1))]|length' <<<"$rcs")/$(jq '.items|length' <<<"$rcs") ready"

# --- 4. jobs / cronjobs / KEDA ------------------------------------------------

jobs="$(kget jobs -n "$namespace")"
failed_window=$((failed_jobs_hours * 3600))
failed_jobs="$(jqr --argjson now "$now_epoch" --argjson win "$failed_window" '
  [.items[]|select((.status.failed // 0) > 0)
   |select(($now - ((.status.completionTime // .metadata.creationTimestamp)|fromdateiso8601)) <= $win)
   |.metadata.name]|.[]' <<<"$jobs")"
if [ -n "$failed_jobs" ]; then
  n="$(wc -l <<<"$failed_jobs" | tr -d ' ')"
  warn "$n job(s) failed in the last ${failed_jobs_hours}h: $(head -5 <<<"$failed_jobs" | paste -sd, -)$([ "$n" -gt 5 ] && echo ',…')"
fi
active_jobs="$(jq '[.items[]|select((.status.active // 0) > 0)]|length' <<<"$jobs")"
fine "jobs $active_jobs active, $(jq '[.items[]|select((.status.succeeded // 0) > 0)]|length' <<<"$jobs") succeeded (retained)"

cronjobs="$(kget cronjobs -n "$namespace")"
while IFS=$'\x1f' read -r name last_ok; do
  [ -z "$name" ] && continue
  warn "cronjob $name has no successful run in the last 48h (last success: ${last_ok:-never})"
done < <(jqr --argjson now "$now_epoch" '
  .items[]|select(.spec.suspend != true)|select(.status.lastScheduleTime != null)
  |select((.status.lastSuccessfulTime == null) or (($now - (.status.lastSuccessfulTime|fromdateiso8601)) > 172800))
  |[.metadata.name, (.status.lastSuccessfulTime // "")]|row' <<<"$cronjobs")

scaledjobs="$(kget scaledjobs.keda.sh -n "$namespace")"
while IFS=$'\x1f' read -r name msg; do
  [ -z "$name" ] && continue
  crit "KEDA scaledjob $name not Ready: ${msg:-see kubectl describe scaledjob $name}"
done < <(jqr '
.items[]|select(any((.status.conditions // [])[]; .type=="Ready" and .status=="False"))
                 |[.metadata.name, ((.status.conditions[]|select(.type=="Ready")).message // "")]|row' <<<"$scaledjobs")
sj_total="$(jq '.items|length' <<<"$scaledjobs")"
[ "$sj_total" -gt 0 ] && fine "KEDA scaledjobs $sj_total present"

# --- 5. storage ---------------------------------------------------------------

pvcs="$(kget pvc -n "$namespace")"
while IFS=$'\x1f' read -r name phase; do
  [ -n "$name" ] && crit "pvc $name is $phase (expected Bound)"
done < <(jqr '.items[]|select(.status.phase != "Bound")|[.metadata.name, .status.phase]|row' <<<"$pvcs")
pvs="$(kget pv)"
while IFS=$'\x1f' read -r name phase; do
  [ -n "$name" ] && crit "pv $name is $phase"
done < <(jqr '.items[]|select(.status.phase == "Failed")|[.metadata.name, .status.phase]|row' <<<"$pvs")
fine "volumes $(jq '[.items[]|select(.status.phase=="Bound")]|length' <<<"$pvcs")/$(jq '.items|length' <<<"$pvcs") PVC bound, $(jq '.items|length' <<<"$pvs") PV"

# --- 6. recent Warning events -------------------------------------------------

events="$(kget events -n "$namespace" --field-selector type=Warning)"
events_summary="$(jq -r --argjson now "$now_epoch" --argjson win "$((events_minutes * 60))" '
  [.items[]
   |select((.lastTimestamp // .eventTime // .metadata.creationTimestamp) != null)
   |select(($now - ((.lastTimestamp // .eventTime // .metadata.creationTimestamp)|sub("\\.[0-9]+";"")|fromdateiso8601)) <= $win)]
  |group_by(.reason + " " + .involvedObject.kind + "/" + .involvedObject.name)
  |map({key: (.[0].reason + " " + .[0].involvedObject.kind + "/" + .[0].involvedObject.name),
        n: (map(.count // 1)|add), msg: (.[-1].message|.[0:110])})
  |sort_by(-.n)|.[0:8][]
  |"  \(.n)x \(.key): \(.msg)"' <<<"$events")"
event_count="$(grep -c . <<<"$events_summary" || true)"
if [ "$event_count" -gt 0 ]; then
  warn "$event_count distinct Warning event(s) in the last ${events_minutes} min (details below)"
else
  fine "no Warning events in the last ${events_minutes} min"
fi

# --- 7. HTTP probes -----------------------------------------------------------

if [ -n "$host" ]; then
  if command -v curl >/dev/null; then
    probe() { # url expected-regex label
      local code
      code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 -L "$1" 2>/dev/null || echo "000")"
      if [[ "$code" =~ $2 ]]; then fine "http $3 -> $code"; else crit "http $3 ($1) returned $code"; fi
    }
    probe "https://$host/" '^(200|30[0-9])$' "webapp"
    probe "https://$host/api/" '^200$' "server api"
    probe "https://$host/socket.io/?EIO=4&transport=polling" '^200$' "socketio"
  else
    warn "curl not available: HTTP probes of $host skipped"
  fi
fi

# --- report -------------------------------------------------------------------

status=0
[ "${#warning[@]}" -gt 0 ] && status=1
[ "${#critical[@]}" -gt 0 ] && status=2

stamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
context="$(kubectl config current-context 2>/dev/null || echo in-cluster)"
report="RMN cluster health — $stamp — context $context, namespace $namespace"$'\n'
case $status in
  0) report+="STATUS: OK"$'\n' ;;
  1) report+="STATUS: WARNING (${#warning[@]})"$'\n' ;;
  2) report+="STATUS: CRITICAL (${#critical[@]} critical, ${#warning[@]} warning)"$'\n' ;;
esac
if [ "${#critical[@]}" -gt 0 ]; then
  report+="CRITICAL:"$'\n'; for l in "${critical[@]}"; do report+="  - $l"$'\n'; done
fi
if [ "${#warning[@]}" -gt 0 ]; then
  report+="WARNING:"$'\n'; for l in "${warning[@]}"; do report+="  - $l"$'\n'; done
fi
if [ -n "$events_summary" ]; then
  report+="Recent Warning events:"$'\n'"$events_summary"$'\n'
fi
report+="OK:"$'\n'; for l in "${ok[@]}"; do report+="  - $l"$'\n'; done

if [ "$quiet" -eq 0 ] || [ "$status" -ne 0 ]; then
  printf '%s' "$report"
fi

# --- Slack (optional, deduplicated through a ConfigMap) -----------------------

if [ "$slack" -eq 1 ]; then
  if [ -z "${SLACK_TOKEN:-}" ] || [ -z "${SLACK_CHANNEL:-}" ]; then
    echo "Slack requested but SLACK_TOKEN / SLACK_CHANNEL not set; skipping." >&2
  else
    # Fingerprint of the *issues* only (events are transient noise): alerts are
    # re-sent only when a problem appears or disappears.
    if command -v sha256sum >/dev/null; then sha() { sha256sum; }; else sha() { shasum -a 256; }; fi  # busybox vs macOS
    fingerprint="$(printf '%s\n' "${critical[@]:-}" "${warning[@]:-}" | grep -v "Warning event" | sort | sha | cut -c1-16)"
    previous=""
    if [ -n "$state_configmap" ]; then
      previous="$(kubectl get configmap "$state_configmap" -n "$namespace" -o jsonpath='{.data.fingerprint}' 2>/dev/null || true)"
    fi
    post=0
    if [ "$slack_always" -eq 1 ]; then post=1
    elif [ -z "$state_configmap" ]; then [ "$status" -ne 0 ] && post=1
    elif [ "$fingerprint" != "$previous" ]; then
      # changed: post issues, or a recovery notice if we went back to healthy
      if [ "$status" -ne 0 ] || [ -n "$previous" ]; then post=1; fi
    fi
    if [ "$post" -eq 1 ]; then
      case $status in
        0) icon="✅"; headline="RMN cluster recovered: all checks healthy" ;;
        1) icon="⚠️"; headline="RMN cluster warning" ;;
        *) icon="🚨"; headline="RMN cluster CRITICAL" ;;
      esac
      text="$icon $headline"$'\n''```'$'\n'"$report"'```'
      resp="$(jq -n --arg ch "$SLACK_CHANNEL" --arg t "$text" '{channel:$ch,text:$t}' \
        | curl -sS --max-time 15 -X POST https://slack.com/api/chat.postMessage \
            -H "Authorization: Bearer $SLACK_TOKEN" -H 'Content-Type: application/json' -d @- || echo '{"ok":false,"error":"curl failed"}')"
      if [ "$(jq -r .ok <<<"$resp")" != "true" ]; then
        echo "Slack post failed: $(jq -r '.error // .' <<<"$resp")" >&2
      fi
    fi
    if [ -n "$state_configmap" ] && [ "$fingerprint" != "$previous" ]; then
      kubectl create configmap "$state_configmap" -n "$namespace" \
        --from-literal=fingerprint="$fingerprint" --from-literal=updated="$stamp" \
        --dry-run=client -o yaml | kubectl apply -f - >/dev/null \
        || echo "could not save state to configmap $state_configmap" >&2
    fi
  fi
fi

exit $status
