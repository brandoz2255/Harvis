import { type NextRequest, NextResponse } from "next/server"

const BACKEND_API = process.env.BACKEND_URL || "http://backend:8000"

export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const { model, scenario } = body

    // Validate inputs
    const validModels = ["gpt-4o", "claude-3", "mistral", "llama3"]
    const validScenarios = [
      "network-intrusion",
      "privilege-escalation",
      "data-exfiltration",
      "lateral-movement",
      "persistence",
    ]

    if (!validModels.includes(model)) {
      return NextResponse.json({ error: "Invalid AI model" }, { status: 400 })
    }

    if (!validScenarios.includes(scenario)) {
      return NextResponse.json({ error: "Invalid scenario" }, { status: 400 })
    }

    const response = await fetch(`${BACKEND_API}/api/start-emulation`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ model, scenario }),
    })

    if (!response.ok) {
      throw new Error(`Backend responded with ${response.status}`)
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (error) {
    console.error("Start emulation API error:", error)
    return NextResponse.json({ error: "Failed to start emulation" }, { status: 500 })
  }
}
