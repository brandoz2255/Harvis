'use client';

import React, { memo } from 'react';
import { Handle, Position, NodeProps } from '@xyflow/react';
import {
  FileText,
  Folder,
  Tag,
  StickyNote,
  Link2,
  GripHorizontal,
} from 'lucide-react';
import { NodeType, WorkspaceNode } from '../../../types/graph';

interface GraphNodeData extends WorkspaceNode {
  isSelected?: boolean;
  isDimmed?: boolean;
  isHighlighted?: boolean;
  connectionCount?: number;
}

const typeIcons: Record<NodeType, typeof FileText> = {
  file: FileText,
  folder: Folder,
  tag: Tag,
  note: StickyNote,
  link: Link2,
};

const typeColors: Record<NodeType, { bg: string; border: string; text: string }> = {
  file: {
    bg: 'bg-blue-500/10',
    border: 'border-blue-500/30',
    text: 'text-blue-400',
  },
  folder: {
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/30',
    text: 'text-amber-400',
  },
  tag: {
    bg: 'bg-emerald-500/10',
    border: 'border-emerald-500/30',
    text: 'text-emerald-400',
  },
  note: {
    bg: 'bg-purple-500/10',
    border: 'border-purple-500/30',
    text: 'text-purple-400',
  },
  link: {
    bg: 'bg-pink-500/10',
    border: 'border-pink-500/30',
    text: 'text-pink-400',
  },
};

export const GraphNode = memo(function GraphNode({
  data,
  selected,
  dragging,
}: NodeProps<GraphNodeData>) {
  const Icon = typeIcons[data.type] || FileText;
  const colors = typeColors[data.type] || typeColors.file;

  // Size based on connection count (hub nodes are bigger)
  const sizeClass =
    data.connectionCount && data.connectionCount > 5
      ? 'scale-110'
      : data.connectionCount && data.connectionCount > 2
      ? 'scale-100'
      : 'scale-90';

  return (
    <div
      className={`
        group relative flex flex-col items-center transition-all duration-200
        ${sizeClass}
        ${data.isDimmed ? 'opacity-30' : 'opacity-100'}
        ${selected ? 'z-50' : 'z-10'}
      `}
    >
      {/* Selection ring */}
      {selected && (
        <div className="absolute inset-0 -m-2 rounded-xl border-2 border-blue-400 animate-pulse" />
      )}

      {/* Node body */}
      <div
        className={`
          relative flex items-center gap-2 px-3 py-2 rounded-lg
          border backdrop-blur-sm
          transition-all duration-200 cursor-pointer
          ${colors.bg} ${colors.border}
          ${
            selected
              ? 'border-blue-400 shadow-lg shadow-blue-500/20 ring-2 ring-blue-400/50'
              : 'hover:border-gray-400 hover:shadow-md'
          }
          ${dragging ? 'cursor-grabbing' : 'cursor-grab'}
          ${data.isHighlighted ? 'ring-2 ring-yellow-400/50' : ''}
        `}
        style={{
          backgroundColor: selected
            ? 'rgba(30, 41, 59, 0.95)'
            : 'rgba(30, 41, 59, 0.8)',
          minWidth: '120px',
          maxWidth: '200px',
        }}
      >
        {/* Drag handle indicator */}
        <div className="absolute -top-1 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-50">
          <GripHorizontal className="w-3 h-3 text-gray-400" />
        </div>

        {/* Icon */}
        <Icon className={`w-4 h-4 ${colors.text} flex-shrink-0`} />

        {/* Label */}
        <span
          className={`
            text-sm font-medium truncate
            ${selected ? 'text-white' : 'text-gray-300'}
          `}
          title={data.label}
        >
          {data.label}
        </span>

        {/* Connection count badge */}
        {data.connectionCount !== undefined && data.connectionCount > 0 && (
          <span
            className={`
              ml-1 text-[10px] px-1.5 py-0.5 rounded-full
              ${selected ? 'bg-blue-500 text-white' : 'bg-gray-700 text-gray-400'}
            `}
          >
            {data.connectionCount}
          </span>
        )}
      </div>

      {/* Hover tooltip with description */}
      {data.description && (
        <div
          className={`
            absolute top-full mt-2 px-3 py-2 rounded-lg text-xs
            bg-gray-900 border border-gray-700 text-gray-300
            opacity-0 group-hover:opacity-100 transition-opacity
            pointer-events-none z-50 max-w-[200px] whitespace-pre-wrap
          `}
        >
          {data.description.length > 100
            ? data.description.slice(0, 100) + '...'
            : data.description}
        </div>
      )}

      {/* Connection handles */}
      <Handle
        type="target"
        position={Position.Top}
        className="!w-2 !h-2 !bg-gray-500 !border-none opacity-0 group-hover:opacity-50"
      />
      <Handle
        type="source"
        position={Position.Bottom}
        className="!w-2 !h-2 !bg-gray-500 !border-none opacity-0 group-hover:opacity-50"
      />
      <Handle
        type="target"
        position={Position.Left}
        className="!w-2 !h-2 !bg-gray-500 !border-none opacity-0 group-hover:opacity-50"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!w-2 !h-2 !bg-gray-500 !border-none opacity-0 group-hover:opacity-50"
      />
    </div>
  );
});
