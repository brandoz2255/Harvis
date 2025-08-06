import { NextRequest, NextResponse } from 'next/server'
import { AuthService } from '@/lib/auth/AuthService'

export async function GET(request: NextRequest) {
  try {
    const user = await AuthService.getCurrentUser(request)
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const authHeader = request.headers.get('authorization')
    if (!authHeader) {
      return NextResponse.json({ error: 'No authorization header' }, { status: 401 })
    }

    const backendUrl = process.env.BACKEND_URL || 'http://backend:8000'
    
    // Use new vibecoding models endpoint
    const response = await fetch(`${backendUrl}/api/models/available`, {
      method: 'GET',
      headers: {
        'Authorization': authHeader,
        'Content-Type': 'application/json',
      },
      // Add timeout to prevent hanging
      signal: AbortSignal.timeout(10000), // 10 second timeout
    })

    if (!response.ok) {
      throw new Error(`Backend responded with status: ${response.status}`)
    }

    const data = await response.json()
    
    // Backend already returns properly formatted models response
    return NextResponse.json(data)

  } catch (error) {
    console.error('Failed to fetch available models:', error)
    
    // Return fallback models when backend is unavailable
    const fallbackModels = [
      {
        name: 'offline-mode',
        displayName: 'Offline Mode',
        status: 'offline',
        size: 'N/A',
        description: 'Limited functionality - backend unavailable',
        capabilities: ['basic-editing'],
        performance: {
          speed: 1,
          quality: 1,
          memory: 0
        },
        lastChecked: new Date().toISOString()
      },
      {
        name: 'mistral',
        displayName: 'Mistral (Simulated)',
        status: 'error',
        size: '7B',
        description: 'Simulated model for development (backend offline)',
        capabilities: ['text-generation'],
        performance: {
          speed: 2,
          quality: 3,
          memory: 1500
        },
        lastChecked: new Date().toISOString()
      }
    ]

    return NextResponse.json({ 
      models: fallbackModels,
      timestamp: new Date().toISOString(),
      backend_status: 'disconnected',
      error: error instanceof Error ? error.message : 'Unknown error'
    }, { status: 200 }) // Return 200 with error info rather than failing completely
  }
}