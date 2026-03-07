'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { AgentEvent, AgentNode, AgentConnection } from '../types/agent-graph';

interface UseAgentStreamOptions {
  url?: string;
  token: string;
  autoReconnect?: boolean;
  reconnectDelay?: number;
  onEvent?: (event: AgentEvent) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
  onError?: (error: Error) => void;
}

interface UseAgentStreamReturn {
  nodes: AgentNode[];
  edges: AgentConnection[];
  isConnected: boolean;
  isConnecting: boolean;
  error: Error | null;
  reconnect: () => void;
  clear: () => void;
}

export function useAgentStream({
  url = typeof window !== 'undefined' 
    ? `ws://${window.location.host}:18789/events` 
    : 'ws://localhost:18789/events',
  token,
  autoReconnect = true,
  reconnectDelay = 3000,
  onEvent,
  onConnect,
  onDisconnect,
  onError,
}: UseAgentStreamOptions): UseAgentStreamReturn {
  const [nodes, setNodes] = useState<AgentNode[]>([]);
  const [edges, setEdges] = useState<AgentConnection[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const shouldReconnectRef = useRef(true);

  const clear = useCallback(() => {
    setNodes([]);
    setEdges([]);
  }, []);

  const applyEvent = useCallback((event: AgentEvent) => {
    switch (event.type) {
      case 'agent.spawned':
        setNodes((prev) => {
          if (prev.some(n => n.id === event.agentId)) {
            return prev.map(n => 
              n.id === event.agentId 
                ? { ...n, ...event.data.agent, status: 'running' }
                : n
            );
          }
          const newAgent: AgentNode = {
            id: event.agentId,
            label: event.agentId.split(':').pop() || event.agentId,
            type: event.data.agent?.type || 'executor',
            status: 'running',
            model: event.data.agent?.model || 'unknown',
            task: event.data.agent?.task,
            parentId: event.data.agent?.parentId,
            subAgentCount: 0,
            startedAt: event.timestamp,
            ...event.data.agent,
          };
          return [...prev, newAgent];
        });
        break;

      case 'agent.updated':
        setNodes((prev) => 
          prev.map(n => n.id === event.agentId ? { ...n, ...event.data.agent } : n)
        );
        break;

      case 'agent.completed':
        setNodes((prev) => 
          prev.map(n => 
            n.id === event.agentId 
              ? { ...n, status: 'completed', completedAt: event.timestamp, ...event.data.agent }
              : n
          )
        );
        break;

      case 'agent.error':
        setNodes((prev) => 
          prev.map(n => 
            n.id === event.agentId 
              ? { ...n, status: 'error', completedAt: event.timestamp, metadata: { ...n.metadata, error: event.data.error } }
              : n
          )
        );
        break;

      case 'agent.cancelled':
        setNodes((prev) => prev.filter(n => n.id !== event.agentId));
        break;

      case 'connection.created':
        setEdges((prev) => {
          if (event.data.connection && 
              !prev.some(e => e.source === event.data.connection?.source && e.target === event.data.connection?.target)) {
            return [...prev, event.data.connection];
          }
          return prev;
        });
        if (event.data.connection) {
          setNodes((prev) => 
            prev.map(n => n.id === event.data.connection?.source ? { ...n, subAgentCount: n.subAgentCount + 1 } : n)
          );
        }
        break;

      case 'connection.removed':
        setEdges((prev) => 
          prev.filter(e => !(e.source === event.data.connection?.source && e.target === event.data.connection?.target))
        );
        break;
    }
    onEvent?.(event);
  }, [onEvent]);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    setIsConnecting(true);
    setError(null);

    try {
      const ws = new WebSocket(`${url}?token=${encodeURIComponent(token)}`);
      
      ws.onopen = () => {
        setIsConnected(true);
        setIsConnecting(false);
        onConnect?.();
        ws.send(JSON.stringify({ type: 'subscribe', channels: ['agents', 'sessions'] }));
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type?.startsWith('agent.') || data.type?.startsWith('connection.')) {
            applyEvent(data as AgentEvent);
          }
          if (data.type === 'agents.snapshot') {
            setNodes(data.agents || []);
            setEdges(data.connections || []);
          }
        } catch (err) {
          console.error('Failed to parse WebSocket message:', err);
        }
      };

      ws.onclose = () => {
        setIsConnected(false);
        setIsConnecting(false);
        onDisconnect?.();
        if (shouldReconnectRef.current && autoReconnect) {
          reconnectTimeoutRef.current = setTimeout(connect, reconnectDelay);
        }
      };

      ws.onerror = () => {
        setError(new Error('WebSocket error'));
        setIsConnecting(false);
      };

      wsRef.current = ws;
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
      setIsConnecting(false);
    }
  }, [url, token, autoReconnect, reconnectDelay, onConnect, onDisconnect, onError, applyEvent]);

  const disconnect = useCallback(() => {
    shouldReconnectRef.current = false;
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    wsRef.current?.close();
    wsRef.current = null;
  }, []);

  useEffect(() => {
    shouldReconnectRef.current = true;
    connect();
    return disconnect;
  }, [connect, disconnect]);

  return {
    nodes,
    edges,
    isConnected,
    isConnecting,
    error,
    reconnect: connect,
    clear,
  };
}
