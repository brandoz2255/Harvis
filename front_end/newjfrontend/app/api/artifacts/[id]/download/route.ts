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
    
    const response = await fetch(`${BACKEND_URL}/api/artifacts/${id}/download`, {
      method: 'GET',
      headers: {
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
        const errorData = await response.json().catch(() => ({ detail: 'Artifact not ready' }));
        return NextResponse.json(
          { error: errorData.detail || 'Artifact not ready' },
          { status: 400 }
        );
      }
      throw new Error(`Backend returned ${response.status}`);
    }

    // Get the file data as arrayBuffer
    const fileData = await response.arrayBuffer();
    
    // Get content type and filename from backend response headers
    const contentType = response.headers.get('content-type') || 'application/octet-stream';
    const contentDisposition = response.headers.get('content-disposition');
    
    // Create response with proper headers
    const nextResponse = new NextResponse(fileData, {
      status: 200,
      headers: {
        'Content-Type': contentType,
        'Content-Disposition': contentDisposition || 'attachment',
      },
    });

    return nextResponse;
  } catch (error) {
    console.error('Error downloading artifact:', error);
    return NextResponse.json(
      { error: 'Failed to download artifact' },
      { status: 500 }
    );
  }
}
