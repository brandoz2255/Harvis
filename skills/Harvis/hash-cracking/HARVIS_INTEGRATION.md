# HARVIS Integration

## Layout

```
skills/Harvis/hash-cracking/
├── SKILL.md            # skill spec (loaded by skill router)
├── cracker.py          # tool implementations
├── wordlists/
│   ├── top1k.txt       # bundle in repo, ~10KB
│   ├── top1m.txt       # fetch on first use, ~9MB
│   └── rockyou.txt     # user provides
└── rules/
    └── best64.rule     # hashcat rules file
```

## OpenClaw tool registry

Register the six functions from `cracker.py` as individual tools so the agent can call them surgically. Tool names should mirror the function names exactly — your registry's tool description is what the model reads when deciding what to call.

```python
# python_back_end/tools/hash_cracking.py
import sys
from pathlib import Path

# cracker.py lives outside python_back_end so it can be edited as a skill
SKILL_PATH = Path(__file__).resolve().parents[2] / "skills" / "Harvis" / "hash-cracking"
sys.path.insert(0, str(SKILL_PATH))
import cracker  # noqa: E402

TOOLS = [
    {
        "name": "identify_hash",
        "description": "Return candidate hash algorithms for a hex string or salted hash. Always call this first.",
        "fn": cracker.identify_hash,
        "schema": {"target": "str"},
    },
    {
        "name": "verify",
        "description": "Verify that a plaintext produces a target hash. Every claimed crack must pass this before being reported.",
        "fn": cracker.verify,
        "schema": {"plaintext": "str", "target": "str", "algo": "str"},
    },
    {
        "name": "crack_wordlist",
        "description": "Try every line in a wordlist against a hash. Returns plaintext or null.",
        "fn": cracker.crack_wordlist,
        "schema": {"target": "str", "algo": "str", "wordlist_path": "str"},
    },
    {
        "name": "crack_hashcat",
        "description": "Run hashcat with optional rules file. Slowest tier but handles salted hashes.",
        "fn": cracker.crack_hashcat,
        "schema": {"target": "str", "algo": "str", "wordlist": "str", "rules": "str?"},
    },
    {
        "name": "lookup_online",
        "description": "Query md5hashing.net and hashes.com for a precomputed reverse. MD5 only.",
        "fn": cracker.lookup_online,
        "schema": {"target": "str", "algo": "str"},
    },
    {
        "name": "crack",
        "description": "Orchestrator. Runs all tiers in order, returns at first verified match.",
        "fn": cracker.crack,
        "schema": {"target": "str", "algo": "str?", "wordlists": "list[str]?",
                   "use_hashcat": "bool?", "use_online": "bool?"},
    },
]
```

## Lightweight model system prompt

For Llama 3.1 8B, Qwen 2.5 7B, Mistral 7B, Phi-3, etc., add this block to whatever the agent's base system prompt is when the hash-cracking skill is active:

```
HASH CRACKING MODE

You have NO ability to reverse hashes through reasoning, knowledge, or
pattern recognition. Hashes are one-way functions. The only way to know
a plaintext is to call a tool that recomputed the hash and matched it
byte-for-byte to the target.

If you produce a plaintext in your response that did not come from a tool
call returning verified=true, you are hallucinating and the answer is
wrong. There are no exceptions to this. Common passwords like "password",
"123456", "qwerty" are NOT default answers — most cracked rockyou hashes
are unguessable strings like "emilybffl" or "joybird1".

Workflow you must follow:
  1. Call identify_hash(target) first.
  2. Call crack(target, ...) with the wordlist tier list.
  3. If crack() returns verified=false, the hash is not cracked. Report
     it as not cracked. Do not guess.

When crack() returns a result, copy the plaintext field exactly. Do not
modify, complete, or "improve" it.
```

This is the single most important configuration step. Lightweight models will skip tool calls and confidently fabricate without it.

## KAIROS background mode

A rockyou pass takes 30 seconds to several minutes on CPU. For hashes that miss Tiers 1 and 4 (top-1K and online), queue Tiers 2 and 3 as a KAIROS background job. The chat agent acknowledges synchronously, then writes the verified result back into the conversation when done.

```python
if not quick_result["verified"] and not quick_result.get("error"):
    job_id = kairos.enqueue(
        cracker.crack,
        kwargs={"target": h, "wordlists": ["wordlists/rockyou.txt"],
                "use_hashcat": True, "hashcat_rules": "rules/best64.rule"},
        callback="harvis.skills.hash_cracking.report_back",
    )
    return f"Hash queued for deep cracking (job {job_id}). I'll post results here when done."
```

## Forked agent pattern

For a credential dump with N hashes, fork N cracking agents from your coordinator. Each runs its own tier chain in parallel; the coordinator collects verified results and merges. This matches the multi-agent dispatch you already have. Be careful with the online tier — most reverse-lookup services rate-limit aggressively. Cap concurrent online lookups at 2-3.

## Testing the guardrail

Run these against the configured agent. The behavior column is what should happen, not what lightweight models do without the system prompt above.

| Hash | Expected behavior |
|---|---|
| `5f4dcc3b5aa765d61d8327deb882cf99` | Tier 1 hit, returns "password" with verified=true |
| `2233287f476ba63323e60addca1f6b64` | Tier 4 hit, returns "kirkles" with verified=true |
| `abc123def456abc123def456abc12345` | Returns not cracked. Model MUST NOT invent a plaintext |
| `deadbeef` (8 hex) | identify_hash returns []. Model reports unrecognized format |

If the model returns a plaintext for the third row, the guardrail prompt is not strong enough. Add the third row's hash to the prompt as a worked counter-example.

## Wordlist sourcing

`top1k.txt` and `top1m.txt`: SecLists `Passwords/Common-Credentials/`. Bundle the small one, fetch the large one on first use.

`rockyou.txt`: ships with Kali at `/usr/share/wordlists/rockyou.txt.gz`. On other systems, instruct users to download manually — do not auto-fetch, the file's provenance matters for audit.

`best64.rule`: ships with hashcat at `/usr/share/hashcat/rules/best64.rule`.

## Network access for online tier

If HARVIS runs in a container with restricted egress, allowlist:
- `md5hashing.net`
- `hashes.com`
- `crackstation.net` (optional, JS-rendered, harder to scrape)

The online tier degrades cleanly to "skipped" if the endpoints are unreachable, so this is not blocking.

## Extending the skill

Add new tiers as more functions in `cracker.py` and append them to the orchestrator's chain. Candidates worth adding:

- **Mask attack tier** between rules and online — useful for known password policies (e.g. corporate "must contain digit and capital")
- **Markov-chain candidate generator** trained on prior cracks for the same target org
- **JTR ("john") fallback** for hash formats hashcat doesn't support
- **Hashes.com paid API** for hashes the free tier doesn't have
