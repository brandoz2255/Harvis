'use client';

import React, { useMemo } from 'react';
import { X, Cpu, Clock, Wrench, FileText } from 'lucide-react';
import { WorkspaceLogEvent } from '../../../stores/openclawStore';
import { AGENT_STATUS_COLORS, AGENT_TYPE_COLORS } from '../../../types/agent-graph';
import { cn } from '../../../lib/utils';

interface AgentDetailPanelProps {
  agentId: string | null;
  logEvents: WorkspaceLogEvent[];
  onClose: () => void;
}

function labelToId(label: string): string {
  return label.toLowerCase().replace(/\s+/g, '-');
}

/** Match SSE events to React Flow node id (`run-<uuid>` or `lbl-<slug>`). */
function eventMatchesGraphNode(evt: WorkspaceLogEvent, graphNodeId: string): boolean {
  if (graphNodeId.startsWith('run-') && evt.run_id) {
    return graphNodeId === `run-${evt.run_id}`;
  }
  if (graphNodeId.startsWith('lbl-')) {
    return graphNodeId === `lbl-${labelToId(evt.agent_label ?? 'Agent')}`;
  }
  return labelToId(evt.agent_label ?? 'Agent') === graphNodeId;
}

interface FileDiff {
  path: string;
  before: string | null;
  after: string;
}

export function AgentDetailPanel({ agentId, logEvents, onClose }: AgentDetailPanelProps) {
  if (!agentId) return null;

  const agentEvents = useMemo(
    () => logEvents.filter((e) => eventMatchesGraphNode(e, agentId)),
    [logEvents, agentId]
  );

  const agentLabel = agentEvents[0]?.agent_label ?? agentId;

  // Derive tool calls
  const toolCalls = useMemo(
    () => agentEvents.filter((e) => e.type === 'tool_call'),
    [agentEvents]
  );

  // Derive file diffs: pair read result with subsequent write for same path
  const fileDiffs = useMemo<FileDiff[]>(() => {
    const diffs: FileDiff[] = [];
    const readMap = new Map<string, string>();

    for (const evt of agentEvents) {
      if (evt.type === 'tool_call' && evt.tool === 'read' && evt.args?.path) {
        // next tool_result for this event will have the read content
        const path = String(evt.args.path);
        readMap.set(path, '');
      }
      if (evt.type === 'tool_result' && evt.output) {
        // heuristic: if any path is tracked, associate this result
        for (const [path] of readMap) {
          if (!readMap.get(path)) {
            readMap.set(path, evt.output);
            break;
          }
        }
      }
      if (evt.type === 'tool_call' && (evt.tool === 'write' || evt.tool === 'edit') && evt.args?.path) {
        const path = String(evt.args.path);
        const content = String(evt.args?.content ?? evt.args?.new_string ?? '');
        diffs.push({
          path,
          before: readMap.get(path) ?? null,
          after: content,
        });
      }
    }
    return diffs;
  }, [agentEvents]);

  // Token count
  const tokenCount = useMemo(
    () => agentEvents.filter((e) => e.type === 'token').reduce((acc, e) => acc + (e.content?.length ?? 0), 0),
    [agentEvents]
  );

  // Duration
  const firstTs = agentEvents[0]?.timestamp;
  const lastTs = agentEvents[agentEvents.length - 1]?.timestamp;
  const durationMs = firstTs && lastTs ? lastTs - firstTs : 0;
  const durationStr =
    durationMs > 60_000
      ? `${Math.floor(durationMs / 60_000)}m ${Math.floor((durationMs % 60_000) / 1000)}s`
      : `${Math.floor(durationMs / 1000)}s`;

  const status = agentEvents.some((e) => e.type === 'error')
    ? 'error'
    : agentEvents.some((e) => e.type === 'done')
    ? 'completed'
    : 'running';

  const statusColor = AGENT_STATUS_COLORS[status] ?? '#6b7280';

  return (
    <div className="w-80 shrink-0 flex flex-col border-l border-border bg-card overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className="w-2 h-2 rounded-full shrink-0"
            style={{ backgroundColor: statusColor, boxShadow: `0 0 6px ${statusColor}` }}
          />
          <span className="text-sm font-semibold text-foreground truncate">{agentLabel}</span>
          <span
            className="text-[10px] font-medium px-1.5 py-0.5 rounded-full border shrink-0"
            style={{ color: statusColor, borderColor: `${statusColor}50`, background: `${statusColor}15` }}
          >
            {status}
          </span>
        </div>
        <button
          onClick={onClose}
          className="h-6 w-6 flex items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-muted/50 shrink-0"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Stats row */}
      <div className="flex items-center gap-3 px-3 py-2 border-b border-border shrink-0 text-xs text-muted-foreground">
        <div className="flex items-center gap-1">
          <Clock className="h-3 w-3" />
          <span className="font-mono">{durationStr}</span>
        </div>
        <div className="flex items-center gap-1">
          <Cpu className="h-3 w-3" />
          <span className="font-mono">{(tokenCount / 4).toFixed(0)}t</span>
        </div>
        <div className="flex items-center gap-1">
          <Wrench className="h-3 w-3" />
          <span>{toolCalls.length} calls</span>
        </div>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-4">

        {/* Tool calls */}
        {toolCalls.length > 0 && (
          <section>
            <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">
              Tool Calls
            </p>
            <div className="space-y-1">
              {toolCalls.map((evt) => (
                <div
                  key={evt.id}
                  className="flex items-start gap-2 p-2 rounded-md bg-muted/30 border border-border/50"
                >
                  <Wrench className="h-3 w-3 text-violet-400 shrink-0 mt-0.5" />
                  <div className="min-w-0">
                    <span className="text-xs font-mono text-violet-300">{evt.tool}</span>
                    {evt.args && (
                      <p className="text-[10px] text-muted-foreground font-mono break-all line-clamp-2 mt-0.5">
                        {JSON.stringify(evt.args)}
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* File diffs */}
        {fileDiffs.length > 0 && (
          <section>
            <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">
              File Changes
            </p>
            <div className="space-y-3">
              {fileDiffs.map((diff, i) => (
                <div key={i} className="rounded-md border border-border/50 overflow-hidden">
                  <div className="flex items-center gap-1.5 px-2 py-1 bg-muted/40 border-b border-border/50">
                    <FileText className="h-3 w-3 text-muted-foreground shrink-0" />
                    <span className="text-[10px] font-mono text-muted-foreground truncate">{diff.path}</span>
                  </div>
                  {diff.before !== null ? (
                    <div className="grid grid-cols-2 divide-x divide-border/50">
                      <div className="overflow-auto max-h-40">
                        <p className="px-2 py-0.5 text-[9px] font-semibold text-red-400 bg-red-500/10 border-b border-border/30">
                          Before
                        </p>
                        <pre className="px-2 py-1.5 text-[9px] font-mono text-muted-foreground whitespace-pre-wrap break-all leading-relaxed">
                          {diff.before.slice(0, 800)}
                        </pre>
                      </div>
                      <div className="overflow-auto max-h-40">
                        <p className="px-2 py-0.5 text-[9px] font-semibold text-green-400 bg-green-500/10 border-b border-border/30">
                          After
                        </p>
                        <pre className="px-2 py-1.5 text-[9px] font-mono text-muted-foreground whitespace-pre-wrap break-all leading-relaxed">
                          {diff.after.slice(0, 800)}
                        </pre>
                      </div>
                    </div>
                  ) : (
                    <div className="overflow-auto max-h-40">
                      <p className="px-2 py-0.5 text-[9px] font-semibold text-green-400 bg-green-500/10 border-b border-border/30">
                        Written
                      </p>
                      <pre className="px-2 py-1.5 text-[9px] font-mono text-muted-foreground whitespace-pre-wrap break-all leading-relaxed">
                        {diff.after.slice(0, 1200)}
                      </pre>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {agentEvents.length === 0 && (
          <p className="text-xs text-muted-foreground text-center py-4">No events for this agent</p>
        )}
      </div>
    </div>
  );
}

export default AgentDetailPanel;
