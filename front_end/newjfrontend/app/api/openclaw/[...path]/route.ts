/**
 * API Routes for OpenClaw — catch-all route
 *
 * Next.js API routes that proxy /api/openclaw/* to the Python backend.
 * Real path segments (e.g. /api/openclaw/tasks/{id}/cancel) are forwarded
 * as-is to ${BACKEND_URL}/api/openclaw/<segments>.
 */

import { NextRequest, NextResponse } from 'next/server'

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000'

type RouteContext = { params: Promise<{ path?: string[] }> }

// Helper to proxy requests to backend
async function proxyToBackend(
  request: NextRequest,
  path: string,
  method: string = 'GET',
  body?: any
) {
  const url = `${BACKEND_URL}/api/openclaw/${path}`

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }

  // Forward auth token
  const authHeader = request.headers.get('Authorization')
  if (authHeader) {
    headers['Authorization'] = authHeader
  }

  const options: RequestInit = {
    method,
    headers,
  }

  if (body && method !== 'GET') {
    options.body = JSON.stringify(body)
  }

  const response = await fetch(url, options)

  if (!response.ok) {
    const error = await response.text()
    return NextResponse.json(
      { error: `Backend error: ${error}` },
      { status: response.status }
    )
  }

  const data = await response.json()
  return NextResponse.json(data)
}

// Resolve the catch-all segments into the backend subpath
async function resolvePath(params: RouteContext['params']): Promise<string> {
  const { path } = await params
  return (path ?? []).join('/')
}

// GET /api/openclaw/*
export async function GET(request: NextRequest, { params }: RouteContext) {
  const path = await resolvePath(params)

  return proxyToBackend(request, path, 'GET')
}

// POST /api/openclaw/*
export async function POST(request: NextRequest, { params }: RouteContext) {
  const path = await resolvePath(params)
  const body = await request.json()

  return proxyToBackend(request, path, 'POST', body)
}

// PATCH /api/openclaw/*
export async function PATCH(request: NextRequest, { params }: RouteContext) {
  const path = await resolvePath(params)
  const body = await request.json()

  return proxyToBackend(request, path, 'PATCH', body)
}

// DELETE /api/openclaw/*
export async function DELETE(request: NextRequest, { params }: RouteContext) {
  const path = await resolvePath(params)

  return proxyToBackend(request, path, 'DELETE')
}
