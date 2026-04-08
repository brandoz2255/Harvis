'use client';

import { useCallback, useEffect, useRef, type Dispatch, type SetStateAction } from 'react';
import type { Edge, Node, NodeChange } from '@xyflow/react';

/**
 * Keeps React Flow node positions when the agent graph updates from SSE.
 * Without this, `setNodes(initialFlowNodes)` resets dragged positions every tick.
 */
export function usePersistedAgentGraphLayout(
  storageKey: string,
  initialFlowNodes: Node[],
  initialFlowEdges: Edge[],
  setNodes: Dispatch<SetStateAction<Node[]>>,
  setEdges: Dispatch<SetStateAction<Edge[]>>,
  onNodesChange: (changes: NodeChange[]) => void
) {
  const positionsRef = useRef<Record<string, { x: number; y: number }>>({});

  useEffect(() => {
    positionsRef.current = {};
    if (typeof window === 'undefined') return;
    try {
      const raw = sessionStorage.getItem(storageKey);
      if (raw) positionsRef.current = JSON.parse(raw) as Record<string, { x: number; y: number }>;
    } catch {
      positionsRef.current = {};
    }
  }, [storageKey]);

  useEffect(() => {
    setNodes((prev) => {
      const prevPos: Record<string, { x: number; y: number }> = {};
      for (const n of prev) prevPos[n.id] = n.position;
      return initialFlowNodes.map((n) => ({
        ...n,
        position: positionsRef.current[n.id] ?? prevPos[n.id] ?? n.position,
      }));
    });
    setEdges(initialFlowEdges);
  }, [initialFlowNodes, initialFlowEdges, setNodes, setEdges]);

  const onNodesChangePersist = useCallback(
    (changes: NodeChange[]) => {
      onNodesChange(changes);
      let dirty = false;
      for (const ch of changes) {
        if (ch.type === 'position' && ch.position != null && ch.dragging === false) {
          positionsRef.current = { ...positionsRef.current, [ch.id]: ch.position };
          dirty = true;
        }
      }
      if (dirty && typeof window !== 'undefined') {
        try {
          sessionStorage.setItem(storageKey, JSON.stringify(positionsRef.current));
        } catch {
          /* ignore quota */
        }
      }
    },
    [onNodesChange, storageKey]
  );

  return onNodesChangePersist;
}
