import { NextRequest, NextResponse } from 'next/server'
import jwt from 'jsonwebtoken'

const BACKEND_URL = process.env.BACKEND_URL || 'http://backend:8000'
const JWT_SECRET = process.env.JWT_SECRET || 'key'

interface JWTPayload {
  sub: string  // Backend uses "sub" for user ID
  email?: string
  username?: string
}

async function verifyToken(request: NextRequest): Promise<JWTPayload | null> {
  try {
    console.log('[FILES API DEBUG] Starting JWT verification...')
    console.log('[FILES API DEBUG] JWT_SECRET:', JWT_SECRET.substring(0, 10) + '... (length: ' + JWT_SECRET.length + ')')
    
    const authHeader = request.headers.get('authorization')
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      console.log('[FILES API DEBUG] No valid auth header')
      return null
    }

    const token = authHeader.substring(7)
    console.log('[FILES API DEBUG] Extracted token:', token.substring(0, 20) + '...')
    
    const decoded = jwt.verify(token, JWT_SECRET) as JWTPayload
    console.log('[FILES API DEBUG] JWT decoded successfully:', decoded)
    return decoded
  } catch (error) {
    console.error('[FILES API DEBUG] Token verification failed:', error)
    return null
  }
}

export async function GET(request: NextRequest) {
  try {
    console.log('[FILES API] Starting GET request')
    
    // No JWT verification needed - backend container endpoints are public

    const { searchParams } = new URL(request.url)
    const sessionId = searchParams.get('session_id')
    const path = searchParams.get('path') || '/workspace'

    console.log('[FILES API] Params:', { sessionId, path })

    if (!sessionId) {
      return NextResponse.json(
        { error: 'Session ID is required' },
        { status: 400 }
      )
    }

    console.log('[FILES API] Forwarding to backend with auth header')

    // Forward request to backend - list files
    const backendResponse = await fetch(`${BACKEND_URL}/api/vibecoding/container/files/list`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        session_id: sessionId,
        path
      })
    })

    console.log('[FILES API] Backend response status:', backendResponse.status)

    if (!backendResponse.ok) {
      const error = await backendResponse.text()
      console.log('[FILES API] Backend error:', error)
      return NextResponse.json(
        { error: 'Failed to list files' },
        { status: backendResponse.status }
      )
    }

    const data = await backendResponse.json()
    console.log('[FILES API] Backend response data:', data)
    return NextResponse.json(data)

  } catch (error) {
    console.error('[FILES API] Error in files API:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}

export async function POST(request: NextRequest) {
  try {
    // Verify JWT token
    const user = await verifyToken(request)
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const body = await request.json()
    const { session_id, action, file_path, content } = body

    if (!session_id) {
      return NextResponse.json(
        { error: 'Session ID is required' },
        { status: 400 }
      )
    }

    let endpoint: string
    let requestBody: any = { session_id }

    switch (action) {
      case 'read':
        endpoint = '/api/vibecoding/container/files/read'
        requestBody.file_path = file_path
        break
      case 'write':
        endpoint = '/api/vibecoding/container/files/write'
        requestBody.file_path = file_path
        requestBody.content = content
        break
      case 'execute':
        endpoint = '/api/vibecoding/container/execute'
        requestBody.command = body.command
        break
      default:
        return NextResponse.json(
          { error: 'Invalid action' },
          { status: 400 }
        )
    }

    // Forward request to backend
    const backendResponse = await fetch(`${BACKEND_URL}${endpoint}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(requestBody)
    })

    if (!backendResponse.ok) {
      const error = await backendResponse.text()
      return NextResponse.json(
        { error: 'File operation failed' },
        { status: backendResponse.status }
      )
    }

    const data = await backendResponse.json()
    return NextResponse.json(data)

  } catch (error) {
    console.error('Error in files API:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}