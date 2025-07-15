import { NextRequest, NextResponse } from 'next/server'
function handleAuthError(error: Error): { message: string, status: number } {
  const errorMessage = error.message
  
  if (errorMessage === 'Authentication failed') {
    return { message: errorMessage, status: 401 }
  }
  
  return { message: errorMessage, status: 500 }
}

const BACKEND_URL = process.env.BACKEND_URL || 'http://backend:8000'

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url)
    const limit = searchParams.get('limit') || '50'
    const offset = searchParams.get('offset') || '0'
    
    // Get auth token from request headers and convert token format
    const authorization = request.headers.get('authorization')
    if (!authorization) {
      return NextResponse.json({ error: 'Authorization required' }, { status: 401 })
    }

    // Use the token directly from the backend login response
    const backendAuth = authorization
    console.log(`🔗 Proxying GET chat sessions to backend`)
    
    const response = await fetch(`${BACKEND_URL}/api/chat-history/sessions?limit=${limit}&offset=${offset}`, {
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
      throw new Error(`Backend responded with ${response.status}: ${errorText}`)
    }

    const data = await response.json()
    console.log(`🔗 Retrieved ${data.length} chat sessions`)
    
    return NextResponse.json(data)

  } catch (error) {
    console.error('🔗 Error proxying chat sessions request:', error)
    const authError = handleAuthError(error instanceof Error ? error : new Error('Failed to fetch chat sessions'))
    return NextResponse.json({ error: authError.message }, { status: authError.status })
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    
    // Get auth token from request headers and convert token format
    const authorization = request.headers.get('authorization')
    if (!authorization) {
      return NextResponse.json({ error: 'Authorization required' }, { status: 401 })
    }

    // Use the token directly from the backend login response
    const backendAuth = authorization
    console.log(`🔗 Proxying POST create session to backend`)
    
    const response = await fetch(`${BACKEND_URL}/api/chat-history/sessions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': backendAuth,
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
    console.log(`🔗 Created chat session: ${data.id}`)
    
    return NextResponse.json(data)

  } catch (error) {
    console.error('🔗 Error proxying create session request:', error)
    const authError = handleAuthError(error instanceof Error ? error : new Error('Failed to create chat session'))
    return NextResponse.json({ error: authError.message }, { status: authError.status })
  }
}