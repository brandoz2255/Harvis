/**
 * Open Notebook API Client
 * 
 * TypeScript client for the Open Notebook REST API.
 * Open Notebook is an open-source alternative to Google Notebook LM.
 * 
 * @see https://github.com/lfnovo/open-notebook
 */

// API Base URL - proxied through nginx
// Open Notebook routes all endpoints under /api
const OPEN_NOTEBOOK_API_BASE = '/open-notebook-api/api';

// ============================================================================
// Types
// ============================================================================

export interface Notebook {
  id: string;
  name: string;
  description?: string;
  archived: boolean;
  created: string;
  updated: string;
  source_count: number;
  note_count: number;
}

export interface NotebookCreate {
  name: string;
  description?: string;
}

export interface NotebookUpdate {
  name?: string;
  description?: string;
  archived?: boolean;
}

export interface Source {
  id: string;
  title: string;
  source_type: string;
  content?: string;
  url?: string;
  file_path?: string;
  processing_status: 'pending' | 'processing' | 'completed' | 'failed';
  error_message?: string;
  created: string;
  updated: string;
  asset_count?: number;
}

export interface SourceCreate {
  type: 'file' | 'url' | 'text' | 'youtube';
  url?: string;
  content?: string;
  title?: string;
  notebook_id?: string;
  notebooks?: string[];  // Multiple notebook IDs
  transformations?: string[];  // Transformation IDs to apply
  embed?: boolean;
  delete_source?: boolean;
  async_processing?: boolean;
}

export interface Note {
  id: string;
  title: string;
  content: string;
  note_type: string;
  notebook_id?: string;
  source_ids: string[];
  created: string;
  updated: string;
  pinned: boolean;
}

export interface NoteCreate {
  title: string;
  content: string;
  notebook_id: string;
  note_type?: string;
  source_ids?: string[];
}

export interface NoteUpdate {
  title?: string;
  content?: string;
  pinned?: boolean;
}

export interface ChatSession {
  id: string;
  title: string;
  notebook_id?: string;
  created: string;
  updated: string;
  message_count?: number;
  model_override?: string;
}

export interface ChatMessage {
  id: string;
  type: 'human' | 'ai';
  content: string;
  timestamp?: string;
}

export interface ChatSessionWithMessages extends ChatSession {
  messages: ChatMessage[];
}

export interface ChatContext {
  sources?: string[];  // Source IDs to include
  notes?: string[];    // Note IDs to include
  use_rag?: boolean;
  include_all_sources?: boolean;
  include_all_notes?: boolean;
}

export interface ChatRequest {
  session_id: string;
  message: string;
  context: ChatContext;
  model_override?: string;
}

export interface ChatResponse {
  session_id: string;
  messages: ChatMessage[];
}

export interface PodcastConfig {
  notebook_id: string;
  title?: string;
  style?: 'conversational' | 'interview' | 'educational' | 'debate' | 'storytelling';
  speakers?: number;  // 1-4
  duration_minutes?: number;
  source_ids?: string[];
  note_ids?: string[];
}

export interface Podcast {
  id: string;
  title: string;
  notebook_id: string;
  status: 'pending' | 'generating' | 'completed' | 'error';
  style: string;
  speakers: number;
  audio_path?: string;
  transcript?: Array<{ speaker: string; dialogue: string }>;
  error_message?: string;
  created: string;
  completed_at?: string;
}

export interface Transformation {
  id: string;
  name: string;
  description?: string;
  prompt_template: string;
  is_system: boolean;
}

export interface Model {
  id: string;
  name: string;
  provider: string;
  type: 'chat' | 'embedding' | 'tts' | 'stt';
  context_length?: number;
}

export interface SearchResult {
  id: string;
  type: 'source' | 'note' | 'notebook';
  title: string;
  content_preview: string;
  score: number;
  notebook_id?: string;
}

// ============================================================================
// API Client
// ============================================================================

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
  const url = `${OPEN_NOTEBOOK_API_BASE}${endpoint}`;
  
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new OpenNotebookApiError(
      response.status,
      errorText || `API error: ${response.status}`
    );
  }

  return response.json();
}

// ============================================================================
// Notebooks API
// ============================================================================

export const NotebooksAPI = {
  /**
   * Get all notebooks
   */
  async list(archived?: boolean): Promise<Notebook[]> {
    const params = new URLSearchParams();
    if (archived !== undefined) {
      params.set('archived', String(archived));
    }
    const query = params.toString() ? `?${params}` : '';
    return apiRequest<Notebook[]>(`/notebooks${query}`);
  },

  /**
   * Get a specific notebook by ID
   */
  async get(notebookId: string): Promise<Notebook> {
    return apiRequest<Notebook>(`/notebooks/${notebookId}`);
  },

  /**
   * Create a new notebook
   */
  async create(data: NotebookCreate): Promise<Notebook> {
    return apiRequest<Notebook>('/notebooks', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  /**
   * Update a notebook
   */
  async update(notebookId: string, data: NotebookUpdate): Promise<Notebook> {
    return apiRequest<Notebook>(`/notebooks/${notebookId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  /**
   * Delete a notebook
   */
  async delete(notebookId: string): Promise<void> {
    await apiRequest<{ message: string }>(`/notebooks/${notebookId}`, {
      method: 'DELETE',
    });
  },

  /**
   * Add a source to a notebook
   */
  async addSource(notebookId: string, sourceId: string): Promise<void> {
    await apiRequest<{ message: string }>(
      `/notebooks/${notebookId}/sources/${sourceId}`,
      { method: 'POST' }
    );
  },

  /**
   * Remove a source from a notebook
   */
  async removeSource(notebookId: string, sourceId: string): Promise<void> {
    await apiRequest<{ message: string }>(
      `/notebooks/${notebookId}/sources/${sourceId}`,
      { method: 'DELETE' }
    );
  },
};

// ============================================================================
// Sources API
// ============================================================================

export const SourcesAPI = {
  /**
   * Get all sources, optionally filtered by notebook
   */
  async list(notebookId?: string): Promise<Source[]> {
    const params = new URLSearchParams();
    if (notebookId) {
      params.set('notebook_id', notebookId);
    }
    const query = params.toString() ? `?${params}` : '';
    return apiRequest<Source[]>(`/sources${query}`);
  },

  /**
   * Get a specific source by ID
   */
  async get(sourceId: string): Promise<Source> {
    return apiRequest<Source>(`/sources/${sourceId}`);
  },

  /**
   * Create a source from URL
   */
  async createFromUrl(data: {
    url: string;
    title?: string;
    notebook_id?: string;
    embed?: boolean;
    async_processing?: boolean;
  }): Promise<Source> {
    const formData = new FormData();
    formData.append('type', 'url');
    formData.append('url', data.url);
    if (data.title) formData.append('title', data.title);
    if (data.notebook_id) formData.append('notebook_id', data.notebook_id);
    if (data.embed !== undefined) formData.append('embed', String(data.embed));
    if (data.async_processing !== undefined) {
      formData.append('async_processing', String(data.async_processing));
    }

    const response = await fetch(`${OPEN_NOTEBOOK_API_BASE}/sources`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      throw new OpenNotebookApiError(response.status, await response.text());
    }

    return response.json();
  },

  /**
   * Create a source from text content
   */
  async createFromText(data: {
    content: string;
    title?: string;
    notebook_id?: string;
    embed?: boolean;
  }): Promise<Source> {
    const formData = new FormData();
    formData.append('type', 'text');
    formData.append('content', data.content);
    if (data.title) formData.append('title', data.title);
    if (data.notebook_id) formData.append('notebook_id', data.notebook_id);
    if (data.embed !== undefined) formData.append('embed', String(data.embed));

    const response = await fetch(`${OPEN_NOTEBOOK_API_BASE}/sources`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      throw new OpenNotebookApiError(response.status, await response.text());
    }

    return response.json();
  },

  /**
   * Upload a file as a source
   */
  async uploadFile(data: {
    file: File;
    title?: string;
    notebook_id?: string;
    embed?: boolean;
    async_processing?: boolean;
  }): Promise<Source> {
    const formData = new FormData();
    formData.append('type', 'file');
    formData.append('file', data.file);
    if (data.title) formData.append('title', data.title);
    if (data.notebook_id) formData.append('notebook_id', data.notebook_id);
    if (data.embed !== undefined) formData.append('embed', String(data.embed));
    if (data.async_processing !== undefined) {
      formData.append('async_processing', String(data.async_processing));
    }

    const response = await fetch(`${OPEN_NOTEBOOK_API_BASE}/sources`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      throw new OpenNotebookApiError(response.status, await response.text());
    }

    return response.json();
  },

  /**
   * Delete a source
   */
  async delete(sourceId: string): Promise<void> {
    await apiRequest<{ message: string }>(`/sources/${sourceId}`, {
      method: 'DELETE',
    });
  },

  /**
   * Get source processing status
   */
  async getStatus(sourceId: string): Promise<{ status: string; error?: string }> {
    return apiRequest<{ status: string; error?: string }>(
      `/sources/${sourceId}/status`
    );
  },
};

// ============================================================================
// Notes API
// ============================================================================

export const NotesAPI = {
  /**
   * Get all notes, optionally filtered by notebook
   */
  async list(notebookId?: string): Promise<Note[]> {
    const params = new URLSearchParams();
    if (notebookId) {
      params.set('notebook_id', notebookId);
    }
    const query = params.toString() ? `?${params}` : '';
    return apiRequest<Note[]>(`/notes${query}`);
  },

  /**
   * Get a specific note by ID
   */
  async get(noteId: string): Promise<Note> {
    return apiRequest<Note>(`/notes/${noteId}`);
  },

  /**
   * Create a new note
   */
  async create(data: NoteCreate): Promise<Note> {
    return apiRequest<Note>('/notes', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  /**
   * Update a note
   */
  async update(noteId: string, data: NoteUpdate): Promise<Note> {
    return apiRequest<Note>(`/notes/${noteId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  /**
   * Delete a note
   */
  async delete(noteId: string): Promise<void> {
    await apiRequest<{ message: string }>(`/notes/${noteId}`, {
      method: 'DELETE',
    });
  },
};

// ============================================================================
// Chat API
// ============================================================================

export const ChatAPI = {
  /**
   * Get all chat sessions for a notebook
   */
  async getSessions(notebookId: string): Promise<ChatSession[]> {
    const params = new URLSearchParams();
    params.set('notebook_id', notebookId);
    return apiRequest<ChatSession[]>(`/chat/sessions?${params}`);
  },

  /**
   * Create a new chat session
   */
  async createSession(data: {
    notebook_id: string;
    title?: string;
    model_override?: string;
  }): Promise<ChatSession> {
    return apiRequest<ChatSession>('/chat/sessions', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  /**
   * Get a chat session with messages
   */
  async getSession(sessionId: string): Promise<ChatSessionWithMessages> {
    return apiRequest<ChatSessionWithMessages>(`/chat/sessions/${sessionId}`);
  },

  /**
   * Delete a chat session
   */
  async deleteSession(sessionId: string): Promise<void> {
    await apiRequest<{ success: boolean }>(`/chat/sessions/${sessionId}`, {
      method: 'DELETE',
    });
  },

  /**
   * Send a message in a chat session
   */
  async sendMessage(data: ChatRequest): Promise<ChatResponse> {
    return apiRequest<ChatResponse>('/chat/execute', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },
};

// ============================================================================
// Podcasts API
// ============================================================================

export const PodcastsAPI = {
  /**
   * Get all podcasts for a notebook
   */
  async list(notebookId: string): Promise<Podcast[]> {
    return apiRequest<Podcast[]>(
      `/podcasts?notebook_id=${encodeURIComponent(notebookId)}`
    );
  },

  /**
   * Get a specific podcast
   */
  async get(podcastId: string): Promise<Podcast> {
    return apiRequest<Podcast>(`/podcasts/${podcastId}`);
  },

  /**
   * Generate a new podcast
   */
  async generate(config: PodcastConfig): Promise<Podcast> {
    return apiRequest<Podcast>('/podcasts/generate', {
      method: 'POST',
      body: JSON.stringify(config),
    });
  },

  /**
   * Get podcast audio URL
   */
  getAudioUrl(podcastId: string): string {
    return `${OPEN_NOTEBOOK_API_BASE}/podcasts/${podcastId}/audio`;
  },

  /**
   * Delete a podcast
   */
  async delete(podcastId: string): Promise<void> {
    await apiRequest<{ message: string }>(`/podcasts/${podcastId}`, {
      method: 'DELETE',
    });
  },
};

// ============================================================================
// Transformations API
// ============================================================================

export const TransformationsAPI = {
  /**
   * Get all available transformations
   */
  async list(): Promise<Transformation[]> {
    return apiRequest<Transformation[]>('/transformations');
  },

  /**
   * Apply a transformation to a source
   */
  async apply(data: {
    source_id: string;
    transformation_id: string;
    model_override?: string;
  }): Promise<{ result: string }> {
    return apiRequest<{ result: string }>('/transformations/apply', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },
};

// ============================================================================
// Models API
// ============================================================================

export const ModelsAPI = {
  /**
   * Get all available AI models
   */
  async list(): Promise<Model[]> {
    return apiRequest<Model[]>('/models');
  },

  /**
   * Get models by type
   */
  async listByType(type: 'chat' | 'embedding' | 'tts' | 'stt'): Promise<Model[]> {
    return apiRequest<Model[]>(`/models?type=${type}`);
  },
};

// ============================================================================
// Search API
// ============================================================================

export const SearchAPI = {
  /**
   * Search across notebooks, sources, and notes
   */
  async search(query: string, notebookId?: string): Promise<SearchResult[]> {
    const params = new URLSearchParams({ q: query });
    if (notebookId) {
      params.set('notebook_id', notebookId);
    }
    return apiRequest<SearchResult[]>(`/search?${params}`);
  },

  /**
   * Vector search (semantic search using embeddings)
   */
  async vectorSearch(
    query: string,
    notebookId?: string,
    limit?: number
  ): Promise<SearchResult[]> {
    const params = new URLSearchParams({ q: query });
    if (notebookId) params.set('notebook_id', notebookId);
    if (limit) params.set('limit', String(limit));
    return apiRequest<SearchResult[]>(`/search/vector?${params}`);
  },
};

// ============================================================================
// Settings API
// ============================================================================

export const SettingsAPI = {
  /**
   * Get current settings
   */
  async get(): Promise<Record<string, any>> {
    return apiRequest<Record<string, any>>('/settings');
  },

  /**
   * Update settings
   */
  async update(settings: Record<string, any>): Promise<Record<string, any>> {
    return apiRequest<Record<string, any>>('/settings', {
      method: 'PUT',
      body: JSON.stringify(settings),
    });
  },
};

// ============================================================================
// Health Check
// ============================================================================

export async function checkOpenNotebookHealth(): Promise<boolean> {
  try {
    // Health endpoint is at root, not under /api
    const response = await fetch('/open-notebook-api/health');
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
