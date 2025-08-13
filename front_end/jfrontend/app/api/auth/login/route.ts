import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.BACKEND_URL || 'http://backend:8000'

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    
    console.log(`Login: Calling backend ${BACKEND_URL}/api/auth/login`)
    const response = await fetch(`${BACKEND_URL}/api/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    })

    console.log(`Login: Backend response status: ${response.status}`)
    if (!response.ok) {
      const errorText = await response.text()
      console.error('Backend login error:', response.status, errorText)
      return NextResponse.json({ message: 'Invalid credentials' }, { status: response.status })
    }

    const data = await response.json()
    console.log('Login: Success, got access_token:', data.access_token ? 'YES' : 'NO')
    
    // Pass through backend response unchanged
    return NextResponse.json(data)
  } catch (error) {
    console.error('Login proxy error:', error)
    return NextResponse.json({ message: 'Login failed' }, { status: 500 })
  }
}