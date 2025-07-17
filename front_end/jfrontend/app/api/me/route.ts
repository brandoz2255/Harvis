import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.BACKEND_URL || 'http://backend:8000'

export async function GET(request: NextRequest) {
  try {
    const authHeader = request.headers.get('authorization')
    
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      return NextResponse.json({ message: 'Unauthorized' }, { status: 401 })
    }
    
    console.log(`/api/me: Calling backend ${BACKEND_URL}/api/auth/me`)
    const response = await fetch(`${BACKEND_URL}/api/auth/me`, {
      method: 'GET',
      headers: {
        'Authorization': authHeader,
      },
    })

    console.log(`/api/me: Backend response status: ${response.status}`)
    if (!response.ok) {
      const errorText = await response.text()
      console.error('/api/me: Backend error:', response.status, errorText)
      return NextResponse.json({ message: 'Authentication failed' }, { status: response.status })
    }
    
    const userData = await response.json()
    console.log('/api/me: Got user data:', userData)
    
    // Convert backend response format to frontend expected format
    return NextResponse.json({
      id: userData.id.toString(),
      name: userData.username,  // Backend returns 'username', frontend expects 'name'
      email: userData.email,
      avatar: userData.avatar
    })
  } catch (error) {
    console.error('/api/me: Error:', error)
    return NextResponse.json({ message: 'Failed to fetch user data' }, { status: 500 })
  }
}