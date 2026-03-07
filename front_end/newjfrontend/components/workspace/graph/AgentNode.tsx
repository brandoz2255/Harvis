'use client';

import React, { memo } from 'react';
import { Handle, Position, NodeProps } from '@xyflow/react';
import { 
  Bot, 
  Code, 
  Search, 
  PenTool, 
  MessageSquare, 
  Sparkles, 
  Play,
  AlertCircle,
  CheckCircle,
  Clock,
  PauseCircle,
  Cpu,
  GitBranch,
} from 'lucide-react';
import { 
  AgentNodeData, 
  AgentNodeType, 
  AgentStatus,
  AGENT_TYPE_COLORS,
  AGENT_STATUS_COLORS,
  AGENT_STATUS_ICONS,
  formatTokenCount,
  getAgentDuration,
} from '../../../types/agent-graph';

const typeIcons: Record<AgentNodeType, typeof Bot> = {
  planner: Sparkles,
  coder: Code,
  researcher: Search,
  writer: PenTool,
  discord: MessageSquare,
  orchestrator: Cpu,
  executor: Play,
  reviewer: Bot,
};

const statusIcons: Record<AgentStatus, typeof CheckCircle> = {
  idle: Clock,
  running: Play,
  waiting: PauseCircle,
  completed: CheckCircle,
  error: AlertCircle,
};

interface AgentNodeProps extends NodeProps<AgentNodeData> {}

export const AgentNode = memo(function AgentNode({ 
  data, 
  selected,
  dragging,
}: AgentNodeProps) {
  const TypeIcon = typeIcons[data.type] || Bot;
  const StatusIcon = statusIcons[data.status];
  const typeColor = AGENT_TYPE_COLORS[data.type];
  const statusColor = AGENT_STATUS_COLORS[data.status];
  
  const duration = data.startedAt ? getAgentDuration(data) : '—';
  const tokenText = data.tokensUsed ? formatTokenCount(data.tokensUsed.total) : '';
  
  // Card width based on content
  const cardWidth = data.task && data.task.length > 40 ? 'w-72' : 'w-56';
  
  return (
    <div className={`
      group relative transition-all duration-200
      ${data.isDimmed ? 'opacity-30' : 'opacity-100'}
      ${selected ? 'z-50' : 'z-10'}
    `}>
      {/* Selection ring */}
      {selected && (
        <div className="absolute inset-0 -m-3 rounded-2xl border-2 border-white animate-pulse" />
      )}
      
      {/* Main card */}
      <div 
        className={`
          relative ${cardWidth} rounded-xl border-2 backdrop-blur-sm
          transition-all duration-200 cursor-pointer overflow-hidden
          ${selected 
            ? 'border-white shadow-xl shadow-white/10 ring-2 ring-white/30' 
            : 'border-gray-700 hover:border-gray-500 hover:shadow-lg'
          }
          ${dragging ? 'cursor-grabbing' : 'cursor-move'}
          bg-[#1a1a1a]/95
        `}
        style={{ borderColor: selected ? typeColor : undefined }}
      >
        {/* Top colored border strip */}
        <div 
          className="absolute top-0 left-0 right-0 h-1"
          style={{ backgroundColor: typeColor }}
        />
        
        {/* Status pulse animation for running agents */}
        {data.status === 'running' && (
          <div 
            className="absolute inset-0 opacity-20 animate-pulse"
            style={{ backgroundColor: statusColor }}
          />
        )}
        
        {/* Header row */}
        <div className="flex items-center justify-between px-3 py-2 border-b border-gray-800">
          {/* Type icon */}
          <div className="flex items-center gap-2">
            <div 
              className="w-6 h-6 rounded-md flex items-center justify-center"
              style={{ backgroundColor: `${typeColor}20` }}
            >
              <TypeIcon 
                size={14} 
                style={{ color: typeColor }}
              />
            </div>
            
            {/* Label */}
            <span className="text-xs font-medium text-gray-300 truncate max-w-28">
              {data.label}
            </span>
          </div>
          
          {/* Status indicator */}
          <div className="flex items-center gap-1.5">
            {data.subAgentCount > 0 && (
              <div className="flex items-center gap-1 text-xs text-gray-400">
                <GitBranch size={12} />
                <span>{data.subAgentCount}</span>
              </div>
            )}
            
            <div 
              className="w-2 h-2 rounded-full"
              style={{ 
                backgroundColor: statusColor,
                boxShadow: `0 0 8px ${statusColor}`,
              }}
            />
          </div>
        </div>
        
        {/* Body content */}
        <div className="px-3 py-2 space-y-2">
          {/* Task description */}
          {data.task && (
            <p className="text-xs text-gray-400 line-clamp-2 leading-relaxed">
              {data.task}
            </p>
          )}
          
          {/* Model info */}
          <div className="flex items-center gap-1.5">
            <Cpu size={12} className="text-gray-500" />
            <span className="text-xs text-gray-500 font-mono">
              {data.model.split('/').pop() || data.model}
            </span>
          </div>
          
          {/* Footer stats */}
          <div className="flex items-center justify-between pt-1 border-t border-gray-800">
            <div className="flex items-center gap-2">
              {/* Duration */}
              <span className="text-xs text-gray-500 font-mono">
                {duration}
              </span>
              
              {/* Tokens */}
              {tokenText && (
                <span className="text-xs text-gray-500">
                  · {tokenText}t
                </span>
              )}
            </div>
            
            {/* Progress bar for running agents */}
            {data.status === 'running' && data.progress !== undefined && (
              <div className="flex items-center gap-1.5">
                <div className="w-16 h-1 bg-gray-800 rounded-full overflow-hidden">
                  <div 
                    className="h-full rounded-full transition-all"
                    style={{ 
                      width: `${data.progress}%`,
                      backgroundColor: typeColor,
                    }}
                  />
                </div>
                <span className="text-xs text-gray-500 font-mono">
                  {Math.round(data.progress)}%
                </span>
              </div>
            )}
            
            {/* Discord channel tag */}
            {data.discordChannel && (
              <div className="flex items-center gap-1 text-xs text-[#5865f2]">
                <MessageSquare size={10} />
                <span className="truncate max-w-16">{data.discordChannel}</span>
              </div>
            )}
          </div>
        </div>
      </div>
      
      {/* Connection handles */}
      <Handle 
        type="target" 
        position={Position.Left} 
        id="target"
        className="!w-2 !h-2 !bg-gray-600 !border-none"
      />
      <Handle 
        type="source" 
        position={Position.Right} 
        id="source"
        className="!w-2 !h-2 !bg-gray-600 !border-none"
      />
      
      {/* Sub-agent count badge */}
      {data.subAgentCount > 0 && (
        <div 
          className="absolute -bottom-1 -right-1 px-1.5 py-0.5 rounded-full text-xs font-medium bg-gray-800 border border-gray-700"
        >
          <span className="text-gray-400">{data.subAgentCount}</span>
        </div>
      )}
    </div>
  );
});

export default AgentNode;
