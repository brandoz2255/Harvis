// app/api/analyze-and-respond/route.ts
import { NextRequest, NextResponse } from "next/server";

const BACKEND_API = process.env.BACKEND_URL || "http://backend:8000";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    const response = await fetch(`${BACKEND_API}/api/analyze-and-respond`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      throw new Error(`Backend responded with ${response.status}`);
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error("Analyze and respond API error:", error);
    return NextResponse.json(
      { error: "Failed to analyze and respond" },
      { status: 500 }
    );
  }
}
