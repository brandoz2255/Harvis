import { type NextRequest, NextResponse } from "next/server"

const BACKEND_API = process.env.BACKEND_URL || "http://backend:8000"

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData()
    
    // Extract model and file parameters  
    const model = formData.get('model') as string
    const file = formData.get('file') as File
    
    // Create FormData with both file and model for the backend (same as regular chat)
    const backendFormData = new FormData()
    backendFormData.append('file', file)
    backendFormData.append('model', model)
    
    const url = `${BACKEND_API}/api/mic-chat`

    const response = await fetch(url, {
      method: "POST",
      body: backendFormData,
    })

    if (!response.ok) {
      throw new Error(`Backend responded with ${response.status}`)
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error("Mic chat API error:", error)
    return NextResponse.json({ error: "Failed to process audio" }, { status: 500 })
  }
}
