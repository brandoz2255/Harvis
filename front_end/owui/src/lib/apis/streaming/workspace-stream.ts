import { EventSourceParserStream } from 'eventsource-parser/stream';
import type { ParsedEvent } from 'eventsource-parser';
import { WEBUI_BASE_URL } from '$lib/constants';

// Harvis workspace stream events are flat JSON: { type, ...payload }.
// (See workspace_router.py stream_workspace — replay + live both emit this shape.)
export type WorkspaceEvent = {
	type: string;
	content?: string;
	tool?: string;
	args?: Record<string, unknown>;
	output?: string;
	success?: boolean;
	message?: string;
	summary?: string;
	fix_hint?: string;
	agent_label?: string;
	model?: string;
	run_id?: string;
	structured_sources?: unknown[];
	structured_artifact_id?: string;
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
		if (evt.type === 'stream_end') break;

		yield evt;

		if (WORKSPACE_TERMINAL.has(evt.type)) break;
	}
}
