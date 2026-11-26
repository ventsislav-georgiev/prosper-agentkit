#!/bin/bash
# Claude Code PreToolUse hook (Bash, Monitor): denies a recursive delete (rm -r, find -delete, find -exec rm -r, xargs rm -r)
# whose target is an unguarded variable, an inherited variable, a command substitution, a top-level or guarded directory, a
# session socket dir, or a git repo or worktree. Plain rm, rmdir and recursive deletes of ordinary paths pass.
# Reads only stdin; arguments are ignored. Any parse failure allows the command: a crashing hook must not block every call.
read -r -d '' PY <<'EOF'
import fnmatch, json, os, re, sys

HOME = os.environ.get('HOME', '').rstrip('/')
UID = str(os.getuid())
INHERITED = {'TMPDIR', 'HOME', 'PWD', 'OLDPWD', 'USER', 'LOGNAME', 'SHELL'}
WRAPPERS = {'sudo', 'nohup', 'exec', 'env', 'xargs', 'command', 'time', 'nice', 'timeout'}
VALUE_OPTS = {'-u', '-g', '-I', '-J', '-n', '-P', '-L', '-s', '-d', '-E', '-k', '-S', '-C', '-p'}
SKIP = {'{', '!', 'then', 'do', 'else', 'if', 'while', 'until', 'elif'}
EXACT = {'/', '.', '..', '*', '.*', '/*', '~'}
SYSTEM_TOPS = {'/tmp', '/private/tmp', '/var/folders', '/private/var/folders', '/Users', HOME, HOME + '/.claude'}
PER_USER_TMP = re.compile(r'^(/private)?/var/folders/[^/]+/[^/]+(/[TCX0])?$')
SOCKETS = re.compile(r'^(/private)?/tmp/(dch-[^/]*|cc-socks)(/|$)')
VAR = re.compile(r'\$(\{)?([A-Za-z_][A-Za-z0-9_]*|[0-9@*#?$!-])')


def expand(g):
    g = g.replace('${HOME}', HOME).replace('$HOME', HOME).replace('$UID', UID).replace('<uid>', UID)
    return HOME + g[1:] if g == '~' or g.startswith('~/') else g


def guards():
    # Under the kit (KIT_CONFIG set) the config is KIT_CONFIG/removeguard.conf; when that file is absent, or standalone, the XDG path.
    kit = os.environ.get('KIT_CONFIG')
    cfg = os.path.join(kit, 'removeguard.conf') if kit else ''
    if not os.path.isfile(cfg):
        cfg = os.path.join(os.environ.get('XDG_CONFIG_HOME') or HOME + '/.config', 'removeguard', 'config')
    out, sec = [], None
    if not os.path.isfile(cfg):
        return out
    for line in open(cfg):
        line = line.strip()
        if line.startswith('['):
            sec = line
        elif line and not line.startswith('#') and sec == '[guard]':
            out.append(expand(line).rstrip('/'))
    return out


def unq(w):
    return re.sub(r'\\(.)', r'\1', w.replace('"', '').replace("'", ''))


def match_paren(s, i):
    depth, j = 0, i
    while j < len(s):
        c = s[j]
        if c == '\\':
            j += 2
            continue
        if c == "'":
            k = s.find("'", j + 1)
            j = (k if k >= 0 else len(s)) + 1
            continue
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return len(s)


def dq_end(s, i):
    j = i + 1
    while j < len(s):
        c = s[j]
        if c == '\\':
            j += 2
            continue
        if c == '"':
            return j
        if c == '$' and s[j + 1:j + 2] == '(':
            j = match_paren(s, j + 1) + 1
            continue
        j += 1
    return len(s)


def scan(s, cmds, depth=0):
    """Split s into simple commands (lists of raw words); quoted and substituted text is scanned again as commands."""
    nested, words, cur, have, drop = [], [], [], False, False
    i, n = 0, len(s)

    def endword():
        nonlocal cur, have, drop
        if have and not drop:
            words.append(''.join(cur))
        if have:
            drop = False
        cur, have = [], False

    def endcmd():
        nonlocal words
        endword()
        if words:
            cmds.append(words)
        words = []

    while i < n:
        c = s[i]
        if c == '\\':
            cur.append(s[i:i + 2]); have = True; i += 2
        elif c in ' \t':
            endword(); i += 1
        elif c == '#' and not have:
            k = s.find('\n', i); i = n if k < 0 else k
        elif c in '"\'`' or (c == '$' and s[i + 1:i + 2] == '('):
            if c == '"':
                k = dq_end(s, i); inner = s[i + 1:k]
            elif c == '$':
                k = match_paren(s, i + 1); inner = s[i + 2:k]
            else:
                k = s.find(c, i + 1); k = n if k < 0 else k; inner = s[i + 1:k]
            nested.append(inner); cur.append(s[i:k + 1]); have = True; i = k + 1
        elif c == '$' and s[i + 1:i + 2] == '{':
            k = s.find('}', i); k = n if k < 0 else k
            cur.append(s[i:k + 1]); have = True; i = k + 1
        elif c in '<>':
            if have and ''.join(cur).isdigit():
                cur, have = [], False
            endword()
            while i < n and s[i] in '<>&':
                i += 1
            drop = True
        elif c in ';&|()\n':
            endcmd(); i += 1
        else:
            cur.append(c); have = True; i += 1
    endcmd()
    if depth < 6:
        for t in nested:
            scan(t, cmds, depth + 1)
    return cmds


def is_recursive_flag(a):
    a = unq(a)
    return a == '--recursive' or (a.startswith('-') and not a.startswith('--') and bool(re.search('[rR]', a)))


def holds_repo(a):
    """a, or a direct child of a, has .git. Two levels only: the hook runs on every call."""
    if os.path.lexists(os.path.join(a, '.git')):
        return True
    try:
        with os.scandir(a) as it:
            return any(e.is_dir(follow_symlinks=False) and os.path.lexists(os.path.join(e.path, '.git')) for e in it)
    except OSError:
        return False


def check_target(raw, cwd):
    if '$(' in raw or '`' in raw:
        return 'a command substitution as the target'
    for m in VAR.finditer(raw):
        name = m.group(2)
        if name in INHERITED:
            return 'the inherited variable $%s, which is never a scratch dir' % name
        if not (m.group(1) and raw[m.end():].startswith(':?')):
            return 'the variable $%s without ${%s:?}; an empty value turns the path into a parent or /' % (name, name)
    p = re.sub('/+', '/', expand(unq(raw)))
    cands = {p.rstrip('/') or '/'}
    for suffix in ('/*', '/.*'):
        if p.endswith(suffix):
            cands.add(p[:-len(suffix)] or '/')
    for c in cands:
        a = os.path.normpath(os.path.join(cwd, c)) if cwd else c
        if c in EXACT or re.fullmatch(r'[./]+', c):
            return 'a top or relative-root target (%s)' % c
        if any(fnmatch.fnmatchcase(a, t) for t in TOPS) or PER_USER_TMP.match(a):
            return 'a guarded top directory (%s)' % a
        if SOCKETS.match(a):
            return 'a session socket directory (%s)' % a
        if '.git' in a.split('/'):
            return 'a .git directory or a path inside one (%s)' % a
        if not re.search(r'[*?\[]', a) and holds_repo(a):
            return 'a git repo or worktree, or a dir holding one (%s); use git worktree remove <path>' % a
    return None


def analyze(words, cwd):
    i, xargs = 0, False
    while i < len(words):
        w = unq(words[i]); b = w.rsplit('/', 1)[-1]
        if w in SKIP or re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', w):
            i += 1
            continue
        if b not in WRAPPERS:
            break
        xargs = xargs or b == 'xargs'
        i += 1
        while i < len(words):
            w2 = unq(words[i]); b2 = w2.rsplit('/', 1)[-1]
            if b2 in WRAPPERS or b2 in ('rm', 'find'):
                break
            if w2 in VALUE_OPTS:
                i += 2
            elif w2.startswith('-') or re.match(r'^[0-9.]+[smhd]?$', w2) or re.match(r'^[A-Za-z_]\w*=', w2) or w2 in ('{}', '%'):
                i += 1
            else:
                break
    if i >= len(words):
        return None
    b = unq(words[i]).rsplit('/', 1)[-1]
    args = words[i + 1:]
    if b == 'rm':
        ops, rec, endopts = [], False, False
        for a in args:
            u = unq(a)
            if not endopts and u == '--':
                endopts = True
            elif not endopts and u.startswith('-') and len(u) > 1:
                rec = rec or is_recursive_flag(a)
            else:
                ops.append(a)
        if not rec:
            return None
        if xargs:
            return 'xargs rm -r: the targets come from stdin and cannot be checked'
        for a in ops:
            r = check_target(a, cwd)
            if r:
                return 'rm -r on %s' % r
        return None
    if b == 'find':
        j, paths = 0, []
        while j < len(args) and unq(args[j]) in ('-H', '-L', '-P', '-E', '-X', '-d', '-s', '-x', '-f'):
            if unq(args[j]) == '-f' and j + 1 < len(args):
                paths.append(args[j + 1]); j += 1
            j += 1
        while j < len(args) and not unq(args[j]).startswith(('-', '(', '!')):
            paths.append(args[j]); j += 1
        rest = [unq(a) for a in args[j:]]
        deleting = '-delete' in rest
        for k, a in enumerate(rest):
            if a in ('-exec', '-execdir', '-ok', '-okdir') and k + 1 < len(rest) and rest[k + 1].rsplit('/', 1)[-1] == 'rm':
                for f in rest[k + 2:]:
                    if f in (';', '+'):
                        break
                    deleting = deleting or is_recursive_flag(f)
        if not deleting:
            return None
        for a in paths or ['.']:
            r = check_target(a, cwd)
            if r:
                return 'find with -delete or -exec rm -r, starting at %s' % r
    return None


def main():
    global TOPS
    TOPS = SYSTEM_TOPS | set(guards())
    data = json.load(sys.stdin)
    cmd = (data.get('tool_input') or {}).get('command') or ''
    cwd = data.get('cwd') or ''
    for words in scan(cmd, []):
        if unq(words[0]) == 'cd' and len(words) == 2 and '$' not in words[1]:
            cwd = os.path.normpath(os.path.join(cwd, expand(unq(words[1]))))
        reason = analyze(words, cwd)
        if reason:
            print(json.dumps({'hookSpecificOutput': {
                'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                'permissionDecisionReason': 'removeguard: recursive delete denied: %s. Use %s/saferm [-n] <path> (it checks scope, '
                'symlinks and worktrees), git worktree remove <path> for a worktree, and ${VAR:?} for any variable target.'
                % (reason, sys.argv[1])}}))
            return


main()
EOF
input=$(</dev/stdin)
# jq when it is on PATH; without it the raw input feeds the same fast filter (a superset), and python parses it.
cmd=$(jq -r '.tool_input.command // empty' <<<"$input" 2>/dev/null) || cmd=$input
# rm covers rmdir and rmtree; every delete the python check knows names one of these.
case $cmd in *rm* | *unlink* | *delete* | *xargs*) ;; *) exit 0 ;; esac
# The deny text names saferm: the KIT_BIN shim under the kit, else the kit copy next to this hook.
sr=${KIT_BIN:-$(cd "${0%"${0##*/}"}../tools/removeguard" 2>/dev/null && pwd)}
out=$("${0%"${0##*/}"}../lib/python3" -c "$PY" "$sr" <<<"$input" 2>/dev/null) || exit 0
[[ -z $out ]] || echo "$out"
exit 0
