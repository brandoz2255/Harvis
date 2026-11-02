---
name: harvis-file
description: >
  Read and analyze user-attached text files — logs (.log), plain text
  (.txt), config files (.conf, .ini, .yaml, .json), CSVs, source code,
  anything grep/awk/cat can handle. Use whenever the user attaches a
  text-format file and asks questions about its contents.
metadata:
  openclaw:
    emoji: "\U0001f4c4"
    always: false
---

# Harvis File Analysis

## You have file-reading tools. Use them, don't describe them.

Every time you're asked about an attached file, the user wants a
**concrete answer extracted from the file's contents** — not a "Step 1:
scan the log… Step 2: extract IPs… Step 3: identify unique sources"
essay. Writing the plan instead of executing it is refusal with extra
steps. If this skill is loaded, the tools are there. Use them.

## The three-step loop you always follow

1. **Download** the attached file (URL from the `[Attached files…]`
   block at the top of your task) to a local path.
2. **Extract** the specific answer with `grep` / `awk` / `sort -u` /
   `head` / `tail` / whatever one-liner actually returns the value
   the user asked for.
3. **Answer** with the literal result. No "Analysis Plan", no "Step
   1", no "Assuming standard format". The extraction already
   happened — just report what the tool printed.

If you catch yourself about to write "I will scan the log for…", stop.
Call `exec` and actually run the command. Your reply should contain
the answer, not the plan.

## Step 1 — Download the attachment

The task message contains a block like:
```
[Attached files from the user]
1. auth.log — text/plain — url=https://cdn.discordapp.com/attachments/.../auth.log
```

Download it:
```
bash -lc "curl -sSL -o /tmp/file.log 'THE_URL'"
```

Pick a `/tmp/` filename that matches the extension (`.log`, `.txt`,
`.csv`, `.json`, `.py`, etc.) so tools behave.

If there are multiple attachments, download each to a distinct path
(`/tmp/a.log`, `/tmp/b.log`). Don't overwrite.

## Step 2 — Extract the answer

Pick the one-liner that answers the specific question. Common
patterns:

### Logs (auth.log, syslog, nginx access, etc.)

| Question | One-liner |
|----------|-----------|
| Hostname the log is from (syslog format) | `awk '{print $4; exit}' /tmp/file.log` |
| All unique source IPs | `grep -oE '\b([0-9]{1,3}\.){3}[0-9]{1,3}\b' /tmp/file.log \| sort -u` |
| Unique source IPs **in order of first appearance** | `grep -oE '\b([0-9]{1,3}\.){3}[0-9]{1,3}\b' /tmp/file.log \| awk '!seen[$0]++'` |
| First IP to attack (first failed-auth IP) | `grep -m1 'Failed password' /tmp/file.log \| grep -oE '\b([0-9]{1,3}\.){3}[0-9]{1,3}\b'` |
| Top N most-frequent IPs | `grep -oE '\b([0-9]{1,3}\.){3}[0-9]{1,3}\b' /tmp/file.log \| sort \| uniq -c \| sort -rn \| head -N` |
| All failed-login usernames | `awk '/Failed password/ {for(i=1;i<=NF;i++)if($i=="for"){print $(i+1)}}' /tmp/file.log \| sort -u` |
| Count lines | `wc -l /tmp/file.log` |
| First/last N lines | `head -N /tmp/file.log` / `tail -N /tmp/file.log` |
| Time range | `head -1 /tmp/file.log; tail -1 /tmp/file.log` |

**For "first/second/third unique IP to attack" questions specifically**
(a common CTF pattern), run:
```
bash -lc "grep -oE '\b([0-9]{1,3}\.){3}[0-9]{1,3}\b' /tmp/file.log | awk '!seen[\$0]++' | head -5"
```
That prints the first five unique IPs in their order of first
appearance — pick the 1st, 2nd, 3rd from the list and answer.

### CSVs

| Question | One-liner |
|----------|-----------|
| Column names | `head -1 /tmp/data.csv` |
| Row count (excl. header) | `tail -n +2 /tmp/data.csv \| wc -l` |
| Unique values in column N (comma-separated) | `tail -n +2 /tmp/data.csv \| cut -d, -f N \| sort -u` |
| Sum of column N | `tail -n +2 /tmp/data.csv \| cut -d, -f N \| awk '{s+=$1} END {print s}'` |

### JSON

- For small files, `cat /tmp/data.json`.
- For extraction, prefer `python3 -c "import json,sys; d=json.load(open('/tmp/data.json')); print(d['key']['nested'])"`.
- `jq` may not be installed; if `which jq` returns empty, fall
  back to Python.

### Source code / text

| Question | One-liner |
|----------|-----------|
| Find string X | `grep -n 'X' /tmp/file.ext` |
| Count occurrences of X | `grep -c 'X' /tmp/file.ext` |
| Functions defined (Python) | `grep -n '^def ' /tmp/file.py` |
| TODO/FIXME/HACK markers | `grep -nE 'TODO\|FIXME\|HACK\|XXX' /tmp/file.ext` |

## Step 3 — Answer directly

For multi-part questions (CTF-style: Q1 hostname, Q2 first IP,
Q3 second IP, Q4 third IP), run **one** combined extraction that
gives all the answers at once, then report them in one reply.

Example for the "auth.log CTF" ask:
```
bash -lc "
  echo 'hostname:'; awk '{print \$4; exit}' /tmp/auth.log;
  echo 'unique attacking IPs (first-seen order):';
  grep -oE '\b([0-9]{1,3}\.){3}[0-9]{1,3}\b' /tmp/auth.log | awk '!seen[\$0]++' | head -5
"
```

Then answer directly:

> **Q1 (hostname):** myraptor
> **Q2 (first IP):** 169.139.243.218
> **Q3 (second IP):** 103.x.x.x
> **Q4 (third IP):** 45.x.x.x

That's it. No plan, no "assuming", no "I will analyze".

## Rules

- **Never** write "Analysis Plan:", "Step 1:", "I will scan…" without
  also immediately calling `exec` to actually do it. If both appear,
  delete the plan — the result *is* the answer.
- **Never** invent an IP address, hostname, or value. If the
  extraction returns nothing, say "no matches in the file" — do not
  generate a plausible-looking fake ("203.0.113.45", "[placeholder]",
  "103.XXX.XXX.XXX" are all fabrications and wrong).
- **Never** answer a file-analysis question without running a tool on
  the file first. "Based on the log file…" in your reply must be
  backed by a real `exec` call earlier in the same turn.
- **Never** end with `Copy that.`, `Standing by.`, `On it.`, or any
  acknowledgment-only reply. For a file task you either extracted the
  answer with a tool or you report the exact blocker.
- **Always** answer every sub-question the user asked. For "Q1
  hostname, Q2 first IP, Q3 second IP, Q4 third IP", do not split
  into four sub-agents — it's one file and one combined extraction.
- If the attachment URL 404s or curl fails, report the exact
  failure and stop — don't simulate an answer.
- If the extraction is ambiguous or returns no clear result, say so
  plainly ("I couldn't determine X confidently from this file") and
  mention the exact failed signal. Do not fill the gap with a guess.
- For files over ~10 MB, `head -c 100000 /tmp/file` first to sample,
  then decide if you need the full thing.
