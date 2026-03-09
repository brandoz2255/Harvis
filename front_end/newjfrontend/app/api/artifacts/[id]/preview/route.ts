import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const BACKEND_URL = process.env.BACKEND_URL || 'http://backend:8000';

export async function GET(
  req: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const { id } = params;
    
    const response = await fetch(`${BACKEND_URL}/api/artifacts/${id}/preview`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': req.headers.get('Authorization') || '',
        'Cookie': req.headers.get('Cookie') || '',
      },
    });

    if (!response.ok) {
      if (response.status === 404) {
        return NextResponse.json(
          { error: 'Artifact not found' },
          { status: 404 }
        );
      }
      if (response.status === 400) {
        const errorData = await response.json().catch(() => ({ detail: 'Preview not available' }));
        return NextResponse.json(
          { error: errorData.detail || 'Preview not available' },
          { status: 400 }
        );
      }
      throw new Error(`Backend returned ${response.status}`);
    }

    const data = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    console.error('Error fetching artifact preview:', error);
    return NextResponse.json(
      { error: 'Failed to fetch artifact preview' },
      { status: 500 }
    );
  }
}
