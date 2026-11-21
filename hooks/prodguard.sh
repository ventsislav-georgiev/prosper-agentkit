#!/usr/bin/env bash
# Claude Code PreToolUse hook for the Bash and Monitor tools: denies the routes an agent could take
# around prodguard's shims. Those routes are the real binary by path, a PATH of its own, a pty to
# answer the override's confirmation, and setting the override itself. The first two are pointed
# back at the shims, so a worker told to use absolute paths retries through them. So is a tool run
# by name when the session's PATH finds the real binary before the shims, which is the normal case
# under the kit: Prosper appends the kit's shim dir (KIT_BIN) to PATH, never prepends it.
#
# A seatbelt like prodguard: a command assembled at run time (a script written to a file first,
# a path built from variables) goes unseen. An input neither jq nor python3 can parse allows the
# call, and prodguard still runs behind it. The shims are $KIT_BIN/<tool> under the kit, else the
# wrapper files in ../tools/prodguard. tests/prodguard.test.sh holds the cases.

input=$(</dev/stdin)
# Fast path: no guarded tool name, make or the override anywhere in the call, nothing to parse.
case $input in *kubectl* | *kubernetes* | *gcloud* | *google-cloud* | *aws* | *terraform* | *tofu* | *make* | *EXPLICIT_OPERATOR*) ;; *) exit 0 ;; esac
# jq when it is on PATH, else python3: the kit does not require jq.
cmd=$(jq -r '.tool_input.command // empty' <<<"$input" 2>/dev/null) ||
  cmd=$(/usr/bin/python3 -Ic 'import json,sys; print((json.load(sys.stdin).get("tool_input") or {}).get("command") or "")' <<<"$input" 2>/dev/null) ||
  exit 0
[[ -n $cmd ]] || exit 0

T='(kubectl|gcloud|aws|terraform|tofu)'
TM='(kubectl|gcloud|aws|terraform|tofu|make)'   # make: a Makefile may run tofu or terraform
TOOL="(^|[^A-Za-z0-9_.-])$T([^A-Za-z0-9_.-]|$)"
TOOLM="(^|[^A-Za-z0-9_.-])$TM([^A-Za-z0-9_.-]|$)"
BYPATH="(bin|sbin|libexec)/+$T([^A-Za-z0-9_.-]|$)|google-cloud-sdk/lib/gcloud\.py|(Cellar|Caskroom)/+(kubernetes-cli|awscli|terraform|opentofu|gcloud-cli|google-cloud-sdk)/|(^|[^A-Za-z0-9_.])\./+$T([^A-Za-z0-9_.-]|$)"
WHICHA='(which|type|whence|where)[[:space:]]+-[a-zA-Z]*[aP]'
LOOKUP="(\\\$\\(|\`)[^)\`]*$WHICHA"
REDIR='>+[[:space:]]*([^[:space:]]+)'
FIRST='^[[:space:]({!]*([^[:space:]({!]*)'   # a segment's command word, past ( { ! and blanks
SETPATH='(^|[[:space:];&|(`"'"'"'])(PATH|path)(\+?)=(\([^)]*\)|"[^"]*"|'"'[^']*'"'|[^[:space:];&|]*)'
# A guarded tool as a command word: at a segment's start or in $(, past ( { ! and blanks, VAR=value
# prefixes, shell keywords, and wrappers that run their argument, with their flags (a one-letter
# one may take a value, as in sudo -u me). command -v only looks, so a flag with v or V does not
# count. Not after a backtick: that is mostly markdown in a heredoc.
RUNS="(^|\\\$\\()[[:space:]({!]*(([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*|if|then|else|elif|do|while|until|([^[:space:]]*/)?(env|time|nohup|nice|exec|sudo|xargs|parallel|watch|timeout|command|eval|sh|bash|zsh))([[:space:]]+(-[^[:space:]vV]*|-[^[:space:]vV-][[:space:]]+[^-[:space:]][^[:space:]]*|[0-9][0-9.]*[smhd]?))*[[:space:]]+)*['\"\\\\]*$T([[:space:]'\"]|$)"
CMDP='(^|[^A-Za-z0-9_])command[[:space:]]+-[a-zA-Z]*p'
OVERRIDE="EXPLICIT_OPERATOR_ALLOW_DESTRUCTIVE_PROD_OPERATIONS[]\\'\"]*[[:space:]]*[:=]"   # X=, ["X"] =, \"X\":
# A pty tool counts only in command position: ( { ! open a subshell or group only right after a
# separator, and a wrapper is a whole word. Otherwise prose such as "(expect about 0)" in a quoted
# argument reads as a pty.
PTY='(^|[;&|`]|\$\(|(^|[^A-Za-z0-9_])(nohup|exec|sudo|xargs|time))[[:space:]({!]*(script|expect|unbuffer|tmux|screen|zellij|osascript|socat)([[:space:]]|$)|(^|[^A-Za-z0-9_])(pty\.|import[[:space:]]+pty|openpty|forkpty|node-pty|pexpect)'
# bash 3.2's ${x//…} and ${x#*…} take quadratic time and worse on a multibyte locale, enough to run
# a big command past the hook's timeout, and a timed-out hook lets the call through. So every
# whole-command pass here is one sed, tr or grep.
here=$(cd "$(dirname "$0")" && pwd)
wd=$(cd "$here/../tools/prodguard" 2>/dev/null && pwd)   # the wrapper files
sd=${KIT_BIN:-$wd}   # where the deny text sends the agent
# prodguard.conf's [trusted-shim-dirs]: absolute dirs whose cloud CLIs are guarded shims of another
# origin (an operator's own prodguard). A tool found there counts as guarded, like the kit's shims.
conf=${KIT_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/prodguard}/prodguard.conf
TRUSTED=$(awk '{ sub(/^[ \t]+/, ""); sub(/[ \t\r]+$/, "") }
  /^\[.*\]$/ { t = ($0 == "[trusted-shim-dirs]"); next } t && $0 != "" && !/^[#;]/' "$conf" 2>/dev/null)
trusted_dir() {
  local x
  while IFS= read -r x; do
    x=${x/#\~\//$HOME/}
    [[ $x == /* && $1 -ef $x ]] && return 0
  done <<<"$TRUSTED"
  return 1
}
# The shims themselves are fine by path: $KIT_BIN/ becomes a word no pattern here reads as a path or a command.
if [[ -n ${KIT_BIN:-} ]]; then
  c=$(LC_ALL=C awk -v p="$KIT_BIN/" '{ while ((i = index($0, p)) > 0) $0 = substr($0, 1, i - 1) "prodguard-shim/" substr($0, i + length(p)); print }' <<<"$cmd")
else
  c=$cmd
fi

# The command's segments, split at ; & | and newlines. feeds is set when one of them starts with
# something that can run what another one printed.
segs=$(LC_ALL=C tr ';&|' '\n\n\n' <<<"$c")
feeds=
LC_ALL=C grep -Eq '^[[:space:]({!]*(xargs|parallel|sh|bash|zsh|eval|source|\.|env)([[:space:]]|$)' <<<"$segs" && feeds=1

# True when a segment names a real binary by path. One that only inspects the file (ls,
# readlink, ...) is fine, unless it copies it out (a redirect to anything but /dev/null), feeds
# is set, or it is too long for the redirect loop to stay cheap.
by_path() {
  local s w r
  while IFS= read -r s; do
    [[ $s =~ $BYPATH ]] || continue
    hit=${BASH_REMATCH[0]}
    [[ $s =~ $FIRST ]]; w=${BASH_REMATCH[1]}
    case $w in ls|readlink|realpath|file|stat|cat|which|brew|codesign|otool|shasum|du) ;; *) return 0 ;; esac
    [[ -n $feeds || ${#s} -gt 512 || $s == *'$('* || $s == *'`'* ]] && return 0
    r=$s
    while [[ $r =~ $REDIR ]]; do
      [[ ${BASH_REMATCH[1]} == /dev/null ]] || return 0
      r=${r#*"${BASH_REMATCH[0]}"}
    done
  done < <(LC_ALL=C grep -E "$BYPATH" <<<"$segs")
  return 1
}

# True when a PATH (or zsh path) assignment could put a real binary ahead of the shims. That is a
# value that drops $PATH, or a dir ahead of $PATH that holds one, is relative or empty (the cwd
# after any cd), or cannot be expanded here. += only appends.
shadows() {
  local m v d t keep parts
  while IFS= read -r m; do
    [[ $m =~ $SETPATH && -z ${BASH_REMATCH[3]} ]] || continue
    keep= v=${BASH_REMATCH[4]}
    v=${v#[(\"\']}; v=${v%[)\"\']}
    IFS=: read -ra parts <<<"${v//[[:space:]]/:}"
    for d in ${parts[@]+"${parts[@]}"}; do
      case $d in '$PATH'|'${PATH}'|'$path'|'${path}'|'${path[@]}') keep=1; break ;; esac
      d=${d/#\~/$HOME}; d=${d//'${HOME}'/$HOME}; d=${d//'$HOME'/$HOME}
      [[ $d == /* && $d != *[\$\`]* ]] || return 0
      for t in kubectl gcloud aws terraform tofu; do
        [[ -x $d/$t && ! $d -ef $sd && ! $d -ef $wd ]] && ! trusted_dir "$d" && return 0
      done
    done
    [[ -n $keep ]] || return 0
  done < <(LC_ALL=C grep -oE "$SETPATH" <<<"$1")
  return 1
}

# Sets u to the tools that, run by name, miss prodguard (the kit's shims or a trusted foreign one).
# The hook shares the session's PATH, and a session started from a shell older than the shims' PATH
# line runs the real binary by name.
unguarded() {
  local x p; u=
  for x in kubectl gcloud aws terraform tofu; do
    p=$(command -v $x) && [[ ! $p -ef $sd/$x && ! $p -ef $wd/$x ]] && ! trusted_dir "${p%/*}" && u+=" $x "
  done
}

# Sets t to the first tool the command runs by name that misses prodguard.
runs_unguarded() {
  local m end="$T[[:space:]'\"]*\$"
  [[ -n $u ]] || return 1
  while IFS= read -r m; do
    [[ $m =~ $end && $u == *" ${BASH_REMATCH[1]} "* ]] && { t=${BASH_REMATCH[1]}; return 0; }
  done < <(LC_ALL=C grep -oE "$RUNS" <<<"$segs")
  return 1
}

# True when a cloud CLI (or make) in the command can run on the pty it drives. A segment whose own
# command word is the tool, before the first pty segment, does not count: it ran on the agent's
# terminal-less stdio, and a pty opened after it cannot become its terminal. A command with no
# segment that matches the pty pattern on its own counts as before.
PLAIN="^[[:space:]({!]*$TM([[:space:]]+[^=[:space:]]|[[:space:]]*\$)"
pty_drives() {
  local s seen=
  while IFS= read -r s; do
    [[ -z $seen && $s =~ $PTY ]] && seen=1
    [[ $s =~ $TOOLM ]] || continue
    [[ -z $seen && $s =~ $PLAIN ]] && continue
    return 0
  done < <(LC_ALL=C grep -E "$PTY|$TOOLM" <<<"${1:-$segs}")
  [[ -z $seen ]]
}

# Prints the command with ; & | ` and $( blanked inside the quoted arguments of a command that only
# reads them as text (a search pattern, a printed string, a ledger note). The shell does not split
# there, so "rg 'screen seam|screen grow'" holds no pty. Only a string the shell cannot expand: one
# in single quotes, or in double quotes without $ or a backtick. $'...' and an unclosed quote stay
# as they are, and so does everything after a ) until the next separator.
read -r -d '' TEXTARGS <<'PL'
my $s = do { local $/; <STDIN> };
my @c = split //, $s;
my $n = @c;
my ($out, $w, $have) = ('', '', 0);   # w: the segment's command word; have: it is complete
for (my $i = 0; $i < $n; $i++) {
  my $ch = $c[$i];
  if ($ch eq '\\') { $out .= $ch . ($c[$i + 1] // ''); $w .= 'x' unless $have; $i++; next; }
  if ($ch eq "'" || $ch eq '"') {
    my $ansi = $ch eq "'" && $i > 0 && $c[$i - 1] eq '$';
    my $j = $i + 1;
    if ($ch eq "'" && !$ansi) { $j++ while $j < $n && $c[$j] ne "'"; }
    else { while ($j < $n && $c[$j] ne $ch) { $j++ if $c[$j] eq '\\'; $j++; } }
    $j = $n if $j > $n;
    my $body = join '', @c[$i + 1 .. $j - 1];
    if (!$have) { $w .= $body; }
    elsif ($j < $n && !$ansi && $w =~ m{(^|/)(rg|grep|egrep|fgrep|echo|printf|todo\.py|memory\.py)$}
           && ($ch eq "'" || $body !~ /[\$`]/)) {
      $body =~ s/\$\(/  /g;
      $body =~ tr/;&|`/    /;
    }
    $out .= $ch . $body . ($j < $n ? $ch : '');
    $i = $j;
    next;
  }
  if ($ch =~ /[;&|\n(`]/) { ($w, $have) = ('', 0); }
  elsif ($ch eq ')') { ($w, $have) = ('', 1); }   # back in an outer command: its word is not known
  elsif (!$have) {
    if ($ch =~ /\s/) {
      if ($w =~ /^[A-Za-z_][A-Za-z0-9_]*=/) { $w = ''; }   # a VAR=value prefix
      elsif ($w ne '') { $have = 1; }
    }
    elsif ($w ne '' || $ch !~ /[{!]/) { $w .= $ch; }
  }
  $out .= $ch;
}
print $out;
PL

# True when the command drives a pty that a cloud CLI (or make) can run on. A command that feeds
# one segment's output to a shell is read as written: there a printed string can be run.
pty_stop() {
  local p ps
  [[ $c =~ $PTY && $c =~ $TOOLM ]] || return 1
  [[ -n $feeds ]] && { pty_drives; return; }
  p=$(perl -e "$TEXTARGS" <<<"$c" 2>/dev/null)
  [[ -n $p ]] || { pty_drives; return; }
  [[ $p =~ $PTY ]] || return 1
  ps=$(LC_ALL=C tr ';&|' '\n\n\n' <<<"$p")
  pty_drives "$ps"
}

# Setting the override or driving a pty is a STOP. A route around the shims gets pointed back at
# them: prodguard still decides what runs.
t= why= stop= stale=
[[ $c =~ $TOOL ]] && t=${BASH_REMATCH[2]}
if [[ $c =~ $OVERRIDE ]]; then
  stop="it sets the production override, which only a human may do"
elif pty_stop; then
  stop="it runs a cloud CLI on a pseudo-terminal, where the override's confirmation could be typed for it"
elif by_path; then
  case $hit in
    *kubectl*|*kubernetes-cli*) t=kubectl ;; *tofu*) t=tofu ;; *terraform*) t=terraform ;; *aws*) t=aws ;; *) t=gcloud ;;
  esac
  why="runs $t by the real binary's path, past prodguard's shims"
elif [[ -n $t ]] && { [[ $c =~ $LOOKUP ]] || [[ -n $feeds && $c =~ $WHICHA ]]; }; then
  why="runs $t found with which/type -a, past prodguard's shims"
elif [[ $c =~ $TOOLM ]] && shadows "$cmd"; then
  why="sets a PATH that can put a real binary ahead of prodguard's shims"
elif [[ -n $t && $c =~ $CMDP ]]; then
  why="looks $t up with command -p, past prodguard's shims"
elif [[ -n $t ]]; then
  unguarded; runs_unguarded && stale=1
fi

if [[ -n $stale && -n ${KIT_BIN:-} ]]; then
  reason="prodguard: in this session, $t run by name is the real binary, unguarded: the kit's guarded copy is at the end of PATH. Run it by its shim path $sd/$t, which is guarded whatever PATH is. Reads pass through it unchanged; production writes are refused, and only a human can run those."
elif [[ -n $stale ]]; then
  reason="prodguard: in this session, $t run by name is the real binary, unguarded: the session's PATH does not reach prodguard's shims. Run it by its shim path $sd/$t, which is guarded whatever PATH is. Reads pass through it unchanged; production writes are refused, and only a human can run those."
elif [[ -n $why ]]; then
  unguarded   # by name only where the name reaches prodguard
  if [[ -n $t ]]; then
    use="run $t by name, or by its shim path $sd/$t"
    [[ $u == *" $t "* ]] && use="run it by its shim path $sd/$t"
  else
    use="run kubectl, gcloud, aws, terraform and tofu by name, or from $sd/"
    [[ -n $u ]] && use="run kubectl, gcloud, aws, terraform and tofu from $sd/"
  fi
  reason="prodguard: this command $why. Use the guarded CLI instead: $use, and leave PATH as it is. Reads pass through it unchanged; production writes are refused, and only a human can run those."
elif [[ -n $stop ]]; then
  reason="prodguard: STOP. This command is denied: $stop. Production writes go through prodguard, and only a human in their own terminal can override it. Do not rephrase, split or retry this command. Tell the user what you were trying to run and let them run it."
else
  exit 0
fi
jq -nc --arg r "$reason" '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}' 2>/dev/null ||
  /usr/bin/python3 -Ic 'import json,sys; print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": sys.argv[1]}}))' "$reason" 2>/dev/null ||
  { echo "$reason" >&2; exit 2; }
