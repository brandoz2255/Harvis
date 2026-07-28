"""ONNX (sherpa-onnx) vs CTranslate2 (Speaches) on identical clips.

Runs from inside harvis-backend, which can reach both sidecars. The clips are
synthesized once by voice-onnx Kokoro and then fed byte-identical to every
engine, so the only variable is the recognizer.

Caveat stated up front: TTS-generated speech is cleaner than a real microphone,
so every WER here is optimistic in absolute terms. The comparison between
engines is still fair — they hear the same audio.
"""
import io
import json
import time
import wave

import requests

ONNX = "http://voice-onnx:8000/v1"
SPEACHES = "http://stt:8000/v1"

SENTENCES = [
    "The quick brown fox jumps over the lazy dog.",
    "Please open the settings panel and change the voice to Michael.",
    "Harvis runs entirely on this machine with no internet connection.",
    "Schedule the deployment for tomorrow at nine thirty in the morning.",
    "What is the current status of the background job I started earlier?",
    "Turn the speech speed up to one point five and read that again.",
    "The database migration added three tables and two indexes.",
    "Can you summarize the last four messages in this conversation?",
    "I need a report comparing the two models on the same audio clips.",
    "The voice service is optional and typed chat works without it.",
    "Send the results to the notebook and keep the raw numbers.",
    "Stop listening now and save everything I said to the transcript.",
]

WORD_OK = "abcdefghijklmnopqrstuvwxyz0123456789'"


def norm(s):
    s = s.lower().replace("-", " ")
    s = "".join(c for c in s if c in WORD_OK or c == " ")
    return s.split()


def wer(ref, hyp):
    r, h = norm(ref), norm(hyp)
    d = [[0] * (len(h) + 1) for _ in range(len(r) + 1)]
    for i in range(len(r) + 1):
        d[i][0] = i
    for j in range(len(h) + 1):
        d[0][j] = j
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1,
                          d[i - 1][j - 1] + (r[i - 1] != h[j - 1]))
    return d[len(r)][len(h)], len(r)


def duration(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return w.getnframes() / float(w.getframerate())


def synth(text):
    t0 = time.perf_counter()
    r = requests.post(f"{ONNX}/audio/speech",
                      json={"model": "tts-1", "voice": "af_heart",
                            "input": text, "speed": 1.0}, timeout=120)
    dt = time.perf_counter() - t0
    r.raise_for_status()
    return r.content, dt


def transcribe(base, wav, model):
    t0 = time.perf_counter()
    r = requests.post(f"{base}/audio/transcriptions",
                      files={"file": ("clip.wav", io.BytesIO(wav), "audio/wav")},
                      data={"model": model}, timeout=600)
    dt = time.perf_counter() - t0
    r.raise_for_status()
    return r.json().get("text", ""), dt


def main():
    print("synthesizing clips (voice-onnx Kokoro)...")
    clips, syn_lat, syn_dur = [], [], []
    for s in SENTENCES:
        wav, dt = synth(s)
        clips.append((s, wav))
        syn_lat.append(dt)
        syn_dur.append(duration(wav))
    total_audio = sum(syn_dur)
    print(f"  {len(clips)} clips, {total_audio:.1f}s audio, "
          f"synthesis {sum(syn_lat):.2f}s wall (RTF {sum(syn_lat)/total_audio:.3f}), "
          f"per-clip median {sorted(syn_lat)[len(syn_lat)//2]:.2f}s")

    configs = [
        ("ONNX      whisper-tiny.en ", ONNX, "whisper-tiny.en"),
        ("ONNX      whisper-base.en ", ONNX, "whisper-base.en"),
        ("CTranslate2 tiny.en       ", SPEACHES, "Systran/faster-whisper-tiny.en"),
        ("CTranslate2 base.en       ", SPEACHES, "Systran/faster-whisper-base.en"),
        ("CTranslate2 small.en      ", SPEACHES, "Systran/faster-whisper-small.en"),
    ]

    results = {}
    for label, base, model in configs:
        print(f"\n{label} warming up...")
        try:
            transcribe(base, clips[0][1], model)  # load model, not timed
        except Exception as e:
            print(f"  SKIPPED: {type(e).__name__}: {str(e)[:160]}")
            continue
        errs = tot = 0
        lat = []
        for ref, wav in clips:
            try:
                hyp, dt = transcribe(base, wav, model)
            except Exception as e:
                print(f"  clip failed: {type(e).__name__}: {str(e)[:100]}")
                continue
            e_, n = wer(ref, hyp)
            errs += e_
            tot += n
            lat.append(dt)
        if not lat:
            continue
        wall = sum(lat)
        results[label] = {
            "wer": 100.0 * errs / tot,
            "rtf": wall / total_audio,
            "wall": wall,
            "median_clip_s": sorted(lat)[len(lat) // 2],
            "clips": len(lat),
        }
        r = results[label]
        print(f"  WER {r['wer']:5.1f}%   RTF {r['rtf']:.3f}   "
              f"{r['wall']:.2f}s for {total_audio:.1f}s audio   "
              f"median clip {r['median_clip_s']:.2f}s")

    print("\n" + "=" * 74)
    print(f"{'engine / model':30} {'WER%':>7} {'RTF':>7} {'wall s':>9} {'med clip':>9}")
    print("-" * 74)
    for k, v in results.items():
        print(f"{k:30} {v['wer']:7.1f} {v['rtf']:7.3f} {v['wall']:9.2f} "
              f"{v['median_clip_s']:9.2f}")
    print("=" * 74)
    print(f"\naudio: {len(clips)} clips / {total_audio:.1f}s, "
          f"synthesis RTF {sum(syn_lat)/total_audio:.3f}")
    print(json.dumps(results))


main()
