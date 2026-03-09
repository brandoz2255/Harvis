'use client';

import { useMemo } from 'react';
import { useOpenClawStore, WorkspaceLogEvent } from '../stores/openclawStore';
import { AgentNode, AgentConnection, AgentNodeType, AgentStatus } from '../types/agent-graph';

export interface WorkspaceAgentGraph {
  nodes: AgentNode[];
  edges: AgentConnection[];
  agentCount: number;
  runningCount: number;
}

function inferAgentType(label: string): AgentNodeType {
  const lower = label.toLowerCase();
  if (lower === 'agent') return 'orchestrator';
  if (lower.includes('plan')) return 'planner';
  if (lower.includes('cod') || lower.includes('dev')) return 'coder';
  if (lower.includes('research') || lower.includes('search')) return 'researcher';
  if (lower.includes('write') || lower.includes('doc')) return 'writer';
  return 'executor';
}

function labelToId(label: string): string {
  return label.toLowerCase().replace(/\s+/g, '-');
}

/**
 * Derives an agent graph from workspace SSE log events stored in openclawStore.
 * No WebSocket required — reads from logEvents already populated by the SSE stream.
 */
export function useWorkspaceAgentGraph(): WorkspaceAgentGraph {
  const logEvents = useOpenClawStore((s) => s.logEvents);

  return useMemo(() => {
    const nodeMap = new Map<string, AgentNode>();
    const edgeSet = new Set<string>();
    const edges: AgentConnection[] = [];
    let prevAgentId: string | null = null;

    for (const evt of logEvents) {
      const label = evt.agent_label ?? 'Agent';
      const id = labelToId(label);

      // Ensure node exists
      if (!nodeMap.has(id)) {
        const type = inferAgentType(label);
        const node: AgentNode = {
          id,
          label,
          type,
          status: 'running',
          model: 'harvis-proxy/kimi-k2.5',
          subAgentCount: 0,
          startedAt: new Date(evt.timestamp).toISOString(),
        };
        nodeMap.set(id, node);

        // Create edge from orchestrator to sub-agent
        if (prevAgentId && prevAgentId !== id) {
          const edgeKey = `${prevAgentId}->${id}`;
          if (!edgeSet.has(edgeKey)) {
            edgeSet.add(edgeKey);
            edges.push({
              source: prevAgentId,
              target: id,
              type: 'spawned',
              createdAt: new Date(evt.timestamp).toISOString(),
            });
            // Update parent's subAgentCount
            const parent = nodeMap.get(prevAgentId);
            if (parent) {
              nodeMap.set(prevAgentId, { ...parent, subAgentCount: parent.subAgentCount + 1 });
            }
          }
        }

        // Track last seen agent so sub-agents connect to the orchestrator
        if (type === 'orchestrator') {
          prevAgentId = id;
        } else if (!prevAgentId) {
          prevAgentId = id;
        }
      }

      const node = nodeMap.get(id)!;

      // Update node state based on event type
      switch (evt.type) {
        case 'tool_call':
          nodeMap.set(id, {
            ...node,
            task: evt.tool ? `${evt.tool}(${JSON.stringify(evt.args ?? {}).slice(0, 60)})` : node.task,
            status: 'running',
          });
          break;
        case 'done':
          nodeMap.set(id, {
            ...node,
            status: 'completed',
            completedAt: new Date(evt.timestamp).toISOString(),
          });
          break;
        case 'error':
          nodeMap.set(id, {
            ...node,
            status: 'error' as AgentStatus,
            completedAt: new Date(evt.timestamp).toISOString(),
          });
          break;
        case 'token':
          // Increment output token count
          nodeMap.set(id, {
            ...node,
            tokensUsed: {
              input: node.tokensUsed?.input ?? 0,
              output: (node.tokensUsed?.output ?? 0) + (evt.content?.length ?? 0),
              total: (node.tokensUsed?.total ?? 0) + (evt.content?.length ?? 0),
            },
          });
          break;
      }
    }

    const nodes = Array.from(nodeMap.values());
    const runningCount = nodes.filter((n) => n.status === 'running').length;

    return { nodes, edges, agentCount: nodes.length, runningCount };
  }, [logEvents]);
}
