import { writable, get } from 'svelte/store';

/**
 * Per-chat background activity, so a run the user walked away from still reports
 * itself in the sidebar.
 *
 * A Deep Research run lives entirely on the backend, but the only thing watching it
 * was the ResearchRunCard inside the open chat — navigate to Cookbook and that
 * component unmounts, taking the stream and every trace of "something is happening"
 * with it. This store is the part that outlives the chat view: the sidebar polls
 * `/api/research/active` for anything still marked `running` here and flips it to
 * `done` when the backend stops reporting it.
 *
 * It is persisted to localStorage so a reload mid-run doesn't lose the thread, and
 * entries are dropped once the user opens the chat (they've seen it) or after a day
 * (the run is long over and the backend has forgotten it).
 */

const KEY = 'harvis.chat.activity';
const MAX_AGE_MS = 24 * 60 * 60 * 1000;

export type ChatActivityState = 'running' | 'done';
export type ChatActivityEntry = {
	state: ChatActivityState;
	/** Backend session id of a Deep Research run still in flight. */
	research?: string;
	/** Workspace id of an agent run still in flight. */
	workspace?: string;
	/**
	 * Which list owns this id. `vibecode` means it is a Build session, not an OWUI chat —
	 * a different sidebar list renders it, and it is the one that gets auto-named on
	 * completion. Recorded when the run is first seen, because by the time it finishes the
	 * backend no longer lists it and there is nothing left to ask.
	 */
	kind?: 'vibecode';
	at: number;
};
export type ChatActivityMap = Record<string, ChatActivityEntry>;

const readStored = (): ChatActivityMap => {
	try {
		if (typeof localStorage === 'undefined') return {};
		const raw = localStorage.getItem(KEY);
		if (!raw) return {};
		const parsed = JSON.parse(raw);
		if (!parsed || typeof parsed !== 'object') return {};
		const now = Date.now();
		const out: ChatActivityMap = {};
		for (const [id, v] of Object.entries<any>(parsed)) {
			if (!v || (v.state !== 'running' && v.state !== 'done')) continue;
			if (typeof v.at !== 'number' || now - v.at > MAX_AGE_MS) continue;
			// Research and workspace runs live on the backend and keep going regardless of
			// this tab; the sidebar poller re-checks them by id and can settle them honestly.
			// An ordinary reply streams over HTTP from the page that asked for it, so anything
			// still marked `running` with neither id has already lost its stream to a reload or
			// a closed tab. It is finished as far as this browser can ever know — call it done
			// rather than leaving a spinner turning forever on a dead run.
			const resumable = v.research || v.workspace;
			const state: ChatActivityState = v.state === 'running' && !resumable ? 'done' : v.state;
			out[id] = {
				state,
				research: v.research,
				workspace: v.workspace,
				kind: v.kind === 'vibecode' ? 'vibecode' : undefined,
				at: v.at
			};
		}
		return out;
	} catch (_) {
		return {};
	}
};

export const chatActivity = writable<ChatActivityMap>(readStored());

const persist = (v: ChatActivityMap) => {
	try {
		if (typeof localStorage === 'undefined') return;
		localStorage.setItem(KEY, JSON.stringify(v));
	} catch (_) {}
};

const commit = (next: ChatActivityMap) => {
	persist(next);
	chatActivity.set(next);
};

export const markChatRunning = (
	chatId: string,
	research?: string,
	workspace?: string,
	kind?: 'vibecode'
) => {
	if (!chatId) return;
	const cur = get(chatActivity);
	const prev = cur[chatId];
	// Don't drop an id the caller didn't happen to know. The reply stream and the sidebar
	// poller both mark the same chat running from different angles, and whichever fires
	// second must not erase the other's handle — that handle is the only way the poller
	// can later tell whether the run is still alive.
	commit({
		...cur,
		[chatId]: {
			state: 'running',
			research: research ?? prev?.research,
			workspace: workspace ?? prev?.workspace,
			kind: kind ?? prev?.kind,
			at: Date.now()
		}
	});
};

export const markChatDone = (chatId: string) => {
	if (!chatId) return;
	const cur = get(chatActivity);
	if (!cur[chatId]) return;
	commit({ ...cur, [chatId]: { ...cur[chatId], state: 'done', at: Date.now() } });
};

export const clearChatActivity = (chatId: string) => {
	if (!chatId) return;
	const cur = get(chatActivity);
	if (!cur[chatId]) return;
	const next = { ...cur };
	delete next[chatId];
	commit(next);
};

/** The chats still waiting on something, as [chatId, entry] pairs. */
export const runningChats = (): [string, ChatActivityEntry][] =>
	Object.entries(get(chatActivity)).filter(([, v]) => v.state === 'running');
