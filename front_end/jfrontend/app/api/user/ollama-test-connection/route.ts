import { NextRequest, NextResponse } from 'next/server';
import jwt from 'jsonwebtoken';

// Get user from JWT token
async function getUserFromToken(request: NextRequest) {
  const authHeader = request.headers.get('authorization');
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return null;
  }

  const token = authHeader.substring(7);
  try {
    const decoded = jwt.verify(token, process.env.JWT_SECRET!) as any;
    return decoded;
  } catch (error) {
    return null;
  }
}

// POST - Test Ollama connection
export async function POST(request: NextRequest) {
  try {
    const user = await getUserFromToken(request);
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { cloud_url, local_url, api_key } = await request.json();

    const results: {
      cloud: { status: string; model_count?: number; models?: string[]; message?: string } | null;
      local: { status: string; model_count?: number; models?: string[]; message?: string } | null;
    } = {
      cloud: null,
      local: null
    };

    // Test cloud connection
    if (cloud_url && cloud_url.trim()) {
      try {
        const headers: Record<string, string> = {
          'Content-Type': 'application/json'
        };

        if (api_key && api_key !== '****') {
          headers['Authorization'] = `Bearer ${api_key}`;
        }

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 10000); // 10 second timeout

        const response = await fetch(`${cloud_url}/api/tags`, {
          headers,
          signal: controller.signal
        });

        clearTimeout(timeoutId);

        if (response.ok) {
          const data = await response.json();
          const models = data.models || [];
          results.cloud = {
            status: 'success',
            model_count: models.length,
            models: models.slice(0, 5).map((m: any) => m.name || 'unknown')
          };
        } else {
          results.cloud = {
            status: 'error',
            message: `HTTP ${response.status}: ${response.statusText}`
          };
        }
      } catch (error: any) {
        results.cloud = {
          status: 'error',
          message: error.name === 'AbortError' ? 'Connection timeout' : error.message
        };
      }
    }

    // Test local connection
    if (local_url && local_url.trim()) {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 10000); // 10 second timeout

        const response = await fetch(`${local_url}/api/tags`, {
          signal: controller.signal
        });

        clearTimeout(timeoutId);

        if (response.ok) {
          const data = await response.json();
          const models = data.models || [];
          results.local = {
            status: 'success',
            model_count: models.length,
            models: models.slice(0, 5).map((m: any) => m.name || 'unknown')
          };
        } else {
          results.local = {
            status: 'error',
            message: `HTTP ${response.status}: ${response.statusText}`
          };
        }
      } catch (error: any) {
        results.local = {
          status: 'error',
          message: error.name === 'AbortError' ? 'Connection timeout' : error.message
        };
      }
    }

    return NextResponse.json(results);
  } catch (error) {
    console.error('Error testing Ollama connection:', error);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}
