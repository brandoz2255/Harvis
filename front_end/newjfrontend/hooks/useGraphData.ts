'use client';

import { useMemo } from 'react';
import { Node, Edge } from '@xyflow/react';
import { NodeType, WorkspaceNode } from '../types/graph';

// Color schemes for Obsidian dark theme
const darkColors: Record<NodeType, { bg: string; border: string }> = {
  file: { bg: '#3b82f620', border: '#3b82f680' },
  folder: { bg: '#f59e0b20', border: '#f59e0b80' },
  tag: { bg: '#10b98120', border: '#10b98180' },
  note: { bg: '#8b5cf620', border: '#8b5cf680' },
  link: { bg: '#ec489920', border: '#ec489980' },
};

const lightColors: Record<NodeType, { bg: string; border: string }> = {
  file: { bg: '#dbeafe', border: '#3b82f6' },
  folder: { bg: '#fef3c7', border: '#f59e0b' },
  tag: { bg: '#d1fae5', border: '#10b981' },
  note: { bg: '#ede9fe', border: '#8b5cf6' },
  link: { bg: '#fce7f3', border: '#ec4899' },
};

export function useGraphData(
  workspaceNodes: WorkspaceNode[],
  connections: Array<{ source: string; target: string; strength?: number }>,
  darkMode: boolean
) {
  return useMemo(() => {
    const colors = darkMode ? darkColors : lightColors;

    // Calculate connection counts for each node
    const connectionCounts = new Map<string, number>();
    connections.forEach((conn) => {
      connectionCounts.set(conn.source, (connectionCounts.get(conn.source) || 0) + 1);
      connectionCounts.set(conn.target, (connectionCounts.get(conn.target) || 0) + 1);
    });

    // Transform to React Flow nodes
    const nodes: Node[] = workspaceNodes.map((node, index) => {
      const color = colors[node.type];
      const connectionCount = connectionCounts.get(node.id) || 0;

      // Distribute nodes in a circle initially
      const angle = (index / workspaceNodes.length) * 2 * Math.PI;
      const radius = Math.min(300, workspaceNodes.length * 30);

      return {
        id: node.id,
        type: 'workspaceNode',
        position: {
          x: 400 + Math.cos(angle) * radius,
          y: 300 + Math.sin(angle) * radius,
        },
        data: {
          ...node,
          connectionCount,
        },
        style: {
          backgroundColor: color.bg,
          borderColor: color.border,
        },
      };
    });

    // Transform to React Flow edges
    const edges: Edge[] = connections.map((conn, index) => ({
      id: `e${index}`,
      source: conn.source,
      target: conn.target,
      type: 'straight',
      style: {
        stroke: darkMode ? '#5c5c5c' : '#94a3b8',
        strokeWidth: Math.max(1, (conn.strength || 0.5) * 2),
        opacity: 0.6,
      },
      data: {
        strength: conn.strength || 0.5,
      },
    }));

    return { nodes, edges };
  }, [workspaceNodes, connections, darkMode]);
}
