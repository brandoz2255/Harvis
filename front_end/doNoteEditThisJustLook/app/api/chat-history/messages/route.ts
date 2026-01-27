import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.BACKEND_URL || 'http://backend:8000'

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    
    // Get auth token from request headers
    const authorization = request.headers.get('authorization')
    if (!authorization) {
      return NextResponse.json({ error: 'Authorization required' }, { status: 401 })
    }

    console.log(`🔗 Proxying POST add message to chat history`)
    
    const response = await fetch(`${BACKEND_URL}/api/chat-history/messages`, {
      method: 'POST',
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
      throw new Error(`Backend responded with ${response.status}: ${errorText}`)
    }

    const data = await response.json()
    console.log(`🔗 Added message to session: ${body.session_id}`)
    
    return NextResponse.json(data)

  } catch (error) {
    console.error('🔗 Error proxying add message request:', error)
    const errorMessage = error instanceof Error ? error.message : 'Failed to add message'
    
    return NextResponse.json({ error: errorMessage }, { 
      status: 500
    })
  }
}