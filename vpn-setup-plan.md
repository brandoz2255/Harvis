# VPN Setup Plan - Harvis AI Infrastructure

**Date:** 2026-02-15 (Tomorrow)  
**Goal:** Connect all K8s nodes to a unified VPN subnet for secure inter-node communication

---

## Pre-VPN Checklist

### 1. Power On RockyVMs
Before starting VPN configuration, ensure all RockyVMs are powered on and joined to the cluster:

```bash
# Start the VMs (run on dulc3-os host)
virsh start rocky2vm
virsh start rocky3vm

# Verify nodes are Ready
kubectl get nodes

# Expected output:
# NAME             STATUS   ROLES                  AGE
# dulc3-os         Ready    control-plane,master   206d
# raspberrypi      Ready    <none>                 91d
# raspberrypi2     Ready    <none>                 90d
# rocky1vm.local   Ready    <none>                 112d
# rocky2vm.local   Ready    <none>                 112d
# rocky3vm.local   Ready    <none>                 112d
```

### 2. Verify Current Deployments
Ensure all Harvis pods are running before VPN changes:

```bash
# Check all namespaces
kubectl get pods -n ai-agents
kubectl get pods -n artifact-executor
kubectl get pods -n argocd
kubectl get pods -n gitlab-runner

# Check node distribution
kubectl get pods --all-namespaces -o wide | grep -E "(ai-agents|artifact-executor)"
```

---

## VPN Architecture

### Proposed VPN Subnet
- **VPN Range:** `10.8.0.0/24`
- **VPN Type:** WireGuard (recommended) or Tailscale
- **Server:** dulc3-os (10.8.0.1)

### Node IP Assignments
| Node | VPN IP | Current Internal IP | Role |
|------|--------|---------------------|------|
| dulc3-os | 10.8.0.1 | 192.168.4.47 | VPN Server + K8s Master |
| rocky1vm.local | 10.8.0.2 | 192.168.122.194 | K8s Worker (Harvis Backend) |
| rocky2vm.local | 10.8.0.3 | 192.168.122.40 | K8s Worker (ArgoCD) |
| rocky3vm.local | 10.8.0.4 | 192.168.122.50 | K8s Worker (Artifact Executor) |
| raspberrypi | 10.8.0.5 | 192.168.4.115 | K8s Worker (CI Runner) |
| raspberrypi2 | 10.8.0.6 | 192.168.4.117 | K8s Worker (CI Runner) |

---

## Implementation Steps

### Step 1: Create Ansible Playbook Structure

Create directory structure:
```bash
mkdir -p ~/ansible-playbooks/vpn-setup/{inventory,playbooks,templates,files}
cd ~/ansible-playbooks/vpn-setup
```

### Step 2: Create Ansible Inventory

**File:** `inventory/hosts.ini`
```ini
[vpn_server]
dulc3-os ansible_host=192.168.4.47 vpn_ip=10.8.0.1

[vpn_clients]
rocky1vm.local ansible_host=192.168.122.194 vpn_ip=10.8.0.2
rocky2vm.local ansible_host=192.168.122.40 vpn_ip=10.8.0.3
rocky3vm.local ansible_host=192.168.122.50 vpn_ip=10.8.0.4
raspberrypi ansible_host=192.168.4.115 vpn_ip=10.8.0.5
raspberrypi2 ansible_host=192.168.4.117 vpn_ip=10.8.0.6

[k8s_nodes:children]
vpn_server
vpn_clients

[all:vars]
ansible_user=your-username
ansible_ssh_private_key_file=~/.ssh/id_rsa
vpn_subnet=10.8.0.0/24
vpn_port=51820
```

### Step 3: Create WireGuard Server Playbook

**File:** `playbooks/setup-vpn-server.yml`
```yaml
---
- name: Setup WireGuard VPN Server on dulc3-os
  hosts: vpn_server
  become: yes
  vars:
    vpn_subnet: "10.8.0.0/24"
    vpn_port: 51820
    
  tasks:
    - name: Install WireGuard
      package:
        name:
          - wireguard-tools
          - linux-headers
        state: present
      
    - name: Ensure WireGuard directory exists
      file:
        path: /etc/wireguard
        state: directory
        mode: '0700'
    
    - name: Generate server private key
      command: wg genkey
      register: server_private_key
      changed_when: false
      no_log: true
    
    - name: Generate server public key
      shell: echo "{{ server_private_key.stdout }}" | wg pubkey
      register: server_public_key
      changed_when: false
      no_log: true
    
    - name: Create server WireGuard config
      template:
        src: wg0-server.conf.j2
        dest: /etc/wireguard/wg0.conf
        mode: '0600'
      vars:
        private_key: "{{ server_private_key.stdout }}"
    
    - name: Enable IP forwarding
      sysctl:
        name: net.ipv4.ip_forward
        value: '1'
        sysctl_set: yes
        state: present
        reload: yes
    
    - name: Configure firewall - Allow WireGuard port
      command: "firewall-cmd --add-port={{ vpn_port }}/udp --permanent"
      ignore_errors: yes
    
    - name: Configure firewall - Allow VPN subnet
      command: "firewall-cmd --add-rich-rule='rule family=ipv4 source address={{ vpn_subnet }} accept' --permanent"
      ignore_errors: yes
    
    - name: Reload firewall
      command: firewall-cmd --reload
      ignore_errors: yes
    
    - name: Start and enable WireGuard
      systemd:
        name: wg-quick@wg0
        enabled: yes
        state: started
    
    - name: Save server keys for client configs
      copy:
        content: |
          SERVER_PRIVATE_KEY={{ server_private_key.stdout }}
          SERVER_PUBLIC_KEY={{ server_public_key.stdout }}
        dest: /etc/wireguard/server-keys.env
        mode: '0600'
      no_log: true
```

### Step 4: Create WireGuard Client Playbook

**File:** `playbooks/setup-vpn-clients.yml`
```yaml
---
- name: Setup WireGuard VPN Clients
  hosts: vpn_clients
  become: yes
  vars:
    vpn_port: 51820
    server_public_key: "{{ lookup('file', '/etc/wireguard/server-keys.env') | regex_search('SERVER_PUBLIC_KEY=(.+)', '\\1') | first }}"
    server_endpoint: "{{ hostvars[groups['vpn_server'][0]]['ansible_host'] }}:{{ vpn_port }}"
  
  tasks:
    - name: Install WireGuard
      package:
        name: wireguard-tools
        state: present
    
    - name: Ensure WireGuard directory exists
      file:
        path: /etc/wireguard
        state: directory
        mode: '0700'
    
    - name: Generate client private key
      command: wg genkey
      register: client_private_key
      changed_when: false
      no_log: true
    
    - name: Generate client public key
      shell: echo "{{ client_private_key.stdout }}" | wg pubkey
      register: client_public_key
      changed_when: false
      no_log: true
    
    - name: Create client WireGuard config
      template:
        src: wg0-client.conf.j2
        dest: /etc/wireguard/wg0.conf
        mode: '0600'
      vars:
        private_key: "{{ client_private_key.stdout }}"
    
    - name: Start and enable WireGuard
      systemd:
        name: wg-quick@wg0
        enabled: yes
        state: started
    
    - name: Display client public key
      debug:
        msg: "Client {{ inventory_hostname }} public key: {{ client_public_key.stdout }}"
```

### Step 5: Create Configuration Templates

**File:** `templates/wg0-server.conf.j2`
```ini
[Interface]
Address = 10.8.0.1/24
ListenPort = {{ vpn_port }}
PrivateKey = {{ private_key }}
PostUp = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE
DNS = 1.1.1.1, 8.8.8.8

# rocky1vm.local
[Peer]
PublicKey = <PLACEHOLDER_FOR_ROCKY1_PUBLIC_KEY>
AllowedIPs = 10.8.0.2/32

# rocky2vm.local
[Peer]
PublicKey = <PLACEHOLDER_FOR_ROCKY2_PUBLIC_KEY>
AllowedIPs = 10.8.0.3/32

# rocky3vm.local
[Peer]
PublicKey = <PLACEHOLDER_FOR_ROCKY3_PUBLIC_KEY>
AllowedIPs = 10.8.0.4/32

# raspberrypi
[Peer]
PublicKey = <PLACEHOLDER_FOR_PI1_PUBLIC_KEY>
AllowedIPs = 10.8.0.5/32

# raspberrypi2
[Peer]
PublicKey = <PLACEHOLDER_FOR_PI2_PUBLIC_KEY>
AllowedIPs = 10.8.0.6/32
```

**File:** `templates/wg0-client.conf.j2`
```ini
[Interface]
Address = {{ vpn_ip }}/24
PrivateKey = {{ private_key }}
DNS = 10.8.0.1, 1.1.1.1

[Peer]
PublicKey = {{ server_public_key }}
Endpoint = {{ server_endpoint }}
AllowedIPs = 10.8.0.0/24
PersistentKeepalive = 25
```

### Step 6: Create Master Playbook

**File:** `playbooks/setup-vpn.yml`
```yaml
---
- import_playbook: setup-vpn-server.yml
- import_playbook: setup-vpn-clients.yml
- import_playbook: verify-vpn.yml
```

### Step 7: Create Verification Playbook

**File:** `playbooks/verify-vpn.yml`
```yaml
---
- name: Verify VPN Connectivity
  hosts: k8s_nodes
  become: yes
  
  tasks:
    - name: Check WireGuard interface status
      command: wg show
      register: wg_status
      changed_when: false
    
    - name: Display WireGuard status
      debug:
        var: wg_status.stdout_lines
    
    - name: Test VPN connectivity to all nodes
      command: "ping -c 2 {{ item }}"
      with_items:
        - 10.8.0.1
        - 10.8.0.2
        - 10.8.0.3
        - 10.8.0.4
        - 10.8.0.5
        - 10.8.0.6
      ignore_errors: yes
      register: ping_results
    
    - name: Display ping results
      debug:
        msg: "Ping to {{ item.item }}: {{ 'SUCCESS' if item.rc == 0 else 'FAILED' }}"
      with_items: "{{ ping_results.results }}"
```

---

## Execution Commands

### Run the Complete VPN Setup

```bash
cd ~/ansible-playbooks/vpn-setup

# Test connectivity first
ansible -i inventory/hosts.ini all -m ping

# Run the VPN setup
ansible-playbook -i inventory/hosts.ini playbooks/setup-vpn.yml

# If you need to run steps individually:
ansible-playbook -i inventory/hosts.ini playbooks/setup-vpn-server.yml
ansible-playbook -i inventory/hosts.ini playbooks/setup-vpn-clients.yml
ansible-playbook -i inventory/hosts.ini playbooks/verify-vpn.yml
```

---

## Post-VPN Verification Checklist

### K8s Cluster Verification
```bash
# 1. Verify all nodes are still Ready
kubectl get nodes -o wide

# 2. Check pod status across all namespaces
kubectl get pods --all-namespaces -o wide

# 3. Verify CoreDNS is working
kubectl run -it --rm debug --image=busybox:1.28 --restart=Never -- nslookup kubernetes.default

# 4. Test inter-pod communication
kubectl run -it --rm debug --image=nicolaka/netshoot --restart=Never -- /bin/bash
# Inside the pod:
ping 10.8.0.1
ping 10.8.0.2
```

### ArgoCD Verification
```bash
# Check ArgoCD is accessible via VPN
kubectl get svc -n argocd

# Port-forward to test UI
kubectl port-forward svc/argocd-server -n argocd 8080:443
# Access: https://localhost:8080
```

### Service Communication Verification
```bash
# Test backend connectivity
curl http://harvis-ai-backend.ai-agents.svc.cluster.local:8000/health

# Test frontend
curl http://harvis-ai-frontend.ai-agents.svc.cluster.local:3000

# Test artifact executor
curl http://artifact-executor.artifact-executor.svc.cluster.local:8080/health
```

---

## Troubleshooting

### Issue: Nodes Not Ready After VPN
**Solution:**
```bash
# Check kubelet logs on affected node
journalctl -u k3s-agent -f

# Restart k3s agent if needed
sudo systemctl restart k3s-agent
```

### Issue: WireGuard Not Starting
**Solution:**
```bash
# Check WireGuard logs
journalctl -u wg-quick@wg0 -f

# Check interface
sudo wg show

# Check firewall rules
sudo firewall-cmd --list-all
```

### Issue: DNS Resolution Failing
**Solution:**
```bash
# Check CoreDNS
kubectl get pods -n kube-system | grep coredns
kubectl logs -n kube-system -l k8s-app=kube-dns

# Restart CoreDNS
kubectl rollout restart deployment coredns -n kube-system
```

### Issue: K8s API Server Unreachable
**Solution:**
```bash
# On dulc3-os (master)
sudo systemctl restart k3s

# On workers
sudo systemctl restart k3s-agent

# Verify cluster
kubectl cluster-info
```

---

## Alternative: Tailscale (Easier Option)

If WireGuard is too complex, use Tailscale:

```bash
# Install Tailscale on all nodes
curl -fsSL https://tailscale.com/install.sh | sh

# Login (do this on each node)
sudo tailscale up

# Get Tailscale IPs
tailscale ip -4

# Enable subnet routing (on dulc3-os)
sudo tailscale up --advertise-routes=192.168.4.0/24,192.168.122.0/24
```

**Benefits:**
- Automatic NAT traversal
- Built-in key management
- Magic DNS
- No port forwarding needed
- Works even behind CGNAT

---

## Documentation Update Tasks

After VPN is working, update these files:

1. **CLAUDE.md** - Add VPN subnet information
2. **k8s-manifests/services/*.yaml** - Update any hardcoded IPs if needed
3. **Network documentation** - Document the new topology

---

## Success Criteria

✅ All nodes can ping each other via VPN IPs (10.8.0.x)  
✅ K8s cluster remains functional after VPN setup  
✅ All pods are Running and Ready  
✅ ArgoCD accessible and functional  
✅ GitLab runners can still reach GitLab  
✅ Backend services can communicate  
✅ No regression in Harvis functionality  

---

## Rollback Plan

If VPN setup fails:

```bash
# Stop WireGuard on all nodes
ansible -i inventory/hosts.ini all -m systemd -a "name=wg-quick@wg0 state=stopped enabled=no" --become

# Remove WireGuard configs
ansible -i inventory/hosts.ini all -m file -a "path=/etc/wireguard state=absent" --become

# Verify K8s is still working
kubectl get nodes
kubectl get pods --all-namespaces
```

---

**Note:** This is a living document. Update it as you learn what works best for your infrastructure.

**Next Review Date:** After VPN is operational
