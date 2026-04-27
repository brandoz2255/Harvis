'use client';

import { useMemo } from 'react';
import { Node, Edge } from '@xyflow/react';
import { 
  AgentNode, 
  AgentConnection, 
  AgentNodeType,
  AgentStatus,
  AGENT_TYPE_COLORS,
  AGENT_STATUS_COLORS,
} from '../types/agent-graph';

interface UseAgentDataOptions {
  /** Agent nodes from WebSocket */
  agents: AgentNode[];
  /** Agent connections from WebSocket */
  connections: AgentConnection[];
  /** Dark mode enabled */
  darkMode: boolean;
  /** Selected agent ID (for highlighting) */
  selectedAgentId?: string | null;
  /** Filter by status */
  filterStatus?: AgentStatus[];
  /** Filter by type */
  filterTypes?: AgentNodeType[];
}

interface UseAgentDataReturn {
  nodes: Node[];
  edges: Edge[];
  agentCount: number;
  runningCount: number;
  completedCount: number;
  errorCount: number;
}

/**
 * Hook to transform agent data for React Flow graph visualization
 * 
 * Takes live agent data from WebSocket and prepares it for
 * React Flow rendering with proper colors, sizes, and positions.
 */
export function useAgentData({
  agents,
  connections,
  darkMode,
  selectedAgentId,
  filterStatus,
  filterTypes,
}: UseAgentDataOptions): UseAgentDataReturn {
  return useMemo(() => {
    // Filter agents if needed
    let filteredAgents = agents;
    if (filterStatus && filterStatus.length > 0) {
      filteredAgents = filteredAgents.filter(a => filterStatus.includes(a.status));
    }
    if (filterTypes && filterTypes.length > 0) {
      filteredAgents = filteredAgents.filter(a => filterTypes.includes(a.type));
    }

    // Calculate connection counts for sizing
    const connectionCounts = new Map<string, number>();
    connections.forEach((conn) => {
      connectionCounts.set(conn.source, (connectionCounts.get(conn.source) || 0) + 1);
      connectionCounts.set(conn.target, (connectionCounts.get(conn.target) || 0) + 1);
    });

    // ─── Radial tree layout ──────────────────────────────────────────────
    // Place each parent, then fan its children around it in an arc. Children
    // of sibling parents stay clustered under their own parent, so subagents
    // spread visually instead of stacking on one row.

    const filteredIds = new Set(filteredAgents.map((a) => a.id));
    const childrenOf = new Map<string | null, AgentNode[]>();
    for (const a of filteredAgents) {
      const key = a.parentId && filteredIds.has(a.parentId) ? a.parentId : null;
      const arr = childrenOf.get(key) || [];
      arr.push(a);
      childrenOf.set(key, arr);
    }

    const positionedAgents = new Map<string, { x: number; y: number }>();
    const NODE_MIN_GAP = 260;

    const placeSubtree = (
      id: string,
      pos: { x: number; y: number },
      parentAngle: number,
      depth: number
    ) => {
      positionedAgents.set(id, pos);
      const kids = childrenOf.get(id) || [];
      if (kids.length === 0) return;

      const radius = depth === 0 ? 320 : 260 + Math.max(0, kids.length - 2) * 20;
      // Arc size scales with child count; capped so kids don't wrap back on parent
      const maxArc = depth === 0 ? Math.PI * 1.5 : Math.PI * 0.9;
      const minArcForSpread =
        kids.length > 1 ? Math.min(maxArc, (kids.length - 1) * (NODE_MIN_GAP / radius)) : 0;
      const arc = Math.max(minArcForSpread, Math.PI * 0.35);
      const step = kids.length > 1 ? arc / (kids.length - 1) : 0;
      const startAngle = parentAngle - arc / 2;

      kids.forEach((k, i) => {
        const angle = kids.length === 1 ? parentAngle : startAngle + i * step;
        const x = pos.x + Math.cos(angle) * radius;
        const y = pos.y + Math.sin(angle) * radius;
        placeSubtree(k.id, { x, y }, angle, depth + 1);
      });
    };

    const roots = childrenOf.get(null) || [];
    if (roots.length === 1) {
      // Single root → children fan downward (angle π/2 = down in screen coords).
      placeSubtree(roots[0].id, { x: 0, y: 0 }, Math.PI / 2, 0);
    } else if (roots.length > 1) {
      // Multiple roots → arrange around origin, each fanning outward.
      const rootRadius = Math.max(160, roots.length * 60);
      roots.forEach((root, i) => {
        const angle = (i / roots.length) * Math.PI * 2 - Math.PI / 2;
        const x = Math.cos(angle) * rootRadius;
        const y = Math.sin(angle) * rootRadius;
        placeSubtree(root.id, { x, y }, angle, 0);
      });
    }

    // Mark nodes spawned in the last ~1.5s so the node can play an entry animation.
    const now = Date.now();
    const SPAWN_ANIM_MS = 1500;

    // Transform to React Flow nodes
    const nodes: Node[] = filteredAgents.map((agent) => {
      const typeColor = AGENT_TYPE_COLORS[agent.type];
      const statusColor = AGENT_STATUS_COLORS[agent.status];
      const connectionCount = connectionCounts.get(agent.id) || 0;
      const isSelected = agent.id === selectedAgentId;

      // Size based on importance
      const hasChildren = agent.subAgentCount > 0;
      const width = hasChildren ? 220 : 180;
      const height = 100;

      const startedAtMs = agent.startedAt ? new Date(agent.startedAt).getTime() : 0;
      const isFreshlySpawned = startedAtMs > 0 && now - startedAtMs < SPAWN_ANIM_MS;

      const classes = [
        agent.status === 'running' ? 'agent-running' : '',
        isFreshlySpawned ? 'agent-spawn-in' : '',
      ]
        .filter(Boolean)
        .join(' ');

      return {
        id: agent.id,
        type: 'agentNode',
        position: positionedAgents.get(agent.id) || { x: 0, y: 0 },
        data: {
          ...agent,
          connectionCount,
          isSelected,
          isFreshlySpawned,
          isDimmed: selectedAgentId && !isSelected && !connections.some(
            c => (c.source === selectedAgentId && c.target === agent.id) ||
                 (c.target === selectedAgentId && c.source === agent.id)
          ),
        },
        style: {
          width,
          height,
        },
        className: classes || undefined,
      };
    });

    // Transform to React Flow edges
    const agentById = new Map(filteredAgents.map((a) => [a.id, a] as const));
    const edges: Edge[] = connections
      .filter(conn =>
        filteredAgents.some(a => a.id === conn.source) &&
        filteredAgents.some(a => a.id === conn.target)
      )
      .map((conn, index) => {
        const targetAgent = agentById.get(conn.target);
        const isChildRunning = targetAgent?.status === 'running';
        const strokeColor = isChildRunning
          ? AGENT_TYPE_COLORS[targetAgent!.type]
          : (darkMode ? '#5c5c5c' : '#94a3b8');
        return {
          id: `e${index}-${conn.source}-${conn.target}`,
          source: conn.source,
          target: conn.target,
          type: 'smoothstep',
          animated: isChildRunning,
          style: {
            stroke: strokeColor,
            strokeWidth: isChildRunning ? 2.5 : 2,
            opacity: selectedAgentId ?
              (conn.source === selectedAgentId || conn.target === selectedAgentId ? 1 : 0.3)
              : (isChildRunning ? 0.9 : 0.5),
          },
          markerEnd: {
            type: 'arrowclosed',
            width: 10,
            height: 10,
            color: strokeColor,
          },
        };
      });

    // Return stats
    return {
      nodes,
      edges,
      agentCount: agents.length,
      runningCount: agents.filter(a => a.status === 'running').length,
      completedCount: agents.filter(a => a.status === 'completed').length,
      errorCount: agents.filter(a => a.status === 'error').length,
    };
  }, [agents, connections, darkMode, selectedAgentId, filterStatus, filterTypes]);
}

export default useAgentData;
