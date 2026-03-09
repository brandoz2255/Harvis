/**
 * Open Notebook API Client
 *
 * Routes through the Python backend's /api/notebooks router,
 * which is proxied by nginx to the FastAPI backend.
 */

const API_BASE = '/api/notebooks';

// ============================================================================
// Types
// ============================================================================

export interface Notebook {
  id: string;
  title: string;
  description?: string;
  is_active?: boolean;
  created_at: string;
  updated_at: string;
  source_count: number;
  note_count: number;
}

export interface NotebookCreate {
  title: string;
  description?: string;
}

export interface NotebookUpdate {
  title?: string;
  description?: string;
}

export interface Source {
  id: string;
  notebook_id: string;
  title?: string;
  source_type?: string;
  storage_path?: string;
  original_filename?: string;
  content?: string;
  content_text?: string;
  status?: 'pending' | 'processing' | 'ready' | 'error';
  error_message?: string;
  metadata?: Record<string, any>;
  chunk_count?: number;
  created_at: string;
  updated_at: string;
}

export interface Note {
  id: string;
  notebook_id: string;
  title?: string;
  content: string;
  type?: string;
  is_pinned: boolean;
  source_meta?: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface NoteCreate {
  title?: string;
  content: string;
  type?: string;
  is_pinned?: boolean;
  source_meta?: Record<string, any>;
}

export interface NoteUpdate {
  title?: string;
  content?: string;
  is_pinned?: boolean;
}

export interface ChatMessage {
  id: string;
  role: 'human' | 'ai' | 'user' | 'assistant';
  content: string;
  created_at?: string;
}

export interface ChatRequest {
  message: string;
  model?: string;
  top_k?: number;
  include_reasoning?: boolean;
}

export interface ChatResponse {
  answer: string;
  reasoning?: string;
  citations?: Array<{
    source_id?: string;
    source_title?: string;
    chunk_id?: string;
    page?: number;
    section?: string;
    quote?: string;
  }>;
  model_used: string;
  message_id?: string;
}

export interface PodcastConfig {
  notebook_id: string;
  title: string;
  style?: string;
  speakers?: number;
  duration_minutes?: number;
  source_ids?: string[];
  note_ids?: string[];
  content?: string;
  generate_audio?: boolean;
}

export interface Podcast {
  id: string;
  notebook_id: string;
  title: string;
  status: 'pending' | 'generating' | 'completed' | 'error' | 'script_only';
  style: string;
  speakers: number;
  duration_minutes?: number;
  audio_path?: string;
  audio_url?: string;
  transcript?: Array<{ speaker: string; dialogue: string }>;
  outline?: string;
  error_message?: string;
  duration_seconds?: number;
  created_at?: string;
  completed_at?: string;
}

export interface Transformation {
  id: string;
  transformation_type: string;
  original_content?: string;
  transformed_content?: string;
  model_used?: string;
  created_at: string;
}

export interface Model {
  name: string;
  type?: string;
}

export interface SearchResult {
  kind: 'source' | 'note';
  notebook_id?: string;
  notebook_title?: string;
  source_id?: string;
  note_id?: string;
  title?: string;
  snippet?: string;
  score?: number;
}

// ============================================================================
// Helpers
// ============================================================================

function getAuthHeaders(): Record<string, string> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return headers;
}

function getAuthHeadersNoContentType(): Record<string, string> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return headers;
}

class OpenNotebookApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'OpenNotebookApiError';
  }
}

async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE}${endpoint}`;

  const headers = {
    ...getAuthHeaders(),
    ...options.headers,
  };

  const response = await fetch(url, {
    ...options,
    headers,
    credentials: 'include',
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new OpenNotebookApiError(
      response.status,
      errorText || `API error: ${response.status}`
    );
  }

  const text = await response.text();
  if (!text) return {} as T;
  return JSON.parse(text);
}

// ============================================================================
// Notebooks API
// ============================================================================

export const NotebooksAPI = {
  async list(): Promise<Notebook[]> {
    const resp = await apiRequest<{ notebooks: Notebook[]; total_count: number }>('');
    return resp.notebooks || [];
  },

  async get(notebookId: string): Promise<Notebook> {
    return apiRequest<Notebook>(`/${notebookId}`);
  },

  async create(data: NotebookCreate): Promise<Notebook> {
    return apiRequest<Notebook>('', {
      method: 'POST',
      body: JSON.stringify({ title: data.title, description: data.description }),
    });
  },

  async update(notebookId: string, data: NotebookUpdate): Promise<Notebook> {
    return apiRequest<Notebook>(`/${notebookId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  async delete(notebookId: string): Promise<void> {
    await apiRequest<{ message: string }>(`/${notebookId}`, {
      method: 'DELETE',
    });
  },
};

// ============================================================================
// Sources API
// ============================================================================

export const SourcesAPI = {
  async list(notebookId: string): Promise<Source[]> {
    return apiRequest<Source[]>(`/${notebookId}/sources`);
  },

  async createFromUrl(data: {
    url: string;
    title?: string;
    notebook_id: string;
  }): Promise<{ source: Source; message: string }> {
    return apiRequest<{ source: Source; message: string }>(
      `/${data.notebook_id}/sources/url`,
      {
        method: 'POST',
        body: JSON.stringify({ url: data.url, title: data.title }),
      }
    );
  },

  async createFromText(data: {
    content: string;
    title: string;
    notebook_id: string;
  }): Promise<{ source: Source; message: string }> {
    const formData = new FormData();
    formData.append('title', data.title);
    formData.append('content', data.content);

    const response = await fetch(`${API_BASE}/${data.notebook_id}/sources/text`, {
      method: 'POST',
      headers: getAuthHeadersNoContentType(),
      body: formData,
      credentials: 'include',
    });

    if (!response.ok) {
      throw new OpenNotebookApiError(response.status, await response.text());
    }

    return response.json();
  },

  async uploadFile(data: {
    file: File;
    title?: string;
    notebook_id: string;
  }): Promise<{ source: Source; message: string }> {
    const formData = new FormData();
    formData.append('file', data.file);
    if (data.title) formData.append('title', data.title);

    const response = await fetch(`${API_BASE}/${data.notebook_id}/sources/upload`, {
      method: 'POST',
      headers: getAuthHeadersNoContentType(),
      body: formData,
      credentials: 'include',
    });

    if (!response.ok) {
      throw new OpenNotebookApiError(response.status, await response.text());
    }

    return response.json();
  },

  async createFromYouTube(data: {
    url: string;
    notebook_id: string;
  }): Promise<{ source: Source; message: string }> {
    return apiRequest<{ source: Source; message: string }>(
      `/${data.notebook_id}/sources/youtube`,
      {
        method: 'POST',
        body: JSON.stringify({ url: data.url }),
      }
    );
  },

  async delete(notebookId: string, sourceId: string): Promise<void> {
    await apiRequest<{ message: string }>(`/${notebookId}/sources/${sourceId}`, {
      method: 'DELETE',
    });
  },

  async getStatus(notebookId: string, sourceId: string): Promise<{ source_id: string; status: string; chunk_count?: number; error_message?: string }> {
    return apiRequest(`/${notebookId}/sources/${sourceId}/status`);
  },

  async retry(notebookId: string, sourceId: string): Promise<{ message: string }> {
    return apiRequest(`/${notebookId}/sources/${sourceId}/retry`, { method: 'POST' });
  },

  async getContent(notebookId: string, sourceId: string): Promise<{ source_id: string; title: string; type: string; content: string; length: number }> {
    return apiRequest(`/${notebookId}/sources/${sourceId}/content`);
  },

  streamStatus(notebookId: string, sourceId: string, onUpdate: (data: any) => void): () => void {
    const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
    const url = `${API_BASE}/${notebookId}/sources/${sourceId}/status/stream`;
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const controller = new AbortController();
    fetch(url, { headers, signal: controller.signal })
      .then(async (resp) => {
        if (!resp.ok || !resp.body) return;
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try { onUpdate(JSON.parse(line.slice(6))); } catch {}
            }
          }
        }
      })
      .catch(() => {});
    return () => controller.abort();
  },
};

// ============================================================================
// Notes API
// ============================================================================

export const NotesAPI = {
  async list(notebookId: string): Promise<Note[]> {
    const resp = await apiRequest<{ notes: Note[]; total_count: number }>(`/${notebookId}/notes`);
    return resp.notes || [];
  },

  async get(notebookId: string, noteId: string): Promise<Note> {
    return apiRequest<Note>(`/${notebookId}/notes/${noteId}`);
  },

  async create(notebookId: string, data: NoteCreate): Promise<Note> {
    return apiRequest<Note>(`/${notebookId}/notes`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async update(notebookId: string, noteId: string, data: NoteUpdate): Promise<Note> {
    return apiRequest<Note>(`/${notebookId}/notes/${noteId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  async delete(notebookId: string, noteId: string): Promise<void> {
    await apiRequest<{ message: string }>(`/${notebookId}/notes/${noteId}`, {
      method: 'DELETE',
    });
  },
};

// ============================================================================
// Chat API
// ============================================================================

export const ChatAPI = {
  async getHistory(notebookId: string): Promise<ChatMessage[]> {
    const resp = await apiRequest<{ messages: ChatMessage[]; total_count: number }>(
      `/${notebookId}/chat/history`
    );
    return resp.messages || [];
  },

  async sendMessage(notebookId: string, data: ChatRequest): Promise<ChatResponse> {
    return apiRequest<ChatResponse>(`/${notebookId}/chat`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async clearHistory(notebookId: string): Promise<void> {
    await apiRequest<{ message: string }>(`/${notebookId}/chat/history`, {
      method: 'DELETE',
    });
  },
};

// ============================================================================
// Podcasts API
// ============================================================================

export const PodcastsAPI = {
  async list(notebookId: string): Promise<Podcast[]> {
    const resp = await apiRequest<{ podcasts: Podcast[]; total_count?: number }>(
      `/${notebookId}/podcasts`
    );
    return resp.podcasts || [];
  },

  async listByNotebook(notebookId: string): Promise<Podcast[]> {
    const resp = await apiRequest<{ podcasts: Podcast[] }>(
      `/podcasts/by-notebook/${encodeURIComponent(notebookId)}`
    );
    return resp.podcasts || [];
  },

  async get(notebookId: string, podcastId: string): Promise<Podcast> {
    return apiRequest<Podcast>(`/${notebookId}/podcasts/${podcastId}`);
  },

  async generate(config: PodcastConfig): Promise<Podcast> {
    return apiRequest<Podcast>('/podcasts/generate', {
      method: 'POST',
      body: JSON.stringify(config),
    });
  },

  async generateStream(config: PodcastConfig): Promise<Response> {
    const url = `${API_BASE}/podcasts/generate/stream`;
    const response = await fetch(url, {
      method: 'POST',
      headers: getAuthHeaders(),
      credentials: 'include',
      body: JSON.stringify(config),
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new OpenNotebookApiError(response.status, errorText);
    }
    return response;
  },

  async generateAudioFromScript(data: {
    podcast_id?: string;
    notebook_id: string;
    title: string;
    style: string;
    speakers: number;
    duration_minutes: number;
    transcript: Array<{ speaker: string; dialogue: string }>;
    custom_speakers?: Array<{ name: string; role?: string; personality?: string; voice_id?: string; rvc_voice_id?: string }>;
  }): Promise<Podcast> {
    return apiRequest<Podcast>('/podcasts/generate/audio', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async getStyles(): Promise<any[]> {
    try {
      return await apiRequest<any[]>('/podcasts/styles');
    } catch {
      return [];
    }
  },

  getAudioUrl(notebookId: string, podcastId: string): string {
    return `${API_BASE}/${notebookId}/podcasts/${podcastId}/audio`;
  },

  async delete(podcastId: string): Promise<void> {
    await apiRequest<{ success: boolean; message: string }>(`/podcasts/${podcastId}`, {
      method: 'DELETE',
    });
  },
};

// ============================================================================
// Transformations API
// ============================================================================

export const TransformationsAPI = {
  async listTypes(): Promise<any> {
    return apiRequest<any>('/transformations/types');
  },

  async apply(notebookId: string, sourceId: string, data: {
    transformation: string;
    model?: string;
    custom_prompt?: string;
  }): Promise<any> {
    return apiRequest<any>(`/${notebookId}/sources/${sourceId}/transform`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  async list(notebookId: string): Promise<Transformation[]> {
    const resp = await apiRequest<{ transformations: any[]; total_count: number }>(
      `/${notebookId}/transformations`
    );
    return resp.transformations || [];
  },
};

// ============================================================================
// Models API (uses main backend /api/models)
// ============================================================================

export const ModelsAPI = {
  async list(): Promise<Model[]> {
    try {
      const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const response = await fetch('/api/models', { headers, credentials: 'include' });
      if (!response.ok) return [];
      const data = await response.json();
      return (data.models || data || []).map((m: any) => ({
        name: m.name || m.model || m.id || 'unknown',
        type: m.type || 'chat',
      }));
    } catch {
      return [];
    }
  },
};

// ============================================================================
// Search API
// ============================================================================

export const SearchAPI = {
  async search(query: string, notebookId?: string): Promise<SearchResult[]> {
    const resp = await apiRequest<{ results: SearchResult[]; total_count: number }>(
      '/search',
      {
        method: 'POST',
        body: JSON.stringify({
          query,
          type: 'text',
          limit: 50,
          search_sources: true,
          search_notes: true,
        }),
      }
    );
    return resp.results || [];
  },

  async vectorSearch(query: string, notebookId?: string, limit?: number): Promise<SearchResult[]> {
    const resp = await apiRequest<{ results: SearchResult[]; total_count: number }>(
      '/search',
      {
        method: 'POST',
        body: JSON.stringify({
          query,
          type: 'vector',
          limit: limit || 20,
          search_sources: true,
          search_notes: false,
        }),
      }
    );
    return resp.results || [];
  },
};

// ============================================================================
// Settings API (no backend equivalent -- stub)
// ============================================================================

export const SettingsAPI = {
  async get(): Promise<Record<string, any>> {
    return {};
  },
  async update(_settings: Record<string, any>): Promise<Record<string, any>> {
    return {};
  },
};

// ============================================================================
// Health Check
// ============================================================================

export async function checkOpenNotebookHealth(): Promise<boolean> {
  try {
    const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const response = await fetch(`${API_BASE}?limit=1`, {
      headers,
      credentials: 'include',
    });
    return response.ok;
  } catch {
    return false;
  }
}

// ============================================================================
// Default Export
// ============================================================================

export const OpenNotebookAPI = {
  notebooks: NotebooksAPI,
  sources: SourcesAPI,
  notes: NotesAPI,
  chat: ChatAPI,
  podcasts: PodcastsAPI,
  transformations: TransformationsAPI,
  models: ModelsAPI,
  search: SearchAPI,
  settings: SettingsAPI,
  checkHealth: checkOpenNotebookHealth,
};

export default OpenNotebookAPI;
