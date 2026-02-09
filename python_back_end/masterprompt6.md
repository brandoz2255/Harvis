You are Antigravity, the senior audio systems engineer for our AIDEV project.

GOAL
Fix choppy/steppy RVC voice conversion in our podcast generation pipeline and add an automatic per-voice “RVC AutoTune” calibration that selects stable inference settings once and caches them. Prioritize audio smoothness and podcast-grade consistency over maximum similarity.

CONTEXT (Current pipeline)
- Orchestration: python_back_end/open_notebook/podcast/generator.py (PodcastGenerator)
- Script generation: ScriptGenerator uses Ollama
- Audio synthesis: python_back_end/open_notebook/podcast/audio.py sends requests to a separate TTS Service container
- TTS Service: python_back_end/tts_system
  - VibeVoice generates base speech
  - RVC (optional) converts base speech to character voices
  - Stitching combines segments with pauses
- Final .wav saved to /app/podcast_data/audio (mapped to host)

PRIMARY PROBLEM
RVC output sounds choppy even with high-epoch models. Voice identity changes are audible, so RVC is applying, but boundaries and audio format handling likely cause artifacts. We suspect:
1) Segment-by-segment conversion causing boundary artifacts and micro-cuts
2) Sample-rate / resampling mismatches repeated across segments
3) Pitch (F0) jitter or unstable settings (index/protect/rms_mix)

REQUIREMENTS
1) Enforce one internal audio working format end-to-end inside tts-service:
   - SR_WORK = 48000 Hz (or 44100 if required by existing RVC code, but choose one and enforce it)
   - mono
   - float32 internal representation
   - normalize peak to about -3 dBFS before RVC
   - only resample once at final export if needed

2) Fix boundary artifacts (must implement at least one):
   A) Preferred: Block conversion
      - Group consecutive segments by speaker into conversion blocks of ~10–25 seconds.
      - Build block base audio by concatenating base TTS segments with intended pauses.
      - Run ONE RVC conversion per block.
      - Slice the converted block back into per-segment audio using known segment durations.
      - Stitch final episode from these sliced segments.
   B) Fallback if block conversion is risky: Overlap + crossfade
      - For each segment i>0, prepend last 250–400ms of segment i-1 before conversion.
      - After conversion, discard the prepended portion.
      - When stitching, apply 80–120ms crossfade at boundaries to hide seams.

3) Add “RVC AutoTune” (run once per voice, cache result):
   - Run calibration only when a given (voice_id, base_tts_voice, SR_WORK) has no cached preset.
   - Generate a fixed 10–12s test phrase containing consonants and vowels (plosives/fricatives + numbers).
   - Evaluate a small grid of inference settings and choose best based on artifact scoring.
   - Store chosen preset in a cache (JSON file in a persistent folder is acceptable initially; DB optional).
   - Use the preset for all segments/blocks during episode generation.

4) Default stable preset for podcasts (used when auto_tune disabled or fails):
   - f0_method: rmvpe
   - index_rate: 0.15
   - protect: 0.40
   - median_filter_radius: 3
   - rms_mix: 0.10

5) AutoTune search grid (keep small & fast):
   - f0_method: ["rmvpe", "fcpe"]  (optionally add harvest if needed)
   - index_rate: [0.0, 0.15, 0.3]
   - protect: [0.2, 0.4, 0.5]
   - rms_mix: [0.0, 0.1]
   (Total 36 combos; if too slow, reduce to ~12–18 combos.)

6) Implement a lightweight “artifact scorer” (no ML):
   - Penalize clipping
   - Penalize high-frequency spikes (click/pop proxy, e.g. band-energy 6–12k bursts)
   - Penalize sudden frame-to-frame RMS jumps (“loudness jerk”)
   - Penalize unexpected silence gaps
   - Prefer outputs within a target loudness range
   - Return numeric score where lower is better

7) Add minimal post-processing after RVC for podcast consistency:
   - high-pass 70–90 Hz
   - gentle compressor (optional)
   - limiter to -1 dBFS
   - keep subtle; do not degrade clarity

8) API/Config exposure:
   - Extend the tts-service request schema to accept:
     - use_rvc (bool)
     - rvc_auto_tune (bool)
     - rvc_preset (optional override)
   - Ensure backend calls remain relative via Nginx (do not introduce browser→backend direct calls).
   - Keep existing endpoints compatible (backward compatible defaults).

9) Logging & Observability:
   - Log which preset is used per voice_id
   - Log whether the preset came from cache or was tuned
   - Log SR_WORK and segment/block sizes
   - Add debug mode to dump calibration outputs for inspection (optional)

DELIVERABLES
- A patch implementing:
  1) SR_WORK enforcement helper(s)
  2) block conversion OR overlap+crossfade boundary fix
  3) AutoTune calibration + caching
  4) Stable default preset and request parameter wiring
  5) Simple post-process chain
- Update/append to front_end/jfrontend/changes.md with:
  timestamp, problem, root cause, solution, files modified, result/status

IMPLEMENTATION GUIDELINES
- Keep the changes contained primarily to python_back_end/tts_system.
- Avoid risky refactors in PodcastGenerator unless required.
- Add unit-ish tests or a CLI script to run:
  - generate test phrase -> convert -> print chosen preset -> save example wav
- Don’t add heavyweight dependencies unless already present; prefer numpy/scipy/ffmpeg already used.
- Maintain Docker compatibility; avoid breaking container file paths and mounts.

VALIDATION CHECKLIST
- Run the “single-chunk test”:
  - Generate 20s continuous base audio
  - Convert in one chunk
  - Confirm choppiness improves compared to segment conversion
- Run a normal full episode:
  - Confirm seams are smooth (no step artifacts)
  - Confirm per-voice preset caching works (second run skips calibration)
  - Confirm output loudness is consistent

START NOW
Proceed directly: locate the RVC inference call site in python_back_end/tts_system, implement SR_WORK normalization, then implement block conversion first (preferred). If block slicing proves too complex, implement overlap+crossfade and ship it, then iterate to block conversion next.
