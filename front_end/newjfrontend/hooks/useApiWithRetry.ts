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
            timeout = 3600000, // 1 hour default (increased from 5min)
            maxRetries = 0,
            retryDelay = 2000,
            lowVram = false
        } = apiOptions

        const controller = new AbortController()
        const timeoutId = setTimeout(() => controller.abort(),
            lowVram ? 3600000 : timeout)

        try {
            console.log(`🌐 Fetching ${url} with timeout ${timeout/1000}s`)

            const response = await fetch(url, {
                ...options,
                headers: {
                    ...options.headers,
                    'Connection': 'keep-alive',
                    'Keep-Alive': 'timeout=3600'
                },
                signal: controller.signal
            })

            clearTimeout(timeoutId)
            console.log(`✅ Fetch completed: ${url} - Status: ${response.status}`)

            if (!response.ok) {
                const errorText = await response.text()
                throw new Error(`HTTP ${response.status}: ${errorText}`)
            }

            // Check if this is an SSE stream (research-chat, mic-chat)
            const contentType = response.headers.get('content-type') || ''
            if (contentType.includes('text/event-stream')) {
                console.log('📡 Detected SSE stream, parsing events...')

                // Handle SSE stream - parse events and return final "complete" payload
                if (!response.body) {
                    throw new Error('ReadableStream not supported')
                }

                const reader = response.body.getReader()
                const decoder = new TextDecoder()
                let buffer = ''
                let finalResult: any = null
                let streamError: string | null = null

                try {
                    while (true) {
                        const { done, value } = await reader.read()
                        if (done) {
                            console.log('📡 SSE stream ended')
                            break
                        }

                        buffer += decoder.decode(value, { stream: true })
                        const lines = buffer.split('\n\n')
                        buffer = lines.pop() || ''

                        for (const line of lines) {
                            const trimmed = line.trim()
                            if (trimmed.startsWith('data: ')) {
                                const jsonStr = trimmed.slice(6)
                                try {
                                    const data = JSON.parse(jsonStr)
                                    console.log('📡 Stream status:', data.status, data.message || data.detail || '')

                                    if (data.status === 'error') {
                                        streamError = data.error || 'Unknown stream error'
                                    }

                                    if (data.status === 'complete') {
                                        console.log('✅ Stream complete, got final data')
                                        finalResult = data
                                    }
                                } catch (parseErr) {
                                    // Log but don't break on parse errors - might be partial chunk
                                    console.warn('⚠️ SSE parse warning (non-fatal):', jsonStr.slice(0, 100))
                                }
                            }
                        }
                    }
                } catch (streamReadError: any) {
                    console.error('❌ Error reading SSE stream:', streamReadError)
                    throw streamReadError
                }

                // Check for errors after stream completes
                if (streamError) {
                    console.error('❌ Stream reported error:', streamError)
                    throw new Error(streamError)
                }

                if (finalResult) {
                    console.log('✅ Returning SSE final result')
                    return finalResult
                }
                throw new Error('Stream ended without complete status')
            }

            // Standard JSON response
            console.log('📄 Parsing JSON response...')
            const jsonData = await response.json()
            console.log('✅ JSON parsed successfully')
            return jsonData
        } catch (error: any) {
            clearTimeout(timeoutId)

            console.error(`❌ Fetch error for ${url}:`, error)

            if (error.name === 'AbortError') {
                const timeoutMsg = `Request timeout after ${(timeout / 1000)}s`
                console.error(`⏰ ${timeoutMsg}`)
                throw new Error(timeoutMsg)
            }

            // Log network errors with more detail
            if (error.name === 'TypeError' && error.message.includes('NetworkError')) {
                console.error('🌐 Network error - possible causes: CORS, connection drop, or DNS issue')
            }

            if (maxRetries > 0 && error.name !== 'AbortError') {
                console.log(`🔄 Retrying request (${maxRetries} retries left)...`)
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
