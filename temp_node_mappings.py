            # Generic aliases that AI might use
            "webhook": {
                "name": "Webhook",
                "type": "n8n-nodes-base.webhook",
                "parameters": {
                    "httpMethod": parameters.get("webhook_method", "POST"),
                    "path": parameters.get("webhook_path", "/webhook")
                }
            },
            "code function": {
                "name": "Code Function",
                "type": "n8n-nodes-base.code",
                "parameters": {
                    "jsCode": parameters.get("code", "// Add your custom code here\\nreturn items;")
                }
            },
            "http request": {
                "name": "HTTP Request",
                "type": "n8n-nodes-base.httpRequest",
                "parameters": {
                    "url": parameters.get("ai_service_url", ""),
                    "requestMethod": "POST",
                    "headers": {"Authorization": f"Bearer {parameters.get('api_key', '')}"},
                    "body": {}
                }
            },
            "twilio node": {
                "name": "Twilio",
                "type": "n8n-nodes-base.twilio",
                "parameters": {
                    "operation": "makeCall",
                    "from": parameters.get("twilio_phone_number", ""),
                    "to": "{{$json.phone_number}}",
                    "url": "{{$json.call_url}}"
                }
            },