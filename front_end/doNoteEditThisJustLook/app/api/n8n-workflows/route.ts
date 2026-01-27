import { NextRequest, NextResponse } from "next/server";

export async function GET(request: NextRequest) {
  try {
    const backendUrl = process.env.BACKEND_URL || 'http://backend:8000';
    console.log(`Frontend n8n-workflows: Attempting to fetch from ${backendUrl}/api/n8n/workflows`);
    
    // Make request to backend for n8n workflows
    const response = await fetch(`${backendUrl}/api/n8n/workflows`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        'User-Agent': 'Jarvis-Frontend/1.0',
        // Forward any authentication headers from the original request
        ...(request.headers.get('authorization') && {
          'Authorization': request.headers.get('authorization')!
        })
      },
      // Add timeout for Docker network
      signal: AbortSignal.timeout(10000) // 10 second timeout
    });

    console.log(`Frontend n8n-workflows: Backend response status: ${response.status}`);

    if (!response.ok) {
      console.error(`Frontend n8n-workflows: Backend returned ${response.status}: ${response.statusText}`);
      // Return empty workflows list if backend fails
      return NextResponse.json({
        workflows: []
      }, { status: 200 });
    }

    const data = await response.json();
    console.log(`Frontend n8n-workflows: Received ${data?.workflows?.length || 0} workflows`);
    return NextResponse.json(data);
    
  } catch (error) {
    console.error('Frontend n8n-workflows: Error fetching n8n workflows:', error);
    
    // Return empty workflows list if there's an error
    return NextResponse.json({
      workflows: []
    }, { status: 200 });
  }
}