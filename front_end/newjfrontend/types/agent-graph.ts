/**
 * Types for the Live Agent Graph
 * Real-time visualization of spawned agents, their state, and sub-agent trees
 */

/** Agent status - reflects the current execution state */
export type AgentStatus = 'idle' | 'running' | 'waiting' | 'completed' | 'error';

/** Agent node type - the role/function of the agent */
export type AgentNodeType = 
  | 'planner'      // High-level task planning
  | 'coder'        // Code generation/review (also OpenCode)
  | 'researcher'   // Web research, data gathering
  | 'writer'       // Document generation
  | 'discord'      // Discord bot/bridge
  | 'orchestrator' // Main agent that spawns others
  | 'executor'     // Task execution
  | 'reviewer'    // Code/content review
  | 'opencode';   // OpenCode coding agent (sub-agent)

/** Color scheme for each agent type */
export const AGENT_TYPE_COLORS: Record<AgentNodeType, string> = {
  planner: '#f59e0b',      // amber-500
  coder: '#3b82f6',        // blue-500
  researcher: '#8b5cf6',   // violet-500
  writer: '#10b981',       // emerald-500
  discord: '#5865f2',        // discord blurple
  orchestrator: '#ec4899', // pink-500
  executor: '#06b6d4',     // cyan-500
  reviewer: '#f97316',     // orange-500
  opencode: '#06b6d4',     // cyan-500 (same as executor)
};

/** Status indicator colors */
export const AGENT_STATUS_COLORS: Record<AgentStatus, string> = {
  idle: '#6b7280',      // gray-500
  running: '#22c55e',   // green-500 (pulse)
  waiting: '#eab308',   // yellow-500
  completed: '#10b981', // emerald-500 (solid)
  error: '#ef4444',     // red-500
};

/** Status indicator icons (emoji or SVG path) */
export const AGENT_STATUS_ICONS: Record<AgentStatus, string> = {
  idle: '○',
  running: '▶',
  waiting: '⏸',
  completed: '✓',
  error: '✕',
};

/** Live agent node - represents a spawned agent */
export interface AgentNode {
  /** Unique identifier (e.g., "agent:main:subagent:abc123") */
  id: string;
  /** Short display label */
  label: string;
  /** Agent type determines color and icon */
  type: AgentNodeType;
  /** Current execution status */
  status: AgentStatus;
  /** Which LLM model this agent uses */
  model: string; // e.g., "kimi-k2.5", "qwen2.5-coder", "gpt-oss:120b"
  /** Current task description (what is it working on?) */
  task?: string;
  /** Parent agent ID - which agent spawned this one */
  parentId?: string;
  /** Number of sub-agents spawned by this agent */
  subAgentCount: number;
  /** Token usage statistics */
  tokensUsed?: {
    input: number;
    output: number;
    total: number;
  };
  /** When the agent started */
  startedAt?: string;
  /** When the agent completed/errored (if applicable) */
  completedAt?: string;
  /** Estimated completion percentage (0-100) */
  progress?: number;
  /** If triggered from Discord */
  discordChannel?: string;
  discordUserId?: string;
  /** Session key for this agent */
  sessionKey?: string;
  /** Additional metadata */
  metadata?: {
    skill?: string;          // Which skill is being used
    repo?: string;           // GitHub repo being worked on
    branch?: string;         // Git branch
    [key: string]: unknown;
  };
}

/** Connection between agents - spawn relationship */
export interface AgentConnection {
  /** Source agent (parent) */
  source: string;
  /** Target agent (child) */
  target: string;
  /** Connection type */
  type: 'spawned' | 'communicates' | 'depends';
  /** When the connection was created */
  createdAt: string;
  /** Optional label */
  label?: string;
  /** Additional metadata */
  metadata?: Record<string, unknown>;
}

/** Live event from WebSocket - updates the graph in real-time */
export interface AgentEvent {
  /** Event type */
  type: 
    | 'agent.spawned'      // New agent created
    | 'agent.updated'      // Agent status/progress changed
    | 'agent.completed'    // Agent finished
    | 'agent.error'        // Agent encountered error
    | 'agent.cancelled'  // Agent was cancelled
    | 'connection.created' // New connection established
    | 'connection.removed'; // Connection removed
  /** Agent ID affected */
  agentId: string;
  /** Event timestamp */
  timestamp: string;
  /** Event data payload */
  data: {
    agent?: Partial<AgentNode>;
    connection?: AgentConnection;
    error?: string;
  };
}

/** Graph filter options */
export interface AgentGraphFilter {
  /** Filter by agent types */
  types?: AgentNodeType[];
  /** Filter by status */
  status?: AgentStatus[];
  /** Filter by model */
  models?: string[];
  /** Search query for label/task */
  searchQuery?: string;
  /** Only show agents with parent (children only) */
  childrenOnly?: boolean;
  /** Only show root agents (no parent) */
  rootsOnly?: boolean;
  /** Only show running agents */
  runningOnly?: boolean;
  /** Filter by Discord channel */
  discordChannel?: string;
}

/** Graph state for persistence */
export interface AgentGraphState {
  nodes: AgentNode[];
  edges: AgentConnection[];
  selectedNodeId: string | null;
  physicsEnabled: boolean;
  zoom: number;
  pan: { x: number; y: number };
  filter: AgentGraphFilter;
}

/** View options */
export interface AgentGraphViewOptions {
  /** Show mini-map */
  showMiniMap: boolean;
  /** Show agent labels */
  showLabels: boolean;
  /** Show status badges */
  showStatus: boolean;
  /** Show token usage */
  showTokens: boolean;
  /** Dark mode */
  darkMode: boolean;
  /** Physics simulation enabled */
  physicsEnabled: boolean;
}

/** Node size based on importance */
export function getAgentNodeSize(agent: AgentNode): { width: number; height: number } {
  const baseSize = { width: 180, height: 80 };
  
  // Orchestrators are larger
  if (agent.type === 'orchestrator') {
    return { width: 220, height: 100 };
  }
  
  // Agents with many children are slightly larger
  if (agent.subAgentCount > 5) {
    return { width: 200, height: 90 };
  }
  
  return baseSize;
}

/** Get duration since agent started */
export function getAgentDuration(agent: AgentNode): string {
  if (!agent.startedAt) return '—';
  
  const start = new Date(agent.startedAt);
  const end = agent.completedAt ? new Date(agent.completedAt) : new Date();
  const diff = end.getTime() - start.getTime();
  
  const seconds = Math.floor(diff / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  
  if (hours > 0) return `${hours}h ${minutes % 60}m`;
  if (minutes > 0) return `${minutes}m ${seconds % 60}s`;
  return `${seconds}s`;
}

/** AgentNodeData — used by ReactFlow node components and AgentGraphView */
export interface AgentNodeData extends AgentNode {
  connectionCount?: number;
  isSelected?: boolean;
  isDimmed?: boolean;
}

/** Format token count nicely */
export function formatTokenCount(count: number): string {
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
  if (count >= 1_000) return `${(count / 1_000).toFixed(1)}k`;
  return count.toString();
}
