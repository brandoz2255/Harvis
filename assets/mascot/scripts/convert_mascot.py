#!/usr/bin/env python3
"""Harvis mascot pipeline: green-screen MP4 → transparent WebM + APNG.

    python3 assets/mascot/scripts/convert_mascot.py            # convert all
    python3 assets/mascot/scripts/convert_mascot.py idle-floating   # just one

Why not `ffmpeg -vf colorkey`
-----------------------------
colorkey thresholds on RGB distance and produces a hard 1-bit-ish cut. On
*compressed* pixel art that leaves a visible green rim, because 4:2:0 chroma
subsampling smears the green into the character's edge pixels before we ever see
them. AI background removers fail differently — they guess a soft matte and eat
the hard pixel edges that make pixel art read as pixel art.

So this does it explicitly:
  * key in HSV, not RGB, so "greenish but darker/lighter" still counts
  * dilate the background mask ~2px to bite through the compression fringe
  * keep the interior fully opaque, and allow only a controlled 1-2px alpha ramp
    at the exterior edge
  * then AUDIT every frame and fail loudly if green survived

The audit is the point. A silent halo is exactly the kind of defect that ships
and then shows up on every screen in the product.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]          # assets/mascot
SOURCE = ROOT / "source"
FRAMES = ROOT / "frames"
OUT = ROOT / "transparent"

# Where the app serves clips from. Kept in sync so there is one build step, not two.
WEB_STATIC = ROOT.parents[1] / "front_end" / "owui" / "static" / "mascot"

FPS = 12          # matches the "12fps stepped animation" in the generation prompts
SMALL_PX = 160    # the small APNG the guide asks for

# ─── keying parameters ───────────────────────────────────────────────────────
# Tuned for #04FA03 chroma green. Widened deliberately: over-keying green costs
# nothing (there is no green in the character), under-keying leaves a halo.
HUE_CENTER = 120.0     # degrees; pure green
HUE_TOLERANCE = 55.0   # accept a wide band — compression drags hue around
MIN_SAT = 0.25         # ignore near-grey pixels that merely lean green
MIN_VAL = 0.15         # ignore near-black pixels
DILATE_PX = 2          # eat the compression fringe
EDGE_FEATHER_PX = 1    # controlled alpha ramp, keeps pixel edges crisp

# ─── audit thresholds ────────────────────────────────────────────────────────
# A pixel that is still visibly green AND still meaningfully opaque = failure.
AUDIT_MIN_ALPHA = 24          # /255 — below this it cannot be seen
AUDIT_GREEN_DOMINANCE = 18    # G exceeds both R and B by this much
AUDIT_MAX_BAD_PIXELS = 0      # zero tolerance


def ffmpeg_cmd() -> list[str]:
    """Find ffmpeg. Falls back to the backend container, which already has
    libvpx-vp9 + apng, so a fresh clone can run this without installing anything."""
    override = os.environ.get("FFMPEG")
    if override:
        return override.split()
    if shutil.which("ffmpeg"):
        return ["ffmpeg"]
    if shutil.which("docker"):
        probe = subprocess.run(
            ["docker", "exec", "harvis-backend", "ffmpeg", "-version"],
            capture_output=True,
        )
        if probe.returncode == 0:
            print("  (using ffmpeg inside harvis-backend — set $FFMPEG to override)")
            return ["__CONTAINER__"]
    sys.exit(
        "ffmpeg not found.\n"
        "  macOS:  brew install ffmpeg\n"
        "  Ubuntu: sudo apt install ffmpeg\n"
        "  or set FFMPEG=/path/to/ffmpeg"
    )


FFMPEG = ffmpeg_cmd()
IN_CONTAINER = FFMPEG == ["__CONTAINER__"]


def _sh(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, **kw)


def ff(args: list[str], workdir: Path) -> None:
    """Execute an ffmpeg invocation whose paths are relative to `workdir`."""
    if not IN_CONTAINER:
        _sh(FFMPEG + args, cwd=workdir)
        return
    # Container path: copy inputs in, run, copy outputs back. Slower but means a
    # clean machine with only Docker can still build the assets.
    cid = "harvis-backend"
    remote = "/tmp/mascot_build"
    _sh(["docker", "exec", cid, "rm", "-rf", remote])
    _sh(["docker", "exec", cid, "mkdir", "-p", remote])
    _sh(["docker", "cp", f"{workdir}/.", f"{cid}:{remote}"])
    _sh(["docker", "exec", "-w", remote, cid, "ffmpeg"] + args)
    tmp = workdir / ".__pull"
    if tmp.exists():
        shutil.rmtree(tmp)
    _sh(["docker", "cp", f"{cid}:{remote}/.", str(tmp)])
    for item in tmp.iterdir():
        dest = workdir / item.name
        if dest.exists() and dest.is_dir():
            shutil.rmtree(dest)
        elif dest.exists():
            dest.unlink()
        shutil.move(str(item), str(dest))
    shutil.rmtree(tmp)


def key_green(rgb: np.ndarray) -> np.ndarray:
    """RGB uint8 (H,W,3) → alpha uint8 (H,W). Background becomes 0."""
    arr = rgb.astype(np.float32) / 255.0
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]

    mx = arr.max(axis=-1)
    mn = arr.min(axis=-1)
    chroma = mx - mn

    # HSV hue, in degrees, computed directly (cheaper than a colorsys round-trip)
    hue = np.zeros_like(mx)
    safe = chroma > 1e-6
    with np.errstate(invalid="ignore", divide="ignore"):
        rmask = safe & (mx == r)
        gmask = safe & (mx == g) & ~rmask
        bmask = safe & (mx == b) & ~rmask & ~gmask
        hue[rmask] = (60 * ((g - b) / chroma))[rmask] % 360
        hue[gmask] = (60 * (2 + (b - r) / chroma))[gmask]
        hue[bmask] = (60 * (4 + (r - g) / chroma))[bmask]

    sat = np.where(mx > 1e-6, chroma / np.maximum(mx, 1e-6), 0.0)

    hue_dist = np.abs(((hue - HUE_CENTER + 180) % 360) - 180)
    is_bg = (hue_dist <= HUE_TOLERANCE) & (sat >= MIN_SAT) & (mx >= MIN_VAL)

    # Also catch flatly green-dominant pixels the hue test may miss at extremes.
    is_bg |= (g > r + 0.08) & (g > b + 0.08) & (sat >= MIN_SAT)

    # Dilate the BACKGROUND mask — this is what removes the compression fringe.
    if DILATE_PX > 0:
        is_bg = ndimage.binary_dilation(is_bg, iterations=DILATE_PX)

    alpha = np.where(is_bg, 0.0, 1.0).astype(np.float32)

    # Controlled edge ramp: soften ONLY the outermost pixel so the silhouette
    # stays hard. A wide feather would smudge the pixel-art edge into mush.
    if EDGE_FEATHER_PX > 0:
        interior = ndimage.binary_erosion(alpha > 0.5, iterations=EDGE_FEATHER_PX)
        blurred = ndimage.uniform_filter(alpha, size=2 * EDGE_FEATHER_PX + 1)
        alpha = np.where(interior, 1.0, np.minimum(alpha, blurred))

    return (alpha * 255).astype(np.uint8)


def audit_frame(rgba: np.ndarray) -> int:
    """Count pixels that are still visibly green AND still visible. 0 = clean."""
    r = rgba[..., 0].astype(np.int16)
    g = rgba[..., 1].astype(np.int16)
    b = rgba[..., 2].astype(np.int16)
    a = rgba[..., 3]
    green_left = (g - r >= AUDIT_GREEN_DOMINANCE) & (g - b >= AUDIT_GREEN_DOMINANCE)
    return int(np.count_nonzero(green_left & (a >= AUDIT_MIN_ALPHA)))


def convert(mp4: Path) -> bool:
    name = mp4.stem
    out_name = f"harvis-{name.split('-')[0]}"   # idle-floating → harvis-idle
    work = FRAMES / name
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    print(f"\n▸ {mp4.name}")

    # 1. extract every frame
    shutil.copy(mp4, work / mp4.name)
    ff(["-y", "-loglevel", "error", "-i", mp4.name, "-vsync", "0", "f_%04d.png"], work)
    frames = sorted(work.glob("f_*.png"))
    if not frames:
        print("  ✗ no frames extracted")
        return False
    print(f"  {len(frames)} frames")

    # 2-5. key + dilate + feather, per frame
    bad_frames: list[tuple[str, int]] = []
    for fp in frames:
        img = Image.open(fp).convert("RGB")
        rgb = np.array(img)
        alpha = key_green(rgb)
        rgba = np.dstack([rgb, alpha])
        # zero the colour of fully-transparent pixels so no green survives in the
        # RGB planes to bleed back during scaling/encoding
        rgba[alpha == 0, :3] = 0
        # 6. audit
        bad = audit_frame(rgba)
        if bad > AUDIT_MAX_BAD_PIXELS:
            bad_frames.append((fp.name, bad))
        Image.fromarray(rgba, "RGBA").save(fp)

    # 7. fail loudly rather than shipping a halo
    if bad_frames:
        print(f"  ✗ AUDIT FAILED — green fringe survived on {len(bad_frames)} frame(s):")
        for fname, count in bad_frames[:8]:
            print(f"      {fname}: {count} px")
        if len(bad_frames) > 8:
            print(f"      … and {len(bad_frames) - 8} more")
        print("    Widen HUE_TOLERANCE or raise DILATE_PX, then re-run.")
        return False
    print("  ✓ audit clean — no green fringe on any frame")

    # 8. export
    OUT.mkdir(parents=True, exist_ok=True)
    ff([
        "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", "f_%04d.png",
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "28",
        "-auto-alt-ref", "0", f"{out_name}.webm",
    ], work)
    ff([
        "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", "f_%04d.png",
        "-f", "apng", "-plays", "0", f"{out_name}.png",
    ], work)
    ff([
        "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", "f_%04d.png",
        "-vf", f"scale={SMALL_PX}:-1:flags=neighbor",   # neighbor = keep pixels crisp
        "-f", "apng", "-plays", "0", f"{out_name}-{SMALL_PX}.png",
    ], work)

    for produced in (f"{out_name}.webm", f"{out_name}.png", f"{out_name}-{SMALL_PX}.png"):
        src = work / produced
        if not src.exists():
            print(f"  ✗ expected output missing: {produced}")
            return False
        shutil.copy(src, OUT / produced)

    WEB_STATIC.mkdir(parents=True, exist_ok=True)
    shutil.copy(OUT / f"{out_name}.webm", WEB_STATIC / f"{out_name}.webm")

    size_kb = (OUT / f"{out_name}.webm").stat().st_size / 1024
    print(f"  → {out_name}.webm ({size_kb:.0f} KB)  + APNG full + APNG {SMALL_PX}px")
    print(f"  → served from front_end/owui/static/mascot/{out_name}.webm")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("names", nargs="*", help="clip stems to convert (default: all)")
    ap.add_argument("--keep-frames", action="store_true", help="keep the PNG frames")
    args = ap.parse_args()

    SOURCE.mkdir(parents=True, exist_ok=True)
    mp4s = sorted(SOURCE.glob("*.mp4"))
    if args.names:
        mp4s = [m for m in mp4s if m.stem in args.names]
    if not mp4s:
        print(f"No MP4s in {SOURCE}.")
        print("Drop the Higgsfield clips there, e.g. idle-floating.mp4")
        return 1

    ok = all([convert(m) for m in mp4s])

    if not args.keep_frames:
        for m in mp4s:
            d = FRAMES / m.stem
            if d.exists():
                shutil.rmtree(d)

    print("\n" + ("✓ all clips converted" if ok else "✗ one or more clips FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
