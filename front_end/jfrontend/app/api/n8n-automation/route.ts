
import { NextRequest, NextResponse } from 'next/server';

// IMPORTANT: Replace with your actual n8n and Ollama details
const N8N_URL = process.env.N8N_URL || 'http://n8n:5678';
const OLLAMA_URL = process.env.OLLAMA_URL || 'http://localhost:11434/api/generate';

async function generateWorkflowJson(prompt: string): Promise<any> {
  const ollamaPrompt = `
    You are an expert n8n workflow generator.
    Based on the following prompt, generate a valid n8n workflow JSON object.
    The JSON object must have two properties: "nodes" and "connections".
    - "nodes" is an array of n8n node objects.
    - "connections" is an object mapping output names to input names.

    Here is an example of a simple workflow that checks if a website is up and sends a message to Discord.

    Prompt: "Every 5 minutes, check if google.com is up. If it's not, send a message to my Discord channel."

    {
      "nodes": [
        {
          "parameters": {
            "rule": {
              "interval": [
                {
                  "field": "minutes",
                  "value": 5
                }
              ]
            }
          },
          "name": "Schedule Trigger",
          "type": "n8n-nodes-base.scheduleTrigger",
          "typeVersion": 1,
          "position": [ 400, 200 ],
          "id": "d7a7a2e7-2031-4f20-a2f3-3e0a1a4e8f44"
        },
        {
          "parameters": {
            "url": "https://google.com",
            "options": {}
          },
          "name": "HTTP Request",
          "type": "n8n-nodes-base.httpRequest",
          "typeVersion": 1,
          "position": [ 600, 200 ],
          "id": "a1b2c3d4-e5f6-7890-1234-567890abcdef"
        },
        {
          "parameters": {
            "conditions": {
              "string": [
                {
                  "value1": "{{$json.statusCode}}",
                  "operation": "notEqual",
                  "value2": "200"
                }
              ]
            }
          },
          "name": "IF",
          "type": "n8n-nodes-base.if",
          "typeVersion": 1,
          "position": [ 800, 200 ],
          "id": "b2c3d4e5-f6a7-8901-2345-67890abcdef1"
        },
        {
          "parameters": {
            "webhookUrl": "YOUR_DISCORD_WEBHOOK_URL",
            "content": "Google.com might be down!",
            "options": {}
          },
          "name": "Discord",
          "type": "n8n-nodes-base.discord",
          "typeVersion": 1,
          "position": [ 1000, 200 ],
          "id": "c3d4e5f6-a7b8-9012-3456-7890abcdef12"
        }
      ],
      "connections": {
        "Schedule Trigger": {
          "main": [
            [
              {
                "node": "HTTP Request",
                "type": "main",
                "index": 0
              }
            ]
          ]
        },
        "HTTP Request": {
          "main": [
            [
              {
                "node": "IF",
                "type": "main",
                "index": 0
              }
            ]
          ]
        },
        "IF": {
          "main": [
            [
              {
                "node": "Discord",
                "type": "main",
                "index": 0
              }
            ]
          ]
        }
      }
    }

    Now, generate a workflow for the following prompt.

    Prompt: "${prompt}"

    n8n Workflow JSON:
  `;

  const response = await fetch(OLLAMA_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: 'mistral', // Or your preferred model
      prompt: ollamaPrompt,
      stream: false
    }),
  });

  if (!response.ok) {
    throw new Error('Failed to communicate with Ollama');
  }

  const data = await response.json();
  
  try {
    // Attempt to extract JSON from the LLM's response, handling markdown code blocks
    const jsonMatch = data.response.match(/```json\n([\s\S]*?)\n```/);
    let jsonString = jsonMatch ? jsonMatch[1] : data.response;

    // Clean up any remaining backticks or extra characters
    jsonString = jsonString.replace(/```/g, '').trim();

    return JSON.parse(jsonString);
  } catch (e) {
    console.error("Invalid JSON from LLM:", data.response);
    throw new Error(`LLM returned invalid JSON. Raw response: ${data.response.substring(0, 200)}...`);
  }
}

export async function POST(req: NextRequest) {
  try {
    const { prompt } = await req.json();

    if (!prompt) {
      return NextResponse.json({ error: 'Prompt is required' }, { status: 400 });
    }

    const workflowJson = await generateWorkflowJson(prompt);

    const createWorkflowResponse = await fetch(`${N8N_URL}/api/v1/workflows`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(workflowJson),
    });

    if (!createWorkflowResponse.ok) {
      const errorData = await createWorkflowResponse.json();
      console.error("n8n API error:", errorData);
      throw new Error(errorData.message || 'Failed to create workflow in n8n');
    }

    const workflow = await createWorkflowResponse.json();

    // Optionally, execute the workflow immediately
    // await fetch(`${N8N_URL}/api/v1/workflows/${workflow.id}/execute`, {
    //   method: 'POST',
    //   headers: { 'Content-Type': 'application/json' },
    // });

    return NextResponse.json({ workflow });

  } catch (error: any) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}
