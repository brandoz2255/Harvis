import { NextRequest, NextResponse } from 'next/server';
import { Pool } from 'pg';

const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
});

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(
  request: NextRequest,
  { params }: { params: { jobId: string } }
) {
  try {
    const { jobId } = params;
    
    // Set SSE headers
    const stream = new ReadableStream({
      async start(controller) {
        const encoder = new TextEncoder();
        
        // Send initial status
        const client = await pool.connect();
        
        try {
          // Get initial job status
          const result = await client.query(
            'SELECT status, result FROM document_jobs WHERE id = $1',
            [jobId]
          );
          
          if (result.rows.length === 0) {
            controller.enqueue(
              encoder.encode(`data: ${JSON.stringify({ type: 'error', message: 'Job not found' })}\n\n`)
            );
            controller.close();
            client.release();
            return;
          }
          
          const job = result.rows[0];
          
          // Send current status
          controller.enqueue(
            encoder.encode(`data: ${JSON.stringify({ 
              type: 'status', 
              status: job.status,
              result: job.result 
            })}\n\n`)
          );
          
          // If already completed or failed, close connection
          if (job.status === 'completed' || job.status === 'failed') {
            controller.enqueue(
              encoder.encode(`data: ${JSON.stringify({ 
                type: job.status === 'completed' ? 'job-complete' : 'job-failed',
                result: job.result,
                error: job.result?.error
              })}\n\n`)
            );
            controller.close();
            client.release();
            return;
          }
          
          // Listen for notifications on this job
          await client.query(`LISTEN job_status_${jobId}`);
          
          client.on('notification', (msg) => {
            try {
              const data = JSON.parse(msg.payload);
              
              if (data.status === 'completed') {
                controller.enqueue(
                  encoder.encode(`data: ${JSON.stringify({ 
                    type: 'job-complete',
                    result: data.result 
                  })}\n\n`)
                );
                controller.close();
                client.release();
              } else if (data.status === 'failed') {
                controller.enqueue(
                  encoder.encode(`data: ${JSON.stringify({ 
                    type: 'job-failed',
                    error: data.result?.error || 'Job failed' 
                  })}\n\n`)
                );
                controller.close();
                client.release();
              } else {
                // Status update (pending, processing)
                controller.enqueue(
                  encoder.encode(`data: ${JSON.stringify({ 
                    type: 'status',
                    status: data.status 
                  })}\n\n`)
                );
              }
            } catch (e) {
              console.error('Error processing notification:', e);
            }
          });
          
          // Heartbeat to keep connection alive (every 15 seconds)
          const heartbeat = setInterval(() => {
            if (controller.desiredSize !== null) {
              controller.enqueue(encoder.encode(': heartbeat\n\n'));
            }
          }, 15000);
          
          // Cleanup on disconnect
          request.signal.addEventListener('abort', () => {
            clearInterval(heartbeat);
            client.query(`UNLISTEN job_status_${jobId}`).catch(console.error);
            client.release();
            controller.close();
          });
          
        } catch (error) {
          console.error('SSE Error:', error);
          controller.enqueue(
            encoder.encode(`data: ${JSON.stringify({ type: 'error', message: 'Internal server error' })}\n\n`)
          );
          controller.close();
          client.release();
        }
      }
    });
    
    return new Response(stream, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
        'X-Accel-Buffering': 'no',  // Disable Nginx buffering for SSE
      },
    });
    
  } catch (error) {
    console.error('Error creating SSE stream:', error);
    return NextResponse.json(
      { error: 'Failed to create event stream' },
      { status: 500 }
    );
  }
}
