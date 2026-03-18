/**
 * Workspace API proxy — catch-all route
 *
 * Proxies all /api/workspace/* requests to the Python backend.
 * SSE streams (/api/workspace/stream/*) are forwarded as raw readable streams
 * so the browser receives Server-Sent Events without buffering.
 */

import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.BACKEND_URL || 'http://backend:8000'

async function proxy(request: NextRequest, params: { path: string[] }) {
  const subpath = params.path.join('/')
  const backendUrl = `${BACKEND_URL}/api/workspace/${subpath}`
  const url = new URL(backendUrl)

  // Forward query params
  request.nextUrl.searchParams.forEach((value, key) => {
    url.searchParams.set(key, value)
  })

  const headers: Record<string, string> = {}
  const authHeader = request.headers.get('Authorization')
  if (authHeader) headers['Authorization'] = authHeader
  const contentType = request.headers.get('Content-Type')
  if (contentType) headers['Content-Type'] = contentType

  const isSSE = subpath.startsWith('stream/')

  const fetchOptions: RequestInit = {
    method: request.method,
    headers,
  }

  if (request.method !== 'GET' && request.method !== 'HEAD') {
    try {
      fetchOptions.body = await request.text()
    } catch {
      // No body
    }
  }

  try {
    const response = await fetch(url.toString(), fetchOptions)

    // SSE: stream the response body directly to the client
    if (isSSE && response.body) {
      return new Response(response.body, {
        status: response.status,
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          'Connection': 'keep-alive',
          'X-Accel-Buffering': 'no',
        },
      })
    }

    // Normal JSON response
    if (!response.ok) {
      const error = await response.text()
      return NextResponse.json(
        { error: `Backend error: ${error}` },
        { status: response.status }
      )
    }

    const data = await response.json()
    return NextResponse.json(data)
  } catch (err: any) {
    console.error('[workspace proxy]', err)
    return NextResponse.json(
      { error: `Proxy error: ${err.message}` },
      { status: 502 }
    )
  }
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
) {
  const params = await context.params
  return proxy(request, params)
}

export async function POST(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
) {
  const params = await context.params
  return proxy(request, params)
}

export async function PUT(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
) {
  const params = await context.params
  return proxy(request, params)
}

export async function DELETE(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> }
) {
  const params = await context.params
  return proxy(request, params)
}
