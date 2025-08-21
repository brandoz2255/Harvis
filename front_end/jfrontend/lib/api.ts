/**
 * Production-ready API utilities for Vibe Coding frontend
 * Option A: Uses Next.js proxy for same-origin requests (eliminates CORS)
 * Option B: Direct backend calls with Bearer tokens for production
 * Handles JSON responses consistently with proper error handling
 */

// API Configuration 
// Option A: Use relative URLs (proxied by Next.js to backend)
// Option B: Use absolute URLs for direct backend access
const USE_PROXY = process.env.NODE_ENV === 'development' || process.env.NEXT_PUBLIC_USE_PROXY === 'true'
const API_BASE_URL = USE_PROXY ? '' : (process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000')
export const API_BASE = API_BASE_URL.replace(/\/+$/, '') // Remove trailing slashes
export const WS_BASE = USE_PROXY ? 'ws://localhost:9000' : API_BASE.replace(/^https?:/, 'ws:') // WebSocket URL

// Error types for structured error handling
export type ApiErrorCode = 
  | 'WRONG_ORIGIN' 
  | 'SESSION_NOT_FOUND' 
  | 'UNAUTHORIZED' 
  | 'INTERNAL' 
  | 'PARSE_ERROR'
  | 'NETWORK_ERROR'

// Global error handler for UI notifications
export type ErrorHandler = (error: { code: ApiErrorCode; message: string; sessionId?: string }) => void
let globalErrorHandler: ErrorHandler | null = null

export function setGlobalErrorHandler(handler: ErrorHandler) {
  globalErrorHandler = handler
}

function notifyGlobalError(code: ApiErrorCode, message: string, sessionId?: string) {
  if (globalErrorHandler) {
    globalErrorHandler({ code, message, sessionId })
  }
}

export interface ApiResponse<T = any> {
  ok: boolean;
  data?: T;
  error?: string;
  code?: ApiErrorCode;
  ready?: boolean;
  sessionId?: string;
}

// Active polling sessions to prevent duplicate polling
const activePollers = new Map<string, Promise<{ ready: boolean; status?: SessionStatusResponse }>>()

/**
 * Safely parse JSON response with content-type checking and origin detection
 */
export async function safeJson(res: Response): Promise<ApiResponse> {
  try {
    // Check if response is JSON
    const contentType = res.headers.get('content-type');
    if (!contentType || !contentType.includes('application/json')) {
      const text = await res.text();
      
      // Detect if we hit Next.js instead of FastAPI (HTML response)
      if (text.includes('<!DOCTYPE html>') || text.includes('<html')) {
        throw new Error(`WRONG_ORIGIN: Requests are hitting Next.js (port 9000) instead of FastAPI backend. Expected JSON but got HTML.`);
      }
      
      throw new Error(`Expected JSON response but got ${contentType}. Response: ${text.substring(0, 200)}`);
    }

    const data = await res.json();
    
    // Handle structured backend error responses
    if (data.ok === false) {
      const code = getErrorCodeFromMessage(data.error);
      return {
        ok: false,
        error: data.error || 'Unknown error from server',
        code,
        data
      };
    }

    return {
      ok: true,
      data: data,
      ...data // Spread to include ready, sessionId, etc.
    };
  } catch (error) {
    console.error('API Response Error:', error);
    
    let code: ApiErrorCode = 'PARSE_ERROR';
    let message = error instanceof Error ? error.message : 'Failed to parse response';
    
    if (message.startsWith('WRONG_ORIGIN:')) {
      code = 'WRONG_ORIGIN';
      message = message.replace('WRONG_ORIGIN: ', '');
    }
    
    return {
      ok: false,
      error: message,
      code
    };
  }
}

/**
 * Map error messages to structured error codes
 */
function getErrorCodeFromMessage(error?: string): ApiErrorCode {
  if (!error) return 'INTERNAL';
  
  const upperError = error.toUpperCase();
  if (upperError.includes('SESSION_NOT_FOUND') || upperError.includes('NOT_FOUND')) return 'SESSION_NOT_FOUND';
  if (upperError.includes('UNAUTHORIZED') || upperError.includes('AUTH')) return 'UNAUTHORIZED';
  if (upperError.includes('INTERNAL') || upperError.includes('SERVER')) return 'INTERNAL';
  
  return 'INTERNAL';
}

/**
 * Enhanced fetch wrapper with proxy-aware URLs and credentials
 */
export async function apiRequest<T = any>(
  endpoint: string, 
  options: RequestInit = {}
): Promise<ApiResponse<T>> {
  try {
    // Use proxy in development, absolute URLs in production
    const url = USE_PROXY 
      ? endpoint // Relative URL, proxied by Next.js
      : (endpoint.startsWith('/api/vibecoding') ? `${API_BASE}${endpoint}` : endpoint);

    console.log(`[API] Making request to: ${url} (proxy: ${USE_PROXY})`);

    const response = await fetch(url, {
      credentials: 'include', // Important for cookies/auth
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
      ...options,
    });

    return await safeJson(response);
  } catch (error) {
    console.error(`API Request failed for ${endpoint}:`, error);
    return {
      ok: false,
      error: error instanceof Error ? error.message : 'Request failed',
      code: 'NETWORK_ERROR'
    };
  }
}

// Session creation and status types
export interface CreateSessionPayload {
  workspace_id: string;
  template?: string;
  image?: string;
  project_name?: string;
  description?: string;
}

export interface SessionStatusResponse {
  ok: boolean;
  ready: boolean;
  phase: string;
  progress: {
    percent?: number;
    eta_ms?: number;
  };
  error?: string;
  session_id?: string;
  message?: string;
}

/**
 * Create a new session with proper validation and error handling
 */
export async function createSession(payload: CreateSessionPayload): Promise<string> {
  try {
    console.log(`[API] Creating session with payload:`, payload);
    
    // Get auth token from localStorage
    const token = localStorage.getItem('token');
    if (!token) {
      throw new Error('UNAUTHORIZED: No authentication token found. Please sign in.');
    }
    
    // Use proxy-aware URL
    const url = USE_PROXY 
      ? '/api/vibecoding/sessions/create'
      : `${API_BASE}/api/vibecoding/sessions/create`;
    
    const response = await fetch(url, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
    });

    const result = await safeJson(response);
    
    if (!result.ok) {
      throw new Error(result.error || 'Session creation failed');
    }
    
    const sessionId = result.data?.session_id;
    if (!sessionId || typeof sessionId !== 'string') {
      throw new Error('SERVER_ERROR: No session ID returned from server');
    }
    
    // Store API token for Option B (if provided)
    const apiToken = result.data?.api_token;
    if (apiToken && !USE_PROXY) {
      localStorage.setItem(`session_token_${sessionId}`, apiToken);
      console.log(`🔑 Session token stored for ${sessionId}`);
    }
    
    console.log(`✅ Session created: ${sessionId}`);
    return sessionId;
  } catch (error) {
    console.error('Failed to create session:', error);
    throw error;
  }
}

/**
 * Get session status with typed response
 */
export async function getSessionStatus(sessionId: string): Promise<SessionStatusResponse> {
  // Guard against undefined/empty session ID
  if (!sessionId || typeof sessionId !== 'string') {
    throw new Error('SESSION_ID_MISSING: Session ID is required');
  }
  
  try {
    // Get auth token (session-specific for Option B, general for Option A)
    let token = localStorage.getItem('token');
    
    // In production mode (Option B), prefer session-specific token
    if (!USE_PROXY) {
      const sessionToken = localStorage.getItem(`session_token_${sessionId}`);
      if (sessionToken) {
        token = sessionToken;
      }
    }
    
    if (!token) {
      throw new Error('UNAUTHORIZED: No authentication token found. Please sign in.');
    }
    
    // Use proxy-aware URL
    const url = USE_PROXY 
      ? `/api/vibecoding/session/status?id=${sessionId}`
      : `${API_BASE}/api/vibecoding/session/status?id=${sessionId}`;
    
    const response = await fetch(url, {
      method: 'GET',
      credentials: USE_PROXY ? 'include' : 'omit', // Include credentials only for proxy mode
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    });

    const result = await safeJson(response);
    
    // Handle different status codes with structured responses
    if (response.status === 404) {
      throw new Error(`SESSION_NOT_FOUND: ${result.error || 'Session not found'}`);
    }
    if (response.status === 401) {
      throw new Error(`UNAUTHORIZED: ${result.error || 'Authentication required'}`);
    }
    if (response.status >= 500) {
      throw new Error(`INTERNAL: ${result.error || 'Server error'}`);
    }
    
    // Type assertion for session status response
    const statusData = result.data as any || result as any;
    
    return {
      ok: result.ok ?? true,
      ready: statusData?.ready ?? false,
      phase: statusData?.phase ?? 'Unknown',
      progress: statusData?.progress ?? {},
      error: statusData?.error ?? result.error,
      session_id: statusData?.session_id ?? sessionId,
      message: statusData?.message
    };
  } catch (error) {
    console.error(`Failed to get session status for ${sessionId}:`, error);
    throw error;
  }
}

/**
 * Wait for session to become ready with backoff polling and terminal state handling
 * Stops immediately on terminal states (ready, error) and auth errors
 */
export async function waitReady(
  sessionId: string, 
  options: { timeoutMs?: number; signal?: AbortSignal } = {}
): Promise<{ ready: boolean; status?: SessionStatusResponse }> {
  const { timeoutMs = 300000, signal } = options;
  
  // Guard against undefined/empty session ID immediately
  if (!sessionId || typeof sessionId !== 'string') {
    throw new Error('SESSION_ID_MISSING: Cannot poll with undefined or empty session ID');
  }
  
  // Prevent duplicate polling for same session
  if (activePollers.has(sessionId)) {
    console.log(`⏳ Already polling session ${sessionId}, reusing existing promise`);
    return activePollers.get(sessionId)!;
  }

  const pollerPromise = waitSessionReady(sessionId, timeoutMs, signal);
  activePollers.set(sessionId, pollerPromise);
  
  try {
    return await pollerPromise;
  } finally {
    activePollers.delete(sessionId);
  }
}

async function waitSessionReady(
  sessionId: string, 
  timeoutMs: number,
  signal?: AbortSignal
): Promise<{ ready: boolean; status?: SessionStatusResponse }> {
  let delay = 800; // ms - start with 800ms
  const maxDelay = 5000; // max 5s between polls
  const startTime = Date.now();
  
  console.log(`⏳ Waiting for session ${sessionId} to be ready (timeout: ${timeoutMs}ms)`);

  for (let i = 0; i < 30; i++) {
    // Check for cancellation
    if (signal?.aborted) {
      throw new Error('ABORTED');
    }
    
    // Check timeout
    if (Date.now() - startTime > timeoutMs) {
      throw new Error('TIMEOUT_WAITING_FOR_SESSION');
    }

    try {
      // Use proxy-aware URL  
      const url = USE_PROXY 
        ? `/api/vibecoding/sessions/${sessionId}/status`
        : `${API_BASE}/api/vibecoding/sessions/${sessionId}/status`;
      
      const response = await fetch(url, {
        credentials: USE_PROXY ? 'include' : 'omit',
        headers: { 
          'Accept': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token')}`,
        },
        signal,
      });

      if (response.status === 404) {
        throw new Error('SESSION_NOT_FOUND');
      }
      if (response.status === 401) {
        notifyGlobalError('UNAUTHORIZED', 'Sign in required to check session status.', sessionId);
        throw new Error('UNAUTHORIZED');
      }

      const data = await response.json();

      // Terminal states - stop polling
      if (data.status === 'ready') {
        console.log(`✅ Session ${sessionId} is ready!`);
        return { ready: true, status: data };
      }
      
      if (data.status === 'error') {
        console.error(`❌ Session ${sessionId} failed: ${data.error}`);
        throw new Error(data.error || 'CREATE_FAILED');
      }

      // Non-terminal states (starting, stopped, etc.) → backoff and continue
      console.log(`⏳ Session ${sessionId}: ${data.status}`);
      
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      
      // Terminal errors - stop immediately
      if (errorMessage === 'SESSION_NOT_FOUND') {
        console.error(`❌ Session not found: ${sessionId}`);
        notifyGlobalError('SESSION_NOT_FOUND', 'Session not found. Please create a new session.', sessionId);
        throw new Error('SESSION_NOT_FOUND');
      }
      
      if (errorMessage === 'UNAUTHORIZED') {
        throw error; // Already notified above
      }
      
      if (errorMessage.includes('CREATE_FAILED') || errorMessage === 'ABORTED') {
        throw error;
      }
      
      // Network errors - continue with backoff
      console.warn(`Network error checking session status (retrying): ${errorMessage}`);
    }

    // Exponential backoff
    await new Promise(resolve => setTimeout(resolve, delay));
    delay = Math.min(maxDelay, Math.round(delay * 1.5));
  }
  
  console.error(`❌ Session ${sessionId} did not become ready after maximum attempts`);
  throw new Error('TIMEOUT_WAITING_FOR_SESSION');
}