#!/usr/bin/env bash
# Measure what a FreeToken node can actually take, so the numbers in
# docs/inference-nodes.md are measured rather than assumed.
#
#   scripts/freetoken/limits.sh              full sweep
#   FT_LIMITS_MAX=8000 scripts/freetoken/limits.sh    stop the prompt sweep earlier
#
# What it reports, and why each one matters to Harvis:
#   * KV capacity — the real context, not the 262K the model advertises. The prober
#     caps the picker's ctx to this, and the thinking policy uses the headroom.
#   * The largest prompt that prefills — above this the node returns "prompt is too
#     long" (clean) and, before FT_MAX_PREFILL was tuned, OOM-killed the scheduler
#     (not clean). This is the number that decides how much reach context is safe.
#   * Decode speed at depth — whether long chats slow down.
#   * Concurrency — what a second simultaneous request costs.
#
# Each request uses max_tokens=8 and thinking off, so the sweep costs seconds of GPU,
# not minutes. It is safe to run against a live node, but it does occupy it.
set -uo pipefail
FT_HOST="${FT_HOST:-127.0.0.1}"; FT_PORT="${FT_PORT:-1919}"
BASE="http://$FT_HOST:$FT_PORT"
MAXP="${FT_LIMITS_MAX:-16000}"

health="$(curl -fsS --max-time 5 "$BASE/health")" || { echo "no node at $BASE"; exit 1; }
MODEL="$(printf '%s' "$health" | python3 -c 'import json,sys; print(json.load(sys.stdin)["model"])')"
echo "node   : $BASE"
echo "model  : $MODEL"

kv="$(curl -fsS "$BASE/v1/stats" | python3 -c 'import json,sys
d=(json.load(sys.stdin).get("kv") or {}); print(d.get("total_pages") or 0)')"
adv="$(curl -fsS "$BASE/v1/models" | python3 -c 'import json,sys
d=json.load(sys.stdin)["data"][0]; print(d.get("context_length") or d.get("max_model_len") or "?")')"
echo "context: advertised $adv, KV cache $kv tokens  <-- the real ceiling"
[ "$kv" = "0" ] && echo "         (0 means no request since the last restart; run one first)"
echo

probe() { # words -> "prompt_tokens wall_seconds" or "FAIL <reason>"
  local words="$1" body t0 t1 out
  body="$(python3 -c '
import json, sys
n = int(sys.argv[1])
filler = " ".join("the quick brown fox jumps over the lazy dog number %d." % i for i in range(n // 10 + 1))
print(json.dumps({"model": sys.argv[2], "max_tokens": 8, "stream": False,
                  "messages": [{"role": "user", "content": filler + "\n\nReply with the single word: ok"}],
                  "chat_template_kwargs": {"enable_thinking": False}}))' "$words" "$MODEL")"
  t0="$(date +%s.%N)"
  out="$(curl -sS --max-time 180 -H 'Content-Type: application/json' -d "$body" "$BASE/v1/chat/completions" 2>&1)"
  t1="$(date +%s.%N)"
  printf '%s' "$out" | python3 -c '
import json, sys
raw = sys.stdin.read()
try: d = json.loads(raw)
except Exception: print("FAIL", raw.strip()[:110] or "no response"); raise SystemExit
if "error" in d and d.get("error"):
    e = d["error"]; print("FAIL", (e.get("message") if isinstance(e, dict) else str(e))[:110]); raise SystemExit
u = d.get("usage") or {}
print(u.get("prompt_tokens", "?"), "%.1f" % (float(sys.argv[2]) - float(sys.argv[1])))' "$t0" "$t1"
}

echo "== prompt sweep (max_tokens=8, thinking off) =="
printf '%-12s %-14s %-9s %s\n' "target" "prompt tokens" "wall" "result"
for words in 500 1500 3000 5000 8000 11000 14000 16000 20000; do
  [ "$words" -gt "$MAXP" ] && break
  r="$(probe "$words")"
  case "$r" in
    FAIL*) printf '%-12s %-14s %-9s %s\n' "$words w" "-" "-" "${r#FAIL }"
           echo "  ^ first refusal — the node stops here, cleanly"; break ;;
    *) set -- $r; printf '%-12s %-14s %-9s %s\n' "$words w" "$1" "${2}s" "ok" ;;
  esac
  systemctl --user is-active --quiet freetoken.service || { echo "  !! service died at $words words"; break; }
  curl -fsS --max-time 5 "$BASE/health" >/dev/null 2>&1 || { echo "  !! node stopped answering at $words words (scheduler gone?)"; break; }
done

echo
echo "== decode speed at depth (max_tokens=120) =="
printf '%-16s %-14s %-9s %s\n' "context" "prompt tokens" "wall" "decode"
for words in 500 8000; do
  body="$(python3 -c '
import json, sys
n = int(sys.argv[1])
filler = " ".join("the quick brown fox jumps over the lazy dog number %d." % i for i in range(n // 10 + 1))
print(json.dumps({"model": sys.argv[2], "max_tokens": 120, "stream": False,
                  "messages": [{"role": "user", "content": filler + "\n\nWrite one paragraph about rain."}],
                  "chat_template_kwargs": {"enable_thinking": False}}))' "$words" "$MODEL")"
  t0="$(date +%s.%N)"
  out="$(curl -sS --max-time 180 -H 'Content-Type: application/json' -d "$body" "$BASE/v1/chat/completions" 2>&1)"
  t1="$(date +%s.%N)"
  printf '%s' "$out" | python3 -c '
import json, sys
try: d = json.loads(sys.stdin.read())
except Exception: print("%-16s %s" % (sys.argv[3] + " words", "FAIL")); raise SystemExit
u = d.get("usage") or {}
wall = float(sys.argv[2]) - float(sys.argv[1])
c = u.get("completion_tokens") or 0
print("%-16s %-14s %-9s %s" % (sys.argv[3] + " words", u.get("prompt_tokens", "?"),
      "%.1fs" % wall, ("%.1f tok/s" % (c / wall)) if wall else "-"))' "$t0" "$t1" "$words"
done

echo
echo "== concurrency (2 at once, ~1.5k-token prompts) =="
t0="$(date +%s.%N)"; probe 1500 >/dev/null & probe 1500 >/dev/null & wait; t1="$(date +%s.%N)"
python3 -c 'print("two parallel requests: %.1fs wall" % (float(__import__("sys").argv[2]) - float(__import__("sys").argv[1])))' "$t0" "$t1"

echo
echo "== counters now =="
curl -fsS "$BASE/v1/stats" | python3 -c 'import json,sys
d = json.load(sys.stdin); r = d.get("requests") or {}; kv = d.get("kv") or {}
print("completed %s  p95 %ss  ttft_mean %ss" % (r.get("completed"), round((r.get("p95_ms") or 0)/1000, 1), round((r.get("ttft_mean_ms") or 0)/1000, 2)))
print("kv pages used %s of %s" % (kv.get("used_pages"), kv.get("total_pages")))'
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader 2>/dev/null | sed 's/^/vram   : /'
echo
echo "warm decode (journal, cold first sample dropped):"
journalctl --user -u freetoken --since "10 min ago" --no-pager 2>/dev/null \
  | grep -oE 'gen throughput \(token/s\): [0-9.]+' | grep -oE '[0-9.]+$' \
  | awk '$1>5{s+=$1;n++} END{if(n) printf "  %.1f tok/s over %d samples\n", s/n, n; else print "  no samples"}'
exit 0
