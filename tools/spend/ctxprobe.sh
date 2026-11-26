#!/bin/sh
# Starting context of a fresh Claude Code session in a folder: ctxprobe.sh [dir] [extra claude args...]
# Runs one `claude -p` with a one-word reply and prints its input + cache read + cache write tokens: what every session
# in that folder pays before your first message. No dir (or a first arg starting with -): a fresh empty temp folder.
# Extra args measure a variant; compare against the plain run:
#   --settings '{"enabledPlugins":{"name@marketplace":false}}'   (one plugin off)
#   --settings '{"permissions":{"deny":["<the MCP server's permission rule>"]}}'   (one MCP server denied)
#   --disable-slash-commands                                       (no skills)
#   --strict-mcp-config                                            (no MCP servers)
# Each run is one real, small model call. Needs claude and jq on PATH. Exit 1 when the reply has no usage.
command -v jq >/dev/null 2>&1 || { echo "ctxprobe: jq is not on PATH" >&2; exit 2; }
tmp=
case ${1:-} in
  ''|-*) tmp=$(mktemp -d "${TMPDIR:-/tmp}/ctxprobe.XXXXXX") || exit 2; dir=$tmp ;;
  *) dir=$1; shift ;;
esac
[ -d "$dir" ] || { echo "ctxprobe: no folder $dir" >&2; exit 2; }
out=$(cd "$dir" && claude -p 'Reply with OK only.' --output-format json "$@" 2>/dev/null)
[ -n "$tmp" ] && rmdir "$tmp" 2>/dev/null
printf '%s' "$out" | jq -er '.usage | (.input_tokens + .cache_read_input_tokens + .cache_creation_input_tokens)' 2>/dev/null ||
  { echo "ctxprobe: no usage in claude's reply" >&2; exit 1; }
