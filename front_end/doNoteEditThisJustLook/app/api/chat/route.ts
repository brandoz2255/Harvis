import { type NextRequest, NextResponse } from "next/server"

const BACKEND_API = process.env.BACKEND_URL || "http://backend:8000"

export async function POST(request: NextRequest) {
  try {
    // Get the authorization header from the frontend request
    const authHeader = request.headers.get('authorization')
    console.log('Proxy received auth header:', authHeader ? `${authHeader.substring(0, 20)}...` : 'null')
    
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      console.log('Proxy: Missing or invalid auth header')
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 })
    }

    const body = await request.json()
    
    console.log(`Proxying to backend with auth header: ${authHeader?.substring(0, 20)}...`)

    const response = await fetch(`${BACKEND_API}/api/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": authHeader, // Forward the auth header to backend
      },
      body: JSON.stringify(body),
    })

    if (!response.ok) {
      const errorData = await response.text()
      console.error(`Backend error ${response.status}:`, errorData)
      
      if (response.status === 401 || response.status === 403) {
        return NextResponse.json({ error: "Authentication failed" }, { status: response.status })
      }
      
      throw new Error(`Backend responded with ${response.status}`)
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error("Chat API error:", error)
    return NextResponse.json({ error: "Failed to process chat request" }, { status: 500 })
  }
}
