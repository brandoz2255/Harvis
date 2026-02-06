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

    // Call Python backend with SSE streaming
    let backendResponse;
    try {
      backendResponse = await fetch(`${BACKEND_URL}/api/chat`, {
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
          text_only: textOnly,  // Pass through from frontend (default true if not specified)
          low_vram: lowVram,    // Pass through from frontend
          session_id: validSessionId,
        }),
      });
    } catch (fetchError) {
      console.error('[AI-Chat] Fetch to backend failed:', fetchError);
      return new Response(JSON.stringify({ error: `Failed to connect to backend: ${fetchError}` }), {
        status: 503,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    if (!backendResponse.ok) {
      const errorText = await backendResponse.text();
      console.error('[AI-Chat] Backend error:', backendResponse.status, errorText);
      return new Response(JSON.stringify({ error: `Backend error: ${backendResponse.status} - ${errorText}` }), {
        status: backendResponse.status,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    if (!backendResponse.body) {
      console.error('[AI-Chat] Backend response has no body');
      return new Response(JSON.stringify({ error: 'Backend returned empty response' }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' }
      });
    }

    // Create a readable stream that transforms SSE to AI SDK format
    const encoder = new TextEncoder();
    let fullText = '';
    let reasoning = '';
    let finalAnswer = '';
    let buffer = '';

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

        // Safe enqueue that handles client disconnection gracefully
        const safeEnqueue = (data: Uint8Array): boolean => {
          if (isClosed) return false;
          try {
            // Debug: log what we're sending
            const textData = new TextDecoder().decode(data);
            console.log(`[AI-Chat] Enqueuing (${data.length} bytes):`, textData.slice(0, 200));
            controller.enqueue(data);
            return true;
          } catch (e) {
            // Controller was closed (client disconnected)
            isClosed = true;
            console.debug('[AI-Chat] Client disconnected, stopping stream');
            return false;
          }
        };

        // Safe close that only closes once
        const safeClose = () => {
          if (!isClosed) {
            isClosed = true;
            try {
              controller.close();
              console.log(`[AI-Chat] Stream closed. Processed ${chunkCount} chunks. Full text length: ${fullText.length}`);
            } catch (e) {
              // Already closed, ignore
            }
          }
        };

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
              if (!line.startsWith('data: ')) continue;

              try {
                const jsonStr = line.slice(6).trim();
                if (!jsonStr) continue;

                let data;
                try {
                  data = JSON.parse(jsonStr);
                  // Debug logging to see what we receive
                  console.log(`[AI-Chat] Received event: status=${data.status}, has_content=${!!data.content}, has_final=${!!data.final_answer}, content_len=${data.content?.length}, final_len=${data.final_answer?.length}`);
                } catch (jsonError) {
                  console.warn('[AI-Chat] Skipping malformed JSON:', jsonStr.slice(0, 100));
                  continue;
                }

                if (data.status === 'streaming' && data.content) {
                  // Stream text chunk in AI SDK format
                  // Format: 0:"text"\n (text part)
                  fullText += data.content;
                  // Ensure content is properly escaped for AI SDK
                  const encodedContent = JSON.stringify(data.content);
                  safeEnqueue(encoder.encode(`0:${encodedContent}\n`));
                }
                else if (data.status === 'generating_audio' || data.status === 'processing' || data.status === 'researching') {
                  // Send status update as custom data (2: prefix) to keep connection alive
                  // and inform frontend of current state
                  const statusData = {
                    type: 'status_update',
                    status: data.status,
                    detail: data.detail || data.message || ''
                  };
                  safeEnqueue(encoder.encode(`2:${JSON.stringify([statusData])}\n`));
                }
                // IMPORTANT: Check for 'complete' status BEFORE checking sources/videos
                // because the complete event can contain all of these fields together.
                // The else-if chain was causing the complete handler to be skipped when
                // sources were present in the response!
                else if (data.status === 'complete') {
                  // Capture reasoning, final answer, and audio path
                  reasoning = data.reasoning || '';
                  finalAnswer = data.final_answer || fullText;

                  console.log(`[AI-Chat] Complete event. fullText len: ${fullText.length}, finalAnswer len: ${finalAnswer?.length}`);

                  // CRITICAL FIX: If we haven't streamed any meaningful text yet (or just whitespace),
                  // but we have a final answer (OR response), stream it now. This happens in Research Mode
                  // where the backend often returns the whole answer in the 'complete' event without streaming tokens.
                  const contentToSend = finalAnswer || data.response;

                  if ((!fullText || fullText.trim().length === 0) && contentToSend) {
                    console.log(`[AI-Chat] Streaming full content from COMPLETE event (${contentToSend.length} chars)`);
                    const encodedContent = JSON.stringify(contentToSend);
                    safeEnqueue(encoder.encode(`0:${encodedContent}\n`));
                    fullText = contentToSend; // Update fullText to reflect that we sent it
                  } else {
                    if (!contentToSend) console.log('[AI-Chat] No content to send in complete event');
                    else console.log('[AI-Chat] Already streamed content, not sending full text again');
                  }

                  const audioPath = data.audio_path || null;

                  // If we have reasoning, send it as a tool invocation
                  if (reasoning) {
                    const steps = reasoning.split('\n').filter((s: string) => s.trim());
                    const toolCallId = `reasoning-${Date.now()}`;

                    // Tool call (9: prefix)
                    const toolCall = {
                      toolCallId,
                      toolName: 'reasoning',
                      args: { steps, finalAnswer }
                    };
                    safeEnqueue(encoder.encode(`9:${JSON.stringify(toolCall)}\n`));

                    // Tool result (a: prefix)
                    const toolResult = {
                      toolCallId,
                      result: { reasoning: { steps, conclusion: finalAnswer } }
                    };
                    safeEnqueue(encoder.encode(`a:${JSON.stringify(toolResult)}\n`));
                  }

                  // Send sources if present (for auto-research mode)
                  if (data.sources || data.search_results) {
                    const searchData = {
                      type: 'search_results',
                      results: data.sources || data.search_results
                    };
                    safeEnqueue(encoder.encode(`2:${JSON.stringify([searchData])}\n`));
                  }

                  // Send videos if present (for auto-research mode)
                  if (data.videos) {
                    const videoData = {
                      type: 'videos',
                      videos: data.videos
                    };
                    safeEnqueue(encoder.encode(`2:${JSON.stringify([videoData])}\n`));
                  }

                  // Send audio path and session info as custom data (2: prefix)
                  if (audioPath || data.session_id) {
                    const customData = {
                      audioPath: audioPath,
                      sessionId: data.session_id,
                    };
                    safeEnqueue(encoder.encode(`2:${JSON.stringify([customData])}\n`));
                  }

                  // Finish message (d: prefix)
                  const finishData = {
                    finishReason: 'stop',
                    usage: { promptTokens: 0, completionTokens: 0 }
                  };
                  safeEnqueue(encoder.encode(`d:${JSON.stringify(finishData)}\n`));
                }
                else if (data.status === 'error') {
                  // Error (3: prefix)
                  safeEnqueue(encoder.encode(`3:${JSON.stringify(data.error || 'Unknown error')}\n`));
                }
                // Ignore other statuses like 'starting', 'processing', etc.
              } catch (parseError) {
                // Only log actual JSON parse errors, not controller close errors
                if (parseError instanceof SyntaxError) {
                  console.debug('[AI-Chat] JSON parse error (likely partial chunk)');
                }
              }
            }
          }

          // If no complete message was received but we have text, send finish
          if (fullText && !finalAnswer && !isClosed) {
            const finishData = {
              finishReason: 'stop',
              usage: { promptTokens: 0, completionTokens: 0 }
            };
            safeEnqueue(encoder.encode(`d:${JSON.stringify(finishData)}\n`));
          }

        } catch (e) {
          console.error('[AI-Chat] Stream error:', e);
          safeEnqueue(encoder.encode(`3:${JSON.stringify('Stream error: ' + String(e))}\n`));
        } finally {
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
    return new Response(JSON.stringify({ error: 'Internal server error' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}
