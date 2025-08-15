# Voice Processing

This document details the voice processing components of the AI Voice Assistant, including speech-to-text (STT) and text-to-speech (TTS) implementations.

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
