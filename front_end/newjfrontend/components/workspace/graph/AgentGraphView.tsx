'use client';

import React, { useCallback, useEffect, useState } from 'react';
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
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { AgentNode } from './AgentNode';
import { useAgentData } from '../../../hooks/useAgentData';
import { useAgentStream } from '../../../hooks/useAgentStream';
import { AgentNodeData } from '../../../types/agent-graph';

const nodeTypes = { agentNode: AgentNode };

interface AgentGraphViewProps {
  token: string;
  wsUrl?: string;
  darkMode?: boolean;
  height?: string;
  onAgentSelect?: (agent: AgentNodeData | null) => void;
}

export function AgentGraphView({ token, wsUrl, darkMode = true, height = '100vh', onAgentSelect }: AgentGraphViewProps) {
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

  const { nodes: agentNodes, edges: agentEdges, isConnected, isConnecting } = useAgentStream({
    url: wsUrl, token, autoReconnect: true,
  });

  const { nodes: initialFlowNodes, edges: initialFlowEdges, agentCount, runningCount } = useAgentData({
    agents: agentNodes, connections: agentEdges, darkMode, selectedAgentId,
  });

  const [nodes, setNodes, onNodesChange] = useNodesState(initialFlowNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialFlowEdges);

  useEffect(() => { setNodes(initialFlowNodes); setEdges(initialFlowEdges); }, [initialFlowNodes, initialFlowEdges]);

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedAgentId(node.id);
    const agentData = agentNodes.find(a => a.id === node.id);
    onAgentSelect?.(agentData ? { ...agentData, ...node.data } as AgentNodeData : null);
  }, [agentNodes, onAgentSelect]);

  const onPaneClick = useCallback(() => {
    setSelectedAgentId(null);
    onAgentSelect?.(null);
  }, [onAgentSelect]);

  if (!isConnected && !isConnecting) {
    return <div className="flex items-center justify-center h-full text-red-400">WebSocket disconnected</div>;
  }

  return (
    <div className={`agent-graph-view ${darkMode ? 'dark' : ''}`} style={{ height, width: '100%' }}>
      <div className="absolute top-4 left-4 z-50 flex items-center gap-2 text-xs">
        <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-400' : 'bg-yellow-400'}`} />
        {isConnected ? `Live · ${agentCount} agents · ${runningCount} running` : 'Connecting...'}
      </div>
      <ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick} onPaneClick={onPaneClick} nodeTypes={nodeTypes} fitView>
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color={darkMode ? '#333' : '#e2e8f0'} />
        <MiniMap />
        <Controls />
      </ReactFlow>
    </div>
  );
}

export default AgentGraphView;
