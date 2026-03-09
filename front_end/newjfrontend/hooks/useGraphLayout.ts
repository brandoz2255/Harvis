'use client';

import { useCallback, useRef } from 'react';
import { Node, Edge } from '@xyflow/react';
import { forceSimulation, forceManyBody, forceCenter, forceLink, forceCollide } from 'd3-force';

interface SimulationNode extends Node {
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
  fx?: number | null;
  fy?: number | null;
}

interface SimulationLink {
  source: string | SimulationNode;
  target: string | SimulationNode;
  strength?: number;
}

export function useGraphLayout() {
  const simulationRef = useRef<ReturnType<typeof forceSimulation> | null>(null);

  const applyForceLayout = useCallback(
    (
      nodes: Node[],
      edges: Edge[],
      onUpdate: (nodes: Node[]) => void,
      onEdgesUpdate?: (edges: Edge[]) => void
    ) => {
      // Stop any existing simulation
      if (simulationRef.current) {
        simulationRef.current.stop();
      }

      // Prepare simulation nodes
      const simulationNodes: SimulationNode[] = nodes.map((node) => ({
        ...node,
        x: node.position?.x ?? Math.random() * 800,
        y: node.position?.y ?? Math.random() * 600,
        vx: 0,
        vy: 0,
      }));

      // Prepare simulation links
      const nodeMap = new Map(simulationNodes.map((n) => [n.id, n]));
      const simulationLinks: SimulationLink[] = edges
        .filter((edge) => nodeMap.has(edge.source) && nodeMap.has(edge.target))
        .map((edge) => ({
          source: edge.source,
          target: edge.target,
          strength: edge.data?.strength || 0.5,
        }));

      // Create force simulation
      const simulation = forceSimulation(simulationNodes as any)
        .force(
          'charge',
          forceManyBody().strength((d: any) => {
            // Hub nodes (many connections) repel less, leaf nodes repel more
            const connectionCount = edges.filter(
              (e) => e.source === d.id || e.target === d.id
            ).length;
            return -300 - connectionCount * 50;
          })
        )
        .force(
          'link',
          forceLink(simulationLinks as any)
            .id((d: any) => d.id)
            .distance((d: any) => 150 - (d.strength || 0.5) * 50)
            .strength((d: any) => d.strength || 0.5)
        )
        .force('collide', forceCollide().radius(80).strength(0.7))
        .force('center', forceCenter(400, 300).strength(0.05))
        .alpha(1)
        .alphaDecay(0.02)
        .on('tick', () => {
          // Update React Flow nodes with new positions
          const updatedNodes = simulationNodes.map((node) => ({
            ...node,
            position: {
              x: node.x || 0,
              y: node.y || 0,
            },
          }));
          onUpdate(updatedNodes);
        });

      simulationRef.current = simulation;

      // Return cleanup function
      return () => {
        simulation.stop();
      };
    },
    []
  );

  const stopSimulation = useCallback(() => {
    if (simulationRef.current) {
      simulationRef.current.stop();
      simulationRef.current = null;
    }
  }, []);

  const reheatSimulation = useCallback(() => {
    if (simulationRef.current) {
      simulationRef.current.alpha(0.3).restart();
    }
  }, []);

  return {
    applyForceLayout,
    stopSimulation,
    reheatSimulation,
  };
}
