import { EventSourceParserStream } from 'eventsource-parser/stream';
import type { ParsedEvent } from 'eventsource-parser';
import { WEBUI_BASE_URL } from '$lib/constants';

// Harvis workspace stream events are flat JSON: { type, ...payload }.
// (See workspace_router.py stream_workspace — replay + live both emit this shape.)
export type WorkspaceEvent = {
	type: string;
	content?: string;
	text?: string;
	tool?: string;
	args?: Record<string, unknown>;
	output?: unknown;
	success?: boolean;
	message?: string;
	summary?: string;
	fix_hint?: string;
	agent_label?: string;
	model?: string;
	run_id?: string;
	structured_sources?: unknown[];
	structured_artifact_id?: string;
	// Harvis Execution Trace (Phase 1) event fields:
	// terminal_output — {command_id, target, stream, content, exit_code?, duration_ms?, truncated?}
	command_id?: string;
	job_id?: string;
	tool_call_id?: string;
	item_id?: string;
	id?: string;
	target?: { kind: string; id: string };
	stream?: 'stdout' | 'stderr';
	exit_code?: number;
	duration_ms?: number;
	truncated?: boolean;
	// decision — {action_id?, tool, lane, tier, policy, reason, source}
	lane?: string;
	tier?: string;
	policy?: 'allow' | 'deny' | 'gate';
	reason?: string;
	action_id?: string;
	// artifact — {artifact_id, path, mime_type, size_bytes, label}
	artifact_id?: string;
	path?: string;
	mime_type?: string;
	size_bytes?: number;
	label?: string;
	// search_trace — {phase, query, provider, result_count, results, collapsed_by_default}
	phase?: string;
	query?: string;
	provider?: string;
	result_count?: number;
	results?: { title?: string; domain?: string; url?: string; favicon?: string; snippet?: string }[];
	collapsed_by_default?: boolean;
	// agent_message — {role, label, content, run_id}: one agent-to-agent CONVERSATION post
	// (coder ↔ reviewer review loop). Distinct from final_message — it's the agents talking,
	// not the run's answer. Reuses `label`, `content`, `run_id` above.
	role?: 'coder' | 'reviewer' | string;
	// final_message — {content} (reuses `content` above)
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	[key: string]: any;
};

export const WORKSPACE_TERMINAL = new Set(['done', 'error', 'cancelled']);

/**
 * Open Harvis's `/api/workspace/stream/{id}` SSE and yield typed events.
 *
 * The backend replays all stored events from the DB first (so this is fully
 * resumable across tab reloads — the persisted run marker is enough to
 * re-attach) and then streams live. Yields each event; returns after a terminal
 * event (done/error/cancelled) or the `stream_end` sentinel. `: ping` heartbeat
 * comments are dropped by the SSE parser.
 */
export async function* createWorkspaceStream(
	workspaceId: string,
	token: string,
	signal?: AbortSignal
): AsyncGenerator<WorkspaceEvent> {
	const res = await fetch(`${WEBUI_BASE_URL}/api/workspace/stream/${workspaceId}`, {
		method: 'GET',
		headers: { Authorization: `Bearer ${token}` },
		credentials: 'include',
		signal
	});

	if (!res.ok || !res.body) {
		yield { type: 'error', message: `Workspace stream unavailable (HTTP ${res.status})` };
		return;
	}

	const reader: ReadableStreamDefaultReader<ParsedEvent> = res.body
		.pipeThrough(new TextDecoderStream())
		.pipeThrough(new EventSourceParserStream())
		.getReader();

	while (true) {
		const { value, done } = await reader.read();
		if (done) break;
		if (!value || !value.data) continue;

		let evt: WorkspaceEvent;
		try {
			evt = JSON.parse(value.data);
		} catch (e) {
			console.error('workspace-stream: failed to parse event', value.data, e);
			continue;
		}
		if (!evt || !evt.type) continue;
		if (evt.type === 'stream_end') {
			// Surface the clean end so consumers can tell "backend closed the stream"
			// (don't reconnect) from "connection dropped mid-run" (do reconnect).
			yield { type: 'stream_end' };
			break;
		}

		yield evt;

		if (WORKSPACE_TERMINAL.has(evt.type)) break;
	}
}
