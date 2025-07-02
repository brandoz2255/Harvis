import { NextResponse } from "next/server"

export async function POST(req: Request) {
  const { email, password } = await req.json()

  // 🔒 Replace this with real DB logic
  const isValid = email === "user@example.com" && password === "secure123"

  if (!isValid) {
    return NextResponse.json({ message: "Invalid credentials" }, { status: 401 })
  }

  // ✅ Set cookie/session/token here if needed
  return NextResponse.json({ success: true })
}
