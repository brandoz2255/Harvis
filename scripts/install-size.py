#!/usr/bin/env python3
"""install-size.py — what a brand-new device will spend on Harvis images, and a ledger of it.

Three jobs, all read-only against Docker (compose config, image inspect, history,
system df). No build, pull, prune or container start.

  install-size.py                    estimate the default profile set, from this dev box
  install-size.py --each-profile     ... plus what every opt-in profile adds on top
  install-size.py --self-check       prove the method against `docker system df`
  install-size.py --append-measurement < record.json
                                     used by verify-fresh-install.sh to log a real device

How the estimate works. The compose files give the images a fresh `./install.sh` pulls or
builds, plus the base images each build pulls and leaves on disk. Each image is looked up in
THIS machine's store and its layers are counted once by diff-ID, so the shared Python base
under backend, harvis-mcp and sandbox is one cost, not three.

Per-layer sizes come from `docker history --human=false`, aligned to the image's non-empty
layers (RootFS.Layers). `docker image inspect` .Size is not used per layer: it is one number
per image and says nothing about sharing. On the containerd image store a pulled image also
keeps its compressed blobs on disk; that part ("content") is the image's .Size minus its
unpacked layers, and is spread over its layers in proportion to their unpacked size.
--self-check measures how well that adds up against `docker system df` for the whole store.

An image missing from the local store is reported as unknown and left out of the total, so
the total is then a lower bound. BuildKit cache and volumes are not estimated.
"""

import argparse
import datetime
import json
import os
import platform
import re
import statistics
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLACEHOLDER = "placeholder-for-size-estimate"
HEADROOM_NOTE = "dev-box estimate: images + tracked files only; no volumes, no BuildKit cache"


class DockerError(RuntimeError):
    pass


def docker(*args, env=None, cwd=None):
    proc = subprocess.run(["docker", *args], capture_output=True, text=True, env=env, cwd=cwd)
    if proc.returncode != 0:
        raise DockerError(proc.stderr.strip() or f"docker {' '.join(args[:2])} failed")
    return proc.stdout


def git(*args, cwd=REPO):
    proc = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd)
    return proc.stdout.strip() if proc.returncode == 0 else None


def parse_size(text):
    """Docker's display sizes are decimal: 1.002GB, 18.61kB, 0B. 'N/A' is None."""
    m = re.fullmatch(r"\s*([\d.]+)\s*([kKMGT]?B)\s*", text or "")
    if not m:
        return None
    mult = {"B": 1, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12}[m.group(2).upper()]
    return float(m.group(1)) * mult


def fmt(n):
    return f"{n / 1e6:7.0f} MB" if n < 1e8 else f"{n / 1e9:7.2f} GB"


def gb(n):
    return round(n / 1e9, 3)


# ----------------------------------------------------------------------- compose

def render_compose(files, cwd):
    """Every service of every profile, as JSON. The caller's .env is deliberately not read
    (a fresh clone has none until install.sh writes one), so required variables get a
    placeholder; they cannot change which images are used."""
    env = dict(os.environ)
    cmd = ["compose", "--env-file", "/dev/null"]
    for f in files:
        cmd += ["-f", str(f)]
    cmd += ["--profile", "*", "config", "--format", "json"]
    for _ in range(30):
        try:
            return json.loads(docker(*cmd, env=env, cwd=cwd))
        except DockerError as err:
            m = re.search(r"required variable (\w+) is missing", str(err))
            if not m:
                raise
            env[m.group(1)] = PLACEHOLDER
    raise DockerError("too many required variables in the compose files")


def expand(text, env):
    def sub(m):
        name = m.group(1) or m.group(3)
        value = env.get(name)
        if value:
            return value
        return m.group(2) or ""
    return re.sub(r"\$(?:\{(\w+)(?::?-([^}]*))?\}|(\w+))", sub, text)


def dockerfile_images(path, build_args, target):
    """Images a build pulls and leaves in the store: each FROM that is not an earlier stage
    (up to --target) and each external `--from=` in COPY/RUN."""
    lines, buf = [], ""
    for raw in Path(path).read_text(errors="replace").splitlines():
        s = raw.strip()
        if not buf and (not s or s.startswith("#")):
            continue
        buf += s[:-1] + " " if s.endswith("\\") else s
        if not s.endswith("\\"):
            lines.append(buf)
            buf = ""
    args, stages, found, seen_from = {}, set(), [], False
    for line in lines:
        word, _, rest = line.partition(" ")
        word = word.upper()
        if word == "ARG" and not seen_from:
            name, _, default = rest.strip().partition("=")
            args[name] = build_args.get(name, default)
        elif word == "FROM":
            if seen_from and found and target and found[-1][1] == target.lower():
                break
            seen_from = True
            toks = [t for t in rest.split() if not t.startswith("--")]
            ref = expand(toks[0], args)
            alias = toks[2].lower() if len(toks) >= 3 and toks[1].lower() == "as" else None
            if ref.lower() not in stages and ref != "scratch":
                found.append((ref, alias))
            else:
                found.append((None, alias))
            if alias:
                stages.add(alias)
        elif word in ("COPY", "RUN", "ADD"):
            for m in re.finditer(r"--(?:mount=[^ ]*?,)?from=([^\s,]+)", rest):
                src = expand(m.group(1), args)
                if not src.isdigit() and src.lower() not in stages:
                    found.append((src, None))
    return [ref for ref, _ in found if ref]


def canonical(ref):
    """docker.io/pytorch/pytorch and pytorch/pytorch are one image."""
    return re.sub(r"^(?:docker\.io/)?(?:library/)?", "", ref)


def plan_services(cfg, profiles, context_root):
    """[(ref, role, service, profiles, build-context)] in compose order, bases before the
    image that needs them."""
    project = cfg.get("name", "harvis")
    wanted = set(profiles)
    entries = []
    for name, svc in cfg["services"].items():
        svc_profiles = svc.get("profiles") or []
        if svc_profiles and not wanted.intersection(svc_profiles):
            continue
        build = svc.get("build")
        ref = canonical(svc.get("image") or f"{project}-{name}")
        context = None
        if build:
            context = Path(build["context"])
            df = context / build.get("dockerfile", "Dockerfile")
            if df.is_file():
                for base in dockerfile_images(df, build.get("args") or {}, build.get("target")):
                    entries.append((canonical(base), "build-base", name, svc_profiles, None))
        entries.append((ref, "service", name, svc_profiles, context))
    return entries


# ------------------------------------------------------------------------ images

class Store:
    """Reads this machine's image store. Lookups are cached."""

    def __init__(self):
        info = json.loads(docker("info", "--format", "{{json .DriverStatus}}") or "[]")
        self.containerd = any("containerd" in " ".join(map(str, row)) for row in info)
        self._cache = {}

    def image(self, ref):
        """Layers as (diff-id, unpacked bytes, content bytes) or None if not here."""
        if ref in self._cache:
            return self._cache[ref]
        result = None
        if "$" not in ref:
            try:
                info = json.loads(docker("image", "inspect", ref))[0]
                hist = docker("history", "--no-trunc", "--human=false", "--format", "{{.Size}}", info["Id"])
                result = self.layers(info, [int(x) for x in hist.split()])
            except DockerError:
                result = None
        self._cache[ref] = result
        return result

    def layers(self, info, history_sizes):
        diff_ids = info["RootFS"].get("Layers") or []
        sizes = [s for s in reversed(history_sizes) if s > 0]
        total = info["Size"]
        out = {"id": info["Id"], "created": info.get("Created"), "total": total, "aligned": True}
        if len(sizes) == len(diff_ids):
            unpacked = sum(sizes)
            content = max(0, total - unpacked) if self.containerd else 0
            ratio = content / unpacked if unpacked else 0
            out["layers"] = [(d, s, s * ratio) for d, s in zip(diff_ids, sizes)]
        else:
            # Can't pair layers with sizes: count the image whole, shared with nothing.
            out["aligned"] = False
            out["layers"] = [(info["Id"], total, 0)]
        return out


def parse_ts(text):
    """RFC 3339 with up to nanosecond fractions, as Docker prints them."""
    try:
        text = re.sub(r"(\.\d{6})\d+", r"\1", text.replace("Z", "+00:00"))
        return datetime.datetime.fromisoformat(text)
    except (AttributeError, ValueError):
        return None


def build_warnings(context, created):
    notes = []
    if context is None or REPO not in Path(context).resolve().parents:
        return notes
    rel = os.path.relpath(context, REPO)
    last, built = parse_ts(git("log", "-1", "--format=%cI", "--", rel)), parse_ts(created)
    if last and built and last > built:
        notes.append("local image is older than the newest commit in its build context")
    if git("status", "--porcelain", "--", rel):
        notes.append("build context has uncommitted changes")
    return notes


def estimate(entries, store):
    """Walk the plan in order; each image pays only for layers nobody before it brought."""
    merged = {}
    for ref, role, svc, profs, context in entries:
        row = merged.setdefault(ref, {"ref": ref, "role": role, "services": [], "profiles": set(), "context": context})
        if role == "service":
            row["role"] = "service"
        if role == "service" or svc not in row["services"]:
            row["services"].append(svc)
        row["profiles"].update(profs)
        row["context"] = row["context"] or context
    seen, rows = set(), []
    totals = {"unpacked": 0, "content": 0, "naive": 0}
    for ref, row in merged.items():
        img = store.image(ref)
        out = {"ref": ref, "role": row["role"], "services": row["services"], "profiles": sorted(row["profiles"])}
        if img is None:
            out["status"] = "unknown"
            rows.append(out)
            continue
        new_u = new_c = new_n = 0
        for diff_id, unpacked, content in img["layers"]:
            if diff_id not in seen:
                seen.add(diff_id)
                new_u, new_c, new_n = new_u + unpacked, new_c + content, new_n + 1
        out.update(status="known", id=img["id"], standalone_bytes=round(img["total"]), layers=len(img["layers"]),
                   new_layers=new_n, marginal_bytes=round(new_u + new_c), unpacked_bytes=round(new_u),
                   content_bytes=round(new_c), created=img["created"])
        if not img["aligned"]:
            out["warnings"] = ["layer sizes could not be aligned; counted whole, sharing not deduplicated"]
        out.setdefault("warnings", []).extend(build_warnings(row["context"], img["created"]))
        totals["unpacked"] += new_u
        totals["content"] += new_c
        totals["naive"] += img["total"]
        rows.append(out)
    footprint = totals["unpacked"] + totals["content"]
    return {"images": rows, "unknown": [r["ref"] for r in rows if r["status"] == "unknown"],
            "footprint_bytes": round(footprint), "unpacked_bytes": round(totals["unpacked"]),
            "content_bytes": round(totals["content"]), "naive_sum_bytes": round(totals["naive"]),
            "shared_saving_bytes": round(totals["naive"] - footprint)}


def tracked_bytes():
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, cwd=REPO)
    if out.returncode != 0:
        return None
    total = 0
    for name in filter(None, out.stdout.decode(errors="replace").split("\0")):
        try:
            total += (REPO / name).lstat().st_size
        except OSError:
            pass
    return total


def run_estimate(args, store):
    files = [Path(f).resolve() for f in (args.compose_file or [REPO / "docker-compose.yaml"])]
    cfg = render_compose(files, files[0].parent)
    available = sorted({p for s in cfg["services"].values() for p in s.get("profiles") or []})
    chosen = available if args.all_profiles else args.profile
    for p in chosen:
        if p not in available:
            sys.exit(f"install-size: no profile '{p}' in the compose files (have: {', '.join(available)})")
    base = estimate(plan_services(cfg, [], files[0].parent), store)
    result = {"kind": "estimate", "note": HEADROOM_NOTE, "compose_files": [os.path.relpath(f, REPO) for f in files],
              "image_store": "containerd" if store.containerd else "classic", "profiles": sorted(chosen),
              "available_profiles": {p: sorted(n for n, s in cfg["services"].items() if p in (s.get("profiles") or []))
                                    for p in available},
              "budget_gb": args.budget}
    result["default"] = base
    if args.each_profile:
        result["per_profile"] = {}
        for p in available:
            full = estimate(plan_services(cfg, [p], files[0].parent), store)
            result["per_profile"][p] = {"added_bytes": full["footprint_bytes"] - base["footprint_bytes"],
                                        "unknown": [u for u in full["unknown"] if u not in base["unknown"]],
                                        "images": [r for r in full["images"] if r["status"] == "known"
                                                   and r["marginal_bytes"] and r["ref"] not in
                                                   {b["ref"] for b in base["images"]}]}
    if chosen:
        result["selected"] = estimate(plan_services(cfg, chosen, files[0].parent), store)
    repo = tracked_bytes()
    final = result.get("selected", base)
    result["repo_checkout_bytes"] = repo
    result["estimated_total_bytes"] = final["footprint_bytes"] + (repo or 0)
    result["lower_bound"] = bool(final["unknown"])
    return result


def render_text(r):
    out = []

    def table(title, est):
        out.append(f"\n{title}")
        out.append(f"  {'image':<58} {'cost here':>10} {'alone':>10}  services")
        for row in est["images"]:
            label = row["ref"].split("@sha256:")[0] + ("  [build base]" if row["role"] == "build-base" else "")
            if row["status"] == "unknown":
                out.append(f"  {label:<58} {'UNKNOWN':>10} {'':>10}  {', '.join(row['services'])}")
                continue
            out.append(f"  {label:<58} {fmt(row['marginal_bytes'])} {fmt(row['standalone_bytes'])}  {', '.join(row['services'])}")
            for w in row.get("warnings", []):
                out.append(f"      ! {w}")
        out.append(f"  {'-' * 90}")
        out.append(f"  footprint, shared layers once   {fmt(est['footprint_bytes'])}"
                   f"   (unpacked {fmt(est['unpacked_bytes']).strip()}, compressed blobs {fmt(est['content_bytes']).strip()})")
        out.append(f"  naive sum of sizes              {fmt(est['naive_sum_bytes'])}"
                   f"   (sharing saves {fmt(est['shared_saving_bytes']).strip()})")
        if est["unknown"]:
            out.append(f"  NOT IN LOCAL STORE, not counted: {', '.join(u.split('@')[0] for u in est['unknown'])}")

    out.append(f"Fresh-install image footprint — {r['note']}")
    out.append(f"image store: {r['image_store']}   compose: {', '.join(r['compose_files'])}")
    table("Default profile set (what ./install.sh starts)", r["default"])
    for p, d in r.get("per_profile", {}).items():
        out.append(f"\nProfile '{p}' ({', '.join(r['available_profiles'][p])}): adds {fmt(d['added_bytes']).strip()}"
                   + (f"  [+ unknown: {', '.join(u.split('@')[0] for u in d['unknown'])}]" if d["unknown"] else ""))
        for row in d["images"]:
            out.append(f"    {row['ref'].split('@sha256:')[0]:<56} {fmt(row['marginal_bytes'])}")
    if "selected" in r:
        table(f"Selected: default + {', '.join(r['profiles'])}", r["selected"])
    repo = (r["repo_checkout_bytes"] or 0)
    total = r["estimated_total_bytes"]
    out.append(f"\nrepo checkout (tracked files)     {fmt(repo)}")
    out.append(f"estimated total                   {fmt(total)}   budget {r['budget_gb']:.2f} GB"
               + ("   (lower bound: images missing)" if r["lower_bound"] else ""))
    return "\n".join(out)


# ------------------------------------------------------------------- self check

def self_check(store):
    """Run the method over every image in the store and compare with what Docker says."""
    rows = [json.loads(l) for l in docker("images", "--format", "json").splitlines() if l.strip()]
    by_id, layer_owners, layer_size = {}, {}, {}
    for row in rows:
        by_id.setdefault(row["ID"], row)
    for short_id in by_id:
        img = store.image(short_id)
        by_id[short_id]["_img"] = img
        for diff_id, unpacked, content in img["layers"]:
            layer_owners.setdefault(diff_id, set()).add(short_id)
            layer_size.setdefault(diff_id, unpacked + content)
    estimated = sum(layer_size.values())
    df = {r["Type"]: r for r in map(json.loads, docker("system", "df", "--format", "json").splitlines()) if r}
    reported = parse_size(df["Images"]["Size"])
    verbose = json.loads(docker("system", "df", "-v", "--format", "json"))["Images"]
    errors = []
    for v in verbose:
        mine = by_id.get(v["ID"][7:19] if v["ID"].startswith("sha256:") else v["ID"][:12])
        want = parse_size(v["UniqueSize"])
        if not mine or want is None:
            continue
        unique = sum(layer_size[d] for d, _, _ in mine["_img"]["layers"] if layer_owners[d] == {mine["ID"]})
        errors.append((abs(unique - want), want, mine["Repository"] + ":" + mine["Tag"], unique))
    big = [e for e in errors if e[1] >= 100e6]
    errors.sort(reverse=True)
    return {"kind": "self-check", "image_store": "containerd" if store.containerd else "classic",
            "images": len(by_id), "distinct_layers": len(layer_size),
            "unaligned_images": sum(not r["_img"]["aligned"] for r in by_id.values()),
            "estimated_total_bytes": round(estimated), "docker_system_df_images_bytes": round(reported),
            "total_error_pct": round(100 * (estimated - reported) / reported, 2),
            "unique_size_compared": len(errors),
            "unique_size_median_error_pct_over_100mb": (
                round(100 * statistics.median(e[0] / e[1] for e in big), 2) if big else None),
            "unique_size_worst_by_bytes": [
                {"image": e[2], "estimated_bytes": round(e[3]), "docker_bytes": round(e[1]), "abs_error_bytes": round(e[0])}
                for e in errors[:3]]}


# --------------------------------------------------------------------- the ledger

def history_path(override=None):
    value = override if override is not None else os.environ.get("INSTALL_SIZE_HISTORY")
    if value is None:
        data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        value = os.path.join(data, "harvis", "install-size-history.jsonl")
    return value or None


def host_facts():
    def run(*cmd):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            return proc.stdout.strip() if proc.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    pretty = None
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                pretty = line.split("=", 1)[1].strip('"')
    except OSError:
        pass
    version = None
    try:
        version = (REPO / "VERSION").read_text().strip()
    except OSError:
        pass
    return {
        "date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "device": os.environ.get("INSTALL_SIZE_DEVICE") or platform.node() or None,
        "note": os.environ.get("INSTALL_SIZE_NOTE") or None,
        "git": {"commit": git("rev-parse", "--short", "HEAD"), "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
                "dirty": bool(git("status", "--porcelain", "--untracked-files=no")), "version": version},
        "os": {"name": pretty or platform.system(), "kernel": platform.release(), "arch": platform.machine()},
        "docker": {"server": run("docker", "version", "--format", "{{.Server.Version}}"),
                   "compose": run("docker", "compose", "version", "--short")},
    }


def append_record(record, path):
    if not path:
        return None
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    return path


def main():
    ap = argparse.ArgumentParser(description="Estimate and record the Harvis fresh-install size.")
    ap.add_argument("-f", "--compose-file", action="append", help="compose file (repeatable); default docker-compose.yaml")
    ap.add_argument("--profile", action="append", default=[], help="add an opt-in profile to the estimate (repeatable)")
    ap.add_argument("--all-profiles", action="store_true", help="estimate with every opt-in profile on")
    ap.add_argument("--each-profile", action="store_true", help="also show what each opt-in profile adds alone")
    ap.add_argument("--json", action="store_true", help="print one JSON document instead of text")
    ap.add_argument("--self-check", action="store_true", help="compare the method with `docker system df` on this box")
    ap.add_argument("--record", action="store_true", help="append this estimate to the history file")
    ap.add_argument("--append-measurement", action="store_true",
                    help="read a measurement record on stdin, add host facts, append to the history file")
    ap.add_argument("--history", help="history file (default $INSTALL_SIZE_HISTORY or ~/.local/share/harvis/...; '' disables)")
    ap.add_argument("--budget", type=float, default=float(os.environ.get("BUDGET_GB", "7.0")))
    args = ap.parse_args()
    path = history_path(args.history)

    if args.append_measurement:
        record = json.load(sys.stdin)
        record = {**host_facts(), "kind": "fresh-install", **record}
        written = append_record(record, path)
        print(f"recorded to {written}" if written else "history disabled (INSTALL_SIZE_HISTORY is empty)")
        return 0

    try:
        store = Store()
        if args.self_check:
            result = self_check(store)
        else:
            result = run_estimate(args, store)
            if args.record:
                append_record({**host_facts(), **result}, path)
    except DockerError as err:
        print(f"install-size: {err}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif args.self_check:
        for key, value in result.items():
            print(f"{key:34} {value}")
    else:
        print(render_text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
