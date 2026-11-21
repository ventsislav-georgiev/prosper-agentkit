#!/bin/bash
# A Deployment's readiness, image and pods, one line per transition.
#
# Usage: k8s-deploy-watch.sh <kube-context> <namespace> <deployment>
#
# Unreachable: silent until the recovery line. Not found: loud (exit 2 at arm time, a line mid-watch).
# Pods: sorted <pod>@<12 hex of the imageID>, which shows a restart onto a re-pushed mutable tag.
# K8S_DEPLOY_WATCH_INTERVAL overrides the poll interval in seconds (default 300).
set -uo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $(basename "$0") <kube-context> <namespace> <deployment>" >&2
  exit 64
fi

CTX="$1"
NS="$2"
DEPLOY="$3"
INTERVAL="${K8S_DEPLOY_WATCH_INTERVAL:-300}"
# A non-number would turn the watch into a tight kubectl loop.
if [[ ! "$INTERVAL" =~ ^[1-9][0-9]*$ ]]; then
  echo "K8S_DEPLOY_WATCH_INTERVAL must be a positive integer (seconds), got '$INTERVAL'" >&2
  exit 64
fi

# --ignore-not-found tells gone (exit 0, empty) from unreachable (nonzero).
probe() {
  kubectl --context "$CTX" -n "$NS" get deploy "$DEPLOY" \
    --request-timeout=15s --ignore-not-found "$@" 2>/dev/null
}

# Arm-time check: refuse a watch that cannot report.
armed=$(probe -o name)
rc=$?
if [[ $rc -ne 0 ]]; then
  # Not fatal: usually the VPN is not up yet.
  echo "$(date -u +%H:%M:%SZ) cannot reach $CTX yet — arming anyway; the first reachable read reports"
elif [[ -z "$armed" ]]; then
  echo "$(date -u +%H:%M:%SZ) FATAL: no deployment $NS/$DEPLOY in $CTX." >&2
  echo "         Nothing to watch, and a watcher armed on a name that does not exist is worse than" >&2
  echo "         none: it stays silent, and silence here means 'nothing changed'. Check the" >&2
  echo "         namespace and the name — kubectl --context $CTX -n $NS get deploy" >&2
  exit 2
fi

prev=""
blind=1
selector=""
pods_prev=""
while true; do
  line=$(probe -o jsonpath='{.status.readyReplicas}/{.status.replicas} {.spec.template.spec.containers[0].image}')
  rc=$?
  if [[ -n "$line" ]]; then
    ready="${line%% *}"
    image="${line#* }"
    # Both fields are absent on a Deployment scaled to zero; the jsonpath renders "/".
    [[ "$ready" == /* ]] && ready="0$ready"
    [[ "$ready" == */ ]] && ready="${ready}0"
    # Image name plus 12 hex of the digest (or the tag): what tells one build from the next.
    image=$(sed -E 's#.*/##; s#@sha256:([0-9a-f]{12})[0-9a-f]*#@\1#' <<<"$image")
    line="$ready $image"
  fi
  if [[ $rc -ne 0 ]]; then
    blind=1
  elif [[ -z "$line" ]]; then
    # Deleted while being watched.
    if [[ "$prev" != "GONE" ]]; then
      echo "$(date -u +%H:%M:%SZ) $NS/$DEPLOY no longer exists in $CTX (was $prev)"
      prev="GONE"
      blind=0
    fi
  elif [[ $blind -eq 1 ]]; then
    echo "$(date -u +%H:%M:%SZ) cluster reachable again — $NS/$DEPLOY $line"
    blind=0
    prev="$line"
  elif [[ "$line" != "$prev" ]]; then
    echo "$(date -u +%H:%M:%SZ) $NS/$DEPLOY $prev -> $line"
    prev="$line"
  fi
  # Pods only after a read that found the Deployment.
  if [[ $rc -eq 0 && -n "$line" ]]; then
    if [[ -z "$selector" ]]; then
      # shellcheck disable=SC2016
      selector=$(probe -o go-template='{{range $k,$v := .spec.selector.matchLabels}}{{$k}}={{$v}},{{end}}')
      selector="${selector%,}"
    fi
    if [[ -n "$selector" ]] && raw=$(kubectl --context "$CTX" -n "$NS" get pods -l "$selector" \
        --request-timeout=15s 2>/dev/null \
        -o jsonpath='{range .items[*]}{.metadata.name}@{.status.containerStatuses[0].imageID}{"\n"}{end}'); then
      # imageID is <repo>@sha256:<64 hex>: keep 12 hex; empty after the @ is pending.
      pods=$(sed -E '/^$/d; s#@.*sha256:([0-9a-f]{12})[0-9a-f]*$#@\1#; s#@$#@pending#' <<<"$raw" \
        | sort | paste -sd, -)
      [[ -z "$pods" ]] && pods="none"
      if [[ -z "$pods_prev" ]]; then
        echo "$(date -u +%H:%M:%SZ) $NS/$DEPLOY pods $pods"
        pods_prev="$pods"
      elif [[ "$pods" != "$pods_prev" ]]; then
        echo "$(date -u +%H:%M:%SZ) $NS/$DEPLOY pods $pods_prev -> $pods"
        pods_prev="$pods"
      fi
    fi
  fi
  command sleep "$INTERVAL"
done
