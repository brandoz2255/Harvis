/**
 * Production-ready API utilities for Vibe Coding frontend
 * Forces all vibecoding API calls to hit FastAPI backend directly
 * Handles JSON responses consistently with proper error handling
 */

// API Configuration - Always use absolute URLs to FastAPI backend
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
export const API_BASE = API_BASE_URL.replace(/\/+$/, '') // Remove trailing slashes
export const WS_BASE = API_BASE.replace(/^https?:/, 'ws:') // Convert http->ws for WebSocket

// Error types for structured error handling
export type ApiErrorCode = 
  | 'WRONG_ORIGIN' 
  | 'SESSION_NOT_FOUND' 
  | 'UNAUTHORIZED' 
  | 'INTERNAL' 
  | 'PARSE_ERROR'
  | 'NETWORK_ERROR'

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
 * Enhanced fetch wrapper with absolute URLs and credentials
 */
export async function apiRequest<T = any>(
  endpoint: string, 
  options: RequestInit = {}
): Promise<ApiResponse<T>> {
  try {
    // Ensure absolute URL for vibecoding endpoints
    const url = endpoint.startsWith('/api/vibecoding') 
      ? `${API_BASE}${endpoint}`
      : endpoint;

    console.log(`[API] Making request to: ${url}`);

    const response = await fetch(url, {
      credentials: 'include', // Important for CORS cookies/auth
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
    
    const response = await fetch(`${API_BASE}/api/vibecoding/sessions/create`, {
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
    // Get auth token from localStorage
    const token = localStorage.getItem('token');
    if (!token) {
      throw new Error('UNAUTHORIZED: No authentication token found. Please sign in.');
    }
    
    const response = await fetch(`${API_BASE}/api/vibecoding/session/status?id=${sessionId}`, {
      method: 'GET',
      credentials: 'include',
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
 * Wait for session to become ready with robust error handling and backoff
 * Stops immediately on wrong origin, auth errors, or non-existent sessions
 */
export async function waitReady(
  sessionId: string, 
  options: { timeoutMs?: number; intervalMs?: number } = {}
): Promise<{ ready: boolean; status?: SessionStatusResponse }> {
  const { timeoutMs = 300000, intervalMs = 400 } = options;
  
  // Guard against undefined/empty session ID immediately
  if (!sessionId || typeof sessionId !== 'string') {
    throw new Error('SESSION_ID_MISSING: Cannot poll with undefined or empty session ID');
  }
  
  // Prevent duplicate polling for same session
  if (activePollers.has(sessionId)) {
    console.log(`⏳ Already polling session ${sessionId}, reusing existing promise`);
    return activePollers.get(sessionId)!;
  }

  const pollerPromise = waitReadyInternal(sessionId, timeoutMs, intervalMs);
  activePollers.set(sessionId, pollerPromise);
  
  try {
    return await pollerPromise;
  } finally {
    activePollers.delete(sessionId);
  }
}

async function waitReadyInternal(
  sessionId: string, 
  timeoutMs: number, 
  intervalMs: number
): Promise<{ ready: boolean; status?: SessionStatusResponse }> {
  const startTime = Date.now();
  let pollInterval = intervalMs; // Start with specified interval, exponential backoff to max 2s
  const maxInterval = 2000;
  const bootstrapWindow = 5000; // Allow SESSION_NOT_FOUND for 5s after creation
  
  console.log(`⏳ Waiting for session ${sessionId} to be ready (timeout: ${timeoutMs}ms)`);
  
  while (Date.now() - startTime < timeoutMs) {
    try {
      const status = await getSessionStatus(sessionId);
      
      if (status.error) {
        // Session has permanent error - stop polling
        console.error(`❌ Session ${sessionId} has error: ${status.error}`);
        return { ready: false, status };
      }
      
      if (status.ready) {
        console.log(`✅ Session ${sessionId} is ready!`);
        return { ready: true, status };
      }
      
      // Session exists but not ready yet - log progress
      const progressInfo = status.progress?.percent !== undefined 
        ? `${status.progress.percent}%` 
        : 'calculating...';
      const etaInfo = status.progress?.eta_ms 
        ? `ETA: ${Math.round(status.progress.eta_ms / 1000)}s` 
        : '';
      
      console.log(`⏳ Session ${sessionId}: ${status.phase} (${progressInfo}) ${etaInfo}`);
      
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      
      // Stop immediately on critical errors
      if (errorMessage.startsWith('WRONG_ORIGIN:') || 
          errorMessage.startsWith('UNAUTHORIZED:') ||
          errorMessage.startsWith('INTERNAL:')) {
        console.error(`❌ Critical error for session ${sessionId}: ${errorMessage}`);
        throw error;
      }
      
      // Handle SESSION_NOT_FOUND with bootstrap window
      if (errorMessage.startsWith('SESSION_NOT_FOUND:')) {
        const elapsed = Date.now() - startTime;
        if (elapsed > bootstrapWindow) {
          console.error(`❌ Session not found: ${errorMessage}`);
          throw error;
        }
        // Within bootstrap window, continue polling
        console.log(`⏳ Session ${sessionId} not found yet (${elapsed}ms elapsed), continuing to poll...`);
      } else {
        // For network errors or other issues, continue polling but warn
        console.warn(`Error checking session status (continuing to poll): ${errorMessage}`);
      }
    }
    
    // Wait before next poll with exponential backoff
    await new Promise(resolve => setTimeout(resolve, pollInterval));
    pollInterval = Math.min(pollInterval * 1.5, maxInterval);
  }
  
  console.error(`❌ Session ${sessionId} did not become ready within ${timeoutMs}ms`);
  return { ready: false };
}