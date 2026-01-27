import { NextRequest, NextResponse } from 'next/server'
import { AuthService } from '@/lib/auth/AuthService'
import pool from '@/lib/db'
import archiver from 'archiver'
import { Readable } from 'stream'

export async function GET(request: NextRequest) {
  try {
    const user = await AuthService.getCurrentUser(request)
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const { searchParams } = new URL(request.url)
    const fileId = searchParams.get('fileId')
    const sessionId = searchParams.get('sessionId')
    const type = searchParams.get('type') || 'file'

    if (!fileId && !sessionId) {
      return NextResponse.json({ error: 'File ID or Session ID is required' }, { status: 400 })
    }

    const client = await pool.connect()
    try {
      if (type === 'session' && sessionId) {
        // Download entire session as ZIP
        return await downloadSessionAsZip(client, sessionId, user.id)
      } else if (fileId) {
        // Download single file or folder
        return await downloadFileOrFolder(client, fileId, user.id)
      } else {
        return NextResponse.json({ error: 'Invalid download request' }, { status: 400 })
      }
    } finally {
      client.release()
    }
  } catch (error) {
    console.error('Error in download:', error)
    return NextResponse.json({ error: 'Download failed' }, { status: 500 })
  }
}

async function downloadFileOrFolder(client: any, fileId: string, userId: string) {
  // Check if user owns this file
  const fileResult = await client.query(`
    SELECT vf.*, vs.user_id, vs.name as session_name
    FROM vibe_files vf
    JOIN vibe_sessions vs ON vf.session_id = vs.id
    WHERE vf.id = $1 AND vs.user_id = $2 AND vs.is_active = true
  `, [fileId, userId])

  if (fileResult.rows.length === 0) {
    return NextResponse.json({ error: 'File not found or access denied' }, { status: 404 })
  }

  const file = fileResult.rows[0]

  if (file.type === 'file') {
    // Download single file
    const content = file.content || ''
    const filename = file.name
    const mimeType = getMimeType(filename)

    return new NextResponse(content, {
      headers: {
        'Content-Type': mimeType,
        'Content-Disposition': `attachment; filename="${filename}"`,
        'Content-Length': Buffer.byteLength(content, 'utf8').toString()
      }
    })
  } else {
    // Download folder as ZIP
    return await downloadFolderAsZip(client, file)
  }
}

async function downloadFolderAsZip(client: any, folder: any) {
  // Get all files in this folder and subfolders
  const filesResult = await client.query(`
    SELECT * FROM vibe_files 
    WHERE session_id = $1 AND (path = $2 OR path LIKE $3) AND type = 'file'
    ORDER BY path
  `, [folder.session_id, folder.path, `${folder.path}/%`])

  const files = filesResult.rows

  if (files.length === 0) {
    return NextResponse.json({ error: 'No files found in folder' }, { status: 404 })
  }

  // Create ZIP archive
  const archive = archiver('zip', { zlib: { level: 9 } })
  const chunks: Buffer[] = []

  return new Promise((resolve, reject) => {
    archive.on('data', (chunk) => chunks.push(chunk))
    archive.on('end', () => {
      const zipBuffer = Buffer.concat(chunks)
      resolve(new NextResponse(zipBuffer, {
        headers: {
          'Content-Type': 'application/zip',
          'Content-Disposition': `attachment; filename="${folder.name}.zip"`,
          'Content-Length': zipBuffer.length.toString()
        }
      }))
    })
    archive.on('error', reject)

    // Add files to archive
    files.forEach((file: any) => {
      const relativePath = file.path.startsWith(folder.path + '/') 
        ? file.path.substring(folder.path.length + 1)
        : file.name
      
      archive.append(file.content || '', { name: relativePath })
    })

    archive.finalize()
  })
}

async function downloadSessionAsZip(client: any, sessionId: string, userId: string) {
  // Check if user owns this session
  const sessionResult = await client.query(`
    SELECT * FROM vibe_sessions 
    WHERE id = $1 AND user_id = $2 AND is_active = true
  `, [sessionId, userId])

  if (sessionResult.rows.length === 0) {
    return NextResponse.json({ error: 'Session not found or access denied' }, { status: 404 })
  }

  const session = sessionResult.rows[0]

  // Get all files in the session
  const filesResult = await client.query(`
    SELECT * FROM vibe_files 
    WHERE session_id = $1 AND type = 'file'
    ORDER BY path
  `, [sessionId])

  const files = filesResult.rows

  if (files.length === 0) {
    return NextResponse.json({ error: 'No files found in session' }, { status: 404 })
  }

  // Create ZIP archive
  const archive = archiver('zip', { zlib: { level: 9 } })
  const chunks: Buffer[] = []

  return new Promise((resolve, reject) => {
    archive.on('data', (chunk) => chunks.push(chunk))
    archive.on('end', () => {
      const zipBuffer = Buffer.concat(chunks)
      resolve(new NextResponse(zipBuffer, {
        headers: {
          'Content-Type': 'application/zip',
          'Content-Disposition': `attachment; filename="${session.name.replace(/[^a-zA-Z0-9]/g, '_')}.zip"`,
          'Content-Length': zipBuffer.length.toString()
        }
      }))
    })
    archive.on('error', reject)

    // Add session info file
    const sessionInfo = `# ${session.name}

${session.description || ''}

Created: ${session.created_at}
Last Updated: ${session.updated_at}
Files: ${files.length}

## Files in this session:
${files.map((f: any) => `- ${f.path}`).join('\n')}
`
    archive.append(sessionInfo, { name: 'SESSION_INFO.md' })

    // Add all files to archive
    files.forEach((file: any) => {
      archive.append(file.content || '', { name: file.path })
    })

    archive.finalize()
  })
}

function getMimeType(filename: string): string {
  const ext = filename.split('.').pop()?.toLowerCase()
  const mimeTypes: { [key: string]: string } = {
    'txt': 'text/plain',
    'md': 'text/markdown',
    'py': 'text/x-python',
    'js': 'application/javascript',
    'ts': 'application/typescript',
    'jsx': 'text/jsx',
    'tsx': 'text/tsx',
    'html': 'text/html',
    'css': 'text/css',
    'json': 'application/json',
    'xml': 'application/xml',
    'yml': 'application/x-yaml',
    'yaml': 'application/x-yaml',
    'sql': 'application/sql',
    'sh': 'application/x-sh',
    'cpp': 'text/x-c++src',
    'c': 'text/x-csrc',
    'java': 'text/x-java-source',
    'rs': 'text/x-rust',
    'go': 'text/x-go'
  }
  return mimeTypes[ext || ''] || 'text/plain'
}