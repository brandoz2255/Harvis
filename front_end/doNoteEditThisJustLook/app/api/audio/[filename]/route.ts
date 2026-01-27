import { type NextRequest, NextResponse } from "next/server"

const BACKEND_API = process.env.BACKEND_URL || "http://backend:8000"

export async function GET(request: NextRequest, { params }: { params: { filename: string } }) {
  try {
    const response = await fetch(`${BACKEND_API}/api/audio/${params.filename}`)

    if (!response.ok) {
      throw new Error(`Backend responded with ${response.status}`)
    }

    const audioBuffer = await response.arrayBuffer()

    return new NextResponse(audioBuffer, {
      headers: {
        "Content-Type": "audio/wav",
        "Cache-Control": "public, max-age=3600",
      },
    })
  } catch (error) {
    console.error("Audio API error:", error)
    return NextResponse.json({ error: "Audio file not found" }, { status: 404 })
  }
}
