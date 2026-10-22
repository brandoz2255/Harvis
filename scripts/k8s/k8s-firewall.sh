# Kubelet port firewall for the k3s server. Sourced by harvis-k8s.sh, which
# provides say, kc and SUDO.
#
# The kubelet API (TCP 10250) can run commands in any pod on the node, and k3s
# listens on every interface. It checks credentials, so this is a second lock:
# only this machine, the pods, the services and the cluster's own nodes may
# connect at all. Port 6443 (the API server) is left open on purpose: workers
# must reach it to join, and it only answers to the join token or a client
# certificate. The rules live in their own chain, so removing them is one chain.
KUBELET_PORT=10250
FW_CHAIN=HARVIS-K3S
POD_CIDR=10.42.0.0/16
SVC_CIDR=10.43.0.0/16

ipt() { $SUDO iptables -w "$@"; }
ipt_restore() { $SUDO iptables-restore -w --noflush; }
have_iptables() { command -v iptables >/dev/null 2>&1 && command -v iptables-restore >/dev/null 2>&1; }

cluster_node_ips() {
  kc get nodes -o jsonpath='{range .items[*]}{range .status.addresses[?(@.type=="InternalIP")]}{.address}{"\n"}{end}{end}' 2>/dev/null || true
}

# The chain's rules, one iptables argument line each. Anything that is not an
# IPv4 address or range is skipped, so a bad node address cannot become a rule.
kubelet_rules() { # node IPs...
  local src
  for src in 127.0.0.0/8 "$POD_CIDR" "$SVC_CIDR" "$@"; do
    [[ $src =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}(/[0-9]{1,2})?$ ]] || continue
    printf -- '-A %s -s %s -j RETURN\n' "$FW_CHAIN" "$src"
  done
  printf -- '-A %s -j DROP\n' "$FW_CHAIN"
}

# Rebuilt from scratch every time, so a re-run (or a node that joined) converges.
# The chain is written in one iptables-restore transaction. k3s's network policy
# controller saves and restores the filter table, and on nf_tables a restore that
# names a chain empties it: rule-by-rule writes could lose the loopback rule while
# DROP stayed, which hangs kubectl exec and logs.
fw_install() { # node IPs...
  { printf '*filter\n:%s - [0:0]\n-F %s\n' "$FW_CHAIN" "$FW_CHAIN"
    kubelet_rules "$@"
    printf 'COMMIT\n'
  } | ipt_restore || return 1
  ipt -C INPUT -p tcp --dport "$KUBELET_PORT" -j "$FW_CHAIN" 2>/dev/null ||
    ipt -I INPUT 1 -p tcp --dport "$KUBELET_PORT" -j "$FW_CHAIN" || return 1
}

apply_kubelet_firewall() { # [quiet]
  have_iptables || { say "⚠ iptables is not installed — kubelet port $KUBELET_PORT stays open to your network"; return 0; }
  local ips
  ips="$(cluster_node_ips | tr '\n' ' ')"
  # Without the node list the server's own address would be missing from the rules.
  [ -n "${ips// /}" ] || { say "⚠ Could not list the cluster's nodes — kubelet port $KUBELET_PORT rules left as they were"; return 0; }
  # shellcheck disable=SC2086
  if fw_install $ips; then
    [ "${1:-}" = quiet ] || say "✓ Kubelet port $KUBELET_PORT is closed to your network (only this machine, the pods and the nodes)"
  else
    say "⚠ Could not set the firewall for kubelet port $KUBELET_PORT — it stays as it was"
  fi
  return 0
}

remove_kubelet_firewall() {
  have_iptables || return 0
  local n=0
  while [ "$n" -lt 20 ] && ipt -C INPUT -p tcp --dport "$KUBELET_PORT" -j "$FW_CHAIN" 2>/dev/null; do
    ipt -D INPUT -p tcp --dport "$KUBELET_PORT" -j "$FW_CHAIN" || break
    n=$((n + 1))
  done
  ipt -F "$FW_CHAIN" 2>/dev/null || true
  ipt -X "$FW_CHAIN" 2>/dev/null || true
  return 0
}
