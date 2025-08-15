
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

root@8426bfb73cec:/app# curl <http://ollama:11434>
Ollama is runningroot@8426bfb73cec:/app# curl <http://ollama:11434/api/generate>

  File "/app/main.py", line 161, in chat
    resp.raise_for_status()
  File "/usr/local/lib/python3.11/site-packages/requests/models.py", line 1026, in raise_for_status
    raise HTTPError(http_error_msg, response=self)
requests.exceptions.HTTPError: 404 Client Error: Not Found for url: <http://ollama:11434/api/chat>
INFO:     172.18.0.5:56908 - "POST /api/chat HTTP/1.0" 500 Internal Server Error
ERROR:main:Chat endpoint crashed
Traceback (most recent call last):
  File "/app/main.py", line 161, in chat
    resp.raise_for_status()
  File "/usr/local/lib/python3.11/site-packages/requests/models.py", line 1026, in raise_for_status
    raise HTTPError(http_error_msg, response=self)
requests.exceptions.HTTPError: 404 Client Error: Not Found for url: <http://ollama:11434/api/chat>
INFO:     172.18.0.5:56912 - "POST /api/chat HTTP/1.0" 500 Internal Server Erro

{"model":"gemma3:1b","created_at":"2025-06-29T19:18:22.069489781Z","message":{"role":"assistant","content":" like"},"done":false}
{"model":"gemma3:1b","created_at":"2025-06-29T19:18:22.086274969Z","message":{"role":"assistant","content":" to"},"done":false}
{"model":"gemma3:1b","created_at":"2025-06-29T19:18:22.104281931Z","message":{"role":"assistant","content":" chat"},"done":false}
{"model":"gemma3:1b","created_at":"2025-06-29T19:18:22.124366998Z","message":{"role":"assistant","content":" about"},"done":false}
{"model":"gemma3:1b","created_at":"2025-06-29T19:18:22.141912356Z","message":{"role":"assistant","content":","},"done":false}
{"model":"gemma3:1b","created_at":"2025-06-29T19:18:22.158952284Z","message":{"role":"assistant","content":" or"},"done":false}
{"model":"gemma3:1b","created_at":"2025-06-29T19:18:22.176331409Z","message":{"role":"assistant","content":" anything"},"done":false}
{"model":"gemma3:1b","created_at":"2025-06-29T19:18:22.194253977Z","message":{"role":"assistant","content":" I"},"done":false}
{"model":"gemma3:1b","created_at":"2025-06-29T19:18:22.209692643Z","message":{"role":"assistant","content":" can"},"done":false}
{"model":"gemma3:1b","created_at":"2025-06-29T19:18:22.22589313Z","message":{"role":"assistant","content":" help"},"done":false}
{"model":"gemma3:1b","created_at":"2025-06-29T19:18:22.241932854Z","message":{"role":"assistant","content":" you"},"done":false}
{"model":"gemma3:1b","created_at":"2025-06-29T19:18:22.257720686Z","message":{"role":"assistant","content":" with"},"done":false}
{"model":"gemma3:1b","created_at":"2025-06-29T19:18:22.276643936Z","message":{"role":"assistant","content":" today"},"done":false}
{"model":"gemma3:1b","created_at":"2025-06-29T19:18:22.293120577Z","message":{"role":"assistant","content":"?"},"done":false}
{"model":"gemma3:1b","created_at":"2025-06-29T19:18:22.310650313Z","message":{"role":"assistant","content":""},"done_reason":"stop","done":true,"total_dur
ation":635305912,"load_duration":20387613,"prompt_eval_count":10,"prompt_eval_duration":20558298,"eval_count":36,"eval_duration":593928641}
root@8426bfb73cec:/app# curl -X POST <http://ollama:11434/api/chat>   -H "Content-Type: application/json"   -d '{"model": "gemma3:1b", "messages": [{"role":
 "user", "content": "Hello"}]}'

i was here 
