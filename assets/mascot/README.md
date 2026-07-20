# Harvis mascot pipeline

Green-screen MP4 → transparent WebM + APNG → animated mascot in the app.

**One command:**

```bash
python3 assets/mascot/scripts/convert_mascot.py                # all clips in source/
python3 assets/mascot/scripts/convert_mascot.py idle-floating  # just one
```

---

## Requirements

`numpy`, `scipy`, `pillow`, and `ffmpeg` with **libvpx-vp9** and **apng**.

```bash
# macOS
brew install ffmpeg python && pip3 install numpy scipy pillow
# Ubuntu
sudo apt install ffmpeg && pip3 install numpy scipy pillow
```

If `ffmpeg` isn't on the host, the script automatically uses the one inside the
running `harvis-backend` container (it has 4.4.2 with both codecs), so a machine
with only Docker can still build the assets. Override with `FFMPEG=/path/to/ffmpeg`.

---

## Layout

```
assets/mascot/
├── source/        harvis-master.png + the Higgsfield MP4s   ← you put files here
├── transparent/   harvis-*.webm, harvis-*.png, harvis-*-160.png   ← output
├── frames/        scratch (auto-deleted; --keep-frames to inspect)
├── scripts/       convert_mascot.py
└── prompts/       master-image.txt, animations.txt          ← keep these
```

The script also copies each `.webm` to `front_end/owui/static/mascot/`, which is
where the app serves them from. One build step, not two.

**Keep `prompts/` in git.** Generation histories disappear; those prompts are what
reproduce the character. Every animation uses `source/harvis-master.png` as its
`start_image` — that, not the prompt text, is what keeps the character consistent.

---

## Workflow

1. **Master still** — Higgsfield `nano_banana_pro`, 1:1, 4 images, prompt in
   `prompts/master-image.txt`. Pick one, save as `source/harvis-master.png`.
   *Check it still reads at 64–96px before going further.*
2. **Animate** — Higgsfield `kling3_0`, `std` mode first (cheap), 1:1, 4s, using the
   master as **both** `start_image` and `end_image`. Prompts in `prompts/animations.txt`.
   Only regenerate the winner in `pro`.
3. **Convert** — drop the MP4s in `source/`, run the script.
4. **Use** — `HarvisAnimatedMascot.svelte` picks clips up by state automatically.

Proof-of-concept order is `idle-floating`, then `working`, then `success-wave`.
Don't generate the full pack until idle is approved and working in the app.

---

## How the keying works, and why not `colorkey`

`ffmpeg -vf colorkey` thresholds on RGB distance and cuts hard. On *compressed*
pixel art that leaves a green rim, because 4:2:0 chroma subsampling smears green
into the character's edge pixels before we ever see them. AI background removers
fail the other way — they guess a soft matte and eat the hard pixel edges that make
pixel art read as pixel art.

So the script does it explicitly:

1. Extract every frame as PNG.
2. Key in **HSV**, not RGB, so "greenish but darker/lighter" still counts
   (hue within ±55° of green, saturation ≥ 0.25, value ≥ 0.15), plus a
   green-dominance test for the extremes.
3. **Dilate the background mask 2px** — this is what removes the compression fringe.
4. Keep the interior fully opaque; allow only a **1px** alpha ramp at the exterior
   so the silhouette stays hard.
5. Zero the RGB of fully-transparent pixels so no green can bleed back during
   scaling or encoding.
6. **Audit every frame** for pixels that are still green *and* still visible.
7. **Fail the whole conversion** and name the offending frames if any survive.

That last step is the point. A silent halo is exactly the kind of defect that ships
and then appears on every screen in the product. If the audit fails, widen
`HUE_TOLERANCE` or raise `DILATE_PX` and re-run.

### Verified

The pipeline was proven against a synthetic compressed green-screen clip before any
real assets existed:

- audit reports **0** bad pixels on a clean frame and **catches** a deliberately
  crippled one (52 px) — so "audit clean" means something
- output WebM carries **real alpha**: container `alpha_mode=1`, and decoding back
  yields 59,442 fully-transparent pixels of 65,536

Note `ffprobe` reports `pix_fmt=yuv420p` for a transparent VP9 WebM. That is normal —
VP9 stores alpha as a separate layer flagged by `alpha_mode=1`, not in the pix_fmt.
Don't let that reading convince you the alpha was lost.

---

## Formats

| Format | Use |
|---|---|
| **WebM** (VP9 + alpha) | primary — what the app plays |
| **APNG** full + 160px | fallback, docs, mockups |
| GIF | avoid — 1-bit transparency gives rough edges on pixel art |

---

## The component

`front_end/owui/src/lib/components/mascot/HarvisAnimatedMascot.svelte`

```svelte
<HarvisAnimatedMascot state="working" size={96} />
```

It handles: `prefers-reduced-motion` (holds frame 0 — the mascot stays *present* and
readable, it just stops moving), pausing on a hidden tab, restarting on state change,
playing `success`/`error`/`cancelled` **once** then settling to `idle`, prefetching
`idle` + `working`, and falling back to `idle` when a clip 404s — so a partial pack
still animates instead of showing a broken element.

`success`/`error`/`cancelled` being one-shot is enforced **in the player**, not left
to call sites: a mascot waving over a finished run implies live activity, and that
exact bug already shipped once with the SVG mascots.

---

## States

| State | Loops | Animation |
|---|---|---|
| `idle` | yes | gentle float + occasional blink |
| `thinking` | yes | eyes scan / processing pulse |
| `working` | yes | hands or interface motion |
| `needs_approval` | yes | looks toward user, raises one hand |
| `success` | **no** | one brief confident wave |
| `error` | **no** | small glitch → stable concerned pose |
| `cancelled` | **no** | activity stops, settles |
| `sleeping` | yes | eyes close, slow idle |
