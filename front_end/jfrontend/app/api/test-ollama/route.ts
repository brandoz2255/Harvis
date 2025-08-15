import { NextResponse } from 'next/server'

export async function GET() {
  try {
    console.log("🧪 Test endpoint called - checking Ollama connectivity")
    
    // Test direct connection to Ollama
    const ollamaUrl = 'http://ollama:11434'
    console.log(`🧪 Testing connection to: ${ollamaUrl}`)
    
    const response = await fetch(`${ollamaUrl}/api/tags`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
      signal: AbortSignal.timeout(10000),
    })
    
    console.log(`🧪 Direct test - Status: ${response.status}`)
    
    if (!response.ok) {
      return NextResponse.json({
        test: "FAILED",
        error: `HTTP ${response.status}: ${response.statusText}`,
        url: ollamaUrl
      })
    }
    
    const data = await response.json()
    console.log(`🧪 Direct test - Raw response:`, data)
    
    return NextResponse.json({
      test: "SUCCESS",
      url: ollamaUrl,
      raw_response: data,
      models_found: data.models?.length || 0,
      model_names: data.models?.map((m: any) => m.name) || []
    })
    
  } catch (error) {
    console.error("🧪 Test endpoint error:", error)
    return NextResponse.json({
      test: "ERROR",
      error: error instanceof Error ? error.message : "Unknown error",
      details: error
    })
  }
}