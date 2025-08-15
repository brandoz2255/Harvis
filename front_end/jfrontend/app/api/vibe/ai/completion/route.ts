import { NextRequest, NextResponse } from 'next/server'
import { AuthService } from '@/lib/auth/AuthService'

export async function POST(request: NextRequest) {
  try {
    const user = await AuthService.getCurrentUser(request)
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const { context, language, position, model = 'mistral' } = await request.json()

    if (!context || !language) {
      return NextResponse.json({ 
        error: 'Context and language are required' 
      }, { status: 400 })
    }

    // Send request to backend for AI code completion
    const backendUrl = process.env.BACKEND_URL || 'http://backend:8000'
    
    try {
      const response = await fetch(`${backendUrl}/api/vibe/code-completion`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          context,
          language,
          position,
          model,
          max_completions: 5
        }),
        signal: AbortSignal.timeout(15000), // 15 second timeout
      })

      if (!response.ok) {
        throw new Error(`Backend responded with status: ${response.status}`)
      }

      const data = await response.json()
      
      return NextResponse.json({
        completions: data.completions || [],
        model: data.model || model,
        language,
        cached: data.cached || false
      })

    } catch (backendError) {
      console.error('Backend completion error:', backendError)
      
      // Fallback: provide basic completions based on language
      const fallbackCompletions = getFallbackCompletions(context, language)
      
      return NextResponse.json({
        completions: fallbackCompletions,
        model: 'fallback',
        language,
        cached: false,
        warning: 'Backend unavailable, using fallback completions'
      })
    }

  } catch (error) {
    console.error('Error in code completion:', error)
    return NextResponse.json({ 
      error: 'Internal server error',
      completions: [] 
    }, { status: 500 })
  }
}

function getFallbackCompletions(context: string, language: string) {
  const lastLine = context.split('\n').pop() || ''
  const completions = []

  // Basic completions based on language and context
  switch (language) {
    case 'python':
      if (lastLine.includes('def ')) {
        completions.push({
          label: 'docstring',
          insertText: '"""${1:Description}\n    \n    Args:\n        ${2:arg}: ${3:description}\n    \n    Returns:\n        ${4:return_description}\n    """',
          documentation: 'Add a docstring to the function'
        })
      }
      if (lastLine.includes('import ') || lastLine.includes('from ')) {
        completions.push(
          { label: 'requests', insertText: 'requests', documentation: 'HTTP library' },
          { label: 'numpy', insertText: 'numpy as np', documentation: 'Numerical computing' },
          { label: 'pandas', insertText: 'pandas as pd', documentation: 'Data manipulation' }
        )
      }
      break

    case 'javascript':
    case 'typescript':
      if (lastLine.includes('console.')) {
        completions.push(
          { label: 'log', insertText: 'log(${1})', documentation: 'Log to console' },
          { label: 'error', insertText: 'error(${1})', documentation: 'Log error to console' },
          { label: 'warn', insertText: 'warn(${1})', documentation: 'Log warning to console' }
        )
      }
      if (lastLine.includes('function ')) {
        completions.push({
          label: 'async function',
          insertText: 'async function ${1:name}(${2:params}) {\n    ${3}\n}',
          documentation: 'Create an async function'
        })
      }
      break

    case 'html':
      if (lastLine.includes('<')) {
        completions.push(
          { label: 'div', insertText: 'div class="${1}">${2}</div>', documentation: 'Div element' },
          { label: 'span', insertText: 'span class="${1}">${2}</span>', documentation: 'Span element' },
          { label: 'p', insertText: 'p>${1}</p>', documentation: 'Paragraph element' }
        )
      }
      break

    case 'css':
      completions.push(
        { label: 'display', insertText: 'display: ${1|block,inline,flex,grid|};', documentation: 'Display property' },
        { label: 'color', insertText: 'color: ${1:#000000};', documentation: 'Text color' },
        { label: 'background', insertText: 'background: ${1:#ffffff};', documentation: 'Background color' }
      )
      break
  }

  // Add common programming constructs
  if (['python', 'javascript', 'typescript'].includes(language)) {
    if (lastLine.includes('if ') || lastLine.includes('elif ') || lastLine.includes('else')) {
      completions.push({
        label: 'try-catch',
        insertText: language === 'python' ? 'try:\n    ${1}\nexcept ${2:Exception} as e:\n    ${3}' : 'try {\n    ${1}\n} catch (${2:error}) {\n    ${3}\n}',
        documentation: 'Try-catch block'
      })
    }
  }

  return completions.slice(0, 5) // Limit to 5 completions
}