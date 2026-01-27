import { type NextRequest, NextResponse } from "next/server"

const BACKEND_API = process.env.BACKEND_URL || "http://backend:8000"

export async function POST(request: NextRequest) {
  try {
    // Get the authorization header from the frontend request
    const authHeader = request.headers.get('authorization')
    console.log('Mic-chat proxy received auth header:', authHeader ? `${authHeader.substring(0, 20)}...` : 'null')

    const formData = await request.formData()

    // Extract all parameters from frontend
    const file = formData.get('file') as File
    const model = formData.get('model') as string
    const sessionId = formData.get('session_id') as string | null
    const researchMode = formData.get('research_mode') as string | null
    const lowVram = formData.get('low_vram') as string | null
    const textOnly = formData.get('text_only') as string | null

    // Create FormData with ALL parameters for the backend
    const backendFormData = new FormData()
    backendFormData.append('file', file)
    backendFormData.append('model', model)

    // Forward optional parameters if provided
    if (sessionId) {
      backendFormData.append('session_id', sessionId)
    }
    if (researchMode) {
      backendFormData.append('research_mode', researchMode)
    }
    if (lowVram) {
      backendFormData.append('low_vram', lowVram)
    }
    if (textOnly) {
      backendFormData.append('text_only', textOnly)
    }

    const url = `${BACKEND_API}/api/mic-chat`

    console.log(`Mic-chat proxying to backend: session_id=${sessionId}, research_mode=${researchMode}, model=${model}`)

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
    console.log(`Mic-chat response: transcription="${data.transcription?.substring(0, 50)}...", has_audio=${!!data.audio_path}`)
    return NextResponse.json(data)
  } catch (error) {
    console.error("Mic chat API error:", error)
    return NextResponse.json({ error: "Failed to process audio" }, { status: 500 })
  }
}
