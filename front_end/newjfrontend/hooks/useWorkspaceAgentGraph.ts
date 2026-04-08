'use client';

import { useMemo } from 'react';
import { useOpenClawStore, type WorkspaceLogEvent } from '../stores/openclawStore';
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
  if (lower.includes('cod') || lower.includes('dev') || lower.includes('opencode')) return 'coder';
  if (lower.includes('research') || lower.includes('search')) return 'researcher';
  if (lower.includes('write') || lower.includes('doc')) return 'writer';
  return 'executor';
}

function labelToId(label: string): string {
  return label.toLowerCase().replace(/\s+/g, '-');
}

/** Stable graph node id: prefer OpenClaw runId so each sub-agent is its own box. */
function eventNodeId(evt: WorkspaceLogEvent): string {
  if (evt.run_id) return `run-${evt.run_id}`;
  return `lbl-${labelToId(evt.agent_label ?? 'Agent')}`;
}

/**
 * Derives an agent graph from workspace SSE log events stored in openclawStore.
 * No WebSocket required — reads from logEvents already populated by the SSE stream.
 */
export function useWorkspaceAgentGraph(): WorkspaceAgentGraph {
  const logEvents = useOpenClawStore((s) => s.logEvents);
  const workspaceModel = useOpenClawStore((s) => s.workspaceModel);
  const workspaceModelName = useOpenClawStore((s) => s.workspaceModelName);

  return useMemo(() => {
    const activeModel = workspaceModelName || workspaceModel;
    const nodeMap = new Map<string, AgentNode>();
    const edgeSet = new Set<string>();
    const edges: AgentConnection[] = [];
    /** First-seen order of node ids (for fallback edges if parent_run_id is missing). */
    const nodeOrder: string[] = [];

    function ensureNode(id: string, label: string, ts: number): AgentNode {
      let n = nodeMap.get(id);
      if (n) return n;
      n = {
        id,
        label,
        type: inferAgentType(label),
        status: 'running',
        model: activeModel,
        subAgentCount: 0,
        startedAt: new Date(ts).toISOString(),
      };
      nodeMap.set(id, n);
      return n;
    }

    for (const evt of logEvents) {
      const label = evt.agent_label ?? 'Agent';
      const id = eventNodeId(evt);

      const isNew = !nodeMap.has(id);
      ensureNode(id, label, evt.timestamp);
      if (isNew) nodeOrder.push(id);

      switch (evt.type) {
        case 'agent_start': {
          const cur = nodeMap.get(id)!;
          nodeMap.set(id, {
            ...cur,
            status: 'running',
            model: evt.model ?? cur.model,
            startedAt: new Date(evt.timestamp).toISOString(),
          });
          if (evt.parent_run_id && evt.run_id) {
            const src = `run-${evt.parent_run_id}`;
            const tgt = `run-${evt.run_id}`;
            ensureNode(src, 'Agent', evt.timestamp);
            const edgeKey = `${src}->${tgt}`;
            if (!edgeSet.has(edgeKey)) {
              edgeSet.add(edgeKey);
              edges.push({
                source: src,
                target: tgt,
                type: 'spawned',
                createdAt: new Date(evt.timestamp).toISOString(),
              });
              const parent = nodeMap.get(src)!;
              nodeMap.set(src, { ...parent, subAgentCount: parent.subAgentCount + 1 });
            }
          }
          break;
        }
        case 'agent_end':
          nodeMap.set(id, {
            ...nodeMap.get(id)!,
            status: 'completed',
            completedAt: new Date(evt.timestamp).toISOString(),
          });
          break;
        case 'tool_call':
          nodeMap.set(id, {
            ...nodeMap.get(id)!,
            task: evt.tool
              ? `${evt.tool}(${JSON.stringify(evt.args ?? {}).slice(0, 60)})`
              : nodeMap.get(id)!.task,
            status: 'running',
          });
          break;
        case 'done':
          nodeMap.set(id, {
            ...nodeMap.get(id)!,
            status: 'completed',
            completedAt: new Date(evt.timestamp).toISOString(),
          });
          break;
        case 'error':
          nodeMap.set(id, {
            ...nodeMap.get(id)!,
            status: 'error' as AgentStatus,
            completedAt: new Date(evt.timestamp).toISOString(),
          });
          break;
        case 'token':
          nodeMap.set(id, {
            ...nodeMap.get(id)!,
            tokensUsed: {
              input: nodeMap.get(id)!.tokensUsed?.input ?? 0,
              output: (nodeMap.get(id)!.tokensUsed?.output ?? 0) + (evt.content?.length ?? 0),
              total: (nodeMap.get(id)!.tokensUsed?.total ?? 0) + (evt.content?.length ?? 0),
            },
          });
          break;
        default:
          break;
      }
    }

    // If OpenClaw never attached parent_run_id on agent_start, we still show links:
    // star from the first agent node to every other node (chronological first-seen).
    if (edges.length === 0 && nodeOrder.length > 1) {
      const hub = nodeOrder[0];
      for (let i = 1; i < nodeOrder.length; i++) {
        const tgt = nodeOrder[i];
        const edgeKey = `${hub}->${tgt}`;
        if (edgeSet.has(edgeKey)) continue;
        edgeSet.add(edgeKey);
        edges.push({
          source: hub,
          target: tgt,
          type: 'spawned',
          createdAt: new Date().toISOString(),
        });
        const parent = nodeMap.get(hub);
        if (parent) {
          nodeMap.set(hub, { ...parent, subAgentCount: parent.subAgentCount + 1 });
        }
      }
    }

    const nodes = Array.from(nodeMap.values());
    const runningCount = nodes.filter((n) => n.status === 'running').length;

    return { nodes, edges, agentCount: nodes.length, runningCount };
  }, [logEvents, workspaceModel, workspaceModelName]);
}
