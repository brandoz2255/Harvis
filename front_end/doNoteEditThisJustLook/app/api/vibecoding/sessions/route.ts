import { NextRequest, NextResponse } from 'next/server'
import jwt from 'jsonwebtoken'

const BACKEND_URL = process.env.BACKEND_URL || 'http://backend:8000'
const JWT_SECRET = process.env.JWT_SECRET || 'key'

// Temporary logging to verify JWT secret is loaded
console.log('Frontend JWT_SECRET loaded:', JWT_SECRET.substring(0, 10) + '...', 'Length:', JWT_SECRET.length)

interface JWTPayload {
  sub: string  // Backend uses "sub" for user ID
  email?: string
  username?: string
}

async function verifyToken(request: NextRequest): Promise<JWTPayload | null> {
  try {
    console.log('[DEBUG] Starting JWT verification...')
    const authHeader = request.headers.get('authorization')
    console.log('[DEBUG] Auth header:', authHeader ? authHeader.substring(0, 20) + '...' : 'MISSING')
    
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      console.log('[DEBUG] No valid auth header found')
      return null
    }

    const token = authHeader.substring(7)
    console.log('[DEBUG] Extracted token:', token.substring(0, 20) + '...')
    console.log('[DEBUG] Using JWT_SECRET:', JWT_SECRET.substring(0, 10) + '... (length:', JWT_SECRET.length + ')')
    
    const decoded = jwt.verify(token, JWT_SECRET) as JWTPayload
    console.log('[DEBUG] JWT decoded successfully:', decoded)
    return decoded
  } catch (error) {
    console.error('[DEBUG] Token verification failed:', error)
    return null
  }
}

export async function GET(request: NextRequest) {
  try {
    // Verify JWT token
    const user = await verifyToken(request)
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const { searchParams } = new URL(request.url)
    const activeOnly = searchParams.get('active_only') !== 'false'

    // Forward request to backend
    const backendResponse = await fetch(`${BACKEND_URL}/api/vibecoding/sessions/${user.sub}?active_only=${activeOnly}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      }
    })

    if (!backendResponse.ok) {
      const error = await backendResponse.text()
      return NextResponse.json(
        { error: 'Failed to fetch sessions' },
        { status: backendResponse.status }
      )
    }

    const data = await backendResponse.json()
    return NextResponse.json(data)

  } catch (error) {
    console.error('Error in sessions API:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}

export async function POST(request: NextRequest) {
  try {
    // Get authorization header (don't verify JWT here, let backend handle it)
    const authHeader = request.headers.get('authorization')
    console.log('[DEBUG] Auth header:', authHeader ? authHeader.substring(0, 20) + '...' : 'MISSING')
    
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      console.log('[DEBUG] No valid auth header found')
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const body = await request.json()
    const { project_name, description } = body
    console.log('[DEBUG] Request body from frontend:', { project_name, description })

    if (!project_name) {
      return NextResponse.json(
        { error: 'Project name is required' },
        { status: 400 }
      )
    }

    console.log('[DEBUG] Forwarding to backend with auth header')

    // Forward request to backend with auth header (let backend handle JWT verification and user_id extraction)
    const backendResponse = await fetch(`${BACKEND_URL}/api/vibecoding/sessions/create`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': authHeader,  // Forward the auth header
      },
      body: JSON.stringify({
        project_name,
        description: description || ''
      })
    })

    if (!backendResponse.ok) {
      const error = await backendResponse.text()
      return NextResponse.json(
        { error: 'Failed to create session' },
        { status: backendResponse.status }
      )
    }

    const data = await backendResponse.json()
    return NextResponse.json(data)

  } catch (error) {
    console.error('Error creating session:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}