# aidev: Voice Chat with Ollama

This project is a voice chat application that allows users to interact with a language model using either text or voice input. It uses Next.js for the web interface, Whisper for speech-to-text (STT), and Chatterbox TTS for text-to-speech (TTS). The backend language model server is provided by Ollama.

## Features

- Voice input and output
- Text-based chat interface
- Model selection with automatic refresh
- Advanced voice settings for customization
- GPU acceleration with fallback to CPU when needed

## Browser Automation Commands

### Voice Commands

- **"Open new tab [URL]"**: Opens a new browser tab with the specified URL.
- **"Search [query]"**: Performs a Google search with the provided query.
- **"Go to [URL]"**: Navigates to the specified URL in the current tab.

### Text Input Commands

You can also type these commands directly into the text chat interface:
- `open new tab [URL]`
- `search [query]`
- `go to [URL]`

## Requirements

- Python 3.10+
- CUDA-enabled GPU (optional, but recommended for TTS)
- ffmpeg for audio processing
- Docker and Docker Compose for containerized deployment

## Installation

### Local Setup

1. Clone the repository:
   ```bash
   git clone <repository_url>
   cd aidev
   ```

2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Ensure ffmpeg is installed on your system:
   ```bash
   sudo apt install ffmpeg  # Debian/Ubuntu
   brew install ffmpeg      # macOS
   ```

4. Install Selenium and webdriver-manager:
   ```bash
   pip install selenium webdriver-manager
   ```

### Docker Setup

1. Build the Docker image:
   ```bash
   docker-compose build
   ```

2. Start the services:
   ```bash
   docker-compose up -d
   ```

## Usage

To run the application locally:

```bash
python new-chatbot.py
```

The web interface will be available at `http://localhost:7860`.

### Docker Compose Services

- **ollama**: The Ollama language model server (port 11434)
- **webui**: Web UI for interacting with the Ollama models (port 3000)
- **n8n**: Workflow automation service (port 5678)
- **agent-zero-run**: Agent Zero Run microservice connected to Ollama (port 5000)

### Running in CPU-only Mode

If you encounter CUDA-related issues or prefer to run without GPU acceleration, you can force CPU mode by setting the `force_cpu` parameter to `True` in the application settings.

## Code Structure

- `new-chatbot.py`: Main application file containing all functionality
- `requirements.txt`: Python dependencies
- `Dockerfile`: Docker configuration for containerized deployment
- `docker-compose.yaml`: Multi-container setup with Ollama, webui, and n8n services

## VRAM Management

The application includes robust VRAM management to handle GPU memory efficiently:

1. Dynamic threshold based on available GPU memory (80% of total VRAM)
2. Automatic fallback to CPU when VRAM is critically low
3. Error handling for CUDA-related issues with retry mechanisms
4. Thorough logging for all operations and error conditions

## Notes

- The application requires the Ollama server to be running before starting the chat interface.
- For detailed CUDA errors, run with `CUDA_LAUNCH_BLOCKING=1` environment variable.

```bash
export CUDA_LAUNCH_BLOCKING=1
python new-chatbot.py
```

## Troubleshooting

If you encounter issues:

1. Check if the Ollama server is running and accessible at `http://localhost:11434`
2. Verify that ffmpeg is installed on your system
3. Check the application logs for error messages
4. Try forcing CPU mode by setting `force_cpu=True` in the advanced settings

## License

This project is open source and available under the MIT License.
