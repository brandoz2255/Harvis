'use client';

import React, { useCallback, useState } from 'react';
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Node,
  Edge,
  useNodesState,
  useEdgesState,
  type NodeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { AgentNode } from './AgentNode';
import { useAgentData } from '../../../hooks/useAgentData';
import { useAgentStream } from '../../../hooks/useAgentStream';
import { useWorkspaceAgentGraph } from '../../../hooks/useWorkspaceAgentGraph';
import { usePersistedAgentGraphLayout } from '../../../hooks/usePersistedAgentGraphLayout';
import { useOpenClawStore } from '../../../stores/openclawStore';
import { AgentNodeData } from '../../../types/agent-graph';

const nodeTypes = { agentNode: AgentNode } as unknown as NodeTypes;

interface AgentGraphViewProps {
  /** Token for WebSocket auth (required in live-ws mode) */
  token?: string;
  wsUrl?: string;
  darkMode?: boolean;
  height?: string;
  onAgentSelect?: (agent: AgentNodeData | null) => void;
  /**
   * 'live-ws' — connects directly to OpenClaw WebSocket (standalone use)
   * 'workspace-store' — derives graph from openclawStore.logEvents via SSE (default, no direct port access)
   */
  mode?: 'live-ws' | 'workspace-store';
}

// ─── Workspace-store mode ─────────────────────────────────────────────────────

function AgentGraphWorkspaceStore({
  darkMode = true,
  height = '100%',
  onAgentSelect,
}: Omit<AgentGraphViewProps, 'mode' | 'token' | 'wsUrl'>) {
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const activeModelLabel = useOpenClawStore(
    (s) => s.workspaceModelName || s.workspaceModel
  );
  const workspaceId = useOpenClawStore((s) => s.workspaceId);
  const graphStorageKey = `harvis-agent-graph-pos:${workspaceId ?? 'none'}`;

  const { nodes: agentNodes, edges: agentEdges, agentCount, runningCount } =
    useWorkspaceAgentGraph();

  const { nodes: initialFlowNodes, edges: initialFlowEdges } = useAgentData({
    agents: agentNodes,
    connections: agentEdges,
    darkMode,
    selectedAgentId,
  });

  const [nodes, setNodes, onNodesChange] = useNodesState(initialFlowNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialFlowEdges);

  const onNodesChangePersist = usePersistedAgentGraphLayout(
    graphStorageKey,
    initialFlowNodes,
    initialFlowEdges,
    setNodes,
    setEdges,
    onNodesChange
  );

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedAgentId(node.id);
      const agentData = agentNodes.find((a) => a.id === node.id);
      onAgentSelect?.(agentData ? ({ ...agentData, ...node.data } as AgentNodeData) : null);
    },
    [agentNodes, onAgentSelect]
  );

  const onPaneClick = useCallback(() => {
    setSelectedAgentId(null);
    onAgentSelect?.(null);
  }, [onAgentSelect]);

  if (agentCount === 0) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
        No agents yet — start a workspace task to see the graph
      </div>
    );
  }

  return (
    <div className={`agent-graph-view ${darkMode ? 'dark' : ''}`} style={{ height, width: '100%' }}>
      <div className="absolute top-2 left-2 z-50 flex items-center gap-2 text-xs text-muted-foreground">
        <span className={`w-2 h-2 rounded-full ${runningCount > 0 ? 'bg-green-400 animate-pulse' : 'bg-gray-500'}`} />
        {agentCount} {agentCount === 1 ? 'agent' : 'agents'}
        {runningCount > 0 && ` · ${runningCount} running`}
        {activeModelLabel && ` · ${activeModelLabel}`}
      </div>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChangePersist}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        nodeTypes={nodeTypes}
        fitView
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color={darkMode ? '#333' : '#e2e8f0'} />
        <MiniMap />
        <Controls />
      </ReactFlow>
    </div>
  );
}

// ─── Live WebSocket mode ──────────────────────────────────────────────────────

function AgentGraphLiveWs({
  token = '',
  wsUrl,
  darkMode = true,
  height = '100vh',
  onAgentSelect,
}: Omit<AgentGraphViewProps, 'mode'>) {
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

  const { nodes: agentNodes, edges: agentEdges, isConnected, isConnecting } = useAgentStream({
    url: wsUrl,
    token,
    autoReconnect: true,
  });

  const { nodes: initialFlowNodes, edges: initialFlowEdges, agentCount, runningCount } = useAgentData({
    agents: agentNodes,
    connections: agentEdges,
    darkMode,
    selectedAgentId,
  });

  const [nodes, setNodes, onNodesChange] = useNodesState(initialFlowNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialFlowEdges);

  const onNodesChangePersist = usePersistedAgentGraphLayout(
    'harvis-agent-graph-pos:live-ws',
    initialFlowNodes,
    initialFlowEdges,
    setNodes,
    setEdges,
    onNodesChange
  );

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedAgentId(node.id);
      const agentData = agentNodes.find((a) => a.id === node.id);
      onAgentSelect?.(agentData ? ({ ...agentData, ...node.data } as AgentNodeData) : null);
    },
    [agentNodes, onAgentSelect]
  );

  const onPaneClick = useCallback(() => {
    setSelectedAgentId(null);
    onAgentSelect?.(null);
  }, [onAgentSelect]);

  if (!isConnected && !isConnecting) {
    return (
      <div className="flex items-center justify-center h-full text-red-400 text-sm">
        WebSocket disconnected
      </div>
    );
  }

  return (
    <div className={`agent-graph-view ${darkMode ? 'dark' : ''}`} style={{ height, width: '100%' }}>
      <div className="absolute top-4 left-4 z-50 flex items-center gap-2 text-xs">
        <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-400' : 'bg-yellow-400'}`} />
        {isConnected
          ? `Live · ${agentCount} agents · ${runningCount} running`
          : 'Connecting...'}
      </div>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChangePersist}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        nodeTypes={nodeTypes}
        fitView
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color={darkMode ? '#333' : '#e2e8f0'} />
        <MiniMap />
        <Controls />
      </ReactFlow>
    </div>
  );
}

// ─── Public export ────────────────────────────────────────────────────────────

export function AgentGraphView({ mode = 'workspace-store', ...props }: AgentGraphViewProps) {
  if (mode === 'live-ws') {
    return <AgentGraphLiveWs {...props} />;
  }
  return <AgentGraphWorkspaceStore {...props} />;
}

export default AgentGraphView;
