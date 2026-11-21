#!/bin/bash
set -uo pipefail

# Watch one GitHub Actions workflow run until it ends, printing only transitions; silence means nothing changed.
#
# Usage:
#   gh-run-watch.sh <run-id> [owner/repo]
#   gh-run-watch.sh --sha <sha> --workflow <name or file substring, any case> [owner/repo]
#
# The --sha form waits while GitHub has not created the run yet. Exits 0 on success, 1 on any other conclusion.

REPO=""
RUN_ID=""
SHA=""
WORKFLOW=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sha) SHA="$2"; shift 2 ;;
    --workflow) WORKFLOW="$2"; shift 2 ;;
    */*) REPO="$1"; shift ;;
    *) RUN_ID="$1"; shift ;;
  esac
done

if [[ -z "$RUN_ID" && ( -z "$SHA" || -z "$WORKFLOW" ) ]]; then
  printf 'usage: %s <run-id> [owner/repo] | --sha <sha> --workflow <name> [owner/repo]\n' "${0##*/}" >&2
  exit 2
fi

# No owner/repo: the current folder's repo.
[[ -n "$REPO" ]] || REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)
if [[ ! "$REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  printf 'no owner/repo given and the current folder is not a GitHub repo gh can read — pass owner/repo\n' >&2
  exit 2
fi

# The runs endpoint matches head_sha exactly, so an abbreviated sha finds nothing and the watch reads "not created
# yet" forever — which is how it sat through a run that had already succeeded.
if [[ -n "$SHA" && ${#SHA} -lt 40 ]]; then
  if ! FULL=$(gh api "/repos/$REPO/commits/$SHA" --jq .sha 2>/dev/null) || [[ ! "$FULL" =~ ^[0-9a-f]{40}$ ]]; then
    printf 'no commit %s in %s — refusing to arm on a sha the API cannot resolve\n' "$SHA" "$REPO" >&2
    exit 2
  fi
  SHA="$FULL"
fi

# A run id from another repo (the current folder's repo when owner/repo was left off) is a 404 forever, which the loop
# below would read as "API unreachable" and sit silent on past the run's end.
if [[ -n "$RUN_ID" ]]; then
  if ! ARM_ERR=$(gh api "/repos/$REPO/actions/runs/$RUN_ID" --jq .id 2>&1 >/dev/null) && [[ "$ARM_ERR" == *"HTTP 404"* ]]; then
    printf 'no run %s in %s (pass owner/repo) — refusing to arm\n' "$RUN_ID" "$REPO" >&2
    exit 2
  fi
fi

ts() { date -u +%H:%M:%SZ; }

resolve_run() {
  gh api "/repos/$REPO/actions/runs?head_sha=$SHA" \
    --jq "(\"$WORKFLOW\" | ascii_downcase) as \$w | .workflow_runs[] | select((.name | ascii_downcase | contains(\$w)) or (.path | contains(\$w))) | .id" 2>/dev/null | head -1
}

LAST=""
STUCK=0

while :; do
  if [[ -z "$RUN_ID" ]]; then
    RUN_ID="$(resolve_run || true)"
    if [[ -z "$RUN_ID" ]]; then
      # Not created yet, or the API is unreachable. Both are "no transition" — stay quiet.
      STUCK=$((STUCK + 1))
      [[ $STUCK -eq 6 ]] && printf '%s no run named "%s" at %s yet after 5m\n' "$(ts)" "$WORKFLOW" "${SHA:0:8}"
      sleep 50
      continue
    fi
    printf '%s run %s resolved for "%s"\n' "$(ts)" "$RUN_ID" "$WORKFLOW"
    STUCK=0
  fi

  # Job-level state: failed step names are what matter.
  STATE="$(gh run view "$RUN_ID" -R "$REPO" --json status,conclusion,jobs \
    --jq '[.status, (.conclusion // "-"), ([.jobs[] | .name + "=" + (.conclusion // .status)] | join(" "))] | @tsv' 2>/dev/null || true)"
  # An unreachable API is not a transition: keep the previous state and say nothing.
  if [[ -z "$STATE" ]]; then
    sleep 50
    continue
  fi

  if [[ "$STATE" != "$LAST" ]]; then
    printf '%s run %s %s\n' "$(ts)" "$RUN_ID" "$STATE"
    LAST="$STATE"
  fi

  if [[ "${STATE%%	*}" == "completed" ]]; then
    REST="${STATE#*	}"
    CONCLUSION="${REST%%	*}"
    # The run's own address: no host is baked in.
    URL=$(gh run view "$RUN_ID" -R "$REPO" --json url --jq .url 2>/dev/null)
    printf '%s run %s TERMINAL %s %s\n' "$(ts)" "$RUN_ID" "$CONCLUSION" "${URL:-(no url)}"
    gh run view "$RUN_ID" -R "$REPO" --json jobs \
      --jq '.jobs[] | .name + ": " + (.conclusion // "?") + (if ([.steps[]?|select(.conclusion=="failure")|.name]|length) > 0 then " | failed steps: " + ([.steps[]?|select(.conclusion=="failure")|.name]|join(", ")) else "" end)' 2>/dev/null
    [[ "$CONCLUSION" == "success" ]] && exit 0
    exit 1
  fi

  sleep 50
done
