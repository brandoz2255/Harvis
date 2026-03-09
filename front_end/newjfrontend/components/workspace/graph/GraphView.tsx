'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
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
  useReactFlow,
  Panel,
  ConnectionMode,
  SelectionMode,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { GraphNode } from './GraphNode';
import { GraphControls } from './GraphControls';
import { GraphSearch } from './GraphSearch';
import { useGraphLayout } from '../../../hooks/useGraphLayout';
import { useGraphData } from '../../../hooks/useGraphData';
import { WorkspaceNode, NodeType } from '../../../types/graph';

const nodeTypes = {
  workspaceNode: GraphNode,
};

interface GraphViewProps {
  /** Initial nodes data */
  initialNodes?: WorkspaceNode[];
  /** Initial edges (connections) between nodes */
  initialEdges?: Array<{ source: string; target: string; strength?: number }>;
  /** Callback when a node is selected */
  onNodeSelect?: (node: WorkspaceNode | null) => void;
  /** Enable physics simulation (force-directed layout) */
  enablePhysics?: boolean;
  /** Enable search functionality */
  enableSearch?: boolean;
  /** Dark mode (Obsidian style) */
  darkMode?: boolean;
  /** Height of the graph container */
  height?: string;
  /** Called when the graph data changes */
  onGraphChange?: (nodes: Node[], edges: Edge[]) => void;
}

export function GraphView({
  initialNodes = [],
  initialEdges = [],
  onNodeSelect,
  enablePhysics = true,
  enableSearch = true,
  darkMode = true,
  height = '100vh',
  onGraphChange,
}: GraphViewProps) {
  // Transform workspace data to React Flow format
  const { nodes: initialFlowNodes, edges: initialFlowEdges } = useGraphData(
    initialNodes,
    initialEdges,
    darkMode
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(initialFlowNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialFlowEdges);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [physicsEnabled, setPhysicsEnabled] = useState(enablePhysics);

  const { fitView, zoomTo, setCenter } = useReactFlow();
  const { applyForceLayout, stopSimulation } = useGraphLayout();

  // Apply force-directed layout when enabled
  useEffect(() => {
    if (physicsEnabled && nodes.length > 0) {
      const cleanup = applyForceLayout(nodes, edges, setNodes, setEdges);
      return cleanup;
    } else {
      stopSimulation();
    }
  }, [physicsEnabled, nodes.length, edges.length]);

  // Notify parent of graph changes
  useEffect(() => {
    onGraphChange?.(nodes, edges);
  }, [nodes, edges, onGraphChange]);

  // Handle node click
  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedNodeId(node.id);
      const workspaceNode = initialNodes.find((n) => n.id === node.id);
      onNodeSelect?.(workspaceNode || null);

      // Highlight connected edges
      setEdges((eds) =>
        eds.map((edge) => ({
          ...edge,
          style: {
            ...edge.style,
            opacity:
              edge.source === node.id || edge.target === node.id ? 1 : 0.2,
            strokeWidth:
              edge.source === node.id || edge.target === node.id ? 2 : 1,
          },
        }))
      );
    },
    [initialNodes, onNodeSelect, setEdges]
  );

  // Handle background click (deselect)
  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null);
    onNodeSelect?.(null);
    setEdges((eds) =>
      eds.map((edge) => ({
        ...edge,
        style: {
          ...edge.style,
          opacity: 0.6,
          strokeWidth: 1,
        },
      }))
    );
  }, [onNodeSelect, setEdges]);

  // Search and filter nodes
  const filteredNodes = useMemo(() => {
    if (!searchQuery.trim()) return nodes;
    const query = searchQuery.toLowerCase();
    return nodes.filter(
      (node) =>
        node.data?.label?.toLowerCase().includes(query) ||
        node.data?.description?.toLowerCase().includes(query) ||
        node.data?.tags?.some((tag: string) =>
          tag.toLowerCase().includes(query)
        )
    );
  }, [nodes, searchQuery]);

  // Filter edges to only show connections between visible nodes
  const visibleNodeIds = useMemo(
    () => new Set(filteredNodes.map((n) => n.id)),
    [filteredNodes]
  );
  const filteredEdges = useMemo(
    () =>
      edges.filter(
        (edge) =>
          visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target)
      ),
    [edges, visibleNodeIds]
  );

  // Highlight search results
  useEffect(() => {
    if (searchQuery.trim()) {
      setNodes((nds) =>
        nds.map((node) => ({
          ...node,
          data: {
            ...node.data,
            isDimmed: !filteredNodes.some((fn) => fn.id === node.id),
            isHighlighted: filteredNodes.some((fn) => fn.id === node.id),
          },
        }))
      );
    } else {
      setNodes((nds) =>
        nds.map((node) => ({
          ...node,
          data: {
            ...node.data,
            isDimmed: false,
            isHighlighted: false,
          },
        }))
      );
    }
  }, [searchQuery, filteredNodes]);

  // Focus on a specific node
  const focusNode = useCallback(
    (nodeId: string) => {
      const node = nodes.find((n) => n.id === nodeId);
      if (node && node.position) {
        setCenter(node.position.x, node.position.y, { zoom: 1.5, duration: 800 });
        setSelectedNodeId(nodeId);
      }
    },
    [nodes, setCenter]
  );

  return (
    <div
      className={`graph-view ${darkMode ? 'graph-dark' : 'graph-light'}`}
      style={{ height, width: '100%' }}
    >
      <ReactFlow
        nodes={filteredNodes}
        edges={filteredEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        onPaneClick={onPaneClick}
        nodeTypes={nodeTypes}
        connectionMode={ConnectionMode.Loose}
        selectionMode={SelectionMode.Partial}
        selectionOnDrag={false}
        panOnDrag={[1, 2]}
        zoomOnScroll={true}
        zoomOnPinch={true}
        zoomOnDoubleClick={true}
        minZoom={0.1}
        maxZoom={4}
        defaultEdgeOptions={{
          type: 'straight',
          style: {
            stroke: darkMode ? '#5c5c5c' : '#94a3b8',
            strokeWidth: 1,
          },
        }}
        proOptions={{ hideAttribution: true }}
        className="obsidian-graph"
      >
        {/* Obsidian-style background with dots */}
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={1}
          color={darkMode ? '#333333' : '#e2e8f0'}
        />

        {/* Mini map in bottom right */}
        <MiniMap
          nodeColor={(node) => {
            const colors: Record<NodeType, string> = {
              file: '#60a5fa',
              folder: '#fbbf24',
              tag: '#34d399',
              note: '#a78bfa',
              link: '#f472b6',
            };
            return colors[node.data?.type as NodeType] || '#94a3b8';
          }}
          maskColor={darkMode ? 'rgba(0, 0, 0, 0.8)' : 'rgba(255, 255, 255, 0.8)'}
          className="rounded-lg border border-border/50"
          style={{
            backgroundColor: darkMode ? '#1e1e1e' : '#ffffff',
          }}
        />

        {/* Custom controls */}
        <Controls
          className="!bg-background !border-border"
          showInteractive={false}
        />

        {/* Top control bar */}
        <Panel position="top-left" className="m-4">
          <GraphControls
            physicsEnabled={physicsEnabled}
            onTogglePhysics={() => setPhysicsEnabled(!physicsEnabled)}
            onFitView={() => fitView({ padding: 0.2, duration: 800 })}
            onZoomIn={() => zoomTo((z) => z * 1.2)}
            onZoomOut={() => zoomTo((z) => z / 1.2)}
            darkMode={darkMode}
          />
        </Panel>

        {/* Search bar */}
        {enableSearch && (
          <Panel position="top-center" className="m-4">
            <GraphSearch
              query={searchQuery}
              onChange={setSearchQuery}
              results={filteredNodes.map((n) => ({
                id: n.id,
                label: n.data?.label || n.id,
                type: n.data?.type,
              }))}
              onSelect={focusNode}
              darkMode={darkMode}
            />
          </Panel>
        )}

        {/* Node count indicator */}
        <Panel position="bottom-left" className="m-4">
          <div
            className={`text-xs px-3 py-1.5 rounded-md ${
              darkMode
                ? 'bg-[#262626] text-gray-400 border border-[#333]'
                : 'bg-white text-gray-600 border border-gray-200 shadow-sm'
            }`}
          >
            {filteredNodes.length} nodes · {filteredEdges.length} links
            {physicsEnabled && (
              <span className="ml-2 text-green-400">● physics on</span>
            )}
          </div>
        </Panel>
      </ReactFlow>
    </div>
  );
}
