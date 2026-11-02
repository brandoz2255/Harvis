#!/usr/bin/env bash
# Tests scripts/browser-egress-lock.sh without touching the real firewall: every
# case runs with a stub `iptables` and `sudo` first on PATH. Run: bash scripts/test_browser_egress_lock.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LOCK="$HERE/browser-egress-lock.sh"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
FAIL=0
ok()   { printf 'ok   %s\n' "$1"; }
bad()  { printf 'FAIL %s\n' "$1"; FAIL=1; }
has()  { grep -qF -- "$2" <<<"$1" && ok "$3" || bad "$3 (missing: $2)"; }
hasnt(){ grep -qF -- "$2" <<<"$1" && bad "$3 (unexpected: $2)" || ok "$3"; }

mkdir -p "$T/bin"
cat >"$T/bin/iptables" <<'STUB'
#!/usr/bin/env bash
echo "$*" >>"$STUB_LOG"
case "$*" in *"-C "*|*"-L "*) exit 1;; esac
exit 0
STUB
printf '#!/usr/bin/env bash\nshift_n=0; [ "$1" = "-n" ] && shift\nexec "$@"\n' >"$T/bin/sudo"
chmod +x "$T/bin/iptables" "$T/bin/sudo"
export STUB_LOG="$T/ipt.log" HARVIS_BROWSER_RESOLV_FILES=/dev/null
# The real docker must never answer for the apply cases below; the preflight has its own stub (5b).
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

# 1. dry-run: defaults, drop list mirrors scripts/k8s/k8s_harden.py PRIVATE
out="$(env -u HARVIS_BROWSER_ALLOW_CIDRS "$LOCK" print)"
for r in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 169.254.0.0/16 127.0.0.0/8 0.0.0.0/8 224.0.0.0/4 240.0.0.0/4; do
  has "$out" "-A HARVIS-BROWSER-FWD -d $r -j DROP" "drops $r"
done
has "$out" "-I DOCKER-USER 1 -s 10.213.83.0/28 -j HARVIS-BROWSER-FWD" "hooks forward path on the default subnet"
has "$out" "-I INPUT 1 -s 10.213.83.0/28 -j HARVIS-BROWSER-IN" "hooks host-bound path"
has "$out" "-A HARVIS-BROWSER-FWD -j RETURN" "public traffic falls through to Docker's own rules"
[ ! -s "$STUB_LOG" ] && ok "print never calls iptables" || bad "print called iptables"

# 2. allow list lands before the drops; DNS allowance; custom subnet list
out="$(HARVIS_BROWSER_ALLOW_CIDRS=192.168.50.0/24,10.9.0.5 HARVIS_BROWSER_DNS=192.168.1.1 HARVIS_BROWSER_SUBNET=10.213.83.0/28,10.213.99.0/28 "$LOCK" print)"
a=$(grep -n -- '-d 192.168.50.0/24 -j ACCEPT' <<<"$out" | grep FWD | head -1 | cut -d: -f1)
d=$(grep -n -- '-d 192.168.0.0/16 -j DROP' <<<"$out" | head -1 | cut -d: -f1)
[ -n "$a" ] && [ -n "$d" ] && [ "$a" -lt "$d" ] && ok "allowed range precedes the drops" || bad "allowed range not before drops"
has "$out" "-d 10.9.0.5/32 -j ACCEPT" "bare IP becomes /32"
has "$out" "-d 192.168.1.1 -p udp --dport 53 -j ACCEPT" "private resolver may be queried on 53"
has "$out" "-I DOCKER-USER 1 -s 10.213.99.0/28" "second stack subnet hooked"
dns=$(grep -- '--dport 53' <<<"$out" | grep -c BROWSER); [ "$dns" -eq 4 ] && ok "DNS allowed only on port 53, udp+tcp, both chains" || bad "dns rule count $dns"

# 3. resolver discovery from a resolv.conf; loopback stub is ignored
printf 'nameserver 127.0.0.53\nnameserver 192.168.8.1\n' >"$T/resolv"
out="$(HARVIS_BROWSER_RESOLV_FILES="$T/resolv" "$LOCK" print)"
has "$out" "-d 192.168.8.1 -p udp --dport 53" "host resolver auto-detected"
hasnt "$out" "-d 127.0.0.53" "loopback stub resolver ignored"

# 4. bad input is refused and nothing is installed
for v in "HARVIS_BROWSER_ALLOW_CIDRS=10.0.0.0/33" "HARVIS_BROWSER_ALLOW_CIDRS=999.1.1.1" "HARVIS_BROWSER_ALLOW_CIDRS=banana" "HARVIS_BROWSER_SUBNET=10.1.1.1"; do
  : >"$STUB_LOG"
  out="$(env "$v" PATH="$T/bin:$PATH" "$LOCK" apply 2>&1)"; rc=$?
  { [ $rc -eq 0 ] && has "$out" "WARNING" "$v: warned" && [ ! -s "$STUB_LOG" ] && ok "$v: nothing installed"; } || bad "$v handling"
done

# 4b. repo-sandbox: pinned subnet gets the same wall, own chains, and its own subnet stays reachable
out="$(env -u HARVIS_REPO_SANDBOX_SUBNET -u HARVIS_BROWSER_ALLOW_CIDRS "$LOCK" print)"
has "$out" "-I DOCKER-USER 1 -s 10.213.84.0/24 -j HARVIS-SANDBOX-FWD" "hooks the repo-sandbox forward path on the default subnet"
has "$out" "-I INPUT 1 -s 10.213.84.0/24 -j HARVIS-SANDBOX-IN" "hooks the repo-sandbox host-bound path"
has "$out" "-A HARVIS-SANDBOX-IN -j DROP" "repo sandboxes cannot talk to the host itself"
for r in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 169.254.0.0/16 127.0.0.0/8; do
  has "$out" "-A HARVIS-SANDBOX-FWD -d $r -j DROP" "repo sandboxes: drops $r"
done
a=$(grep -n -- '-A HARVIS-SANDBOX-FWD -s 10.213.84.0/24 -d 10.213.84.0/24 -j ACCEPT' <<<"$out" | cut -d: -f1)
d=$(grep -n -- '-A HARVIS-SANDBOX-FWD -d 10.0.0.0/8 -j DROP' <<<"$out" | cut -d: -f1)
[ -n "$a" ] && [ -n "$d" ] && [ "$a" -lt "$d" ] && ok "own-subnet traffic is accepted before the drops" || bad "own-subnet accept missing or late"
c=$(grep -n -- '-A HARVIS-SANDBOX-IN -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT' <<<"$out" | cut -d: -f1)
i=$(grep -n -- '-A HARVIS-SANDBOX-IN -j DROP' <<<"$out" | cut -d: -f1)
[ -n "$c" ] && [ -n "$i" ] && [ "$c" -lt "$i" ] && ok "replies (published preview port) pass before the host-bound drop" || bad "conntrack accept missing or late"
out="$(HARVIS_BROWSER_ALLOW_CIDRS=192.168.50.0/24 "$LOCK" print)"
hasnt "$(grep SANDBOX <<<"$out")" "192.168.50.0/24" "the browser's allowed range does not widen the sandboxes"
out="$(HARVIS_REPO_SANDBOX_SUBNET=10.213.84.0/24,10.213.90.0/24 "$LOCK" print)"
has "$out" "-I DOCKER-USER 1 -s 10.213.90.0/24 -j HARVIS-SANDBOX-FWD" "second stack's sandbox subnet hooked"
: >"$STUB_LOG"
out="$(env HARVIS_REPO_SANDBOX_SUBNET=banana PATH="$T/bin:$PATH" "$LOCK" apply 2>&1)"; rc=$?
{ [ $rc -eq 0 ] && has "$out" "HARVIS_REPO_SANDBOX_SUBNET" "bad sandbox subnet: warned" && [ ! -s "$STUB_LOG" ]; } && ok "bad sandbox subnet: nothing installed" || bad "bad sandbox subnet handling"

# 5. real apply path against the stub: hooks go in, run twice is the same
: >"$STUB_LOG"; PATH="$T/bin:$PATH" "$LOCK" apply >/dev/null 2>&1
n1=$(grep -c -- '-I DOCKER-USER 1' "$STUB_LOG"); n2=$(grep -c -- '-I INPUT 1' "$STUB_LOG")
{ [ "$n1" -eq 2 ] && [ "$n2" -eq 2 ]; } && ok "apply inserts each hook once (browser + repo sandbox)" || bad "hook counts $n1/$n2"
grep -q -- '-w 5 -S DOCKER-USER' "$STUB_LOG" && ok "checks DOCKER-USER exists first" || bad "no DOCKER-USER probe"


# 5b. preflight: the apply is refused when it would miss the sandbox or cut the backend off
unset HARVIS_LOCK_SKIP_PREFLIGHT
installed() { grep -cE -- ' -[AIN] ' "$STUB_LOG"; }
run_apply() { : >"$STUB_LOG"; out="$(env PATH="$T/bin:$PATH" "$@" "$LOCK" apply 2>&1)"; rc=$?; }
# network left on the subnet Docker picked before the pin
run_apply STUB_SBX_NET=harvis_repo-sandbox STUB_SBX_SUBNET=172.19.0.0/16
{ [ $rc -eq 3 ] && has "$out" "harvis_repo-sandbox' is on 172.19.0.0/16" "old-subnet network: refused and named" \
  && has "$out" "docker network rm harvis_repo-sandbox" "old-subnet network: one-line fix given" \
  && [ "$(installed)" -eq 0 ]; } && ok "old-subnet network: no rule installed" || bad "old-subnet network rc=$rc rules=$(installed)"
# same network on the pinned subnet, backend routed through ollama-n8n-network: applies
run_apply STUB_SBX_NET=harvis_repo-sandbox STUB_SBX_SUBNET=10.213.84.0/24 STUB_BACKEND=abc123 STUB_GW_HEX=$OLLAMA_GW
{ [ $rc -eq 0 ] && [ "$(installed)" -gt 0 ]; } && ok "pinned subnet + backend on ollama-n8n-network: applies" || bad "good state refused rc=$rc: $out"
# backend default route through repo-sandbox: refused, nothing installed
run_apply STUB_SBX_NET=harvis_repo-sandbox STUB_SBX_SUBNET=10.213.84.0/24 STUB_BACKEND=abc123 STUB_GW_HEX=$SBX_GW
{ [ $rc -eq 3 ] && has "$out" "default route through the repo-sandbox network" "backend on repo-sandbox route: refused" \
  && has "$out" "docker compose up -d backend" "backend route: one-line fix given" \
  && [ "$(installed)" -eq 0 ]; } && ok "backend route: no rule installed" || bad "backend route rc=$rc rules=$(installed)"
# a custom pinned subnet list is honoured
run_apply STUB_SBX_NET=harvis_repo-sandbox STUB_SBX_SUBNET=10.213.90.0/24 HARVIS_REPO_SANDBOX_SUBNET=10.213.90.0/24
{ [ $rc -eq 0 ] && [ "$(installed)" -gt 0 ]; } && ok "network on the configured subnet: applies" || bad "configured subnet refused rc=$rc: $out"
# the override and the dry run are not blocked
run_apply STUB_SBX_NET=harvis_repo-sandbox STUB_SBX_SUBNET=172.19.0.0/16 HARVIS_LOCK_SKIP_PREFLIGHT=1
{ [ $rc -eq 0 ] && [ "$(installed)" -gt 0 ]; } && ok "HARVIS_LOCK_SKIP_PREFLIGHT=1 applies anyway" || bad "override rc=$rc"
out="$(env PATH="$T/bin:$PATH" STUB_SBX_NET=harvis_repo-sandbox STUB_SBX_SUBNET=172.19.0.0/16 "$LOCK" print 2>&1)"; rc=$?
{ [ $rc -eq 0 ] && has "$out" "-A HARVIS-SANDBOX-IN -j DROP" "print ignores the preflight"; } || bad "print blocked rc=$rc"
export HARVIS_LOCK_SKIP_PREFLIGHT=1

# 6. remove unhooks and deletes both chains
: >"$STUB_LOG"; PATH="$T/bin:$PATH" "$LOCK" remove >/dev/null 2>&1
grep -q -- '-w 5 -S DOCKER-USER' "$STUB_LOG" && ok "remove looks for the hooks" || bad "remove did not look for hooks"
rm_out="$("$LOCK" remove --dry-run)"
has "$rm_out" "-X HARVIS-BROWSER-FWD" "remove deletes forward chain"
has "$rm_out" "-X HARVIS-BROWSER-IN" "remove deletes input chain"
has "$rm_out" "-X HARVIS-SANDBOX-FWD" "remove deletes the repo-sandbox forward chain"
has "$rm_out" "-X HARVIS-SANDBOX-IN" "remove deletes the repo-sandbox input chain"

# 7. missing iptables / sudo: warn and exit 0
if PATH=/usr/bin:/bin command -v iptables >/dev/null 2>&1; then ok "skip no-iptables case (iptables in /usr/bin here)"; else
  out="$(env PATH=/usr/bin:/bin "$LOCK" apply 2>&1)"; rc=$?
  { [ $rc -eq 0 ] && has "$out" "iptables not found" "no iptables: warns, exits 0"; } || bad "no-iptables path rc=$rc"
fi
printf '#!/usr/bin/env bash\nexit 1\n' >"$T/bin/sudo"
if [ "$(id -u)" -ne 0 ]; then
  out="$(PATH="$T/bin:$PATH" "$LOCK" apply 2>&1)"; rc=$?
  { [ $rc -eq 0 ] && has "$out" "needs root" "no sudo: warns, exits 0"; } || bad "no-sudo path rc=$rc"
fi

[ $FAIL -eq 0 ] && echo "ALL PASS" || { echo "FAILURES"; exit 1; }
