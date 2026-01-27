import { NextRequest, NextResponse } from 'next/server'

export async function GET() {
  try {
    // Call the backend API to get models (backend can reach ollama via Docker network)
    const backendUrl = process.env.BACKEND_URL || 'http://backend:8000'
    console.log(`🔗 Proxying to backend at: ${backendUrl}`)
    
    const response = await fetch(`${backendUrl}/api/ollama-models`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
      signal: AbortSignal.timeout(10000), // 10 second timeout
    })

    console.log(`🔗 Backend response status: ${response.status} ${response.statusText}`)

    if (!response.ok) {
      throw new Error(`Backend responded with ${response.status}: ${response.statusText}`)
    }

    const data = await response.json()
    console.log(`🔗 Backend response data:`, data)
    console.log(`🔗 Data type:`, typeof data, `Is array:`, Array.isArray(data))
    
    // Backend returns array of model names directly: ["model1", "model2"]
    if (Array.isArray(data)) {
      console.log(`🔗 Found ${data.length} models:`, data)
      return NextResponse.json(data) // Return the array directly to match backend format
    } else {
      console.log(`🔗 Unexpected backend response format:`, data)
      return NextResponse.json([]) // Return empty array
    }

  } catch (error) {
    console.error('🔗 Error proxying to backend:', error)
    const errorMessage = error instanceof Error ? error.message : 'Failed to connect to backend'
    console.error('🔗 Full error details:', {
      name: error instanceof Error ? error.name : 'Unknown',
      message: errorMessage,
      cause: error instanceof Error ? error.cause : undefined
    })
    
    // Return empty array to match backend format
    return NextResponse.json([], { 
      status: 200 // Return 200 so the frontend can handle gracefully
    })
  }
}

// Add POST method to handle server URL updates
export async function POST(request: NextRequest) {
  try {
    const body = await request.json()
    const { serverUrl } = body

    if (!serverUrl) {
      return NextResponse.json({
        success: false,
        error: 'Server URL is required'
      }, { status: 400 })
    }

    console.log(`🔗 Testing connection to custom Ollama URL: ${serverUrl}`)

    // Test connection to the provided Ollama server
    const response = await fetch(`${serverUrl}/api/tags`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
      signal: AbortSignal.timeout(10000),
    })

    if (!response.ok) {
      throw new Error(`Cannot connect to Ollama server at ${serverUrl}`)
    }

    const data = await response.json()
    const models = data.models?.map((model: any) => ({
      name: model.name,
      size: model.size,
      modified_at: model.modified_at,
      digest: model.digest,
      details: model.details
    })) || []

    return NextResponse.json({
      success: true,
      models: models,
      count: models.length,
      server_url: serverUrl,
      message: 'Successfully connected to Ollama server'
    })

  } catch (error) {
    console.error('🔗 Error testing Ollama connection:', error)
    
    return NextResponse.json({
      success: false,
      models: [],
      count: 0,
      error: error instanceof Error ? error.message : 'Failed to connect to Ollama server'
    }, { status: 200 })
  }
}