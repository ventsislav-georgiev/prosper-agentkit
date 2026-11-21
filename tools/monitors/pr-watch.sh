#!/bin/bash
# One line per state transition of a pull request, plus self-healing for the ways a PR gets stuck
# on infrastructure rather than on its own code. Exits once the PR is merged or closed.
#
# Usage: pr-watch.sh <pr-number|url> [owner/repo] [local-repo-dir]
#
# Passing a local repo dir enables the last-resort retrigger: an empty commit pushed with plumbing,
# which is the only retrigger that works when a provider outage killed the runs the merge gate
# reads. Without it the watcher still reruns jobs, it just cannot escalate.
#
# Needs gh, jq, curl. Kit settings ai_reviewer, actions_status_url (KIT_*; the unprefixed env names win).
set -uo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: ${0##*/} <pr-number|url> [owner/repo] [local-repo-dir]" >&2
  exit 64
fi
PR="$1"
REPO="${2:-}"
REPO_DIR="${3:-}"
R=()
[[ -n "$REPO" ]] && R=(-R "$REPO")

# Resolved once rather than left empty: infra_failure builds a `repos/$REPO/actions/jobs/` path, so an omitted repo
# argument silently turned every rerun probe into a 404 and read as "no infra failure" — the watcher healed nothing
# and said nothing.
[[ -z "$REPO" ]] && REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)
PR_NUM="${PR##*/}"

INTERVAL=${INTERVAL:-300}
AUTOMERGE=${AUTOMERGE:-1}          # 0 to only watch, never merge
MERGE_METHOD=${MERGE_METHOD:-squash}
STUCK_POLLS=${STUCK_POLLS:-6}      # ~30 min at the default interval
ESCALATE_AFTER=${ESCALATE_AFTER:-2} # reruns per head sha before pushing an empty commit
# The bot whose CHANGES_REQUESTED re-runs only on a push or a `/ai-review` comment.
AI_REVIEWER=${AI_REVIEWER:-${KIT_AI_REVIEWER:-}}  # empty: every reviewer is treated as a human
# Status page components.json; empty: no outage hold.
STATUS_URL=${ACTIONS_STATUS_URL:-${KIT_ACTIONS_STATUS_URL:-}}

log() { echo "$(date -u +%H:%M:%SZ) PR $PR $*"; }

# Watches have died with 128+16 while their processes were still alive, which reads as "nobody looked" and is the one
# failure this script exists to avoid.
trap '' URG PIPE
for _sig in TERM INT QUIT HUP; do
  # shellcheck disable=SC2064 # $_sig must expand now, at trap-installation time
  trap "log 'watch ending on SIG$_sig'; exit 0" "$_sig"
done
unset _sig

# A second watcher on the same PR doubles every poll and, worse, doubles the healing: two instances that both see the
# same infra failure push two empty commits.
kill_duplicate_watchers() {
  local pid args other other_pr other_repo
  for pid in $(pgrep -f 'pr-watch\.sh' 2>/dev/null); do
    [[ "$pid" == "$$" || "$pid" == "$PPID" ]] && continue
    args=$(ps -o args= -p "$pid" 2>/dev/null) || continue
    other=$(awk '{for(i=1;i<=NF;i++) if($i ~ /pr-watch\.sh$/){print $(i+1), $(i+2); exit}}' <<<"$args")
    other_pr="${other%% *}"
    other_repo="${other#* }"
    [[ "${other_pr##*/}" == "$PR_NUM" ]] || continue
    if [[ "$other_repo" == */* && "$other_repo" != "$REPO" ]]; then continue; fi
    kill "$pid" 2>/dev/null && log "killed duplicate watcher (pid $pid) of PR $PR_NUM"
  done
}

# gh's table prints cancelled checks in the same `fail` column as real failures, so a run its own concurrency group
# cancelled reads as dozens of failures and every one of them looks infra-shaped: a cancelled job has no failed step.
failed_urls() {
  gh pr checks "$PR" "${R[@]}" --json bucket,link 2>/dev/null |
    jq -r '.[]|select(.bucket=="fail")|.link'
}

# A job that failed without a single failed step never ran its own code: the runner could not resolve an action, could
# not reach the registry, or was evicted.
infra_failure() {
  local url id
  while read -r url; do
    [[ "$url" == *"/job/"* ]] || continue
    id="${url##*/job/}"
    if [[ -z "$(gh api "repos/$REPO/actions/jobs/$id" 2>/dev/null |
      jq -r '.steps[]?|select(.conclusion=="failure")|.name')" ]]; then
      return 0
    fi
  done < <(failed_urls)
  return 1
}

rerun_failed() {
  local url run n=0
  while read -r url; do
    run="${url##*/runs/}"
    run="${run%%/*}"
    [[ -n "$run" ]] || continue
    gh run rerun "$run" --failed "${R[@]}" >/dev/null 2>&1 && n=$((n + 1))
  done < <(failed_urls | sed -E 's#/job/[0-9]+##' | sort -u)
  [[ $n -gt 0 ]]
}

# Reruns re-run the same workflow file against the same commit; when the outage broke checks the merge gate reads by
# name, only a new commit re-attaches them.
empty_commit() {
  local branch c head
  [[ -n "$REPO_DIR" ]] || return 1
  branch=$(gh pr view "$PR" "${R[@]}" --json headRefName -q .headRefName 2>/dev/null) || return 1
  [[ -n "$branch" ]] || return 1
  git -C "$REPO_DIR" fetch -q origin "$branch" 2>/dev/null || return 1
  head=$(git -C "$REPO_DIR" rev-parse "origin/$branch" 2>/dev/null) || return 1
  c=$(git -C "$REPO_DIR" commit-tree "$head^{tree}" -p "$head" -m "chore: retrigger CI") || return 1
  git -C "$REPO_DIR" push -q origin "$c:refs/heads/$branch" 2>/dev/null || return 1
  log "empty commit ${c:0:10} pushed to $branch"
}

# One escalation ladder for every flavour of stuck, because the cure is the same and classifying them precisely buys
# nothing: rerun what failed, then force a fresh commit, then say so out loud.
provider_down() {
  local s
  [[ -n "$STATUS_URL" ]] || return 1
  s=$(curl -fsS "$STATUS_URL" 2>/dev/null |
    jq -r '.components[]|select(.name=="Actions")|.status')
  [[ -n "$s" && "$s" != operational ]]
}

heal() {
  local reason="$1"
  if provider_down; then
    [[ "$waiting" == "1" ]] || log "$reason — GitHub Actions is not operational; holding the retrigger"
    waiting=1
    return
  fi
  if [[ "$waiting" == "1" ]]; then
    log "GitHub Actions operational again — retriggering"
    waiting=0
    reruns=0
    cooldown=0
  fi
  if [[ $reruns -lt $ESCALATE_AFTER ]] && rerun_failed; then
    reruns=$((reruns + 1))
    log "$reason — rerunning failed jobs (attempt $reruns on ${sha:0:10})"
    return
  fi
  # A provider outage lasts hours and fails every retrigger the same way, so escalation is rate limited: one new
  # commit per cooldown, not one per poll.
  if [[ $cooldown -gt 0 ]]; then
    return
  fi
  if empty_commit; then
    reruns=0
    cooldown=$STUCK_POLLS
    return
  fi
  log "$reason — cannot self-heal (no rerunnable jobs, no local repo dir); needs a human"
}

# What the comments say, not how many there are.
report_comments() {
  local since="$1"
  gh api "repos/$REPO/pulls/$PR_NUM/comments" --paginate \
    --jq "[.[]|select(.id > $since)]|.[]|\"    \(.user.login) on \(.path):\(.line // .original_line // 0)\n      \" + ((.body|split(\"\n\")|map(select(length>0 and (startswith(\"<!--\")|not))))[0:2]|join(\" / \")|.[0:300])" 2>/dev/null
}

# The AI review workflow's own account of why it produced nothing.
review_missing_note() {
  local url id
  url=$(gh pr checks "$PR" "${R[@]}" --json name,bucket,link 2>/dev/null |
    jq -r '.[]|select(.bucket=="fail" and .name=="review / review-missing")|.link' | head -1)
  [[ "$url" == *"/job/"* ]] || return 1
  id="${url##*/job/}"
  gh api "repos/$REPO/check-runs/$id/annotations" 2>/dev/null |
    jq -r '[.[]|select(.annotation_level=="failure")|.message|select(startswith("Process completed")|not)]|.[0] // empty' |
    cut -c1-300
}

# What re-runs the review when the answers needed no code change.
retrigger_hint() {
  if [[ -n "$AI_REVIEWER" && "${cr_author:-}" == "$AI_REVIEWER" ]]; then
    echo "comment \`/ai-review\` on the PR (the AI reviewer re-runs only on a push or that comment; resolving threads triggers nothing)"
  else
    echo "request a re-review from ${cr_author:-the reviewer}"
  fi
}

# Every way a PR sits still looks the same from the outside — one line that stops changing — but they are owed to
# different people, and a generic "STUCK" read as "something is broken" on PRs that were merely waiting on their
# author.
stuck_report() {
  local mins=$((STUCK_POLLS * INTERVAL / 60))
  if [[ ${pending_jobs:-${pending:-0}} -gt 0 ]]; then
    log "STUCK ${mins}m: $line — holding retrigger, ${pending} check(s) still queued"
  elif [[ "$mss" == BEHIND ]]; then
    # Attempted once per head sha: a repo that refuses the update refuses it every poll, and the refusal is the thing
    # worth saying rather than repeating the attempt.
    if [[ "$updated_sha" == "$sha" ]]; then
      author_owes=1
      log "STUCK m: behind base and the branch update did not take — needs a manual rebase"
    elif gh pr update-branch "$PR" "${R[@]}" >/dev/null 2>&1; then
      updated_sha="$sha"
      log "behind base — branch updated"
    else
      updated_sha="$sha"
      author_owes=1
      log "STUCK m: behind base and update-branch was refused — needs a manual rebase"
    fi
  elif [[ "$mss" == DIRTY ]]; then
    author_owes=1
    log "STUCK m: merge conflict with the base branch — no retrigger clears this, needs a human"
  elif [[ "${unresolved:-0}" -gt 0 ]]; then
    author_owes=1
    log "STUCK ${mins}m: waiting on the AUTHOR — ${_rest}, ${unresolved} unresolved thread(s); reply, resolve, then push"
  elif [[ "$_rest" == CHANGES_REQUESTED ]]; then
    # A CHANGES_REQUESTED review outlives the comments it was made of: resolving every thread does not dismiss it,
    # only a newer review from the same reviewer does.
    if [[ -n "${changes_requested_sha:-}" && "$changes_requested_sha" != "-" && "$changes_requested_sha" != "$sha" ]]; then
      log "STUCK ${mins}m: waiting on a REVIEWER — every thread resolved and the head moved since the review; the CHANGES_REQUESTED stands until a fresh review dismisses it"
    else
      author_owes=1
      log "STUCK ${mins}m: waiting on the AUTHOR — CHANGES_REQUESTED with no unresolved threads left and nothing pushed since; push a change, or re-trigger without one: $(retrigger_hint)"
    fi
  elif [[ "$_rest" == REVIEW_REQUIRED ]]; then
    # Red outranks the review state here, because the two lines say opposite things about who is owed and only one of
    # them can be true.
    if [[ -n "$bad" ]]; then
      log "STUCK ${mins}m: waiting on a REVIEWER, but the board is RED — ${bad}; no review runs against a red head, so nothing moves until it is green"
    else
      log "STUCK ${mins}m: waiting on a REVIEWER — checks are clean and nothing is owed by the author"
    fi
  elif [[ -n "$bad" || $no_checks -eq 1 ]]; then
    # No checks at all is not "nothing to fix" — a throttled or dropped webhook leaves a PR with no run to rerun, and
    # only a new commit re-attaches one.
    heal "stuck ${mins}m: $line"
  elif [[ "${draft_reviewers:-}" == true\ * ]]; then
    # mergeable_now sets draft_reviewers as a side effect on every poll, so a draft reaches here named.
    log "STUCK ${mins}m: waiting on the AUTHOR — still a draft, nothing to retrigger"
  else
    log "STUCK ${mins}m: $line"
  fi
}

# A repo with no required checks and no required reviews reports CLEAN the moment the PR opens, so CLEAN alone never
# means ready — the check counts do.
mergeable_now() {
  [[ "$mss" == CLEAN || "${_mss:-}" == UNKNOWN ]] || return 1
  [[ -z "$bad" && "${pending:-0}" == 0 && $no_checks -eq 0 ]] || return 1
  case "$_rest" in CHANGES_REQUESTED | REVIEW_REQUIRED) return 1 ;; esac
  draft_reviewers=$(gh pr view "$PR" "${R[@]}" --json isDraft,reviewRequests \
    -q '(.isDraft|tostring)+" "+(.reviewRequests|length|tostring)' 2>/dev/null) || return 1
  [[ "$draft_reviewers" == false\ * ]]
}

merge_now() {
  # --auto first (a repo with required checks queues); plain merge where auto-merge is off.
  if gh pr merge "$PR" "${R[@]}" "--$MERGE_METHOD" --auto >/dev/null 2>&1 ||
    gh pr merge "$PR" "${R[@]}" "--$MERGE_METHOD" >/dev/null 2>&1; then
    [[ $was_ready -eq 1 ]] || log "ready and unblocked — merge requested ($MERGE_METHOD)"
  elif [[ "${_mss:-}" == UNKNOWN ]]; then
    # A refusal while GitHub is still computing mergeability says nothing about the PR; giving up merging for the rest
    # of the watch on it would turn a transient into a human's job.
    [[ $was_ready -eq 1 ]] || log "ready but the merge was refused while mergeStateStatus is UNKNOWN — retrying every poll"
  else
    log "ready but merge was rejected — needs a human"
    AUTOMERGE=0
  fi
}

# Merging is held to a stricter bar than announcing: never merge out from under a reviewer still on the request list.
ready_step() {
  local hold="" unknown=""
  [[ "$draft_reviewers" == "false 0" ]] || hold="${draft_reviewers##false } reviewer(s) still requested"
  [[ "${_mss:-}" == UNKNOWN ]] && unknown=" (mergeStateStatus UNKNOWN — GitHub is still computing it)"
  if [[ "$AUTOMERGE" == 1 && -z "$hold" ]]; then
    merge_now
  elif [[ $was_ready -eq 0 ]]; then
    if [[ "$AUTOMERGE" == 1 ]]; then
      log "MERGEABLE but not merging: ${hold} — this watch never merges out from under a requested reviewer; merge by hand or drop the request${unknown}"
    else
      log "MERGEABLE: approved, every check green — GitHub would merge this now, waiting on a human${hold:+ (${hold} — does not block the merge)}${unknown}"
    fi
  fi
  was_ready=1
}

# tests/monitors.test.sh sources this file to call its functions in isolation; without a stop here the source would
# enter the poll loop and never return.
[[ -n "${PR_WATCH_NO_LOOP:-}" ]] && { return 0 2>/dev/null || exit 0; }

kill_duplicate_watchers

prev=""
prev_comment=""
# Empty until the first poll: whatever is already on the PR when the watch starts is the baseline, not a round that
# just arrived.
seen_comment=""
sha=""
mss=""
reruns=0
stuck=0
query_fails=0
cooldown=0
waiting=0
was_ready=0
updated_sha=""
ci_red_seen=""
review_missing_seen=""
prev_unresolved=0
cr_author="-"

while true; do
  s=$(gh pr view "$PR" "${R[@]}" --json state,mergeStateStatus,reviewDecision,headRefOid \
    -q '.state+" "+.mergeStateStatus+" "+(.reviewDecision//"-")+" "+.headRefOid' 2>/dev/null || true)
  if [[ -z "$s" ]]; then
    # The API being unreachable is not a PR transition.
    query_fails=$((query_fails + 1))
    [[ $((query_fails % STUCK_POLLS)) -eq 0 ]] &&
      log "unreadable for $((query_fails * INTERVAL / 60))m — check auth, network, or VPN"
    command sleep "$INTERVAL"
    continue
  fi
  query_fails=0
  [[ $cooldown -gt 0 ]] && cooldown=$((cooldown - 1))

  new_sha="${s##* }"
  s="${s% *}"

  # GitHub reports mergeStateStatus=UNKNOWN while it recomputes mergeability after a push — it is the absence of an
  # answer, not a new state.
  read -r _st _mss _rest <<<"$s"
  if [[ "$_mss" == "UNKNOWN" && -n "$mss" ]]; then
    s="$_st $mss $_rest"
  elif [[ "$_mss" != "UNKNOWN" ]]; then
    mss="$_mss"
  fi
  if [[ "$new_sha" != "$sha" ]]; then
    sha="$new_sha"
    reruns=0
  fi

  # An empty check list means "nothing attached" only when gh says so.
  checks=$(gh pr checks "$PR" "${R[@]}" --json name,bucket 2>&1 || true)
  no_checks=0
  [[ "$checks" == *"no checks reported"* ]] && no_checks=1
  bad=$(jq -r '[.[]|select(.bucket=="fail")|.name]|join(",")' <<<"$checks" 2>/dev/null)
  pending=$(jq -r '[.[]|select(.bucket=="pending")]|length' <<<"$checks" 2>/dev/null)
  # Queued JOBS, which is not the same set as pending checks.
  pending_jobs=$(jq -r '[.[]|select(.bucket=="pending")|select(.name|test("Required reviewers")|not)]|length' <<<"$checks" 2>/dev/null)
  # CI's verdict without the AI review's own checks.
  ci_bad=$(jq -r '[.[]|select(.bucket=="fail")|select(.name|test("^(ai-)?review / ")|not)|.name]|join(",")' <<<"$checks" 2>/dev/null)

  # reviewDecision alone is too coarse to be the review signal. PR_WATCH_HELD_THREADS: comma-separated thread ids
  # (PRRT_...) held open by agreement; they do not count as owed by the author.
  threads=$(gh api graphql \
    -f query='query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n){pullRequest(number:$p){reviews(last:20,states:[CHANGES_REQUESTED]){nodes{commit{oid} author{login}}} latestReview:reviews(last:1){nodes{submittedAt}} reviewThreads(last:100){nodes{id isResolved comments(last:1){nodes{databaseId}}}}}}}' \
    -F o="${REPO%%/*}" -F n="${REPO##*/}" -F p="$PR_NUM" \
    -q '.data.repository.pullRequest as $pr
        | ((env.PR_WATCH_HELD_THREADS // "") | split(",") | map(select(length > 0))) as $held
        | [$pr.reviewThreads.nodes[]|select(.isResolved==false)|select(.id as $i|($held|index($i))|not)] as $u
        | "\($u|length) \([$u[].comments.nodes[].databaseId]|max // 0) \($pr.reviews.nodes[-1].commit.oid // "-") \($pr.latestReview.nodes[-1].submittedAt // "-") \($pr.reviews.nodes[-1].author.login // "-")"' 2>/dev/null || true)
  # A failed query is not "all threads resolved".
  thread_re='^[0-9]+ [0-9]+ [0-9a-f-]+ [0-9TZ:.-]+ []A-Za-z0-9_.[-]+$'
  if [[ "$threads" =~ $thread_re ]]; then
    read -r unresolved newest_comment changes_requested_sha latest_review cr_author <<<"$threads"
  fi

  line="$s ${bad:+failing=$bad}${pending:+ pending=$pending}"
  [[ "${unresolved:-0}" -gt 0 ]] && line="$line unresolved=$unresolved"

  # What is compared is not what is printed: the newest comment id has to move the signature so a second round of
  # comments counts as a transition, but a bare id on the line is noise in a log whose whole point is that every line
  # is worth reading.
  sig="$line ${newest_comment:-0} ${latest_review:--}"
  # Strip both trailing fields: `${prev% *}` would leave the comment id on and never match again.
  if [[ "$sig" != "$prev" && "$line" == "${prev% * *}" && -n "$prev" ]]; then
    # Name which of the two moved.
    if [[ "${newest_comment:-0}" == "$prev_comment" ]]; then
      line="$line — new review"
    else
      line="$line — new comment"
    fi
  fi
  if [[ "$sig" != "$prev" ]]; then
    log "$line"
    prev="$sig"
    prev_comment="${newest_comment:-0}"
    stuck=0
  else
    stuck=$((stuck + 1))
  fi

  # Three states the line shows but does not explain, each said once per head so the explanation lands with the
  # transition and not on every poll after it.
  if [[ -n "$ci_bad" && "$ci_bad@$sha" != "$ci_red_seen" ]]; then
    ci_red_seen="$ci_bad@$sha"
    log "CI RED on ${sha:0:10}: $ci_bad — no AI review runs against a red head (the review workflow skips it as skipped_ci); fix and push, which re-triggers CI and the review together, or rerun the job if it was flaky"
  fi
  # review-missing red means the diff was never reviewed, not that it was reviewed and found wanting.
  if [[ "$bad" == *"review / review-missing"* && "$sha" != "$review_missing_seen" ]]; then
    review_missing_seen="$sha"
    note=$(review_missing_note)
    log "AI REVIEW MISSING on ${sha:0:10}: ${note:-no review was produced} — once the cause has cleared, comment \`/ai-review\` to re-trigger (a push re-triggers it too)"
  fi
  # Resolving the last thread moves the state line but starts no run.
  if [[ "${prev_unresolved:-0}" -gt 0 && "${unresolved:-0}" -eq 0 && "$_rest" == CHANGES_REQUESTED && "${changes_requested_sha:-}" == "$sha" ]]; then
    log "every thread resolved with nothing pushed since the CHANGES_REQUESTED on ${sha:0:10} — if the answers needed no code change, $(retrigger_hint)"
  fi
  prev_unresolved="${unresolved:-0}"

  # A round of comments ends the watch rather than waiting out a stuck window.
  if [[ -n "$seen_comment" && "${newest_comment:-0}" -gt "$seen_comment" ]]; then
    log "new review comment(s):"
    report_comments "$seen_comment"
    seen_comment="$newest_comment"
    if [[ "${unresolved:-0}" -gt 0 ]]; then
      log "ending the watch: the author owes a reply. Answer the comments above, resolve the threads, push, then restart the watcher."
      exit 3
    fi
  fi
  [[ -z "$seen_comment" || "${newest_comment:-0}" -gt "$seen_comment" ]] && seen_comment="${newest_comment:-0}"

  case "$s" in MERGED*|CLOSED*) exit 0 ;; esac

  if mergeable_now; then
    ready_step
    command sleep "$INTERVAL"
    continue
  fi
  # A push or a new review round takes it out of ready, so the next green is announced again.
  was_ready=0

  if [[ -n "$bad" ]] && infra_failure; then
    heal "infrastructure failure (a job failed with no failed step)"
  elif [[ $stuck -ge $STUCK_POLLS ]]; then
    stuck=0
    author_owes=0
    stuck_report
    # Nothing this watcher can do moves a PR that is waiting on its author, and the caller only ever learns a watch
    # ended — a background command notifies on exit, never on a new line of output.
    if [[ "$author_owes" == "1" ]]; then
      log "ending the watch: only the author can move this. Act on the line above, then restart the watcher."
      exit 3
    fi
  fi

  command sleep "$INTERVAL"
done
