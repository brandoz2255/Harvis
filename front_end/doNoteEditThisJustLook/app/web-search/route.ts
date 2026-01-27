import { type NextRequest, NextResponse } from "next/server"

const BACKEND_API = process.env.BACKEND_URL || "http://localhost:8000"

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const { query, model = "mistral", maxResults = 5 } = body

    if (!query) {
      return NextResponse.json({ error: "Search query is required" }, { status: 400 })
    }

    const response = await fetch(`${BACKEND_API}/api/web-search`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        query,
        model,
        maxResults,
      }),
    })

    if (!response.ok) {
      throw new Error(`Backend responded with ${response.status}`)
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error("Web search API error:", error)
    return NextResponse.json({ error: "Failed to perform web search" }, { status: 500 })
  }
}
