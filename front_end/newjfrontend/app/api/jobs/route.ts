import { NextRequest, NextResponse } from 'next/server';
import { Pool } from 'pg';
import { v4 as uuidv4 } from 'uuid';

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
});

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { 
      code, 
      documentType, 
      title, 
      sessionId, 
      userId,
      priority = 0 
    } = body;

    // Validate required fields
    if (!code || !documentType || !title) {
      return NextResponse.json(
        { error: 'Missing required fields: code, documentType, title' },
        { status: 400 }
      );
    }

    if (!userId) {
      return NextResponse.json(
        { error: 'Missing required field: userId' },
        { status: 400 }
      );
    }

    // Generate job ID
    const jobId = uuidv4();

    // Insert job into document_jobs table
    await pool.query(
      `INSERT INTO document_jobs (
        id, user_id, session_id, job_type, status, 
        payload, priority, created_at
      ) VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())`,
      [
        jobId,
        userId,
        sessionId || null,
        documentType,
        'pending',
        JSON.stringify({ code, title }),
        priority
      ]
    );

    // Also add to pg-boss queue for processing
    // This is done via the Python backend API
    const backendUrl = process.env.BACKEND_URL || 'http://backend:8000';
    
    try {
      const queueResponse = await fetch(`${backendUrl}/api/jobs/enqueue`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          name: 'generate-document',
          data: {
            document_job_id: jobId,
            code,
            document_type: documentType,
            title,
            user_id: userId,
            session_id: sessionId
          },
          retry_limit: 3,
          priority
        })
      });

      if (!queueResponse.ok) {
        console.error('Failed to enqueue job:', await queueResponse.text());
        // Don't fail the request - the job is in the DB and will be picked up by polling
      }
    } catch (queueError) {
      console.error('Error enqueuing job:', queueError);
      // Continue - job is in DB and will be processed
    }

    return NextResponse.json({ 
      jobId,
      status: 'pending',
      message: 'Job created successfully'
    });

  } catch (error) {
    console.error('Error creating job:', error);
    return NextResponse.json(
      { error: 'Failed to create job' },
      { status: 500 }
    );
  }
}

// Get job status
export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url);
    const jobId = searchParams.get('jobId');

    if (!jobId) {
      return NextResponse.json(
        { error: 'Missing jobId parameter' },
        { status: 400 }
      );
    }

    const result = await pool.query(
      'SELECT id, status, result, error, created_at, started_at, completed_at FROM document_jobs WHERE id = $1',
      [jobId]
    );

    if (result.rows.length === 0) {
      return NextResponse.json(
        { error: 'Job not found' },
        { status: 404 }
      );
    }

    const job = result.rows[0];
    
    return NextResponse.json({
      jobId: job.id,
      status: job.status,
      result: job.result,
      error: job.error,
      createdAt: job.created_at,
      startedAt: job.started_at,
      completedAt: job.completed_at
    });

  } catch (error) {
    console.error('Error getting job status:', error);
    return NextResponse.json(
      { error: 'Failed to get job status' },
      { status: 500 }
    );
  }
}
