import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.BACKEND_URL || 'http://backend:8000'

export async function PUT(
  request: NextRequest,
  { params }: { params: { sessionId: string } }
) {
  try {
    const body = await request.json()
    
    // Get auth token from request headers
    const authorization = request.headers.get('authorization')
    if (!authorization) {
      return NextResponse.json({ error: 'Authorization required' }, { status: 401 })
    }

    console.log(`🔗 Proxying PUT update session title for ${params.sessionId}`)
    
    const response = await fetch(`${BACKEND_URL}/api/chat-history/sessions/${params.sessionId}/title`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': authorization,
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(10000),
    })

    console.log(`🔗 Backend response status: ${response.status} ${response.statusText}`)

    if (!response.ok) {
      const errorText = await response.text()
      if (response.status === 404) {
        return NextResponse.json({ error: 'Session not found' }, { status: 404 })
      }
      throw new Error(`Backend responded with ${response.status}: ${errorText}`)
    }

    const data = await response.json()
    console.log(`🔗 Updated title for session ${params.sessionId}`)
    
    return NextResponse.json(data)

  } catch (error) {
    console.error('🔗 Error proxying update session title request:', error)
    const errorMessage = error instanceof Error ? error.message : 'Failed to update session title'
    
    return NextResponse.json({ error: errorMessage }, { 
      status: 500
    })
  }
}