import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const BACKEND_URL = process.env.BACKEND_URL || 'http://backend:8000';

export async function GET(req: NextRequest) {
    try {
        const response = await fetch(`${BACKEND_URL}/api/models`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                // Forward auth token if present
                'Authorization': req.headers.get('Authorization') || '',
                'Cookie': req.headers.get('Cookie') || '',
            },
        });

        if (!response.ok) {
            throw new Error(`Backend returned ${response.status}`);
        }

        const data = await response.json();
        return NextResponse.json(data);
    } catch (error) {
        console.error('Error fetching models:', error);
        return NextResponse.json(
            { error: 'Failed to fetch models' },
            { status: 500 }
        );
    }
}
