import { type NextRequest, NextResponse } from "next/server"

const BACKEND_API = process.env.BACKEND_URL || "http://backend:8000"

export async function POST(request: NextRequest) {
  try {
    const formData = await request.formData()
    const model = formData.get("model") || "mistral"

    // Create new FormData for backend
    const backendFormData = new FormData()
    const file = formData.get("file")
    if (file) {
      backendFormData.append("file", file)
    }

    const response = await fetch(`${BACKEND_API}/api/voice-transcribe?model=${model}`, {
      method: "POST",
      body: backendFormData,
    })

    if (!response.ok) {
      throw new Error(`Backend responded with ${response.status}`)
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error("Voice transcription API error:", error)
    return NextResponse.json({ error: "Failed to transcribe audio" }, { status: 500 })
  }
}
