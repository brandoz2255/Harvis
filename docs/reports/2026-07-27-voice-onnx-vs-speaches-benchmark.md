# Voice: ONNX sidecar vs Speaches — measured comparison

**Date:** 2026-07-27 · **Box:** dev laptop, CPU only (no GPU used by either service)
**Question:** can `voice-onnx` replace the Speaches/CTranslate2 STT sidecar in the default
install, so the recommended Voice-First preset carries no PyTorch and no CUDA?

**Answer: yes on speed, size and memory. Not yet proven on accuracy** — see the caveat in
§2, which is the reason `stt` stays available behind the `voice-fallback` profile for now.

---

## 1. What was compared

Both services expose the same OpenAI-shaped `/v1/audio/transcriptions`, so the backend's
`sidecar` provider talks to either one unchanged.

| | `voice-onnx` | `stt` (Speaches) |
|---|---|---|
| runtime | sherpa-onnx (ONNX Runtime) | faster-whisper (CTranslate2) |
| PyTorch in image | no | no |
| CUDA in image | no | no |
| does | STT + VAD + Kokoro TTS | STT only |

Neither carries torch, so the torch-free claim was never the differentiator — capability
and cost are. `voice-onnx` also serves TTS and VAD, which is what lets one ~1 GB service
replace a stack that otherwise needs a second sidecar for speech out.

### Method

Twelve sentences were synthesized **once** by `voice-onnx` Kokoro, then the byte-identical
WAVs were fed to all five recognizer configurations. Only the recognizer varies. Every
config got an untimed warm-up call first so model-load time is excluded from the numbers.
Script: `scripts/voice_bench.py`, run inside `harvis-backend` (the only container that
can reach both sidecars).

---

## 2. Transcription quality — and why this column does not decide anything yet

```
engine / model                    WER%
ONNX      whisper-tiny.en          4.6
ONNX      whisper-base.en          4.6
CTranslate2 tiny.en                4.6
CTranslate2 base.en                4.6
CTranslate2 small.en               4.6
```

Five configurations spanning three model sizes and two runtimes returned **identical** word
error rates. That is not a tie — it is a measurement that failed to discriminate, and it
would be dishonest to report it as "ONNX matches CTranslate2 on accuracy".

Inspecting the hypotheses shows why. Every engine makes the same two errors:

| reference | every engine heard |
|---|---|
| "**Harvis** runs entirely on this machine" | "**Harvest** runs entirely on this machine" |
| "at **nine thirty** in the morning" | "at **9.30** in the morning" (ONNX tiny: "930") |
| "up to **one point five** and read that again" | "up to **1.5** and read that again" |

Those are an out-of-vocabulary product name and Whisper's number normalization — properties
of the *reference text*, not of the recognizer. Kokoro speech is also far cleaner than a
real microphone: no room noise, no clipping, no accent, no crosstalk. The clips simply
aren't hard enough to separate a 75 MB model from a 464 MB one.

**What this means:** item 12's quality question is open. Closing it needs real recorded
audio — a phone mic, background noise, a non-American accent — with a reference transcript
that avoids product names and spoken numerals, or a scorer that normalizes them. Until
that exists, ONNX is unproven-equal, not proven-equal, and Speaches stays reachable.

## 3. CPU latency — measured, and this one is decisive

Identical audio, 39.2 s across 12 clips, warm models, CPU only.

| engine / model | RTF | wall for 39.2 s audio | median clip |
|---|---|---|---|
| **ONNX whisper-tiny.en** | **0.066** | 2.58 s | 0.21 s |
| **ONNX whisper-base.en** | **0.100** | 3.90 s | 0.33 s |
| CTranslate2 tiny.en | 0.142 | 5.54 s | 0.46 s |
| CTranslate2 base.en | 0.204 | 7.99 s | 0.65 s |
| CTranslate2 small.en | 0.525 | 20.54 s | 1.67 s |

ONNX `tiny.en` is **2.2× faster** than CTranslate2 `tiny.en`. More usefully: ONNX **base**.en
(0.100) beats CTranslate2 **tiny**.en (0.142), so the ONNX path can afford a larger model
and still be quicker than the fallback's smallest one.

Median clip latency matters more than RTF for a voice UI — 0.21 s versus 0.46 s is the
difference between "it answered" and "it thought about it".

A second run on the same box moved every figure by a few percent and changed no ordering
(ONNX tiny 0.065, ONNX base 0.104, CT2 tiny 0.138, CT2 base 0.207, CT2 small 0.554 —
a 2.1× lead instead of 2.2×). Treat the third digit as noise; the ranking is stable.

## 4. Synthesis latency

`voice-onnx` Kokoro, same 12 sentences: **RTF 0.320**, 12.52 s wall for 39.2 s of audio,
**median 1.05 s per sentence**. Faster than real time on CPU with no GPU involved, so a
spoken reply starts playing before the sentence finishes generating. Speaches has no TTS,
so there is nothing to compare against here.

## 5. Image size and model storage

| | image | models on disk | total |
|---|---|---|---|
| `voice-onnx` (STT + VAD + TTS) | 1.04 GB | 744 MB | **1.78 GB** |
| `stt` Speaches (STT only) | 3.04 GB | 1.3 GB | **4.34 GB** |

`voice-onnx` model volume, itemized — nothing ships inside the image, everything lands in
the `harvis_voice-models` volume on first use:

```
383.5 MB  tts/kokoro-multi-lang-v1_0     53 voices
244.7 MB  asr/sherpa-onnx-whisper-tiny.en
115.6 MB  browser/                        Kokoro mirror for in-tab playback
  0.6 MB  vad/silero_vad.onnx
────────
744.4 MB  default install
+432.1 MB  asr/…-base.en — pulled by this benchmark only, not by default
```

Speaches' `harvis_stt-cache` holds 1.3 GB for the three models this benchmark pulled
(tiny.en 74.5 MB, base.en 141 MB, small.en 464 MB, plus a 672 MB `xet` download cache).

The 115.6 MB browser mirror is worth calling out: it is what makes in-tab Kokoro playback
work without reaching `huggingface.co`, and it is served by `voice-onnx` — so it disappears
along with the service if voice is not installed.

## 6. RAM

`docker stats` RSS, measured after a container restart so nothing is carried over.

| state | `voice-onnx` | `stt` (Speaches) |
|---|---|---|
| booted, nothing loaded | 42.5 MB | 143.4 MB |
| after one transcription (tiny.en) | 259.3 MB | 337.5 MB |
| after transcription + one Kokoro synthesis | 750.6 MB | — (no TTS) |
| every model warm | 1.29 GB | 1.91 GB |

Comparing like with like — one `tiny.en` transcription and nothing else — ONNX holds
**259 MB against 338 MB**, about 23 % less. `voice-onnx` runs under a hard 2 GB compose
limit; the "every model warm" row is it holding tiny.en + base.en + Kokoro + VAD at once,
which a normal install never does.

Idle cost is the more interesting number for a laptop: a voice service nobody has spoken to
yet costs 42.5 MB rather than 143 MB.

---

## 7. Verdict

| criterion | result |
|---|---|
| no PyTorch, no CUDA | both pass — not a differentiator |
| CPU latency | **ONNX wins, 2.2× on like models** |
| synthesis latency | ONNX only (RTF 0.320); Speaches has no TTS |
| image + model storage | **ONNX wins, 1.78 GB vs 4.34 GB** |
| RAM | **ONNX wins, 259 MB vs 338 MB warm; 42 MB vs 143 MB idle** |
| transcription quality | **not established** — the clip set doesn't discriminate |

`voice-onnx` is the default in the recommended preset (`COMPOSE_PROFILES=voice`), which is
justified on cost and speed. Speaches stays available behind `COMPOSE_PROFILES=voice-fallback`
until quality is measured on audio that can actually tell the two apart — that is item 14 of
the Voice-First batch, and it stays open on purpose.

## 8. Reproducing this

```bash
docker compose --profile voice --profile voice-fallback up -d
docker exec -i harvis-backend python - < scripts/voice_bench.py
```

The script synthesizes its own clips, so it needs no fixture audio. Adding real recordings
is the next step, not a rerun of this one.
