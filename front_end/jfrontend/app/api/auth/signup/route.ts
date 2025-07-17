import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.BACKEND_URL || 'http://backend:8000'

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    
    const response = await fetch(`${BACKEND_URL}/api/auth/signup`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    })

    if (!response.ok) {
      const errorText = await response.text()
      console.error('Backend signup error:', errorText)
      return NextResponse.json({ message: 'Signup failed' }, { status: response.status })
    }

    const data = await response.json()
    
    // Convert backend response format to frontend expected format
    return NextResponse.json({ token: data.access_token })
  } catch (error) {
    console.error('Signup proxy error:', error)
    return NextResponse.json({ message: 'Signup failed' }, { status: 500 })
  }
}