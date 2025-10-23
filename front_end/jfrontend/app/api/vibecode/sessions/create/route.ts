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
    const authHeader = request.headers.get('authorization')
    console.log('[DEBUG] Auth header:', authHeader ? `${authHeader.substring(0, 20)}...` : 'null')
    
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

export async function POST(request: NextRequest) {
  try {
    // Verify JWT token
    const user = await verifyToken(request)
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const body = await request.json()
    const { name, template, description } = body

    if (!name) {
      return NextResponse.json(
        { error: 'Session name is required' },
        { status: 400 }
      )
    }

    // Forward request to backend
    const backendResponse = await fetch(`${BACKEND_URL}/api/vibecode/sessions/create`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': request.headers.get('authorization') || '',
      },
      body: JSON.stringify({
        name,
        template: template || 'base',
        description: description || ''
      })
    })

    if (!backendResponse.ok) {
      const error = await backendResponse.text()
      console.error('Backend session creation failed:', error)
      return NextResponse.json(
        { error: 'Session creation failed' },
        { status: backendResponse.status }
      )
    }

    const data = await backendResponse.json()
    return NextResponse.json(data)

  } catch (error) {
    console.error('Error in session creation API:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}