import { createOpenAI } from '@ai-sdk/openai';
import { streamText, tool } from 'ai';
import { z } from 'zod';

export async function POST(req: Request) {
    try {
        const { messages, model } = await req.json();

        // Use K8s DNS URL from env or fallback to localhost, enabling OpenAI compatibility
        // Prioritize runtime env var (OLLAMA_URL), then build-time (NEXT_PUBLIC_), then K8s service default
        const ollamaBaseUrl = process.env.OLLAMA_URL || process.env.NEXT_PUBLIC_OLLAMA_URL || 'http://harvis-ai-merged-backend:11434';
        const baseURL = `${ollamaBaseUrl.replace(/\/$/, '')}/v1`;

        const ollama = createOpenAI({
            baseURL,
            apiKey: 'ollama', // Required but unused for local Ollama
        });

        const defaultModel = process.env.DEFAULT_MODEL || 'llama3.2';

        const result = await streamText({
            model: ollama(model || defaultModel), // Dynamic model selection
            system: 'Think step-by-step. Use the reasoning tool to explain your thought process before giving the final answer.',
            tools: {
                reasoning: tool({
                    description: 'Output your step-by-step reasoning',
                    parameters: z.object({
                        steps: z.array(z.string()).describe('The logical steps taken to reach the conclusion'),
                        finalAnswer: z.string().describe('The concise final answer to the user\'s question'),
                    }),
                    // @ts-ignore
                    execute: async ({ steps, finalAnswer }: { steps: string[]; finalAnswer: string }) => {
                        // This function is called if the model calls the tool.
                        // In a streaming context, the tool call itself is streamed to the client.
                        return { reasoning: { steps, conclusion: finalAnswer } };
                    },
                }),
            },
            messages,
        });

        // @ts-ignore
        return result.toDataStreamResponse();
    } catch (error) {
        console.error('[Chat Route] Error:', error);
        // CRITICAL: Return a stream response, not JSON, to prevent AI SDK "Error in input stream"
        const encoder = new TextEncoder();
        const errorMessage = error instanceof Error ? error.message : 'Internal server error';
        const stream = new ReadableStream({
            start(controller) {
                // Send error in AI SDK format: 3:"error message"\n
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
