import { NextRequest, NextResponse } from "next/server";

export async function GET(request: NextRequest) {
  console.log('Frontend n8n-stats route called');
  try {
    const backendUrl = process.env.BACKEND_URL || 'http://backend:8000';
    console.log(`Frontend n8n-stats: Attempting to fetch from ${backendUrl}/api/n8n/stats`);
    
    // Make request to backend for n8n workflow statistics
    const response = await fetch(`${backendUrl}/api/n8n/stats`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        // Forward any authentication headers from the original request
        ...(request.headers.get('authorization') && {
          'Authorization': request.headers.get('authorization')!
        })
      }
    });

    console.log(`Frontend n8n-stats: Backend response status: ${response.status}`);

    if (!response.ok) {
      console.error(`Frontend n8n-stats: Backend returned ${response.status}: ${response.statusText}`);
      // Log response body for debugging
      try {
        const errorBody = await response.text();
        console.error(`Frontend n8n-stats: Backend error body:`, errorBody);
      } catch (e) {
        console.error(`Frontend n8n-stats: Could not read error body`);
      }
      
      // Return default values with proper status
      return NextResponse.json({
        totalWorkflows: 0,
        activeWorkflows: 0,
        totalExecutions: 0
      }, { status: 200 }); // Still return 200 to frontend to prevent errors
    }

    const data = await response.json();
    console.log(`Frontend n8n-stats: Received data:`, data);
    return NextResponse.json(data);
    
  } catch (error) {
    console.error('Frontend n8n-stats: Error fetching n8n stats:', error);
    
    // Return default stats if there's an error
    return NextResponse.json({
      totalWorkflows: 0,
      activeWorkflows: 0,
      totalExecutions: 0,
      error: 'Connection failed'
    }, { status: 200 });
  }
}