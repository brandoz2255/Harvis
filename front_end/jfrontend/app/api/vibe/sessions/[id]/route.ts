import { NextRequest, NextResponse } from 'next/server'
import { AuthService } from '@/lib/auth/AuthService'
import pool from '@/lib/db'

export async function GET(request: NextRequest, { params }: { params: { id: string } }) {
  try {
    const user = await AuthService.getCurrentUser(request)
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const sessionId = params.id
    const client = await pool.connect()
    
    try {
      // Get session details
      const sessionResult = await client.query(`
        SELECT * FROM vibe_sessions 
        WHERE id = $1 AND user_id = $2 AND is_active = true
      `, [sessionId, user.id])

      if (sessionResult.rows.length === 0) {
        return NextResponse.json({ error: 'Session not found' }, { status: 404 })
      }

      const session = sessionResult.rows[0]

      // Get all files in the session
      const filesResult = await client.query(`
        SELECT * FROM vibe_files 
        WHERE session_id = $1 
        ORDER BY type DESC, name ASC
      `, [sessionId])

      // Get recent chat history
      const chatResult = await client.query(`
        SELECT * FROM vibe_chat 
        WHERE session_id = $1 
        ORDER BY created_at ASC
        LIMIT 50
      `, [sessionId])

      // Get recent executions
      const executionsResult = await client.query(`
        SELECT * FROM vibe_executions 
        WHERE session_id = $1 
        ORDER BY created_at DESC
        LIMIT 20
      `, [sessionId])

      return NextResponse.json({
        session,
        files: filesResult.rows,
        chat: chatResult.rows,
        executions: executionsResult.rows
      })
    } finally {
      client.release()
    }
  } catch (error) {
    console.error('Error fetching session details:', error)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}

export async function PUT(request: NextRequest, { params }: { params: { id: string } }) {
  try {
    const user = await AuthService.getCurrentUser(request)
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const sessionId = params.id
    const { name, description } = await request.json()

    const client = await pool.connect()
    try {
      const result = await client.query(`
        UPDATE vibe_sessions 
        SET name = $1, description = $2, updated_at = CURRENT_TIMESTAMP
        WHERE id = $3 AND user_id = $4
        RETURNING *
      `, [name, description, sessionId, user.id])

      if (result.rows.length === 0) {
        return NextResponse.json({ error: 'Session not found' }, { status: 404 })
      }

      return NextResponse.json({ session: result.rows[0] })
    } finally {
      client.release()
    }
  } catch (error) {
    console.error('Error updating session:', error)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}

export async function DELETE(request: NextRequest, { params }: { params: { id: string } }) {
  try {
    const user = await AuthService.getCurrentUser(request)
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const sessionId = params.id
    const client = await pool.connect()
    
    try {
      const result = await client.query(`
        UPDATE vibe_sessions 
        SET is_active = false, updated_at = CURRENT_TIMESTAMP
        WHERE id = $1 AND user_id = $2
        RETURNING *
      `, [sessionId, user.id])

      if (result.rows.length === 0) {
        return NextResponse.json({ error: 'Session not found' }, { status: 404 })
      }

      return NextResponse.json({ message: 'Session deleted successfully' })
    } finally {
      client.release()
    }
  } catch (error) {
    console.error('Error deleting session:', error)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}