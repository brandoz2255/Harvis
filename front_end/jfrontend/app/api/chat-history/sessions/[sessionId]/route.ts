import { NextRequest, NextResponse } from 'next/server'
function handleAuthError(error: Error): { message: string, status: number } {
  const errorMessage = error.message
  
  if (errorMessage === 'Authentication failed') {
    return { message: errorMessage, status: 401 }
  }
  
  return { message: errorMessage, status: 500 }
}

const BACKEND_URL = process.env.BACKEND_URL || 'http://backend:8000'

export async function GET(
  request: NextRequest,
  { params }: { params: { sessionId: string } }
) {
  try {
    const { searchParams } = new URL(request.url)
    const limit = searchParams.get('limit') || '100'
    const offset = searchParams.get('offset') || '0'
    
    // Get auth token from request headers
    const authorization = request.headers.get('authorization')
    if (!authorization) {
      return NextResponse.json({ error: 'Authorization required' }, { status: 401 })
    }

    // Use the token directly from the backend login response
    const backendAuth = authorization
    console.log(`🔗 Proxying GET session messages for ${params.sessionId}`)
    
    const response = await fetch(`${BACKEND_URL}/api/chat-history/sessions/${params.sessionId}?limit=${limit}&offset=${offset}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': backendAuth,
      },
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
    console.log(`🔗 Retrieved ${data.messages?.length || 0} messages for session ${params.sessionId}`)
    
    return NextResponse.json(data)

  } catch (error) {
    console.error('🔗 Error proxying session messages request:', error)
    const authError = handleAuthError(error instanceof Error ? error : new Error('Failed to fetch session messages'))
    return NextResponse.json({ error: authError.message }, { status: authError.status })
  }
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: { sessionId: string } }
) {
  try {
    // Get auth token from request headers
    const authorization = request.headers.get('authorization')
    if (!authorization) {
      return NextResponse.json({ error: 'Authorization required' }, { status: 401 })
    }

    console.log(`🔗 Proxying DELETE session ${params.sessionId}`)
    
    const response = await fetch(`${BACKEND_URL}/api/chat-history/sessions/${params.sessionId}`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': backendAuth,
      },
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
    console.log(`🔗 Deleted session ${params.sessionId}`)
    
    return NextResponse.json(data)

  } catch (error) {
    console.error('🔗 Error proxying delete session request:', error)
    const errorMessage = error instanceof Error ? error.message : 'Failed to delete session'
    
    return NextResponse.json({ error: errorMessage }, { 
      status: 500
    })
  }
}