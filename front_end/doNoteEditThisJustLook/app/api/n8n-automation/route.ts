import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://backend:8000';

export async function POST(req: NextRequest) {
  try {
    const { prompt, model = 'mistral' } = await req.json();

    if (!prompt) {
      return NextResponse.json({ error: 'Prompt is required' }, { status: 400 });
    }

    // Forward request to Python backend which has sophisticated n8n automation logic
    const response = await fetch(`${BACKEND_URL}/api/n8n/automate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        prompt,
        model
      }),
    });

    if (!response.ok) {
      const errorData = await response.json();
      console.error("Backend n8n automation error:", errorData);
      return NextResponse.json(
        { error: errorData.detail || errorData.error || 'Failed to create workflow' }, 
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);

  } catch (error: any) {
    console.error("n8n automation proxy error:", error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}