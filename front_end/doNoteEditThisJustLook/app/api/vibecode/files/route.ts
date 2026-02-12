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

export async function POST(request: NextRequest) {
  try {
    // Verify JWT token for write operations only
    const body = await request.json()
    const { action, session_id, path, content, old_path, new_path, source_path, target_dir } = body

    if (!session_id) {
      return NextResponse.json(
        { error: 'Session ID is required' },
        { status: 400 }
      )
    }

    let endpoint: string
    let needsAuth = false

    switch (action) {
      case 'list':
        endpoint = '/api/vibecode/files/tree'  // Use tree for list action
        break
      case 'tree':
        endpoint = '/api/vibecode/files/tree'
        break
      case 'read':
        endpoint = '/api/vibecode/files/read'
        break
      case 'save':
        endpoint = '/api/vibecode/files/save'
        needsAuth = true
        break
      case 'create':
        endpoint = '/api/vibecode/files/create'
        needsAuth = true
        break
      case 'rename':
        endpoint = '/api/vibecode/files/rename'
        needsAuth = true
        break
      case 'move':
        endpoint = '/api/vibecode/files/move'
        needsAuth = true
        break
      case 'delete':
        endpoint = '/api/vibecode/files/delete'
        needsAuth = true
        break
      default:
        return NextResponse.json(
          { error: 'Invalid action' },
          { status: 400 }
        )
    }

    // Verify JWT token for write operations
    if (needsAuth) {
      const user = await verifyToken(request)
      if (!user) {
        return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
      }
    }

    let requestBody: any = { session_id }

    // Build request body based on action
    switch (action) {
      case 'list':
      case 'tree':
        requestBody.path = path || '/workspace'
        break
      case 'read':
        requestBody.file_path = path
        break
      case 'save':
        requestBody.file_path = path
        requestBody.content = content
        break
      case 'create':
        requestBody.file_path = path
        break
      case 'rename':
        requestBody.old_path = old_path
        requestBody.new_path = new_path
        break
      case 'move':
        requestBody.source_path = source_path
        requestBody.target_dir = target_dir
        break
      case 'delete':
        requestBody.file_path = path
        break
    }

    // Forward request to backend
    const backendResponse = await fetch(`${BACKEND_URL}${endpoint}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(needsAuth && { 'Authorization': request.headers.get('authorization') || '' })
      },
      body: JSON.stringify(requestBody)
    })

    if (!backendResponse.ok) {
      const error = await backendResponse.text()
      console.error(`Backend file operation (${action}) failed:`, error)
      return NextResponse.json(
        { error: `File ${action} operation failed` },
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