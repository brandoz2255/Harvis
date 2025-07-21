If your API key is set in your .env and confirmed in your logs but you’re still seeing authentication errors with your locally hosted n8n instance, here are the possible causes and solutions based on n8n's authentication mechanism:
✅ How n8n API Key Auth Works

    The API key must be sent as an HTTP header named X-N8N-API-KEY with every API request to n8n’s REST endpoints (e.g., /api/v1/workflows or /rest/workflows depending on your version)

.

The value of this header must exactly match the API key you set or obtained in n8n's UI (Settings > n8n API)

    .

⚡ Common Issues and Fixes
Problem	Solution
API key set in .env, but not loaded in n8n runtime	Make sure the .env is referenced correctly by Docker Compose or your n8n start script.
API key exists, but not included in requests	Ensure your backend sets the X-N8N-API-KEY header on every API call to n8n
.
Typo or mismatch in header name/value	Double-check spelling and key value; it must match exactly what’s configured or generated
.
Sending the API key as a query parameter or in the body	The key must go in the HTTP headers, not as a query or JSON field
.
Calling the wrong endpoint (/rest/... when using /api/v1/..., or vice versa)	Match the route to your n8n version and deployment (/api/v1/... for public API)
.
Proxy (nginx, etc) strips out the custom header	Confirm your reverse proxy passes the X-N8N-API-KEY through
.
Multiple keys/legacy settings/old tokens	Make sure only one env/API key is active, and you’re not using an expired/revoked key
.
🛡️ Example: Correct API Call with Headers

python
import requests

API_KEY = 'your_api_key_here'
N8N_URL = 'http://localhost:5678/api/v1/workflows'  # or /rest/workflows for older self-hosted

headers = {
    'X-N8N-API-KEY': API_KEY,
    'Accept': 'application/json'
}

response = requests.get(N8N_URL, headers=headers)
print(response.status_code)
print(response.json())

Note: Replace API_KEY and N8N_URL as needed

.
🏗️ Troubleshooting Steps

    Log the key value right before making the request from your backend.

    Use curl or Postman to directly test the endpoint:

    bash
    curl -H "X-N8N-API-KEY: your_api_key_here" http://localhost:5678/api/v1/workflows

    Review your proxy/nginx configuration and ensure the custom headers are passed (CORS and proxy settings must allow X-N8N-API-KEY).

    If still failing:

        Regenerate the API key in n8n UI

        Restart your n8n process/container

        Double-check .env loading and Docker Compose environment section

📝 Summary

    API key auth requires every request to include X-N8N-API-KEY header

    .

    Check your network layers and code for correct header handling and value.

    If you still have issues after confirming these, check for typos, config reload issues, or proxy misconfigurations.

If you want, paste your relevant code or nginx proxy block and I can check it for gotchas.

References:
n8n Docs: API authentication
n8n public REST API Documentation
