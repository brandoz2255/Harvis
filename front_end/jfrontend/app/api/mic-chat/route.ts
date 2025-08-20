import { type NextRequest, NextResponse } from "next/server"

const BACKEND_API = process.env.BACKEND_URL || "http://backend:8000"

export async function POST(request: NextRequest) {
  try {
    // Get the authorization header from the frontend request
    const authHeader = request.headers.get('authorization')
    console.log('Mic-chat proxy received auth header:', authHeader ? `${authHeader.substring(0, 20)}...` : 'null')

    const formData = await request.formData()
    
    // Extract model and file parameters  
    const model = formData.get('model') as string
    const file = formData.get('file') as File
    
    // Create FormData with both file and model for the backend (same as regular chat)
    const backendFormData = new FormData()
    backendFormData.append('file', file)
    backendFormData.append('model', model)
    
    const url = `${BACKEND_API}/api/mic-chat`

    console.log(`Mic-chat proxying to backend with auth header: ${authHeader?.substring(0, 20)}...`)

    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Authorization": authHeader, // Forward the auth header to backend
      },
      body: backendFormData,
    })

    if (!response.ok) {
      const errorData = await response.text()
      console.error(`Mic-chat backend error ${response.status}:`, errorData)
      
      if (response.status === 401 || response.status === 403) {
        return NextResponse.json({ error: "Authentication failed" }, { status: response.status })
      }
      
      throw new Error(`Backend responded with ${response.status}`)
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error("Mic chat API error:", error)
    return NextResponse.json({ error: "Failed to process audio" }, { status: 500 })
  }
}
