"use client";

import { useEffect, useState } from 'react';
import { Loader2, AlertCircle, FileText } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { ArtifactBlock } from "./ArtifactBlock";
import type { Artifact } from "@/types/message";

interface DocumentGeneratorProps {
  jobId: string;
  documentType: string;
  title?: string;
  onComplete?: (artifact: Artifact) => void;
  onError?: (error: string) => void;
}

interface JobStatus {
  status: 'pending' | 'processing' | 'completed' | 'failed';
  result?: {
    artifact_id?: string;
    download_url?: string;
    error?: string;
  };
}

export function DocumentGenerator({ 
  jobId, 
  documentType, 
  title = "Document",
  onComplete,
  onError 
}: DocumentGeneratorProps) {
  const [status, setStatus] = useState<JobStatus['status']>('pending');
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<string>('Initializing...');

  useEffect(() => {
    if (!jobId) return;

    const eventSource = new EventSource(`/api/jobs/${jobId}/events`);

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        
        switch (data.type) {
          case 'status':
            setStatus(data.status);
            if (data.status === 'processing') {
              setProgress('Generating document...');
            } else if (data.status === 'pending') {
              setProgress('Waiting in queue...');
            }
            break;
            
          case 'job-complete':
            setStatus('completed');
            setProgress('Complete!');
            
            // Create artifact object from result
            if (data.result) {
              const newArtifact: Artifact = {
                id: data.result.artifact_id || jobId,
                type: documentType as any,
                title: title,
                status: 'ready',
                downloadUrl: data.result.download_url,
                previewUrl: undefined,
                code: undefined,
              };
              
              setArtifact(newArtifact);
              onComplete?.(newArtifact);
            }
            
            eventSource.close();
            break;
            
          case 'job-failed':
            setStatus('failed');
            setError(data.error || 'Document generation failed');
            setProgress('Failed');
            onError?.(data.error || 'Document generation failed');
            eventSource.close();
            break;
            
          case 'error':
            setError(data.message || 'An error occurred');
            onError?.(data.message || 'An error occurred');
            eventSource.close();
            break;
        }
      } catch (e) {
        console.error('Error parsing SSE data:', e);
      }
    };

    eventSource.onerror = (err) => {
      console.error('SSE error:', err);
      // Don't immediately fail - the connection might reconnect
      setTimeout(() => {
        if (status !== 'completed' && status !== 'failed') {
          setError('Connection lost. Please refresh to check status.');
          onError?.('Connection lost');
        }
      }, 5000);
    };

    return () => {
      eventSource.close();
    };
  }, [jobId, documentType, title, onComplete, onError, status]);

  if (error) {
    return (
      <Alert variant="destructive" className="bg-red-500/10 border-red-500/20">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (artifact) {
    return <ArtifactBlock artifact={artifact} />;
  }

  // Show loading state
  return (
    <div className="flex flex-col items-center justify-center p-8 bg-slate-900/30 rounded-lg border border-slate-700">
      <div className="flex items-center gap-3 mb-3">
        <Loader2 className="h-6 w-6 animate-spin text-violet-400" />
        <span className="text-sm font-medium text-foreground">
          {status === 'pending' && 'Waiting in queue...'}
          {status === 'processing' && 'Generating document...'}
          {status === 'completed' && 'Document ready!'}
        </span>
      </div>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <FileText className="h-3.5 w-3.5" />
        <span>{title}</span>
        <span className="text-slate-500">•</span>
        <span className="capitalize">{documentType}</span>
      </div>
      {status === 'processing' && (
        <div className="mt-3 w-48 h-1 bg-slate-800 rounded-full overflow-hidden">
          <div className="h-full bg-violet-500 animate-pulse" style={{ width: '60%' }} />
        </div>
      )}
    </div>
  );
}

export default DocumentGenerator;
