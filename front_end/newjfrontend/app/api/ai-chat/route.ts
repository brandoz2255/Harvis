import { NextRequest } from 'next/server';

/**
 * AI SDK Bridge Route
 *
 * This route bridges the Vercel AI SDK format to the Python backend format.
 * It transforms:
 *   AI SDK: { messages: [{role, content}], model }
 *   → Python: { message, history, model, text_only, ... }
 *
 * And streams the response back in AI SDK data stream format.
 *
 * The Python backend already handles <think>...</think> tags for reasoning.
 * This route preserves that reasoning and sends it via AI SDK's tool mechanism.
 */

// Use Node.js runtime to access Docker internal network
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// Retry configuration
const MAX_RETRIES = 3;
const RETRY_DELAY = 1000; // ms
const FETCH_TIMEOUT = 30000; // 30 seconds for initial connection

export async function POST(req: NextRequest) {
  // Default to K8s service name - works in both Docker Compose (with BACKEND_URL override) and K8s
  const BACKEND_URL = process.env['BACKEND_URL'] ?? 'http://harvis-ai-merged-backend:8000';

  try {
    const body = await req.json();
    const { messages, model, sessionId, textOnly = true, lowVram = false } = body;

    if (!messages || !Array.isArray(messages) || messages.length === 0) {
      return new Response(JSON.stringify({ error: 'No messages provided' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Get the last user message
    const lastMessage = messages[messages.length - 1];
    const messageContent = typeof lastMessage.content === 'string'
      ? lastMessage.content
      : lastMessage.content?.[0]?.text || '';

    // Build history from previous messages (excluding the last one)
    const history = messages.slice(0, -1).map((m: any) => ({
      role: m.role,
      content: typeof m.content === 'string' ? m.content : m.content?.[0]?.text || ''
    }));

    // Forward auth token
    const authHeader = req.headers.get('Authorization');
    const cookieHeader = req.headers.get('Cookie');

    // Use the session ID from the frontend store (UUID format) if provided
    // This ensures conversation continuity and proper history saving
    const validSessionId = sessionId && typeof sessionId === 'string' && sessionId.length >= 32
      ? sessionId
      : null;

    console.log(`[AI-Chat] Calling backend at ${BACKEND_URL} - model: ${model || 'mistral'}, session: ${validSessionId || 'new'}, message: ${messageContent.slice(0, 50)}...`);

    // Helper to return a stream with an error message
    const createErrorStreamResponse = (errorMessage: string, status: number = 500) => {
      const encoder = new TextEncoder();
      const stream = new ReadableStream({
        start(controller) {
          // Send error in AI SDK format: 3:"error message"\n
          const encodedError = JSON.stringify(errorMessage);
          controller.enqueue(encoder.encode(`3:${encodedError}\n`));
          controller.close();
        }
      });
      return new Response(stream, {
        status: 200, // Always return 200 so client stream reader starts
        headers: {
          'Content-Type': 'text/plain; charset=utf-8',
          'X-Vercel-AI-Data-Stream': 'v1',
          'Cache-Control': 'no-cache',
          'Connection': 'keep-alive',
        }
      });
    };

    // Helper function to fetch with timeout and retry logic
    const fetchWithRetry = async (retries = MAX_RETRIES): Promise<Response> => {
      let lastError: Error | null = null;
      
      for (let attempt = 1; attempt <= retries; attempt++) {
        try {
          console.log(`[AI-Chat] Fetch attempt ${attempt}/${retries} to ${BACKEND_URL}/api/chat`);
          
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT);
          
          const response = await fetch(`${BACKEND_URL}/api/chat`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...(authHeader && { 'Authorization': authHeader }),
              ...(cookieHeader && { 'Cookie': cookieHeader }),
            },
            body: JSON.stringify({
              message: messageContent,
              history: history,
              model: model || 'mistral',
              text_only: textOnly,
              low_vram: lowVram,
              session_id: validSessionId,
            }),
            signal: controller.signal,
          });
          
          clearTimeout(timeoutId);
          
          if (response.ok || response.status >= 400) {
            // Return response if successful OR if we got a valid HTTP error (not network error)
            return response;
          }
          
          // If response is not ok, throw to trigger retry
          throw new Error(`HTTP ${response.status}: ${response.statusText}`);
          
        } catch (error) {
          lastError = error as Error;
          console.warn(`[AI-Chat] Fetch attempt ${attempt} failed:`, error);
          
          if (attempt < retries) {
            console.log(`[AI-Chat] Retrying in ${RETRY_DELAY}ms...`);
            await new Promise(resolve => setTimeout(resolve, RETRY_DELAY));
          }
        }
      }
      
      throw lastError || new Error('All retry attempts failed');
    };

    // Call Python backend with SSE streaming and retry logic
    let backendResponse: Response;
    try {
      backendResponse = await fetchWithRetry();
    } catch (fetchError) {
      console.error('[AI-Chat] Fetch to backend failed after retries:', fetchError);
      return createErrorStreamResponse(`Failed to connect to backend after ${MAX_RETRIES} attempts: ${fetchError}`);
    }

    if (!backendResponse.ok) {
      const errorText = await backendResponse.text();
      console.error('[AI-Chat] Backend error:', backendResponse.status, errorText);
      return createErrorStreamResponse(`Backend error: ${backendResponse.status} - ${errorText}`);
    }

    if (!backendResponse.body) {
      console.error('[AI-Chat] Backend response has no body');
      return createErrorStreamResponse('Backend returned empty response');
    }

    // Create a readable stream that transforms SSE to AI SDK format
    const encoder = new TextEncoder();
    let fullText = '';
    let reasoning = '';
    let finalAnswer = '';
    let buffer = '';
    let assistantMessageCreated = false;
    let lastActivity = Date.now();
    const KEEPALIVE_INTERVAL = 15000; // Send keepalive every 15 seconds

    const stream = new ReadableStream({
      async start(controller) {
        const reader = backendResponse.body?.getReader();
        if (!reader) {
          console.error('[AI-Chat] Failed to get reader from backend response');
          controller.close();
          return;
        }

        const decoder = new TextDecoder();
        let isClosed = false;
        let chunkCount = 0;
        let keepaliveTimer: NodeJS.Timeout | null = null;

        // Safe enqueue that handles client disconnection gracefully
        const safeEnqueue = (data: Uint8Array): boolean => {
          if (isClosed) return false;
          try {
            controller.enqueue(data);
            lastActivity = Date.now();
            return true;
          } catch (e) {
            isClosed = true;
            console.debug('[AI-Chat] Client disconnected, stopping stream');
            return false;
          }
        };

        // Safe close that only closes once
        const safeClose = () => {
          if (!isClosed) {
            isClosed = true;
            if (keepaliveTimer) {
              clearInterval(keepaliveTimer);
              keepaliveTimer = null;
            }
            try {
              controller.close();
              console.log(`[AI-Chat] Stream closed. Processed ${chunkCount} chunks. Full text length: ${fullText.length}`);
            } catch (e) {
              // Already closed, ignore
            }
          }
        };

        // Start keepalive timer to prevent connection timeout
        keepaliveTimer = setInterval(() => {
          if (isClosed) {
            if (keepaliveTimer) {
              clearInterval(keepaliveTimer);
              keepaliveTimer = null;
            }
            return;
          }
          
          const timeSinceLastActivity = Date.now() - lastActivity;
          if (timeSinceLastActivity >= KEEPALIVE_INTERVAL) {
            // Send empty text chunk as keepalive (0: prefix for AI SDK data protocol)
            try {
              safeEnqueue(encoder.encode(`0:""\n`));
            } catch (e) {
              // Connection likely closed
            }
          }
        }, 5000); // Check every 5 seconds

        try {
          while (true) {
            if (isClosed) break;

            const { done, value } = await reader.read();
            if (done) {
              console.log('[AI-Chat] Backend stream done');
              break;
            }

            chunkCount++;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || ''; // Keep incomplete line in buffer

            for (const line of lines) {
              if (isClosed) break;
              
              // Skip empty lines, comments (keepalive), and malformed lines
              const trimmedLine = line.trim();
              if (!trimmedLine || trimmedLine.startsWith(':')) {
                continue;
              }
              
              // Only process valid SSE data lines
              if (!trimmedLine.startsWith('data: ')) {
                // Log any non-data lines that aren't keepalive comments for debugging
                if (!trimmedLine.startsWith(':')) {
                  console.warn('[AI-Chat] Skipping unexpected line:', trimmedLine.slice(0, 100));
                }
                continue;
              }

              try {
                const jsonStr = trimmedLine.slice(6).trim();
                if (!jsonStr) continue;

                let data;
                try {
                  data = JSON.parse(jsonStr);
                } catch (jsonError) {
                  console.warn('[AI-Chat] Skipping malformed JSON:', jsonStr.slice(0, 100));
                  continue;
                }

                if (data.status === 'streaming' && data.content) {
                  // Stream text chunk in AI SDK format
                  // Sanitize content to prevent newlines from breaking the stream protocol
                  const sanitizedContent = data.content.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
                  fullText += sanitizedContent;
                  assistantMessageCreated = true;
                  const encodedContent = JSON.stringify(sanitizedContent);
                  if (!safeEnqueue(encoder.encode(`0:${encodedContent}\n`))) break;
                }
                else if (data.status === 'generating_audio' || data.status === 'processing') {
                  // Send status update as custom data (2: prefix) to keep connection alive
                  const statusData = {
                    type: 'status_update',
                    status: data.status,
                    detail: data.detail || data.message || ''
                  };
                  if (!safeEnqueue(encoder.encode(`2:${JSON.stringify([statusData])}\n`))) break;
                }
                else if (data.status === 'researching') {
                  // CRITICAL FIX: For auto-research mode, just log research progress
                  // Don't send through AI SDK stream to avoid parsing errors
                  // The research chain UI will be updated separately via the complete event
                  console.log('[AI-Chat] Auto-research progress (buffered):', data.detail || data.type);
                  
                  // Create assistant message on first research event if needed
                  if (!assistantMessageCreated) {
                    console.log('[AI-Chat] Creating assistant message placeholder for auto-research');
                    if (!safeEnqueue(encoder.encode(`0:" "\n`))) break;
                    assistantMessageCreated = true;
                  }
                  
                  // NOTE: Research chain events are NOT sent through AI SDK stream
                  // They will be included in the final response with the complete event
                }
                else if (data.status === 'complete') {
                  // Capture reasoning, final answer, and audio path
                  reasoning = data.reasoning || '';
                  finalAnswer = data.final_answer || fullText;

                  console.log(`[AI-Chat] Complete event. fullText len: ${fullText.length}, finalAnswer len: ${finalAnswer?.length}`);

                  // CRITICAL FIX: If we haven't streamed any meaningful text yet
                  const contentToSend = finalAnswer || data.response;

                  if ((!fullText || fullText.trim().length === 0) && contentToSend) {
                    console.log(`[AI-Chat] Streaming full content from COMPLETE event (${contentToSend.length} chars)`);

                    // CRITICAL: Send entire content as a single chunk to avoid streaming issues
                    // The AI SDK can handle the full content at once, and this prevents
                    // issues with newline boundaries when chunking
                    const encodedContent = JSON.stringify(contentToSend);
                    console.log(`[AI-Chat] Sending content with 0: prefix, length: ${encodedContent.length}`);
                    if (!safeEnqueue(encoder.encode(`0:${encodedContent}\n`))) break;
                    fullText = contentToSend;
                    console.log(`[AI-Chat] Content sent successfully`);
                  }

                  const audioPath = data.audio_path || null;

                  // If we have reasoning, send it via data stream (2: prefix)
                  if (reasoning) {
                    const steps = reasoning.split('\n').filter((s: string) => s.trim());
                    const reasoningData = {
                      type: 'reasoning',
                      steps,
                      finalAnswer
                    };
                    if (!safeEnqueue(encoder.encode(`2:${JSON.stringify([reasoningData])}\n`))) break;
                  }

                  // Send sources if present (for auto-research mode)
                  if (data.sources || data.search_results) {
                    const searchData = {
                      type: 'search_results',
                      results: data.sources || data.search_results,
                      isAutoResearch: data.auto_researched || false
                    };
                    console.log(`[AI-Chat] Sending ${searchData.results?.length || 0} sources from complete event`);
                    if (!safeEnqueue(encoder.encode(`2:${JSON.stringify([searchData])}\n`))) break;
                  }

                  // Send videos if present (for auto-research mode)
                  if (data.videos) {
                    const videoData = {
                      type: 'videos',
                      videos: data.videos
                    };
                    if (!safeEnqueue(encoder.encode(`2:${JSON.stringify([videoData])}\n`))) break;
                  }

                  // Send audio path and session info
                  if (audioPath || data.session_id) {
                    const customData = {
                      audioPath: audioPath,
                      sessionId: data.session_id,
                    };
                    if (!safeEnqueue(encoder.encode(`2:${JSON.stringify([customData])}\n`))) break;
                  }

                  // Finish event (e: prefix) - required before d: finish data
                  const finishEvent = {
                    finishReason: 'stop',
                    usage: { promptTokens: 0, completionTokens: 0 },
                    isContinued: false
                  };
                  if (!safeEnqueue(encoder.encode(`e:${JSON.stringify(finishEvent)}\n`))) break;

                  // Finish data (d: prefix)
                  const finishData = {
                    finishReason: 'stop',
                    usage: { promptTokens: 0, completionTokens: 0 }
                  };
                  if (!safeEnqueue(encoder.encode(`d:${JSON.stringify(finishData)}\n`))) break;
                }
                else if (data.status === 'error') {
                  // Error (3: prefix)
                  if (!safeEnqueue(encoder.encode(`3:${JSON.stringify(data.error || 'Unknown error')}\n`))) break;
                }
              } catch (parseError) {
                if (parseError instanceof SyntaxError) {
                  console.debug('[AI-Chat] JSON parse error (likely partial chunk)');
                }
              }
            }
          }

          // If no complete message was received but we have text, send content and finish
          if (fullText && !finalAnswer && !isClosed) {
            console.log('[AI-Chat] Sending content and finish for incomplete stream');
            
            // Send the content we collected
            const encodedContent = JSON.stringify(fullText);
            safeEnqueue(encoder.encode(`0:${encodedContent}\n`));
            
            const finishEvent = {
              finishReason: 'stop',
              usage: { promptTokens: 0, completionTokens: 0 },
              isContinued: false
            };
            safeEnqueue(encoder.encode(`e:${JSON.stringify(finishEvent)}\n`));

            const finishData = {
              finishReason: 'stop',
              usage: { promptTokens: 0, completionTokens: 0 }
            };
            safeEnqueue(encoder.encode(`d:${JSON.stringify(finishData)}\n`));
          }

        } catch (e) {
          console.error('[AI-Chat] Stream error:', e);
          if (!isClosed) {
            safeEnqueue(encoder.encode(`3:${JSON.stringify('Stream error: ' + String(e))}\n`));
          }
        } finally {
          if (keepaliveTimer) {
            clearInterval(keepaliveTimer);
            keepaliveTimer = null;
          }
          safeClose();
        }
      }
    });

    // Return AI SDK formatted stream
    return new Response(stream, {
      headers: {
        'Content-Type': 'text/plain; charset=utf-8',
        'X-Vercel-AI-Data-Stream': 'v1',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      },
    });

  } catch (error) {
    console.error('[AI-Chat] Route error:', error);
    // CRITICAL: Always return a stream response, never JSON
    const encoder = new TextEncoder();
    const errorMessage = error instanceof Error ? error.message : 'Internal server error';
    const stream = new ReadableStream({
      start(controller) {
        const encodedError = JSON.stringify(errorMessage);
        controller.enqueue(encoder.encode(`3:${encodedError}\n`));
        controller.close();
      }
    });
    return new Response(stream, {
      status: 200,
      headers: {
        'Content-Type': 'text/plain; charset=utf-8',
        'X-Vercel-AI-Data-Stream': 'v1',
        'Cache-Control': 'no-cache',
        'Connection': 'keep-alive',
      }
    });
  }
}
