import { type NextRequest, NextResponse } from "next/server"

const BACKEND_API = process.env.BACKEND_URL || "http://backend:8000"

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url)
    const sessionId = searchParams.get("sessionId")

    if (!sessionId) {
      return NextResponse.json({ error: "Session ID is required" }, { status: 400 })
    }

    const response = await fetch(`${BACKEND_API}/api/screen-feed?sessionId=${sessionId}`, {
      method: "GET",
    })

    if (!response.ok) {
      throw new Error(`Backend responded with ${response.status}`)
    }

    // Forward the image response
    const imageBuffer = await response.arrayBuffer()

    return new NextResponse(imageBuffer, {
      headers: {
        "Content-Type": response.headers.get("Content-Type") || "image/png",
        "Cache-Control": "no-cache",
      },
    })
  } catch (error) {
    console.error("Screen feed API error:", error)
    return NextResponse.json({ error: "Failed to retrieve screen feed" }, { status: 500 })
  }
}
