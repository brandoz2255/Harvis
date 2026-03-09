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

    // Calculate hierarchy levels (for Y positioning)
    const getHierarchyLevel = (agent: AgentNode, visited = new Set<string>()): number => {
      if (visited.has(agent.id)) return 0;
      visited.add(agent.id);
      
      if (!agent.parentId) return 0;
      
      const parent = agents.find(a => a.id === agent.parentId);
      if (!parent) return 0;
      
      return 1 + getHierarchyLevel(parent, visited);
    };

    // Group by hierarchy level
    const levelGroups = new Map<number, AgentNode[]>();
    filteredAgents.forEach((agent) => {
      const level = getHierarchyLevel(agent);
      const group = levelGroups.get(level) || [];
      group.push(agent);
      levelGroups.set(level, group);
    });

    // Position nodes in a hierarchical tree layout
    const positionedAgents = new Map<string, { x: number; y: number }>();
    
    levelGroups.forEach((group, level) => {
      const levelWidth = group.length * 220;
      const startX = -levelWidth / 2;
      
      group.forEach((agent, index) => {
        // X: distributed horizontally
        // Y: level-based with spacing
        const x = startX + (index * 240) + 120;
        const y = level * 140;
        
        positionedAgents.set(agent.id, { x, y });
      });
    });

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

      return {
        id: agent.id,
        type: 'agentNode',
        position: positionedAgents.get(agent.id) || { x: 0, y: 0 },
        data: {
          ...agent,
          connectionCount,
          isSelected,
          isDimmed: selectedAgentId && !isSelected && !connections.some(
            c => (c.source === selectedAgentId && c.target === agent.id) ||
                 (c.target === selectedAgentId && c.source === agent.id)
          ),
        },
        style: {
          width,
          height,
        },
        // Dynamic styling based on status
        className: agent.status === 'running' ? 'agent-running' : undefined,
      };
    });

    // Transform to React Flow edges
    const edges: Edge[] = connections
      .filter(conn => 
        filteredAgents.some(a => a.id === conn.source) &&
        filteredAgents.some(a => a.id === conn.target)
      )
      .map((conn, index) => ({
        id: `e${index}-${conn.source}-${conn.target}`,
        source: conn.source,
        target: conn.target,
        type: 'smoothstep',
        animated: false,
        style: {
          stroke: darkMode ? '#5c5c5c' : '#94a3b8',
          strokeWidth: 2,
          opacity: selectedAgentId ? 
            (conn.source === selectedAgentId || conn.target === selectedAgentId ? 1 : 0.3)
            : 0.6,
        },
        markerEnd: {
          type: 'arrowclosed',
          width: 10,
          height: 10,
          color: darkMode ? '#5c5c5c' : '#94a3b8',
        },
      }));

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
