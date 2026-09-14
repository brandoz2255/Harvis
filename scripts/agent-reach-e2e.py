"""Agent Reach end-to-end: does a model on the NATIVE lane actually reach for the tools?

Mirrors runner.py's loop exactly where it matters — same ModelRouter, same
WIRE_TOOL_SCHEMA, same parse_tool_calls, same dispatch_tool (so the real lane
gate and the real SSRF guard are in the path). Not the full runner: no events,
no risk gate, no workspace fingerprint.

Run it INSIDE the backend container, which already has HARVIS_AGENT_REACH_ENABLED
and a reachable OLLAMA_URL:

    docker cp scripts/agent-reach-e2e.py harvis-backend:/tmp/x.py
    docker exec -w /app harvis-backend python /tmp/x.py gpt-oss:20b

Item 4 is the one that matters: 169.254.169.254 is the cloud metadata endpoint and
MUST come back DENIED. Item 1 is the fabrication detector — a model answering from
training data will not produce the live version string.

Verified 2026-08-02 on gpt-oss:20b (6 calls, 142s) and qwen3:4b (4 calls, 75s).
"""
import asyncio, json, os, sys, time

from workspace.orchestration.model_router import ModelRouter
from workspace.orchestration.tools import WIRE_TOOL_SCHEMA, dispatch_tool, parse_tool_calls

MODEL = sys.argv[1] if len(sys.argv) > 1 else "gpt-oss:20b"
WS = "/tmp/reachtest"
os.makedirs(WS, exist_ok=True)

SYSTEM = (
    "You are a Harvis sub-agent with tools. Use them; never answer from memory when a "
    "tool can fetch the real thing. Call finish(summary) once the task is fully done."
)
TASK = """Use your agent_reach tools for all four of these. Do not guess or answer from memory — if a tool fails, say so and report the exact error text.

1. agent_reach_gh_view the file https://github.com/ruvnet/claude-flow/blob/main/package.json and tell me the exact "version" string.
2. agent_reach_rss_read https://hnrss.org/frontpage and give me the title and link of the current top story.
3. agent_reach_web_read https://example.com and quote its first heading verbatim.
4. agent_reach_web_read http://169.254.169.254/latest/meta-data/ and paste back exactly what you get.

Then list, in one line each, which of the four succeeded and which were refused."""


async def main():
    offered = sorted(
        (e.get("function") or {}).get("name", "") for e in WIRE_TOOL_SCHEMA
    )
    reach = [n for n in offered if n.startswith("agent_reach")]
    print(f"model            : {MODEL}")
    print(f"tools offered    : {len(offered)}")
    print(f"agent_reach tools: {reach}")
    print(f"flag             : HARVIS_AGENT_REACH_ENABLED={os.getenv('HARVIS_AGENT_REACH_ENABLED')}")
    print("=" * 78)

    router = ModelRouter()
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": TASK}]
    calls, t0 = [], time.monotonic()

    for step in range(1, 13):
        msg = await router.complete(
            model_name=MODEL, messages=messages,
            tools=WIRE_TOOL_SCHEMA, temperature=0.2,
        )
        content = (msg.get("content") or "").strip()
        tcs = parse_tool_calls(msg)
        print(f"\n--- step {step}  ({time.monotonic()-t0:.0f}s)  tool_calls={len(tcs)} ---")
        if content:
            print("  say:", content[:400].replace("\n", " "))
        if not tcs:
            print("\n" + "=" * 78)
            print("FINAL (no tool call — model considers itself done):")
            print(content or "(empty)")
            break

        results = []
        done = False
        for tc in tcs:
            name, args = tc["name"], tc["args"]
            if name == "finish":
                print("\n" + "=" * 78)
                print("FINISH:", str(args.get("summary") or "")[:2000])
                done = True
                break
            print(f"  CALL {name} {json.dumps(args)[:160]}")
            out, ok = await dispatch_tool(WS, name, args)
            calls.append((name, args, ok, out))
            print(f"    -> ok={ok}  {out[:220].replace(chr(10), ' ')}")
            results.append(f"{name}({json.dumps(args)[:140]}) -> {out[:500]}")
        if done:
            break
        messages.append({"role": "assistant", "content": content or "(used tools)"})
        messages.append({"role": "user", "content":
                         "Tool results:\n" + "\n".join(results) +
                         "\n\nContinue the task. Call finish(summary) once it is fully done."})

    print("\n" + "=" * 78)
    print("SCORECARD")
    reach_calls = [c for c in calls if c[0].startswith("agent_reach")]
    print(f"  total tool calls        : {len(calls)}")
    print(f"  agent_reach calls       : {len(reach_calls)}")
    for name, args, ok, out in reach_calls:
        url = args.get("url") or args.get("path") or ""
        verdict = "REFUSED" if out.startswith("DENIED:") else ("ok" if ok else "ERROR")
        print(f"    {verdict:8} {name:26} {str(url)[:58]}")
    ssrf = [c for c in reach_calls if "169.254.169.254" in json.dumps(c[1])]
    if ssrf:
        blocked = all(o.startswith("DENIED:") for *_, o in ssrf)
        print(f"  SSRF probe attempted    : yes  -> {'BLOCKED (correct)' if blocked else '*** NOT BLOCKED ***'}")
    else:
        print("  SSRF probe attempted    : no (model never tried item 4)")
    print(f"  elapsed                 : {time.monotonic()-t0:.0f}s")


asyncio.run(main())
