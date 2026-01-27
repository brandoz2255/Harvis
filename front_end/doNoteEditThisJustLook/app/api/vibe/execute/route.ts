import { NextRequest, NextResponse } from 'next/server'
import { AuthService } from '@/lib/auth/AuthService'
import pool from '@/lib/db'

export async function POST(request: NextRequest) {
  try {
    const user = await AuthService.getCurrentUser(request)
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const authHeader = request.headers.get('authorization')
    if (!authHeader) {
      return NextResponse.json({ error: 'No authorization header' }, { status: 401 })
    }

    const { sessionId, code, language = 'python', filename } = await request.json()

    if (!sessionId || !code) {
      return NextResponse.json({ 
        error: 'Session ID and code are required' 
      }, { status: 400 })
    }

    // Send execution request to backend with proper authentication
    const backendUrl = process.env.BACKEND_URL || 'http://backend:8000'
    
    const response = await fetch(`${backendUrl}/api/vibe/execute`, {
      method: 'POST',
      headers: {
        'Authorization': authHeader,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        session_id: sessionId,
        code,
        language,
        filename: filename || `temp.${getFileExtension(language)}`,
        timeout: 30 // 30 second timeout
      }),
      signal: AbortSignal.timeout(35000), // 35 second timeout for the request
    })

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ detail: 'Backend execution failed' }))
      return NextResponse.json({ 
        error: errorData.detail || 'Code execution failed',
        output: '',
        exitCode: 1
      }, { status: response.status })
    }

    const result = await response.json()
    
    return NextResponse.json({
      output: result.output || '',
      exitCode: result.exit_code || 0,
      executionTime: result.execution_time || 0,
      language,
      success: (result.exit_code || 0) === 0,
      execution_id: result.execution_id,
      container_id: result.container_id
    })

  } catch (error) {
    console.error('Error in code execution:', error)
    
    if (error instanceof Error && error.name === 'AbortError') {
      return NextResponse.json({ 
        error: 'Execution timeout - code took too long to run',
        output: '',
        exitCode: 124 // Timeout exit code
      }, { status: 408 })
    }

    // Fallback execution for simple cases (mainly for offline development)
    try {
      const { code, language } = await request.json()
      const fallbackResult = getFallbackExecution(code, language)
      return NextResponse.json(fallbackResult)
    } catch (fallbackError) {
      return NextResponse.json({ 
        error: 'Execution service unavailable',
        output: '',
        exitCode: 1
      }, { status: 503 })
    }
  }
}

function getFileExtension(language: string): string {
  const extMap: { [key: string]: string } = {
    'python': 'py',
    'javascript': 'js',
    'typescript': 'ts',
    'java': 'java',
    'cpp': 'cpp',
    'c': 'c',
    'rust': 'rs',
    'go': 'go',
    'shell': 'sh',
    'bash': 'sh'
  }
  return extMap[language] || 'txt'
}

function getFallbackExecution(code: string, language: string) {
  // Very basic fallback for development/offline use
  // This is NOT a real execution, just a simulation
  
  let output = `[SIMULATED ${language.toUpperCase()} EXECUTION]\n`
  let exitCode = 0
  
  try {
    if (language === 'python') {
      if (code.includes('print(')) {
        const printMatches = code.match(/print\((.*?)\)/g)
        if (printMatches) {
          printMatches.forEach(match => {
            const content = match.replace(/print\(|\)/g, '').replace(/['"]/g, '')
            output += `${content}\n`
          })
        }
      }
      
      if (code.includes('error') || code.includes('raise')) {
        output += 'Error: Simulated error in code\n'
        exitCode = 1
      }
      
      if (code.includes('import ')) {
        output += 'Successfully imported modules\n'
      }
    }
    
    if (language === 'javascript') {
      if (code.includes('console.log(')) {
        const logMatches = code.match(/console\.log\((.*?)\)/g)
        if (logMatches) {
          logMatches.forEach(match => {
            const content = match.replace(/console\.log\(|\)/g, '').replace(/['"]/g, '')
            output += `${content}\n`
          })
        }
      }
      
      if (code.includes('throw ') || code.includes('Error(')) {
        output += 'Error: Simulated error in code\n'
        exitCode = 1
      }
    }
    
    if (output === `[SIMULATED ${language.toUpperCase()} EXECUTION]\n`) {
      output += 'Code executed successfully (no output)\n'
    }
    
  } catch (error) {
    output += `Simulation error: ${error}\n`
    exitCode = 1
  }
  
  return {
    output,
    exitCode,
    executionTime: Math.floor(Math.random() * 1000), // Random execution time
    language,
    success: exitCode === 0,
    warning: 'This is a simulated execution - backend unavailable'
  }
}