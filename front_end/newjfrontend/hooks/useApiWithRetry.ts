import { useCallback } from 'react'

interface ApiOptions {
    timeout?: number
    maxRetries?: number
    retryDelay?: number
    lowVram?: boolean
}

export const useApiWithRetry = () => {
    const fetchWithRetry = useCallback(async (
        url: string,
        options: RequestInit & { body?: any },
        apiOptions: ApiOptions = {}
    ): Promise<any> => {
        const {
            timeout = 300000, // 5min default
            maxRetries = 0,
            retryDelay = 2000,
            lowVram = false
        } = apiOptions

        const controller = new AbortController()
        const timeoutId = setTimeout(() => controller.abort(),
            lowVram ? 3600000 : timeout)

        try {
            const response = await fetch(url, {
                ...options,
                headers: {
                    ...options.headers,
                    'Connection': 'keep-alive',
                    'Keep-Alive': 'timeout=600'
                },
                signal: controller.signal
            })

            clearTimeout(timeoutId)

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`)
            }

            // Check if this is an SSE stream (research-chat, mic-chat)
            const contentType = response.headers.get('content-type') || ''
            if (contentType.includes('text/event-stream')) {
                // Handle SSE stream - parse events and return final "complete" payload
                if (!response.body) {
                    throw new Error('ReadableStream not supported')
                }

                const reader = response.body.getReader()
                const decoder = new TextDecoder()
                let buffer = ''
                let finalResult: any = null
                let streamError: string | null = null

                while (true) {
                    const { done, value } = await reader.read()
                    if (done) break

                    buffer += decoder.decode(value, { stream: true })
                    const lines = buffer.split('\n\n')
                    buffer = lines.pop() || ''

                    for (const line of lines) {
                        const trimmed = line.trim()
                        if (trimmed.startsWith('data: ')) {
                            const jsonStr = trimmed.slice(6)
                            try {
                                const data = JSON.parse(jsonStr)
                                console.log('Stream status:', data.status, data.detail || '')

                                if (data.status === 'error') {
                                    streamError = data.error || 'Unknown stream error'
                                }

                                if (data.status === 'complete') {
                                    finalResult = data
                                }
                            } catch (parseErr) {
                                // Log but don't break on parse errors - might be partial chunk
                                console.warn('SSE parse warning (non-fatal):', jsonStr.slice(0, 100))
                            }
                        }
                    }
                }

                // Check for errors after stream completes
                if (streamError) {
                    throw new Error(streamError)
                }

                if (finalResult) {
                    return finalResult
                }
                throw new Error('Stream ended without complete status')
            }

            // Standard JSON response
            return await response.json()
        } catch (error: any) {
            clearTimeout(timeoutId)

            if (error.name === 'AbortError') {
                throw new Error(`Request timeout (${(timeout / 1000)}s)`)
            }

            if (maxRetries > 0 && error.name !== 'AbortError') {
                await new Promise(r => setTimeout(r, retryDelay))
                return fetchWithRetry(url, options, {
                    ...apiOptions,
                    maxRetries: maxRetries - 1
                })
            }

            throw error
        }
    }, [])

    return { fetchWithRetry }
}
