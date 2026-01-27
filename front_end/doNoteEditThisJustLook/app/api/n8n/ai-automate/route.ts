import { NextRequest, NextResponse } from 'next/server';

const BACKEND_URL = process.env.BACKEND_URL || 'http://backend:8000';

export async function POST(req: NextRequest) {
  try {
    const { prompt, model } = await req.json();

    if (!prompt) {
      return NextResponse.json({ error: 'Prompt is required' }, { status: 400 });
    }

    // Get user auth token from cookies
    const token = req.cookies.get('token')?.value;
    
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
    };

    // Add auth header if token exists
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }

    // Forward request to Python backend AI automation endpoint
    const response = await fetch(`${BACKEND_URL}/api/n8n/ai-automate`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        prompt,
        model
      }),
    });

    if (!response.ok) {
      const errorData = await response.json();
      console.error("Backend n8n AI automation error:", errorData);
      return NextResponse.json(
        { error: errorData.detail || errorData.error || 'Failed to create workflow' }, 
        { status: response.status }
      );
    }

    const data = await response.json();
    return NextResponse.json(data);

  } catch (error: any) {
    console.error("n8n AI automation proxy error:", error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }
}