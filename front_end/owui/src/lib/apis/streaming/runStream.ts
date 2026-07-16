import { writable, get, type Readable } from 'svelte/store';
import {
	createWorkspaceStream,
	WORKSPACE_TERMINAL,
	type WorkspaceEvent
} from './workspace-stream';

// ── Shared, ref-counted SSE consumer per run_id ─────────────────────────────
// Every view of a run (RunView inline + dock + stream, the WorkflowInspector, the
// chat-Controls RunWorkspace, the ReviewMirror) used to open its OWN createWorkspaceStream
// and re-fold the whole event array on EVERY streamed event. Two problems fell out of that:
//  1. N views ⇒ N connections to one host — the browser's ~6-per-host HTTP/1.1 cap got
//     saturated, and a severed-but-replayable stream could storm reconnects.
//  2. N views each re-rendering per event (SvelteFlow/WorkflowCanvas is not cheap) pegged the
//     main thread when a run streamed fast + a 2nd/3rd heavy view was open → the page froze.
//
// This store fixes both: ONE connection per run_id, fanned to all subscribers, and event
// delivery is BATCHED (flushed at most every FLUSH_MS) so re-render frequency is bounded no
// matter how fast the backend streams — while terminal events flush immediately so the run
// still "ends" instantly. The resume-on-drop breaker (forward-progress high-water + capped
// exponential backoff) lives here once instead of copy-pasted in four components.

export type RunPhase = 'connecting' | 'running' | 'done' | 'error' | 'cancelled';
export interface RunStreamState {
	events: WorkspaceEvent[];
	phase: RunPhase;
}

const FLUSH_MS = 140; // upper bound on UI update cadence (≈7 fps) — smooth but can't peg the thread
const TERMINAL_PHASES: RunPhase[] = ['done', 'error', 'cancelled'];

interface Entry {
	store: import('svelte/store').Writable<RunStreamState>;
	refs: number;
	controller: AbortController;
	cancelled: boolean;
}

const entries = new Map<string, Entry>();

function startConsume(id: string, entry: Entry): void {
	let pending: WorkspaceEvent[] = [];
	let flushTimer: ReturnType<typeof setTimeout> | null = null;

	const flush = () => {
		flushTimer = null;
		if (!pending.length) return;
		const batch = pending;
		pending = [];
		entry.store.update((s) => {
			let phase = s.phase;
			for (const evt of batch) {
				if (evt.type === 'done') phase = 'done';
				else if (evt.type === 'error') phase = 'error';
				else if (evt.type === 'cancelled') phase = 'cancelled';
				else if (phase === 'connecting') phase = 'running';
			}
			return { events: [...s.events, ...batch], phase };
		});
	};
	const schedule = () => {
		if (flushTimer === null) flushTimer = setTimeout(flush, FLUSH_MS);
	};

	(async () => {
		let failed = 0;
		let seen = 0; // high-water mark of events received across (re)connects
		while (
			!entry.cancelled &&
			!TERMINAL_PHASES.includes(get(entry.store).phase)
		) {
			let cleanEnd = false;
			try {
				for await (const evt of createWorkspaceStream(
					id,
					localStorage.token,
					entry.controller.signal
				)) {
					if (evt.type === 'stream_end') {
						cleanEnd = true;
						break;
					}
					pending.push(evt);
					if (WORKSPACE_TERMINAL.has(evt.type)) {
						flush(); // terminal event ends the run — surface it immediately
						break;
					}
					schedule();
				}
			} catch (e: any) {
				if (e?.name === 'AbortError') return;
			}
			flush(); // drain any batched-but-unflushed events before deciding to reconnect
			const st = get(entry.store);
			if (cleanEnd || TERMINAL_PHASES.includes(st.phase) || entry.cancelled) break;
			// Break on lack of FORWARD PROGRESS, not "got any event": every reconnect replays the
			// full history so events.length is always > 0. Only NEW events past the high-water mark
			// reset the breaker; a severed-but-replayable stream must eventually give up.
			const progressed = st.events.length > seen;
			seen = Math.max(seen, st.events.length);
			failed = progressed ? 0 : failed + 1;
			if (failed > 20) {
				// Give up — but mark the store TERMINAL first. Otherwise the shared entry stays
				// cached at 'connecting'/'running' with no consume loop running: every current AND
				// future subscriber (refs > 0 keeps it in the map) shows a run that pulses "live"
				// forever and never lets RunArtifacts `done` fire. Terminal lets views settle and a
				// later reopen (after all refs drop) start a fresh connection.
				entry.store.update((s) => ({ ...s, phase: 'error' as RunPhase }));
				break;
			}
			// Reconnect: replay rebuilds the full history, so clear to avoid dupes.
			pending = [];
			entry.store.set({ events: [], phase: 'connecting' });
			await new Promise((r) => setTimeout(r, Math.min(30000, 1500 * 2 ** Math.min(failed, 5))));
		}
	})();
}

/**
 * Subscribe to a run's live event stream. All callers for the same `id` share ONE underlying
 * SSE connection and one batched event pipeline. Returns the reactive state store plus an
 * `unsubscribe()` — call it on unmount / when switching runs. The connection is torn down when
 * the LAST subscriber unsubscribes.
 */
export function subscribeRun(id: string): {
	store: Readable<RunStreamState>;
	unsubscribe: () => void;
} {
	let entry = entries.get(id);
	if (!entry) {
		entry = {
			store: writable<RunStreamState>({ events: [], phase: 'connecting' }),
			refs: 0,
			controller: new AbortController(),
			cancelled: false
		};
		entries.set(id, entry);
		startConsume(id, entry);
	}
	entry.refs++;
	let done = false;
	return {
		store: { subscribe: entry.store.subscribe },
		unsubscribe: () => {
			if (done) return;
			done = true;
			const e = entries.get(id);
			if (!e) return;
			e.refs--;
			if (e.refs <= 0) {
				e.cancelled = true;
				try {
					e.controller.abort();
				} catch (_) {
					/* already gone */
				}
				entries.delete(id);
			}
		}
	};
}
