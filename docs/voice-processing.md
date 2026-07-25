# Voice Processing

This document details the voice processing components of the AI Voice Assistant, including speech-to-text (STT) and text-to-speech (TTS) implementations.

> **Note (2026-07-25):** the sections from "Microphone Recording Implementation" onward describe
> `front_end/script.js`, which no longer exists. The live voice surface is the OWUI call overlay
> documented in the next section. Treat the older material as historical.

---

## The voice overlay (call mode) — current state and known gaps

**Status: works end to end, but not good enough to ship as a headline feature.** This section is the
honest inventory of what is wired and what still needs work. It is written against the code, with
file and line references, so the next person starts from facts rather than from this doc's
aspirational older sections.

### What exists today

The overlay is `front_end/owui/src/lib/components/chat/MessageInput/CallOverlay.svelte` (~1,200
lines), opened by the `showCallOverlay` store and rendered from
`front_end/owui/src/lib/components/chat/ChatControls.svelte:325`. One call turn runs:

1. **Capture** — `MediaRecorder` on the mic stream, with a Web Audio analyser tapping the same
   stream for voice-activity detection.
2. **Turn detection** — a frame counts as speech when its normalized RMS exceeds
   `SPEECH_RMS_THRESHOLD`; the turn ends after `SILENCE_DURATION_MS` below it
   (`CallOverlay.svelte:165-166`, defaults `0.01` and `1500`).
3. **Transcribe** — the recorded blob goes to `POST /api/v1/audio/transcriptions`
   (`main.py:5320`), which saves it to a temp file and runs Harvis's Whisper helper
   (`transcribe_with_whisper_optimized`) in a threadpool.
4. **Respond** — the transcript is submitted as an ordinary chat prompt, so a call turn is a normal
   chat turn with `voice: true` attached (`Chat.svelte:2534`).
5. **Speak** — the reply is split on punctuation and each sentence is synthesized by
   `POST /api/v1/audio/speech` (`main.py:5350`), queued, and played
   (`CallOverlay.svelte:536-548`, `monitorAndPlayAudio` at `:562`).

TTS defaults to **Piper** (CPU, no VRAM, ~0.1s per sentence) and falls back to the neural `qwen`
engine if Piper is missing (`main.py:5365-5382`). The synth call passes `auto_unload=False` so the
model stays warm between sentences — without it the model reloaded on every sentence and playback
crawled.

### Known gaps

**1. TTS failure is silent to the user.** `synthesizeOpenAISpeech(...)` swallows its error into a
`console.error` and returns null (`CallOverlay.svelte:537-542`), and the enclosing `try` does the
same at `:552`. The server returns a real `503 TTS unavailable` (`main.py:5402`). Put together: if
TTS is down, the overlay listens, transcribes, thinks, and then simply never speaks — with nothing
on screen saying why. This is the same silent-success shape found in the research pipeline
(`docs/handoffs/2026-07-24-research-pipeline-never-ran.md`); it needs a visible failed-to-speak
state and a fall back to showing the text.

**2. The advertised TTS engine and the actual TTS engine disagree.** `/api/v1/audio/config` reports
`MODEL: os.getenv("HARVIS_TTS_ENGINE", "qwen")` (`main.py:5287`) while `/api/v1/audio/speech`
resolves the same variable with `os.getenv("HARVIS_TTS_ENGINE", "piper")` (`main.py:5365`). With
the variable unset — the default deployment — the Settings UI reports `qwen` and the server
actually speaks with Piper. One of the two defaults has to move.

**3. `/api/v1/audio/config/update` does not persist anything.** It echoes the request body back
(`main.py:5302-5317`). An admin editing audio settings gets a success response and no change. The
docstring is honest about this, the API is not.

**4. The engine and voice lists are wrong.** `/api/v1/audio/models` advertises `qwen` and
`chatterbox` and omits `piper` — the actual default (`main.py:5406`). `/api/v1/audio/voices`
returns exactly one voice, `alloy` (`main.py:5411`), so the overlay's `getVoiceId()` plumbing is
decorative: Piper speaks with its one baked-in voice regardless of what is selected.

**5. Voice-activity detection is a fixed threshold with no calibration.** `SPEECH_RMS_THRESHOLD`
is a constant read once from settings; there is no ambient-noise measurement at call start and no
adaptation while the call runs. A quiet room and a noisy room need different numbers, and the only
way to change them is by hand-editing the settings JSON — there is no UI for either value. In a
noisy room the turn never ends; with a soft speaker it ends mid-sentence. Auto-calibrating from
the first second of ambient audio is the obvious fix.

**6. Latency stacks per sentence.** Each sentence is its own HTTP round trip to `/audio/speech`,
serialized behind the queue. Whisper transcription also runs in the backend's threadpool, competing
with LLM inference on the same box — on the 8GB laptop the whole turn serializes. Streaming
synthesis, or synthesizing the next sentence while the current one plays, would cut the gap between
"done thinking" and "starts speaking."

**7. No calibration, device-selection, or diagnostics UI.** There is no way from the interface to
pick an input device, see the measured noise floor, confirm which TTS engine actually answered, or
test the round trip. Every one of the gaps above is currently diagnosed from the browser console
and the backend log.

### Where to start

Gaps 1 through 4 are small, self-contained honesty fixes on code that already exists — an
afternoon each. Gap 5 (VAD calibration) is the one that most changes how the feature *feels*.
Gap 6 is the largest and should not be attempted before the others are done, because its symptoms
are currently masked by them.

## Speech-to-Text (STT)

### Whisper Model

#### Overview
- Open-source speech recognition model
- Multi-language support
- High accuracy transcription
- Real-time processing capabilities

#### Implementation
```python
from transformers import pipeline

def init_stt_model():
    stt_pipeline = pipeline(
        "automatic-speech-recognition",
        model="openai/whisper-base.en",
        device="cuda" if torch.cuda.is_available() else "cpu"
    )
    return stt_pipeline

def transcribe_audio(audio_path, stt_pipeline):
    try:
        result = stt_pipeline(audio_path)
        return result["text"]
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        raise
```

#### Key Features
1. **Audio Processing**
   - Format conversion
   - Noise reduction
   - Sample rate adjustment
   - Channel management

2. **Model Configuration**
   - Batch size optimization
   - Device selection (CPU/GPU)
   - Memory management
   - Error handling

3. **Performance Optimization**
   - Caching mechanisms
   - Parallel processing
   - Resource management
   - Latency reduction

## Text-to-Speech (TTS)

### Chatterbox TTS

#### Overview
- High-quality voice synthesis
- Real-time processing
- Customizable voice parameters
- Streaming capabilities

For detailed information about the Chatterbox TTS implementation and its integration with the main module, see [Main and Chatterbox TTS Integration](main-chatterbox-integration.md).

#### Implementation
```python
from chatterbox.tts import ChatterboxTTS, punc_norm

def init_tts_model():
    model = ChatterboxTTS.from_pretrained(
        device="cuda" if torch.cuda.is_available() else "cpu"
    )
    return model

def generate_speech(text, model, audio_prompt=None, 
                   exaggeration=0.5, temperature=0.8, 
                   cfg_weight=0.5):
    try:
        normalized = punc_norm(text)
        wav = model.generate(
            normalized,
            audio_prompt_path=audio_prompt,
            exaggeration=exaggeration,
            temperature=temperature,
            cfg_weight=cfg_weight
        )
        return (model.sr, wav.squeeze(0).numpy())
    except Exception as e:
        logger.error(f"TTS generation error: {e}")
        raise
```

#### Key Features
1. **Voice Synthesis**
   - Natural intonation
   - Emotion expression
   - Speed control
   - Pitch adjustment

2. **Audio Processing**
   - Format conversion
   - Quality optimization
   - Stream handling
   - Buffer management

3. **Performance Features**
   - GPU acceleration
   - Memory optimization
   - Caching strategies
   - Error recovery

## Audio Pipeline

### Input Processing
1. **Microphone Input**
   - Sample rate: 16kHz
   - Format: WAV
   - Channels: Mono
   - Bit depth: 16-bit

2. **Audio Preprocessing**
   - Noise reduction
   - Normalization
   - Format conversion
   - Quality checks

### Output Processing
1. **Audio Generation**
   - Sample rate: 24kHz
   - Format: WAV
   - Channels: Mono
   - Bit depth: 16-bit

2. **Post-processing**
   - Volume normalization
   - Format conversion
   - Quality optimization
   - Stream preparation

## Performance Optimization

### Memory Management
```python
def manage_audio_memory():
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.set_per_process_memory_fraction(0.8)  # Dynamic VRAM threshold based on available GPU memory
```

### Latency Reduction
1. **Streaming Optimization**
   - Buffer size adjustment
   - Chunk processing
   - Parallel operations
   - Caching strategies

2. **Resource Management**
   - GPU memory monitoring with dynamic VRAM thresholds
   - CPU utilization
   - Process prioritization
   - Resource cleanup

## Microphone Recording Implementation

The microphone recording feature was implemented in `front_end/script.js`. Here's a breakdown of how it works:

1. **Button Creation**: We add a microphone button to the chat container that users can click to start/stop recording.
2. **Recording State Management**:
   - We use an `isRecording` flag to track whether we're currently recording or not.
   - When in recording mode, clicking the button will stop the recording and process the audio.
3. **MediaRecorder API**:
   - We use the MediaRecorder API to capture audio data from the user's microphone.
   - The recorded chunks are stored in an array until the recording stops.
4. **Audio Processing**:
   - When recording stops, we create a Blob with the collected audio chunks and send it to our backend via a POST request.
5. **Backend Response Handling**:
   - After sending the audio, we handle the response by updating the chat history and playing any returned audio.

## Challenges & Solutions

1. **Stopping Recording Issue**: Initially, users couldn't stop recording once started. This was resolved by:
   - Moving the `mediaRecorder` declaration outside the event handler to maintain its reference across clicks.
   - Using a flag (`isRecording`) to track the recording state and toggle between start/stop actions.

2. **Backend Communication**: Ensuring proper communication with the backend for audio processing involved:
   - Creating a Blob from the recorded data with the correct MIME type
   - Setting up FormData correctly for the POST request

## CSS Styling

The microphone button is styled to be easily identifiable:
- Background color: Orange (#ff9800)
- Text color: White (#fff)
- Hover effect changes background to a darker orange (#e68900)

This styling is defined in `front_end/style.css` under the `.mic-button` class.

### Common Issues
1. **Audio Input**
   - Device not found
   - Format mismatch
   - Quality issues
   - Buffer overflow

2. **Processing**
   - Memory errors
   - GPU issues
   - Timeout errors
   - Format errors

3. **Output**
   - Device errors
   - Format issues
   - Stream errors
   - Quality problems

### Error Recovery
```python
def handle_audio_error(error):
    logger.error(f"Audio processing error: {error}")
    if "CUDA" in str(error):
        torch.cuda.empty_cache()
        return retry_operation()
    elif "device" in str(error).lower():
        return switch_to_cpu()
    else:
        return graceful_degradation()
```

## Best Practices

### Code Organization
1. **Modular Design**
   - Separate STT and TTS
   - Clear interfaces
   - Reusable components
   - Clean architecture

2. **Error Handling**
   - Comprehensive try-catch
   - Detailed logging
   - User feedback
   - Recovery mechanisms

3. **Performance**
   - Resource monitoring
   - Optimization strategies
   - Caching implementation
   - Memory management

### Testing
1. **Unit Tests**
   - Component testing
   - Error scenarios
   - Performance metrics
   - Resource usage

2. **Integration Tests**
   - Pipeline testing
   - End-to-end testing
   - Stress testing
   - Recovery testing

## Interview Preparation

### Technical Questions
1. How is audio quality maintained?
2. What strategies reduce latency?
3. How is memory managed?
4. What error handling is implemented?
5. How is performance optimized?

### Implementation Questions
1. How is real-time processing achieved?
2. What are the trade-offs in the design?
3. How is the system scaled?
4. What are the failure points?
5. How is the system tested?

### Architecture Questions
1. Why were these models chosen?
2. What are the alternatives?
3. How is the system deployed?
4. What are the security considerations?
5. How is the system monitored?
