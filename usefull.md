
Run this all in bash does not work in fish

```bash
curl http://localhost:11434/api/generate -d '{"model": "devstral", "keep_alive": 0}'
```

```bash
docker run -d \
  --name ollama \
  --gpus all \
  --network ollama-n8n-network \
  -p 11434:11434 \
  -v ollama:/root/.ollama \
  -e NVIDIA_VISIBLE_DEVICES=all \
  -e OLLAMA_FLASH_ATTENTION=1 \
  --tty \
  ollama/ollama:latest
```

```bash
docker run -d --gpus all \
  --name ollama \
  --network ollama-n8n-network \
  -v ollama:/root/.ollama \
  -p 11434:11434 \
  ollama-gpu


```

```bash
docker build -t backend ./python_back_end
```

```bash
docker run -d \
  --name backend \
  --gpus all \
  -e PYTHONPATH=/app \
  -e NVIDIA_VISIBLE_DEVICES=all \
  -e OLLAMA_FLASH_ATTENTION=1 \
  -p 8000:8000 \
  --restart unless-stopped \
  --network ollama-n8n-network \
  -v "$(pwd)/python_back_end":/app \
  backend
```