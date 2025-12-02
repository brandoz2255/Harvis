"use client"

export interface PollOptions {
  fn: () => Promise<any>
  isDone: (result: any) => boolean
  timeoutMs?: number
  intervalMs?: number
  onProgress?: (result: any) => void
}

export async function pollUntil<T>({
  fn,
  isDone,
  timeoutMs = 30000,
  intervalMs = 1000,
  onProgress
}: PollOptions): Promise<T> {
  const startTime = Date.now()
  
  while (Date.now() - startTime < timeoutMs) {
    try {
      const result = await fn()
      
      if (onProgress) {
        onProgress(result)
      }
      
      if (isDone(result)) {
        return result
      }
      
      // Wait before next poll
      await new Promise(resolve => setTimeout(resolve, intervalMs))
    } catch (error) {
      console.warn('Poll attempt failed:', error)
      // Continue polling on error, but wait a bit longer
      await new Promise(resolve => setTimeout(resolve, intervalMs * 2))
    }
  }
  
  throw new Error(`Polling timed out after ${timeoutMs}ms`)
}

export function createCancellablePoll<T>(options: PollOptions) {
  let cancelled = false
  
  const cancel = () => {
    cancelled = true
  }
  
  const poll = async (): Promise<T> => {
    const startTime = Date.now()
    const { fn, isDone, timeoutMs = 30000, intervalMs = 1000, onProgress } = options
    
    while (!cancelled && Date.now() - startTime < timeoutMs) {
      try {
        const result = await fn()
        
        if (onProgress) {
          onProgress(result)
        }
        
        if (isDone(result)) {
          return result
        }
        
        // Wait before next poll
        await new Promise(resolve => setTimeout(resolve, intervalMs))
      } catch (error) {
        if (cancelled) {
          throw new Error('Polling cancelled')
        }
        console.warn('Poll attempt failed:', error)
        await new Promise(resolve => setTimeout(resolve, intervalMs * 2))
      }
    }
    
    if (cancelled) {
      throw new Error('Polling cancelled')
    }
    
    throw new Error(`Polling timed out after ${timeoutMs}ms`)
  }
  
  return { poll, cancel }
}
