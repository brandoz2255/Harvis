import { NextRequest, NextResponse } from 'next/server'

export async function GET(request: NextRequest) {
  try {
    // Get Ollama server URL from environment or default to localhost
    const ollamaUrl = process.env.OLLAMA_URL || 'http://localhost:11434'
    
    // Fetch available models from Ollama API
    const response = await fetch(`${ollamaUrl}/api/tags`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
      // Add timeout for the request
      signal: AbortSignal.timeout(5000), // 5 second timeout
    })

    if (!response.ok) {
      throw new Error(`Ollama server responded with ${response.status}: ${response.statusText}`)
    }

    const data = await response.json()
    
    // Extract model names from the response
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
      server_url: ollamaUrl
    })

  } catch (error) {
    console.error('Error fetching Ollama models:', error)
    
    // Return empty array with error info instead of failing completely
    return NextResponse.json({
      success: false,
      models: [],
      count: 0,
      error: error instanceof Error ? error.message : 'Failed to connect to Ollama server',
      server_url: process.env.OLLAMA_URL || 'http://localhost:11434'
    }, { 
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

    // Test connection to the provided Ollama server
    const response = await fetch(`${serverUrl}/api/tags`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
      signal: AbortSignal.timeout(5000),
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
    console.error('Error testing Ollama connection:', error)
    
    return NextResponse.json({
      success: false,
      models: [],
      count: 0,
      error: error instanceof Error ? error.message : 'Failed to connect to Ollama server'
    }, { status: 200 })
  }
}