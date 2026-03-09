'use client';

import React from 'react';
import {
  X,
  FileText,
  Folder,
  Tag,
  StickyNote,
  Link2,
  Calendar,
  Hash,
  ExternalLink,
  ArrowRight,
} from 'lucide-react';
import { NodeType, WorkspaceNode } from '../../../types/graph';

const typeIcons: Record<NodeType, typeof FileText> = {
  file: FileText,
  folder: Folder,
  tag: Tag,
  note: StickyNote,
  link: Link2,
};

const typeLabels: Record<NodeType, string> = {
  file: 'File',
  folder: 'Folder',
  tag: 'Tag',
  note: 'Note',
  link: 'Link',
};

interface GraphSidebarProps {
  node: WorkspaceNode | null;
  isOpen: boolean;
  onClose: () => void;
  allNodes: WorkspaceNode[];
  connections: Array<{ source: string; target: string; strength?: number }>;
}

export function GraphSidebar({
  node,
  isOpen,
  onClose,
  allNodes,
  connections,
}: GraphSidebarProps) {
  const Icon = node ? typeIcons[node.type] : FileText;

  // Get connected nodes
  const connectedNodes = connections
    .map((conn) => {
      const otherId = conn.source === node?.id ? conn.target : conn.source;
      const otherNode = allNodes.find((n) => n.id === otherId);
      return otherNode
        ? { ...otherNode, isSource: conn.source === node?.id, strength: conn.strength }
        : null;
    })
    .filter(Boolean) as Array<WorkspaceNode & { isSource: boolean; strength: number }>;

  return (
    <>
      {/* Backdrop for mobile */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 lg:hidden"
          onClick={onClose}
        />
      )}

      {/* Sidebar */}
      <div
        className={`
          fixed lg:static right-0 top-0 h-full w-[350px] z-50
          bg-[#1a1a1a] border-l border-[#333]
          transform transition-transform duration-300 ease-out
          ${isOpen ? 'translate-x-0' : 'translate-x-full lg:translate-x-0 lg:hidden'}
          flex flex-col
        `}
      >
        {node ? (
          <>
            {/* Header */}
            <div className="flex items-start justify-between p-4 border-b border-[#333]">
              <div className="flex items-center gap-3">
                <div
                  className={`
                    p-2 rounded-lg
                    ${
                      node.type === 'file'
                        ? 'bg-blue-500/20 text-blue-400'
                        : node.type === 'folder'
                        ? 'bg-amber-500/20 text-amber-400'
                        : node.type === 'tag'
                        ? 'bg-emerald-500/20 text-emerald-400'
                        : node.type === 'note'
                        ? 'bg-purple-500/20 text-purple-400'
                        : 'bg-pink-500/20 text-pink-400'
                    }
                  `}
                >
                  <Icon className="w-5 h-5" />
                </div>
                <div>
                  <span className="text-xs text-gray-500 uppercase tracking-wider">
                    {typeLabels[node.type]}
                  </span>
                  <h2 className="font-semibold text-white leading-tight">
                    {node.label}
                  </h2>
                </div>
              </div>
              <button
                onClick={onClose}
                className="p-1.5 rounded-md text-gray-400 hover:text-white hover:bg-[#333] transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Scrollable content */}
            <div className="flex-1 overflow-y-auto p-4 space-y-6">
              {/* Description */}
              {node.description && (
                <div>
                  <h3 className="text-sm font-medium text-gray-400 mb-2">
                    Description
                  </h3>
                  <p className="text-sm text-gray-300 leading-relaxed">
                    {node.description}
                  </p>
                </div>
              )}

              {/* Tags */}
              {node.tags && node.tags.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-gray-400 mb-2 flex items-center gap-2">
                    <Hash className="w-4 h-4" />
                    Tags
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {node.tags.map((tag) => (
                      <span
                        key={tag}
                        className="px-2.5 py-1 rounded-full text-xs bg-[#262626] text-gray-300 border border-[#333]"
                      >
                        #{tag}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Connected nodes */}
              <div>
                <h3 className="text-sm font-medium text-gray-400 mb-2">
                  Connections ({connectedNodes.length})
                </h3>
                <div className="space-y-1">
                  {connectedNodes.map((connected) => {
                    const ConnectedIcon = typeIcons[connected.type];
                    return (
                      <button
                        key={connected.id}
                        className="w-full flex items-center gap-3 p-2 rounded-lg hover:bg-[#262626] transition-colors text-left group"
                      >
                        <ConnectedIcon className="w-4 h-4 text-gray-500 group-hover:text-gray-400" />
                        <div className="flex-1 min-w-0">
                          <span className="text-sm text-gray-300 truncate block">
                            {connected.label}
                          </span>
                          <span className="text-xs text-gray-500">
                            {connected.isSource ? '→ outgoing' : '← incoming'} ·
                            strength: {Math.round((connected.strength || 0) * 100)}%
                          </span>
                        </div>
                        <ArrowRight className="w-4 h-4 text-gray-600 opacity-0 group-hover:opacity-100 transition-opacity" />
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Metadata */}
              {(node.createdAt || node.updatedAt) && (
                <div>
                  <h3 className="text-sm font-medium text-gray-400 mb-2 flex items-center gap-2">
                    <Calendar className="w-4 h-4" />
                    Timeline
                  </h3>
                  <div className="space-y-2 text-sm">
                    {node.createdAt && (
                      <div className="flex justify-between">
                        <span className="text-gray-500">Created</span>
                        <span className="text-gray-300">
                          {new Date(node.createdAt).toLocaleDateString()}
                        </span>
                      </div>
                    )}
                    {node.updatedAt && (
                      <div className="flex justify-between">
                        <span className="text-gray-500">Updated</span>
                        <span className="text-gray-300">
                          {new Date(node.updatedAt).toLocaleDateString()}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Footer actions */}
            <div className="p-4 border-t border-[#333] space-y-2">
              {node.url && (
                <a
                  href={node.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center justify-center gap-2 w-full px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors"
                >
                  <ExternalLink className="w-4 h-4" />
                  Open
                </a>
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
            <div className="w-16 h-16 rounded-full bg-[#262626] flex items-center justify-center mb-4">
              <FileText className="w-8 h-8 text-gray-600" />
            </div>
            <h3 className="text-gray-300 font-medium mb-1">No node selected</h3>
            <p className="text-sm text-gray-500">
              Click on a node in the graph to view its details
            </p>
          </div>
        )}
      </div>
    </>
  );
}
