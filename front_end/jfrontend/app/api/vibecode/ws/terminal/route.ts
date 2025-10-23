import { NextRequest } from 'next/server'

const BACKEND_URL = process.env.BACKEND_URL || 'http://backend:8000'

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url)
  const sessionId = searchParams.get('session_id')

  if (!sessionId) {
    return new Response('Session ID is required', { status: 400 })
  }

  // Check if this is a WebSocket upgrade request
  const upgrade = request.headers.get('upgrade')

  if (upgrade !== 'websocket') {
    return new Response('Expected WebSocket upgrade', { status: 426 })
  }

  // For WebSocket endpoints, we need to let Nginx handle the proxying
  // This is a placeholder - the actual WebSocket upgrade will be handled by Nginx
  return new Response('WebSocket endpoint - should be proxied by Nginx', {
    status: 501,
    headers: {
      'X-Backend-URL': `${BACKEND_URL}/api/vibecode/ws/terminal?session_id=${sessionId}`
    }
  })
}