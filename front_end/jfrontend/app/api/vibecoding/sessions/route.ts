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
    const authHeader = request.headers.get('authorization')
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      return null
    }

    const token = authHeader.substring(7)
    const decoded = jwt.verify(token, JWT_SECRET) as JWTPayload
    return decoded
  } catch (error) {
    console.error('Token verification failed:', error)
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
    // Verify JWT token
    const user = await verifyToken(request)
    console.log('[DEBUG] JWT User object:', user)
    if (!user) {
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

    // Convert string user ID to number for backend
    console.log('[DEBUG] user.sub value:', user.sub, 'type:', typeof user.sub)
    const userId = parseInt(user.sub)
    console.log('[DEBUG] Parsed userId:', userId, 'isNaN:', isNaN(userId))
    
    if (isNaN(userId)) {
      console.error('[DEBUG] Failed to parse user ID from:', user.sub)
      return NextResponse.json(
        { error: 'Invalid user ID' },
        { status: 400 }
      )
    }

    const requestBody = {
      user_id: userId,
      project_name,
      description: description || ''
    }
    
    console.log('[DEBUG] Final request body to backend:', requestBody)
    console.log('[DEBUG] Stringified body:', JSON.stringify(requestBody))

    // Forward request to backend
    const backendResponse = await fetch(`${BACKEND_URL}/api/vibecoding/sessions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(requestBody)
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