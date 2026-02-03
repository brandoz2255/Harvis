/**
 * RAG Corpus API Client
 * 
 * Functions for interacting with the RAG corpus management endpoints
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';

// ─── Types ───────────────────────────────────────────────────────────────────

export interface RagUpdateRequest {
    sources: string[];
    keywords?: string[];
    extra_urls?: string[];
    python_libraries?: string[];
    docker_topics?: string[];      // For docker_docs source (engine, compose, swarm, etc.)
    kubernetes_topics?: string[];  // For kubernetes_docs source (concepts, tasks, networking, etc.)
}

export interface JobProgress {
    total_docs: number;
    processed: number;
    current_source: string | null;
    current_phase: string;
}

export interface RagJob {
    id: string;
    status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED';
    sources: string[];
    keywords: string[];
    extra_urls: string[];
    progress: JobProgress;
    error: string | null;
    created_at: string;
    updated_at: string;
}

export interface SourceStats {
    available_sources: string[];
    indexed_stats: Record<string, number>;
    total_documents: number;
}

export interface RagHealthResponse {
    status: 'healthy' | 'degraded' | 'unhealthy';
    services: Record<string, string>;
    vectordb_details?: Record<string, unknown>;
    embedding_details?: Record<string, unknown>;
}

export interface RagConfigResponse {
    rag_dir: string;
    ollama_url: string;
    embedding_model: string;
    available_sources: string[];
}

export interface OllamaModel {
    name: string;
    size_gb: number;
    modified: string;
    is_embedding_model: boolean;
}

export interface OllamaModelsResponse {
    models: OllamaModel[];
    current_model: string;
    total_count: number;
}

// ─── API Functions ───────────────────────────────────────────────────────────

/**
 * Start a RAG update job
 */
export async function startRagUpdate(request: RagUpdateRequest): Promise<{ job_id: string; status: string; message: string }> {
    const response = await fetch(`${API_BASE}/api/rag/update-local`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
        credentials: 'include',
    });

    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(error.detail || 'Failed to start RAG update');
    }

    return response.json();
}

/**
 * Get the status of a RAG job
 */
export async function getRagJobStatus(jobId: string): Promise<RagJob> {
    const response = await fetch(`${API_BASE}/api/rag/jobs/${jobId}`, {
        credentials: 'include',
    });

    if (!response.ok) {
        throw new Error('Failed to get job status');
    }

    return response.json();
}

/**
 * List recent RAG jobs
 */
export async function listRagJobs(limit: number = 10): Promise<{ jobs: RagJob[]; count: number }> {
    const response = await fetch(`${API_BASE}/api/rag/jobs?limit=${limit}`, {
        credentials: 'include',
    });

    if (!response.ok) {
        throw new Error('Failed to list jobs');
    }

    return response.json();
}

/**
 * Cancel a running RAG job
 */
export async function cancelRagJob(jobId: string): Promise<{ message: string }> {
    const response = await fetch(`${API_BASE}/api/rag/jobs/${jobId}/cancel`, {
        method: 'POST',
        credentials: 'include',
    });

    if (!response.ok) {
        throw new Error('Failed to cancel job');
    }

    return response.json();
}

/**
 * Get source stats
 */
export async function getRagSourceStats(): Promise<SourceStats> {
    const response = await fetch(`${API_BASE}/api/rag/sources`, {
        credentials: 'include',
    });

    if (!response.ok) {
        throw new Error('Failed to get source stats');
    }

    return response.json();
}

/**
 * Rebuild a specific source
 */
export async function rebuildRagSource(source: string): Promise<{ job_id: string; deleted: number; message: string }> {
    const response = await fetch(`${API_BASE}/api/rag/rebuild`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source }),
        credentials: 'include',
    });

    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(error.detail || 'Failed to rebuild source');
    }

    return response.json();
}

/**
 * Clear a source from the vector database
 */
export async function clearRagSource(source: string): Promise<{ source: string; deleted: number; message: string }> {
    const response = await fetch(`${API_BASE}/api/rag/sources/${source}`, {
        method: 'DELETE',
        credentials: 'include',
    });

    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(error.detail || 'Failed to clear source');
    }

    return response.json();
}

/**
 * Get RAG service health
 */
export async function getRagHealth(): Promise<RagHealthResponse> {
    const response = await fetch(`${API_BASE}/api/rag/health`, {
        credentials: 'include',
    });

    if (!response.ok) {
        throw new Error('Failed to get RAG health');
    }

    return response.json();
}

/**
 * Get RAG configuration
 */
export async function getRagConfig(): Promise<RagConfigResponse> {
    const response = await fetch(`${API_BASE}/api/rag/config`, {
        credentials: 'include',
    });

    if (!response.ok) {
        throw new Error('Failed to get RAG config');
    }

    return response.json();
}

/**
 * Poll job status until completion
 */
export async function pollJobUntilComplete(
    jobId: string,
    onProgress?: (job: RagJob) => void,
    pollIntervalMs: number = 2000,
    maxWaitMs: number = 600000 // 10 minutes
): Promise<RagJob> {
    const startTime = Date.now();

    while (Date.now() - startTime < maxWaitMs) {
        const job = await getRagJobStatus(jobId);

        if (onProgress) {
            onProgress(job);
        }

        if (job.status === 'COMPLETED' || job.status === 'FAILED') {
            return job;
        }

        await new Promise(resolve => setTimeout(resolve, pollIntervalMs));
    }

    throw new Error('Job timed out');
}

/**
 * Get available Ollama models for embedding
 */
export async function getOllamaModels(): Promise<OllamaModelsResponse> {
    const response = await fetch(`${API_BASE}/api/rag/models`, {
        credentials: 'include',
    });

    if (!response.ok) {
        throw new Error('Failed to get Ollama models');
    }

    return response.json();
}
