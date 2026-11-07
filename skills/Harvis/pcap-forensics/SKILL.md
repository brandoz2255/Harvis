---
name: pcap-forensics
description: Answer questions about a packet capture (.pcap/.pcapng) for forensics or CTF work, and write packet-crafting scripts for live "knock" challenges. Trigger when the user attaches a capture, mentions Wireshark/tshark/tcpdump, ARP/DNS/NTLM attacks, or NCL / Cyber Skyline packet challenges. Flags look like SKY-XXXX-XXXX.
---

# PCAP forensics

## Setup in your box
- Uploads are in `/workspace/uploads/`. Work on that file directly; never edit the original.
- `tshark`, `tcpdump` and Python `scapy` are installed. `sudo apt-get install` works for anything else.
- Your box has no network path to a challenge's target. For live challenges, write a script the user runs on the challenge machine (see the last section).

## Procedure
1. Overview first: `tshark -r FILE -q -z io,phs` (protocol tree) and `tshark -r FILE -q -z conv,ip` (who talked to whom).
2. Build ground-truth maps in scapy before answering:
   - IP -> set of MACs that sent ARP replies for it. An IP claimed by more than one MAC is spoofed.
   - MAC -> set of source IPs seen in real IP traffic. This gives each MAC's true identity.
3. Answer each question from the maps plus targeted field extraction (`tshark -Y <filter> -T fields -e <field>`).
4. Name the packet numbers that prove each answer, and say whether an attack succeeded: what arrived, not what was sent.
5. Parse, don't eyeball. Counting by hand across hundreds of packets is where answers go wrong.

## Attack patterns
- **ARP spoofing / MITM:** unsolicited ARP replies (op 2) claiming an IP another MAC owns, usually in both directions (gateway toward victim and victim toward gateway). The rogue MAC is the one claiming an IP it never sources traffic from. A redundant gateway (HSRP/VRRP) also announces the gateway IP but steadily and periodically; it is not the attacker.
- **DNS -> LLMNR/NBNS spoofing:** the victim's DNS query fails, it falls back to LLMNR (224.0.0.252:5355) or NBNS (137), and the attacker answers with its own IP. The forged reply's Ethernet source is the attacker's MAC. The name being resolved is the query name.
- **NTLM capture/relay (SMB 445/139):** find `NTLMSSP\x00`; the type byte at +8 is 1 negotiate, 2 challenge, 3 authenticate. A relay opens a new connection to a different server at the same moment the victim's type 1 arrives; that server is the relay target. In the type 3 message, domain/user/host are security buffers at offsets 28/36/44 (len 2, maxlen 2, offset 4, UTF-16LE). `tshark -Y ntlmssp.auth.username -T fields -e ntlmssp.auth.domain -e ntlmssp.auth.username` does this for you.
- **Traceroute covert channel:** UDP to ports 33434+ with rising TTL. The normal payload is the bytes 0x40-0x5f (`@ABC...^_`). A hidden message overwrites one byte per packet; read it in port order and compare against a clean traceroute. Only packets whose TTL reached the target were delivered, usually just the last one.
- **File exfiltration:** after auth, search packet bytes for a known label in ASCII and UTF-16LE and dump the printable bytes around it, or use `tshark --export-objects smb,DIR` / `http,DIR`.

## Live packet ("knock") challenges
Some challenges give a live target and say "knock in an orderly fashion": each question describes one packet, and a correct packet makes the target send back a reply carrying the flag.

Decode each clue to a packet. Clues are trivia:
- "ping" = ICMP echo request
- a chemical element = UDP to its atomic number
- "Nth Mersenne prime" = UDP to that number (3, 7, 31, 127, 8191, ...)
- "eleet" = UDP 31337
- "alphabet generator and reflector" = chargen and echo: UDP source port 19, destination port 7
- "information request" = ICMP type 15. If a question is quoted, the question text goes in the payload; the target matches the string, not a port.

Write a self-contained `knock.py` for the user to run as root on the machine that can reach the target. The target is the other live host on that machine's subnet (`nmap -sn <subnet>`), not the user's own address. The script must start a sniffer before sending:

```python
from scapy.all import IP, ICMP, UDP, Raw, AsyncSniffer, send, conf
import binascii, re, sys, time
conf.verb = 0
T = sys.argv[1]
def knock(pkt):
    s = AsyncSniffer(filter=f"host {T}", store=True); s.start(); time.sleep(0.3)
    send(pkt); time.sleep(3.5)
    for p in s.stop():
        if p.haslayer(Raw):
            raw = bytes(p[Raw].load)
            texts = [raw.decode(errors="replace")]
            try: texts.append(binascii.unhexlify(raw.strip()).decode(errors="replace"))
            except (binascii.Error, ValueError): pass
            for txt in texts:
                print(p.summary(), "|", txt)   # print it all, never truncate
                m = re.search(r"SKY-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}", txt)
                if m: print("FLAG", m.group())
knock(IP(dst=T)/ICMP())
```

Pitfalls:
- The reply payload is often ASCII hex, so a plain search for `SKY-` finds nothing. Decode hex first; the script above tries both.
- Don't sweep all 65535 ports. The target floods unreachables and drops real knocks. Send one clean packet at a time.
- `nmap` showing no open ports means a passive knock matcher, not a dead end.
- If every port guess for a number fails, the clue probably maps to a payload string. Print every reply to see what the target reacts to.
