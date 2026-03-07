/**
 * Types for the Workspace Knowledge Graph
 */

export type NodeType = 'file' | 'folder' | 'tag' | 'note' | 'link';

export interface WorkspaceNode {
  /** Unique identifier */
  id: string;
  /** Display label */
  label: string;
  /** Node type for styling */
  type: NodeType;
  /** Optional description shown on hover */
  description?: string;
  /** Tags for categorization */
  tags?: string[];
  /** URL or path to the actual resource */
  url?: string;
  /** Timestamp */
  createdAt?: string;
  updatedAt?: string;
  /** Additional metadata */
  metadata?: Record<string, unknown>;
}

export interface NodeConnection {
  /** Source node ID */
  source: string;
  /** Target node ID */
  target: string;
  /** Connection strength (0-1) */
  strength?: number;
  /** Connection type */
  type?: 'reference' | 'contains' | 'tags' | 'links';
  /** Metadata about the connection */
  metadata?: Record<string, unknown>;
}

export interface GraphState {
  nodes: WorkspaceNode[];
  edges: NodeConnection[];
  selectedNodeId: string | null;
  physicsEnabled: boolean;
  zoom: number;
  pan: { x: number; y: number };
}

export interface GraphFilter {
  types?: NodeType[];
  tags?: string[];
  searchQuery?: string;
  minConnections?: number;
  maxConnections?: number;
}
