#!/usr/bin/env bash
# Tests scripts/ollama-lan-lock.sh without touching the real firewall: every
# case runs against a stub `iptables` and `sudo` first on PATH, and the script
# is copied to a temp tree so it never reads a real .env.
# Run: bash scripts/test_ollama_lan_lock.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
FAIL=0
ok()   { printf 'ok   %s\n' "$1"; }
bad()  { printf 'FAIL %s\n' "$1"; FAIL=1; }
has()  { grep -qF -- "$2" <<<"$1" && ok "$3" || bad "$3 (missing: $2)"; }
hasnt(){ grep -qF -- "$2" <<<"$1" && bad "$3 (unexpected: $2)" || ok "$3"; }

mkdir -p "$T/bin" "$T/repo/scripts"
cp "$HERE/ollama-lan-lock.sh" "$HERE/lock-preflight.sh" "$T/repo/scripts/"
LOCK="$T/repo/scripts/ollama-lan-lock.sh"
cat >"$T/bin/iptables" <<'STUB'
#!/usr/bin/env bash
echo "$*" >>"$STUB_LOG"
case "$*" in *"-C "*|*"-L "*) exit 1;; esac
exit 0
STUB
printf '#!/usr/bin/env bash\n[ "$1" = "-n" ] && shift\nexec "$@"\n' >"$T/bin/sudo"
chmod +x "$T/bin/iptables" "$T/bin/sudo"
export STUB_LOG="$T/ipt.log"
# The real docker must never answer for the apply cases; the preflight has its own stub (4b).
export HARVIS_LOCK_SKIP_PREFLIGHT=1
# docker stub for the preflight cases: what compose networks exist, on which subnet,
# and what the running backend's default route is, all driven by environment variables.
cat >"$T/bin/docker" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  "ps") exit 0 ;;
  *"network ls"*"compose.network=repo-sandbox"*) printf '%s' "${STUB_SBX_NET:+$STUB_SBX_NET$'\n'}" ;;
  *"network ls"*"compose.network=browser-egress"*) printf '%s' "${STUB_BR_NET:+$STUB_BR_NET$'\n'}" ;;
  *"network inspect"*repo-sandbox*) echo "$STUB_SBX_SUBNET " ;;
  *"network inspect"*browser-egress*) echo "$STUB_BR_SUBNET " ;;
  *"ps -q"*"service=backend"*) printf '%s' "${STUB_BACKEND:+$STUB_BACKEND$'\n'}" ;;
  *"exec "*"/proc/net/route"*) printf 'Iface\tDestination\tGateway\tFlags\n'; printf 'eth0\t00000000\t%s\t0003\n' "$STUB_GW_HEX" ;;
  *"inspect -f"*) echo /harvis-backend ;;
esac
exit 0
STUB
chmod +x "$T/bin/docker"
# 10.213.84.1 and 172.18.0.1 as /proc/net/route prints them (little-endian hex)
SBX_GW=0154D50A; OLLAMA_GW=010012AC
clean() { env -u HARVIS_OLLAMA_PORT -u HARVIS_OLLAMA_ALLOW_CIDRS -u HARVIS_REPO_SANDBOX_SUBNET -u HARVIS_BROWSER_SUBNET "$@"; }

# 1. print: defaults, untrusted subnets dropped before any bridge accept, then default drop
out="$(clean "$LOCK" print)"
has "$out" "-A HARVIS-OLLAMA-IN -s 10.213.84.0/24 -j DROP" "drops the repo-sandbox subnet"
has "$out" "-A HARVIS-OLLAMA-IN -s 10.213.83.0/28 -j DROP" "drops the browser-egress subnet"
has "$out" "-A HARVIS-OLLAMA-IN -i lo -j ACCEPT" "loopback allowed"
has "$out" "-A HARVIS-OLLAMA-IN -i docker0 -j ACCEPT" "docker0 allowed"
has "$out" "-A HARVIS-OLLAMA-IN -i br-+ -j ACCEPT" "compose bridges allowed"
has "$out" "-I INPUT 1 -p tcp --dport 11434 -j HARVIS-OLLAMA-IN" "hooked from INPUT for 11434 only"
last=$(grep -- '-A HARVIS-OLLAMA-IN' <<<"$out" | tail -1)
[ "$last" = "iptables -w 5 -A HARVIS-OLLAMA-IN -j DROP" ] && ok "LAN falls to the final DROP" || bad "final rule is not DROP: $last"
d=$(grep -n -- '-s 10.213.84.0/24 -j DROP' <<<"$out" | head -1 | cut -d: -f1)
b=$(grep -n -- '-i br-+ -j ACCEPT' <<<"$out" | head -1 | cut -d: -f1)
[ -n "$d" ] && [ -n "$b" ] && [ "$d" -lt "$b" ] && ok "sandbox drop precedes the bridge accept" || bad "sandbox drop not before br-+ accept"
[ ! -s "$STUB_LOG" ] && ok "print never calls iptables" || bad "print called iptables"

# 2. env overrides: port, allowed LAN hosts, pinned subnets
out="$(clean HARVIS_OLLAMA_PORT=11500 HARVIS_OLLAMA_ALLOW_CIDRS=192.168.1.0/24,10.9.0.5 HARVIS_REPO_SANDBOX_SUBNET=10.99.1.0/24 "$LOCK" print)"
has "$out" "--dport 11500 -j HARVIS-OLLAMA-IN" "custom port hooked"
has "$out" "-A HARVIS-OLLAMA-IN -s 192.168.1.0/24 -j ACCEPT" "allowed LAN range accepted"
has "$out" "-A HARVIS-OLLAMA-IN -s 10.9.0.5/32 -j ACCEPT" "bare IP becomes /32"
has "$out" "-A HARVIS-OLLAMA-IN -s 10.99.1.0/24 -j DROP" "pinned sandbox subnet dropped"
hasnt "$out" "-s 10.213.84.0/24" "default sandbox subnet replaced by the pinned one"

# 3. bad input is refused and nothing is installed
for v in "HARVIS_OLLAMA_PORT=99999" "HARVIS_OLLAMA_PORT=abc" "HARVIS_OLLAMA_ALLOW_CIDRS=10.0.0.0/33" "HARVIS_OLLAMA_ALLOW_CIDRS=999.1.1.1" "HARVIS_REPO_SANDBOX_SUBNET=10.1.1.1"; do
  : >"$STUB_LOG"
  out="$(clean env "$v" PATH="$T/bin:$PATH" "$LOCK" apply 2>&1)"; rc=$?
  { [ $rc -eq 0 ] && has "$out" "WARNING" "$v: warned" && [ ! -s "$STUB_LOG" ] && ok "$v: nothing installed"; } || bad "$v handling"
done

# 4. apply with a stub: unhooks first, builds the chain, hooks once, exits 0
: >"$STUB_LOG"
out="$(clean PATH="$T/bin:$PATH" "$LOCK" apply 2>&1)"; rc=$?
log="$(cat "$STUB_LOG")"
[ $rc -eq 0 ] && ok "apply exits 0" || bad "apply rc=$rc"
has "$log" "-N HARVIS-OLLAMA-IN" "apply creates the chain"
has "$log" "-A HARVIS-OLLAMA-IN -j DROP" "apply appends the default drop"
has "$log" "-I INPUT 1 -p tcp --dport 11434 -j HARVIS-OLLAMA-IN" "apply hooks INPUT"
hasnt "$log" "-X HARVIS-OLLAMA-IN" "apply never deletes the chain"


# 4b. preflight: refused when the sandbox is on another subnet or the backend routes through it
unset HARVIS_LOCK_SKIP_PREFLIGHT
installed() { grep -cE -- ' -[AIN] ' "$STUB_LOG"; }
run_apply() { : >"$STUB_LOG"; out="$(clean env PATH="$T/bin:$PATH" "$@" "$LOCK" apply 2>&1)"; rc=$?; }
run_apply STUB_SBX_NET=harvis_repo-sandbox STUB_SBX_SUBNET=172.19.0.0/16
{ [ $rc -eq 3 ] && has "$out" "docker network rm harvis_repo-sandbox" "old-subnet network: refused with the fix" && [ "$(installed)" -eq 0 ]; } && ok "old-subnet network: nothing installed" || bad "old-subnet network rc=$rc rules=$(installed)"
run_apply STUB_SBX_NET=harvis_repo-sandbox STUB_SBX_SUBNET=10.213.84.0/24 STUB_BACKEND=abc123 STUB_GW_HEX=$SBX_GW
{ [ $rc -eq 3 ] && has "$out" "default route through the repo-sandbox network" "backend on repo-sandbox route: refused" && [ "$(installed)" -eq 0 ]; } && ok "backend route: nothing installed" || bad "backend route rc=$rc rules=$(installed)"
run_apply STUB_SBX_NET=harvis_repo-sandbox STUB_SBX_SUBNET=10.213.84.0/24 STUB_BACKEND=abc123 STUB_GW_HEX=$OLLAMA_GW
{ [ $rc -eq 0 ] && [ "$(installed)" -gt 0 ]; } && ok "good state: applies" || bad "good state refused rc=$rc: $out"
run_apply STUB_SBX_NET=harvis_repo-sandbox STUB_SBX_SUBNET=172.19.0.0/16 HARVIS_LOCK_SKIP_PREFLIGHT=1
{ [ $rc -eq 0 ] && [ "$(installed)" -gt 0 ]; } && ok "HARVIS_LOCK_SKIP_PREFLIGHT=1 applies anyway" || bad "override rc=$rc"
export HARVIS_LOCK_SKIP_PREFLIGHT=1

# 5. remove: unhook, flush, delete; and it is the only thing it touches
: >"$STUB_LOG"
sed -i 's/exit 1;;/exit 0;;/' "$T/bin/iptables"   # chain exists for this case
clean PATH="$T/bin:$PATH" "$LOCK" remove >/dev/null 2>&1; rc=$?
log="$(cat "$STUB_LOG")"
[ $rc -eq 0 ] && ok "remove exits 0" || bad "remove rc=$rc"
has "$log" "-X HARVIS-OLLAMA-IN" "remove deletes the chain"
hasnt "$(grep -v HARVIS-OLLAMA <<<"$log" | grep -vE -- '^-w 5 -S INPUT$|^-w 5 -L ')" "-F INPUT" "remove never flushes INPUT"

# 6. no iptables: says so, exits 0
out="$(clean PATH="$(dirname "$(command -v bash)"):/usr/bin:/bin" env -i PATH="$T/empty" "$(command -v bash)" "$LOCK" apply 2>&1)"; rc=$?
[ $rc -eq 0 ] && has "$out" "iptables not found" "missing iptables handled" || bad "missing iptables rc=$rc: $out"

# 7. bad mode
clean "$LOCK" bogus >/dev/null 2>&1; [ $? -eq 2 ] && ok "unknown mode exits 2" || bad "unknown mode exit code"

[ $FAIL -eq 0 ] && echo ALL PASS || { echo SOME FAILED; exit 1; }
